"""
Phase 2 — Match Card Scraping

Queries Matches for played fixtures within the lookback window,
cross-references HKHA Sync State to find those needing (re-)scraping,
then fetches match cards from MCInfo.asp and upserts to Match Cards.

Incremental logic
──────────────────
  Never synced         → always scrape
  Sync Status = Error  → always retry
  Sync Status = Complete AND fixture within RECENT_DAYS
                       → re-scrape once per day
                         (scores / disciplinary records can arrive late)
  Sync Status = Complete AND fixture older than RECENT_DAYS
                       → skip (data is stable)

Session reuse
─────────────
Fixtures are grouped by their recorded Source Team so that only one
login per team account is needed per run.  If no Source Team is stored
(e.g. discovered by the Make.com legacy scenario), the team is inferred
from the home/away fields.
"""
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.config.settings import HKHA_PASSWORD, LOOKBACK_DAYS, RECENT_DAYS
from src.config.teams import TEAMS
from src.hkha.auth import login
from src.hkha.match_cards import get_match_card
from src.airtable.matches import get_played_fixtures
from src.airtable.match_cards import upsert_match_cards
from src.airtable.sync_state import get_sync_state_map, mark_scraped

logger = logging.getLogger(__name__)

_INTER_FIXTURE_DELAY = 0.5   # seconds between HKHA MCInfo requests
_INTER_TEAM_DELAY    = 2     # seconds between new team logins


# ── Incremental decision ──────────────────────────────────────────────────────

def _needs_scrape(state: dict, fixture_date_str: str, recent_days: int) -> bool:
    """
    Return True if this fixture should be (re-)scraped this run.

    Args:
        state:            Fields dict from HKHA Sync State (empty dict if not found).
        fixture_date_str: ISO datetime string from Airtable Matches.Date field.
        recent_days:      Re-scrape window in days.
    """
    status = state.get('Sync Status')

    if status is None or status == 'Error':
        return True

    if status != 'Complete':
        return True

    # Already complete — only re-scrape if the fixture is recent
    try:
        now = datetime.now(timezone.utc)

        # Was the match played recently?
        if fixture_date_str:
            fixture_dt = datetime.fromisoformat(
                fixture_date_str.replace('Z', '+00:00')
            )
            if fixture_dt < now - timedelta(days=recent_days):
                return False   # Old and complete — skip

        # Was it scraped today already?
        last_str = state.get('Last Scraped', '')
        if last_str:
            last_dt = datetime.fromisoformat(last_str.replace('Z', '+00:00'))
            if (now - last_dt) < timedelta(hours=20):
                return False   # Already refreshed today

    except (ValueError, TypeError):
        pass   # Unparseable dates — default to scraping

    return True


# ── Team inference ─────────────────────────────────────────────────────────────

def _infer_source_team(fixture: dict, state: dict) -> str:
    """
    Determine which HKFC team account to use for scraping.

    Priority:
      1. Stored Source Team in HKHA Sync State.
      2. Home / away team field matches a known team.
      3. Fall back to first team in TEAMS list.
    """
    stored = state.get('Source Team')
    if stored and stored in TEAMS:
        return stored

    for field in ('home_team', 'away_team'):
        val = fixture.get(field, '')
        for team in TEAMS:
            if team in val:
                return team

    logger.debug(
        'Could not infer team for fixture %s — defaulting to %s',
        fixture.get('fixture_id'), TEAMS[0],
    )
    return TEAMS[0]


# ── Main entry point ──────────────────────────────────────────────────────────

def run(lookback_days: int = LOOKBACK_DAYS, recent_days: int = RECENT_DAYS) -> None:
    """
    Scrape match cards for all played fixtures needing (re-)sync.

    Args:
        lookback_days: How far back to look in the Matches table.
        recent_days:   Fixtures within this window are re-scraped daily.
    """
    logger.info(
        '--- Phase 2: Match Card Sync (lookback=%dd, recent=%dd) ---',
        lookback_days, recent_days,
    )

    # ── Step 1: get played fixtures within window ─────────────────────────────
    played = get_played_fixtures(lookback_days=lookback_days)
    if not played:
        logger.info('No played fixtures found within lookback window — nothing to do.')
        return
    logger.info('Found %d played fixture(s) in lookback window', len(played))

    # ── Step 2: cross-reference sync state ───────────────────────────────────
    fixture_ids = [f['fixture_id'] for f in played]
    sync_states = get_sync_state_map(fixture_ids)

    # ── Step 3: filter to those that need scraping ────────────────────────────
    to_scrape: List[dict] = [
        f for f in played
        if _needs_scrape(
            sync_states.get(f['fixture_id'], {}),
            f.get('date', ''),
            recent_days,
        )
    ]
    logger.info(
        '%d fixture(s) need scraping (%d skipped as up-to-date)',
        len(to_scrape), len(played) - len(to_scrape),
    )

    if not to_scrape:
        return

    # ── Step 4: group by team to minimise logins ──────────────────────────────
    by_team: Dict[str, List[dict]] = defaultdict(list)
    for f in to_scrape:
        state = sync_states.get(f['fixture_id'], {})
        team  = _infer_source_team(f, state)
        by_team[team].append(f)

    # ── Step 5: scrape ────────────────────────────────────────────────────────
    total_ok = total_err = 0

    for team, fixtures in by_team.items():
        logger.info('  Logging in as %s to scrape %d fixture(s)', team, len(fixtures))
        try:
            session = login(team, HKHA_PASSWORD)
        except Exception as exc:
            logger.error('  Login failed for %s: %s — marking %d as Error', team, exc, len(fixtures))
            for f in fixtures:
                mark_scraped(f['fixture_id'], status='Error', error=f'Login failed: {exc}')
                total_err += 1
            continue

        for f in fixtures:
            fid           = f['fixture_id']
            match_rec_id  = f.get('record_id')

            try:
                result  = get_match_card(session, fid)
                players = result.get('players', [])

                upsert_match_cards(
                    players,
                    fixture_id=fid,
                    match_record_id=match_rec_id,
                )
                mark_scraped(fid, status='Complete', match_record_id=match_rec_id)

                logger.info(
                    '  ✓ %s: %d HKFC player(s) synced', fid, len(players)
                )
                total_ok += 1

            except Exception as exc:
                logger.error('  ✗ %s failed: %s', fid, exc)
                mark_scraped(fid, status='Error', error=str(exc))
                total_err += 1

            time.sleep(_INTER_FIXTURE_DELAY)

        time.sleep(_INTER_TEAM_DELAY)

    logger.info(
        'Phase 2 complete: %d synced, %d errors', total_ok, total_err,
    )
    
