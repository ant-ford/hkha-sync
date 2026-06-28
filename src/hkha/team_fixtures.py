from bs4 import BeautifulSoup
from src.config.settings import MCLIST_URL


def get_fixture_list(session):
    response = session.get(MCLIST_URL, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')

    fixtures = []

    for row in soup.find_all('tr'):
        row_id = row.get('id', '')
        if not row_id.startswith('Row'):
            continue

        fixture_id = row_id.replace('Row', '')
        fixtures.append({
            'fixture_id': fixture_id
        })

    return fixtures
