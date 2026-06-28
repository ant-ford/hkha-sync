from src.config.teams import TEAMS
from src.config.settings import HKHA_PASSWORD
from src.hkha.auth import login
from src.hkha.team_fixtures import get_fixture_list


def run():
    for team in TEAMS:
        session = login(team, HKHA_PASSWORD)
        fixtures = get_fixture_list(session)
        print(f'{team}: {len(fixtures)} fixtures')

if __name__ == '__main__':
    run()
