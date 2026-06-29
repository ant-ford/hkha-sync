"""
Scrape the public MenFixture.asp page for current-season fixtures.

No authentication is required.  This page shows the full season
fixture list for all men's teams and is the primary source for
scheduled (future) fixtures.

The page uses the same HKHA backend as MCList.asp, so row IDs follow
the same Row{N} pattern and cells are laid out identically.

Column layout (0-indexed, based on MCList.asp pattern):
  cells[0] – unused (row number / checkbox)
  cells[1] – date         DD/MM/YYYY
  cells[2] – division
  cells[3] – home team
  cells[4] – home score   (blank when unplayed)
  cells[5] – away team
  cells[6] – away score   (blank when unplayed)
  cells[7] – venue

If the page changes layout (e.g. a time column is inserted), the
DEBUG-level row dumps will show what was found so you can adjust
the column indices below.
"""
import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.config.settings import HKHA_BASE_URL

logger = logging.getLogger(__name__)

MEN_FIXTURE_URL = f'{HKHA_BASE_URL}/MenFixture.asp'

# Matches a fixture ID inside any MCInfo.asp href
_FIXTURE_ID_HREF_RE = re.compile(r'FixtureId[=:](\d+)', re.IGNORECASE)

# ── Column indices ────────────────────────────────────────────────────────────
# Adjust these if HKHA change their page layout.
_COL_DATE       = 1
_COL_DIVISION   = 2
_COL_HOME_TEAM  = 3
_COL_HOME_SCORE = 4
_COL_AWAY_TEAM  = 5
_COL_AWAY_SCORE = 6
_COL_VENUE      = 7
_MIN_COLS       = 6          # minimum cells needed to attempt parsing


def _text(td) -> str:
    return td.get_text(separator=' ', strip=True) if td else ''


def _extract_fixture_id(row) -> Optional[str]:
    """
    Try three methods to extract a fixture ID from a table row.

    1. id="Row12345" attribute on the <tr> (same pattern as MCList.asp)
    2. href="MCInfo.asp?FixtureId=12345" on any link inside the row
    3. data-fixtureid / data-id attribute on any element inside the row
    """
    # Method 1 – row id attribute
    row_id = row.get('id', '')
    if row_id.startswith('Row') and row_id[3:].isdigit():
        return row_id[3:]

    # Method 2 – MCInfo link
    for a in row.find_all('a', href=True):
        m = _FIXTURE_ID_HREF_RE.search(a['href'])
        if m:
            return m.group(1)

    # Method 3 – data attribute
    for tag in row.find_all(True):
        for attr in ('data-fixtureid', 'data-id', 'data-fixture'):
            val = tag.get(attr, '')
            if val and str(val).isdigit():
                return str(val)

    return None


def _is_hkfc(home: str, away: str) -> bool:
    return 'HKFC' in home or 'HKFC' in away


def _clean_score(raw: str) -> str:
    """Return a numeric string or '' for non-numeric / separator values."""
    s = raw.strip()
    if not s or s.upper() in ('VS', 'V', 'WO', '-', 'N/A', 'TBC', 'TBD'):
        return ''
    try:
        int(s)
        return s
    except ValueError:
        return ''


def _parse_row(row) -> Optional[dict]:
    """
    Attempt to parse one <tr> into a fixture dict.

    Returns None if the row doesn't look like a fixture row.
    """
    cells = row.find_all('td')
    if len(cells) < _MIN_COLS:
        return None

    texts = [_text(c) for c in cells]

    # Validate: the date cell must look like DD/MM/YYYY
    date_raw = texts[_COL_DATE] if len(texts) > _COL_DATE else ''
    if not re.match(r'\d{2}/\d{2}/\d{4}', date_raw):
        return None

    fixture_id = _extract_fixture_id(row)

    home_score = _clean_score(texts[_COL_HOME_SCORE]) if len(texts) > _COL_HOME_SCORE else ''
    away_score = _clean_score(texts[_COL_AWAY_SCORE]) if len(texts) > _COL_AWAY_SCORE else ''

    fixture = {
        'fixture_id': fixture_id,           # None for unplayed / unpublished fixtures
        'date':       date_raw,
        'division':   texts[_COL_DIVISION]   if len(texts) > _COL_DIVISION  else '',
        'home_team':  texts[_COL_HOME_TEAM]  if len(texts) > _COL_HOME_TEAM else '',
        'home_score': home_score,
        'away_team':  texts[_COL_AWAY_TEAM]  if len(texts) > _COL_AWAY_TEAM else '',
        'away_score': away_score,
        'venue':      texts[_COL_VENUE]      if len(texts) > _COL_VENUE     else '',
        'is_played':  bool(home_score and away_score),
        'source':     'MenFixture',
    }

    logger.debug(
        'MenFixture row: id=%s date=%s %s v %s score=%s-%s',
        fixture_id or 'NONE',
        date_raw,
        fixture['home_team'],
        fixture['away_team'],
        home_score or '?',
        away_score or '?',
    )

    return fixture


def get_public_fixtures(hkfc_only: bool = True) -> list[dict]:
    """
    Fetch and parse MenFixture.asp.

    No login is required.  A plain requests.Session is used.

    Args:
        hkfc_only: When True (default), only return fixtures where at
                   least one team contains "HKFC".

    Returns:
        List of fixture dicts.  ``fixture_id`` may be None for future
        fixtures that HKHA has not yet assigned an ID to; these will be
        resolved later by MCList.asp via composite-key matching.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
    })

    try:
        resp = session.get(MEN_FIXTURE_URL, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        logger.error('Failed to fetch MenFixture.asp: %s', exc)
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')

    all_rows = soup.find_all('tr')
    logger.debug('MenFixture.asp: %d <tr> elements found', len(all_rows))

    fixtures: list[dict] = []
    skipped_no_date = 0

    for row in all_rows:
        f = _parse_row(row)
        if f is None:
            skipped_no_date += 1
            continue
        if hkfc_only and not _is_hkfc(f['home_team'], f['away_team']):
            continue
        fixtures.append(f)

    with_id    = sum(1 for f in fixtures if f['fixture_id'])
    without_id = sum(1 for f in fixtures if not f['fixture_id'])

    logger.info(
        'MenFixture.asp: %d HKFC fixtures parsed '
        '(%d with ID, %d without ID, %d rows skipped)',
        len(fixtures), with_id, without_id, skipped_no_date,
    )

    if len(fixtures) == 0:
        logger.warning(
            'MenFixture.asp returned 0 HKFC fixtures. '
            'The page may use a different column layout — '
            'run with DEBUG logging to inspect raw rows. '
            'Check _COL_* constants in src/hkha/men_fixture.py'
        )

    return fixtures
  
