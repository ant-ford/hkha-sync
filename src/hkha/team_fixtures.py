"""
Scrape the MCList.asp fixture list for a logged-in team.

MCList can contain:
1. A current/upcoming fixture table.
2. A historical played-fixtures table.

Only played fixtures should be parsed because Fixture Ids are assigned
only after a match has been played.
"""
import logging

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
    resp = session.get(MCLIST_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'html.parser')
    fixtures: list[dict] = []

    tables = soup.find_all('table')

    if len(tables) >= 2:
        fixture_table = tables[1]
        logger.info('MCList found %s tables, parsing played-fixtures table (index 1)', len(tables))
    elif tables:
        fixture_table = tables[0]
        logger.info('MCList found 1 table, parsing table 0')
    else:
        logger.warning('MCList contained no tables')
        return []

    for row in fixture_table.find_all('tr'):
        row_id = row.get('id', '')
        if not row_id.startswith('Row'):
            continue

        cells = row.find_all('td')
        if len(cells) < 11:
            continue

        fixture = {
            'fixture_id': row_id.replace('Row', ''),
            'date': _text(cells[1]),
            'division': _text(cells[2]),
            'home_team': _text(cells[3]),
            'home_score': _text(cells[4]),
            'away_team': _text(cells[5]),
            'away_score': _text(cells[6]),
            'venue': _text(cells[7]),
            'time': _text(cells[8]),
            'umpire1': _text(cells[9]),
            'umpire2': _text(cells[10]),
        }

        fixture['is_played'] = _is_played(fixture)

        if not fixture['is_played']:
            continue

        if hkfc_only and not _is_hkfc_fixture(fixture):
            continue

        fixtures.append(fixture)

    logger.info('MCList returned %s played HKFC fixture(s)', len(fixtures))
    return fixtures