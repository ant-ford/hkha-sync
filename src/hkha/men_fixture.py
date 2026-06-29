"""
Scrape the public MenFixture.asp page for current-season fixtures.

No authentication is required.  This page shows the full season
fixture list for all men's teams.  Dates are grouped in "title" rows.
Each fixture row contains: C/P, Div, Time, Venue, Home, Away, Umpire1, Umpire2, Match Official.

There are no fixture IDs or scores on this page.
"""

import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

from src.config.settings import HKHA_BASE_URL

logger = logging.getLogger(__name__)

MEN_FIXTURE_URL = f'{HKHA_BASE_URL}/MenFixture.asp?ClubId=1'

# ── HTML structure constants ────────────────────────────────────────────────
TABLE_CLASS = 'standing'
TITLE_ROW_CLASS = 'title'
FIXTURE_ROW_CLASSES: Set[str] = {'odd', 'even', 'inactive'}

# ── Column indices for fixture rows (0‑based) ───────────────────────────────
_COL_CP = 0  # unused (often "Res" or "&nbsp;")
_COL_DIVISION = 1
_COL_TIME = 2
_COL_VENUE = 3
_COL_HOME_TEAM = 4
_COL_AWAY_TEAM = 5
_COL_UMPIRE1 = 6
_COL_UMPIRE2 = 7
_COL_MATCH_OFFICIAL = 8
_MIN_FIXTURE_COLS = 9  # must have all 9 cells to be a valid fixture row

# ── Expected header keywords (exact match, case‑insensitive) ───────────────
_EXPECTED_HEADERS = {
    'c/p', 'div', 'time', 'venue', 'home', 'away',
    'umpire 1', 'umpire 2', 'match official'
}

# ── Retry settings ──────────────────────────────────────────────────────────
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2  # seconds, doubled each retry


def _text(td) -> str:
    """Extract stripped text from a td element, normalising non‑breaking spaces."""
    if not td:
        return ''
    text = td.get_text(separator=' ', strip=True)
    return text.replace('\xa0', ' ').strip()


def _normalize_time(time_str: str) -> str:
    """
    Convert various time formats to HH:MM (24‑hour).

    Handles: "17:00", "5:00 PM", "5:00PM", "TBC", empty strings.
    Returns "TBC" if the time cannot be parsed (or is explicitly TBC).
    """
    time_str = time_str.strip().upper()
    if not time_str or time_str in ('TBC', 'TBD', 'N/A'):
        return 'TBC'
    for fmt in ('%I:%M %p', '%I:%M%p', '%H:%M'):
        try:
            return datetime.strptime(time_str, fmt).strftime('%H:%M')
        except ValueError:
            continue
    # If all formats fail, keep the original (might be something like "TBC" already)
    return time_str


def _parse_date_title(title_row):

    text = title_row.get_text(" ", strip=True)

    text = text.replace("Top", "").strip()

    try:
        dt = datetime.strptime(text, "%A, %d %b %Y")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        logger.warning(
            "Could not parse date from title row: %r",
            text
        )
        return None


def _validate_headers(table) -> bool:
    """
    Verify the table contains the expected column headers.

    Checks that all keywords in ``_EXPECTED_HEADERS`` appear (case‑insensitive)
    in the first row.
    """
    header_row = table.find('tr')
    if not header_row:
        return False
    headers = {_text(td).lower() for td in header_row.find_all(['td', 'th'])}
    return _EXPECTED_HEADERS.issubset(headers)


def _is_hkfc(home: str, away: str) -> bool:
    """Return True if either team name contains 'HKFC'."""
    return 'HKFC' in home or 'HKFC' in away


def _fixture_key(f: Dict) -> Tuple:
    """Return a hashable key for deduplication (including venue)."""
    return (f['date'], f['division'], f['time'], f['home_team'], f['away_team'], f['venue'])


def _parse_fixture_row(row, current_date: str) -> Optional[Dict]:
    """
    Parse a fixture row into a fixture dict.

    Valid rows have class in ``FIXTURE_ROW_CLASSES`` and at least
    ``_MIN_FIXTURE_COLS`` cells.  Returns None otherwise.
    """
    cells = row.find_all('td')
    if len(cells) < _MIN_FIXTURE_COLS:
        return None

    texts = [_text(c) for c in cells]

    time_raw = texts[_COL_TIME]
    if not time_raw:
        return None

    return {
        'fixture_id': None,
        'date': current_date,
        'time': _normalize_time(time_raw),
        'division': texts[_COL_DIVISION],
        'venue': texts[_COL_VENUE],
        'home_team': texts[_COL_HOME_TEAM],
        'away_team': texts[_COL_AWAY_TEAM],
        'umpire1': texts[_COL_UMPIRE1],
        'umpire2': texts[_COL_UMPIRE2],
        'match_official': texts[_COL_MATCH_OFFICIAL],
        'is_played': False,
        'source': 'MenFixture',
    }


def _fetch_with_retry(url: str, headers: Dict, timeout: int = 30) -> Optional[requests.Response]:
    """
    Fetch a URL with simple exponential‑backoff retry.

    Returns the Response on success, or None after exhausting retries.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with requests.Session() as session:
                session.headers.update(headers)
                resp = session.get(url, timeout=timeout)
                resp.raise_for_status()
                return resp
        except requests.RequestException as exc:
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "Fetch attempt %d/%d failed: %s – retrying in %ds",
                    attempt, _MAX_RETRIES, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Fetch failed after %d attempts: %s",
                    _MAX_RETRIES, exc,
                )
    return None


def get_public_fixtures(hkfc_only: bool = True) -> List[Dict]:
    """
    Fetch and parse MenFixture.asp.

    No login is required.

    Args:
        hkfc_only: When True (default), only return fixtures where at
                   least one team contains "HKFC".

    Returns:
        List of fixture dicts.  Each dict includes:
            - fixture_id: always None (no ID on this page)
            - date: DD/MM/YYYY
            - time: HH:MM or "TBC"
            - datetime_combined: ISO‑8601 combined date+time (default 00:00 for TBC)
            - division, venue, home_team, away_team, umpire1, umpire2, match_official
            - is_played: False (always)
            - source: "MenFixture"
    """
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
    }

    resp = _fetch_with_retry(MEN_FIXTURE_URL, headers)
    if resp is None:
        return []

    # Handle encoding – Hong Kong sites may use Big5 / Windows‑1252
    resp.encoding = resp.apparent_encoding or 'utf-8'

    soup = BeautifulSoup(resp.text, 'html.parser')

    # ── Locate and validate the fixtures table ──────────────────────────
    logger.info(
        "Found %d tables on page",
        len(soup.find_all("table"))
    )
    
    table = soup.find('table', class_=TABLE_CLASS)
    if not table:
        logger.error("Could not find <table class='%s'> on MenFixture.asp", TABLE_CLASS)
        return []

    if not _validate_headers(table):
        logger.error(
            "Table header validation failed on MenFixture.asp – "
            "page structure may have changed"
        )
        return []

    rows = table.find_all('tr')

    for i, row in enumerate(rows[:20]):
        logger.info(
            "Row %s classes=%s text=%s",
            i,
            row.get("class"),
            row.get_text(" ", strip=True)[:120]
        )

    logger.debug("MenFixture.asp: %d <tr> elements found in table", len(rows))

    # ── Iterate rows, tracking the current date ─────────────────────────
    fixtures: List[Dict] = []
    current_date: Optional[str] = None
    skipped_no_date = 0
    skipped_invalid = 0

    for row in rows:

        cells = row.find_all("td")

        if not cells:
            continue

        # Date row
        if len(cells) == 1:
            date_str = _parse_date_title(row)

            if date_str:
                current_date = date_str

            continue

        # Header row
        if len(cells) >= 9:
            first_cell = _text(cells[0]).lower()

            if first_cell == "c/p":
                continue

        # Fixture row
        if len(cells) >= _MIN_FIXTURE_COLS:

            if current_date is None:
                skipped_no_date += 1
                continue

            f = _parse_fixture_row(row, current_date)

            if f is None:
                skipped_invalid += 1
                continue

            if hkfc_only and not _is_hkfc(
                f["home_team"],
                f["away_team"]
            ):
                continue

            fixtures.append(f)

    # ── Deduplicate ─────────────────────────────────────────────────────
    seen: Set[Tuple] = set()
    unique_fixtures: List[Dict] = []
    dupes = 0
    for f in fixtures:
        key = _fixture_key(f)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        unique_fixtures.append(f)

    logger.info(
        "MenFixture.asp: %d unique HKFC fixtures parsed (all without ID). "
        "Skipped: %d rows (no date), %d invalid fixture rows, %d duplicates.",
        len(unique_fixtures), skipped_no_date, skipped_invalid, dupes,
    )

    if len(unique_fixtures) == 0:
        logger.warning(
            "MenFixture.asp returned 0 HKFC fixtures. "
            "The page may have changed structure or the season has no HKFC matches."
        )

    return unique_fixtures
    
