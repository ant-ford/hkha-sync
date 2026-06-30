"""
Scrape the MCList.asp fixture list for a logged-in team.

Each team account on HKHA only sees its own fixtures, but when multiple
HKFC teams share a division (e.g. A vs B inter-section), the same
fixture_id can appear in both teams' lists.  Deduplication happens at
the job level (sync_fixtures.py) using a shared seen-set; this module
simply returns whatever HKHA exposes for the current session.
"""
import logging
from typing import Optional

from bs4 import BeautifulSoup

from src.config.settings import MCLIST_URL

logger = logging.getLogger(__name__)


def _text(td) -> str:
    return td.get_text(strip=True) if td else ''


def _is_hkfc_fixture(f: dict) -> bool:
    return 'HKFC' in f.get('home_team', '') or 'HKFC' in f.get('away_team', '')


def _is_played(f: dict) -> bool:
    return bool(f.get('home_score', '').strip()) and bool(f.get('away_score', '').strip())


def get_fixture_list(session, hkfc_only: bool = True) -> list[dict]:
    """
    Return fixtures visible to the currently authenticated session.

    Args:
        session:    Authenticated requests.Session.
        hkfc_only: When True (default) only include fixtures where at
                   least one team name contains "HKFC".

    Returns:
        List of fixture dicts:
            fixture_id, date (DD/MM/YYYY), division,
            home_team, home_score, away_team, away_score,
            venue, is_played (bool).
    """
    resp = session.get(MCLIST_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'html.parser')
    fixtures: list[dict] = []

    for row in soup.find_all('tr'):
        row_id = row.get('id', '')
        if not row_id.startswith('Row'):
            continue

        cells = row.find_all('td')
        if len(cells) < 8:
            continue

        fixture: dict = {
            'fixture_id': row_id.replace('Row', ''),
            'date':       _text(cells[1]),
            'division':   _text(cells[2]),
            'home_team':  _text(cells[3]),
            'home_score': _text(cells[4]),
            'away_team':  _text(cells[5]),
            'away_score': _text(cells[6]),
            'venue':      _text(cells[7]),
            'time':       _text(cells[8]),
            'umpire1':     _text(cells[9]),
            'umpire2':     _text(cells[10]),
        }
        fixture['is_played'] = _is_played(fixture)

        if hkfc_only and not _is_hkfc_fixture(fixture):
            continue

        fixtures.append(fixture)

    logger.info(f'MCList returned {len(fixtures)} HKFC fixture(s)')
    return fixtures
