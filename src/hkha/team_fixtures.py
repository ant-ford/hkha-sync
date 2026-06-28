from bs4 import BeautifulSoup
from src.config.settings import MCLIST_URL


def _text(td):
    return td.get_text(strip=True) if td else ''


def get_fixture_list(session):
    response = session.get(MCLIST_URL, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    fixtures = []

    for row in soup.find_all('tr'):
        row_id = row.get('id', '')
        if not row_id.startswith('Row'):
            continue

        cells = row.find_all('td')
        fixture_id = row_id.replace('Row', '')

        fixture = {
            'fixture_id': fixture_id,
            'date': _text(cells[1]) if len(cells) > 1 else '',
            'division': _text(cells[2]) if len(cells) > 2 else '',
            'home_team': _text(cells[3]) if len(cells) > 3 else '',
            'home_score': _text(cells[4]) if len(cells) > 4 else '',
            'away_team': _text(cells[5]) if len(cells) > 5 else '',
            'away_score': _text(cells[6]) if len(cells) > 6 else '',
            'venue': _text(cells[7]) if len(cells) > 7 else ''
        }

        fixtures.append(fixture)

    return fixtures