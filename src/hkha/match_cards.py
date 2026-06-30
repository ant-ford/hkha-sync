"""
Scrape MCInfo.asp match-card pages.

Only HKFC team blocks are extracted; opposition players are ignored.
The scraper retries on transient HTTP errors with exponential backoff.
"""
import logging
import time

import requests
from bs4 import BeautifulSoup, NavigableString

from src.config.settings import MCINFO_URL
from src.hkha.player_parser import parse_player_row, extract_cards

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS  = 5
_BASE_DELAY_S  = 3      # seconds; doubles each attempt


def _fetch(session, fixture_id: str):
    """GET MCInfo.asp with per-request retry / backoff."""
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = session.get(
                MCINFO_URL,
                params={'FixtureId': fixture_id},
                timeout=30,
            )
            resp.raise_for_status()
            return resp

        except requests.exceptions.HTTPError as exc:
            # Don't retry genuine client errors (401, 403, 404, …)
            if exc.response is not None and exc.response.status_code < 500:
                raise
            last_exc = exc

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            last_exc = exc

        if attempt < _MAX_ATTEMPTS:
            delay = _BASE_DELAY_S * (2 ** (attempt - 1))
            logger.warning(
                f'MCInfo fetch failed for fixture {fixture_id} '
                f'(attempt {attempt}/{_MAX_ATTEMPTS}), retrying in {delay} s: {last_exc}'
            )
            time.sleep(delay)

    raise RuntimeError(
        f'Failed to fetch match card for fixture {fixture_id} '
        f'after {_MAX_ATTEMPTS} attempts'
    ) from last_exc


def _extract_team_block(container) -> dict | None:
    """Parse a Home or Away <div style="width: 480px"> block."""
    header = container.find('div', class_=['Home', 'Away'])
    if not header:
        return None

    spans = header.find_all('span')
    if not spans:
        return None
    team_name = spans[0].get_text(strip=True)

    players: list[dict] = []

    for div in container.find_all('div', class_='team'):
        raw = div.get_text(' ', strip=True)
        if not raw or raw.startswith('Score'):
            continue

        name_text = ' '.join(
            ''.join(c for c in div.contents if isinstance(c, NavigableString)).split()
        )

        player = parse_player_row(name_text)
        player['Cards'] = extract_cards(raw)

        # Goals Scored
        for inner in div.find_all('div'):
            if 'Score:' in inner.get_text():
                try:
                    player['Goals Scored'] = int(inner.get_text().split(':')[1].strip())
                except (ValueError, IndexError):
                    player['Goals Scored'] = 0

        # Player Team (filled when playing up — contains <b class="playerteam">)
        pt = div.find('b', class_='playerteam')
        player['Player Team'] = pt.get_text(strip=True) if pt else team_name
        player['Team']        = team_name

        players.append(player)

    return {'team': team_name, 'players': players}


def get_match_card(session, fixture_id: str) -> dict:
    """
    Scrape the match card for *fixture_id* using *session*.

    Returns:
        {'fixture_id': str, 'players': list[dict]}

    Only HKFC team blocks are included.  An empty players list is
    returned for walkovers or fixtures where HKHA has no card yet.
    """
    resp = _fetch(session, fixture_id)
    soup = BeautifulSoup(resp.text, 'html.parser')

    containers = [
        div
        for div in soup.find_all('div')
        if div.find('div', class_=['Home', 'Away'])
    ]

    players: list[dict] = []
    for c in containers:
        block = _extract_team_block(c)
        if block and 'HKFC' in block.get('team', ''):
            players.extend(block['players'])

    logger.info(f'Fixture {fixture_id}: {len(players)} HKFC player(s) found on card')
    return {'fixture_id': fixture_id, 'players': players}
    
