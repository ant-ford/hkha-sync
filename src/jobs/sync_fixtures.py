"""
Phase 1 — Fixture Discovery

Sources (in order):
  1. MenFixture.asp (public, no auth)
     Current-season fixtures for all men's teams.
     Primary source — run first so the testing workflow can verify
     the public page alone before introducing per-team logins.

  2. MCList.asp (per-team, authenticated)
     Supplements with fixtures missing from MenFixture.asp:
       • Previous-season results still in team accounts
       • Cup / shield fixtures published on team pages before the public page
       • Any fixture that MenFixture.asp returned without a fixture_id

Deduplication strategy
──────────────────────
A ``seen_fixture_ids`` set tracks every fixture_id processed so far.
The MCList pass skips any fixture_id already in that set.

For MenFixture.asp rows where no fixture_id could be extracted, a
composite-key lookup is built:

    (normalised_date, normalised_home, normalised_away)
        → fixture dict (without ID)

When MCList.asp later returns the same fixture (with its fixture_id),
it is treated as new and upserted — the Airtable upsert key (Match Key)
ensures no duplicate Matches record is created.

Test workflow
─────────────
  # Step 1 — public fixtures only
  python src/main.py --job fixtures --source public

  # Step 2 — add per-team MCList fixtures
  python src/main.py --job fixtures --source mclist

  # Normal combined run (both sources)
  python src/main.py --job fixtures
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
from src.airtable.sync_state import mark_fixture_discovered

logger = logging.getLogger(__name__)

INTER_TEAM_DELAY = 2   # seconds between HKHA team logins


# ── Composite key helpers ─────────────────────────────────────────────────────

def _normalise_team(name: str) -> str:
    """Lower-case and collapse whitespace for fuzzy team matching."""
    return re.sub(r'\s+', ' ', name.strip().lower())


def _normalise_date(date_str: str) -> str:
    """DD/MM/YYYY → YYYY-MM-DD for consistent comparison."""
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


# ── Phase 1a — MenFixture.asp ─────────────────────────────────────────────────

# ── Phase 1a — MenFixture.asp ─────────────────────────────────────────────────

def run_public(seen_ids: Optional[set] = None) -> tuple[set, dict]:
    """
    Scrape MenFixture.asp and upsert all HKFC fixtures.

    MenFixture.asp is now the authoritative source for scheduled fixtures.
    These fixtures are inserted immediately, even though they do not yet
    have HKHA Fixture IDs.

    Returns:
        seen_ids:      Updated set of fixture_ids processed.
                       (normally unchanged because MenFixture has no IDs)

        no_id_by_key:  {composite_key: fixture}
                       Used later by MCList.asp to resolve Fixture IDs.
    """
    if seen_ids is None:
        seen_ids = set()

    no_id_by_key: dict = {}

    logger.info('--- Phase 1a: MenFixture.asp (public, no auth) ---')

    fixtures = get_public_fixtures(hkfc_only=True)

    upserted = 0

    for f in fixtures:
        try:
            record_id = upsert_match(f)

            key = _composite_key(f)

            no_id_by_key[key] = {
                **f,
                'record_id': record_id,
            }

            upserted += 1

        except Exception as exc:
            logger.error(
                'Failed to upsert MenFixture fixture %s %s v %s: %s',
                f.get('date'),
                f.get('home_team'),
                f.get('away_team'),
                exc,
            )

    logger.info(
        'Phase 1a complete: %d upserted, %d awaiting ID from MCList',
        upserted,
        len(no_id_by_key),
    )

    return seen_ids, no_id_by_key


# ── Phase 1b — MCList.asp (per-team) ─────────────────────────────────────────

def run_mclist(seen_ids: Optional[set] = None, no_id_by_key: Optional[dict] = None) -> set:
    """
    Scrape MCList.asp for each team, supplement the Matches table.

    Skips fixture_ids already in *seen_ids*.  Detects fixtures that
    were in MenFixture.asp without an ID via *no_id_by_key* and logs
    when they are resolved (the upsert handles dedup automatically).

    Returns:
        Updated seen_ids set.
    """
    if seen_ids is None:
        seen_ids = set()
    if no_id_by_key is None:
        no_id_by_key = {}

    logger.info('--- Phase 1b: MCList.asp (per-team, authenticated) ---')
    total_new = 0

    for team in TEAMS:
        logger.info('  Team: %s', team)
        try:
            session = login(team, HKHA_PASSWORD)
            fixtures = get_fixture_list(session, hkfc_only=True)
        except Exception as exc:
            logger.error('  Failed to get fixtures for %s: %s', team, exc)
            time.sleep(INTER_TEAM_DELAY)
            continue

        new_for_team = 0
        for f in fixtures:
            fid = f.get('fixture_id')
            if not fid:
                logger.debug('  MCList row without fixture_id — skipping')
                continue

            if fid in seen_ids:
                continue
            seen_ids.add(fid)

            # Log if this resolves a MenFixture.asp no-ID row
            key = _composite_key(f)
            if key in no_id_by_key:
                logger.debug(
                    '  Resolved MenFixture no-ID row → fixture_id %s (%s %s v %s)',
                    fid, f.get('date'), f.get('home_team'), f.get('away_team'),
                )

            try:
                record_id = upsert_match(f)
                mark_fixture_discovered(fid, source_team=team, match_record_id=record_id)
                new_for_team += 1
            except Exception as exc:
                logger.error('  Failed to upsert fixture %s: %s', fid, exc)

        logger.info('  %s: %d new fixture(s)', team, new_for_team)
        total_new += new_for_team
        time.sleep(INTER_TEAM_DELAY)

    logger.info('Phase 1b complete: %d new fixture(s) from MCList', total_new)
    return seen_ids


# ── Combined entry point ───────────────────────────────────────────────────────

def run(source: str = 'all') -> None:
    """
    Run fixture discovery.

    Args:
        source: 'public'  – MenFixture.asp only  (use for initial testing)
                'mclist'  – MCList.asp only
                'all'     – both sources (default)
    """
    seen_ids: set = set()
    no_id_by_key: dict = {}

    if source in ('public', 'all'):
        seen_ids, no_id_by_key = run_public(seen_ids)

    if source in ('mclist', 'all'):
        seen_ids = run_mclist(seen_ids, no_id_by_key)

    logger.info(
        'Fixture discovery complete: %d unique HKFC fixture(s) processed',
        len(seen_ids),
    )
