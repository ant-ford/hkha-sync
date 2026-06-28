from bs4 import BeautifulSoup
from src.config.settings import MCINFO_URL


def get_match_card(session, fixture_id):
    response = session.get(
        MCINFO_URL,
        params={'FixtureId': fixture_id},
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')

    return {
        'fixture_id': fixture_id,
        'html_length': len(response.text)
    }
