"""
Phase 1 — Fixture Discovery

MenFixture.asp
    Creates and updates scheduled fixtures.

MCList.asp
    Authoritative source for fixture IDs, scores, officials,
    venue and schedule corrections.

MCList is allowed to create historical fixtures that never
appeared in MenFixture.asp.
"""
import logging
import re
import time
from typing import Optional

from src.config.settings import HKHA_PASSWORD
from src.config.teams import TEAMS
from src.hkha.auth import login
from src.hkha.men_fixture import get_public_fixtures
from src.hkha.team_fixtures import get_fixture_list
from src.airtable.matches import upsert_match

logger = logging.getLogger(__name__)

INTER_TEAM_DELAY = 2


def _normalise_team(name: str) -> str:
    return re.sub(r'\s+', ' ', name.strip().lower())


def _normalise_date(date_str: str) -> str:
    parts = date_str.strip().split('/')
    if len(parts) == 3:
        return f'{parts[2]}-{parts[1]}-{parts[0]}'
    return date_str.strip()


def _composite_key(fixture: dict) -> tuple:
    return (
        _normalise_date(fixture.get('date', '')),
        _normalise_team(fixture.get('home_team', '')),
        _normalise_team(fixture.get('away_team', '')),
    )


def run_public(seen_ids: Optional[set] = None) -> tuple[set, dict]:
    if seen_ids is None:
        seen_ids = set()

    no_id_by_key = {}

    logger.info('--- Phase 1a: MenFixture.asp (public, no auth) ---')

    fixtures = get_public_fixtures(hkfc_only=True)
    upserted = 0

    for f in fixtures:
        record_id = upsert_match(f)

        no_id_by_key[_composite_key(f)] = {
            **f,
            'record_id': record_id,
        }

        upserted += 1

    logger.info(
        'Phase 1a complete: %d upserted, %d awaiting ID from MCList',
        upserted,
        len(no_id_by_key),
    )

    return seen_ids, no_id_by_key


def run_mclist(seen_ids: Optional[set] = None, no_id_by_key: Optional[dict] = None) -> set:
    if seen_ids is None:
        seen_ids = set()

    if no_id_by_key is None:
        no_id_by_key = {}

    logger.info('--- Phase 1b: MCList.asp (per-team, authenticated) ---')

    total_processed = 0

    for team in TEAMS:
        logger.info('  Team: %s', team)

        try:
            session = login(team, HKHA_PASSWORD)
            fixtures = get_fixture_list(session, hkfc_only=True)
        except Exception as exc:
            logger.error('  Failed to get fixtures for %s: %s', team, exc)
            time.sleep(INTER_TEAM_DELAY)
            continue

        processed_for_team = 0

        for f in fixtures:
            fid = f.get('fixture_id')

            if fid:
                seen_ids.add(fid)

            key = _composite_key(f)
            if key in no_id_by_key:
                logger.debug(
                    'Resolved MenFixture fixture with HKHA fixture id %s',
                    fid,
                )

            try:
                upsert_match(f)
                processed_for_team += 1
            except Exception as exc:
                logger.error('Failed to upsert fixture %s: %s', fid, exc)

        logger.info('  %s: %d fixture(s) processed', team, processed_for_team)
        total_processed += processed_for_team
        time.sleep(INTER_TEAM_DELAY)

    logger.info('Phase 1b complete: %d fixture(s) processed from MCList', total_processed)
    return seen_ids


def run(source: str = 'all') -> None:
    seen_ids = set()
    no_id_by_key = {}

    if source in ('public', 'all'):
        seen_ids, no_id_by_key = run_public(seen_ids)

    if source in ('mclist', 'all'):
        seen_ids = run_mclist(seen_ids, no_id_by_key)

    logger.info(
        'Fixture discovery complete: %d fixture id(s) observed',
        len(seen_ids),
    )
