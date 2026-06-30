"""
Phase 2 — Match Card Scraping
"""
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from src.config.settings import HKHA_PASSWORD, LOOKBACK_DAYS, RECENT_DAYS
from src.config.teams import TEAMS
from src.hkha.auth import login
from src.hkha.match_cards import get_match_card
from src.airtable.matches import get_played_fixtures
from src.airtable.match_cards import upsert_match_cards
from src.airtable.sync_state import get_sync_state_map, mark_scraped

logger = logging.getLogger(__name__)

_INTER_FIXTURE_DELAY = 0.5
_INTER_TEAM_DELAY = 2

def _needs_scrape(state: dict, fixture_date_str: str, recent_days: int) -> bool:
    status = state.get('Sync Status')
    if status is None or status == 'Error':
        return True
    if status != 'Complete':
        return True
    try:
        now = datetime.now(timezone.utc)
        if fixture_date_str:
            fixture_dt = datetime.fromisoformat(fixture_date_str.replace('Z', '+00:00'))
            if fixture_dt < now - timedelta(days=recent_days):
                return False
        last_str = state.get('Last Scraped', '')
        if last_str:
            last_dt = datetime.fromisoformat(last_str.replace('Z', '+00:00'))
            if (now - last_dt) < timedelta(hours=20):
                return False
    except (ValueError, TypeError):
        pass
    return True

def _infer_source_team(fixture: dict, state: dict) -> str:
    stored = state.get('Source Team')
    if stored and stored in TEAMS:
        return stored

    for field in ('home_team', 'away_team'):
        val = fixture.get(field, '')
        for team in TEAMS:
            if team in val:
                return team

    raise ValueError(
        f"Unable to determine source team for fixture {fixture.get('fixture_id')}"
    )


def run(lookback_days: int = LOOKBACK_DAYS, recent_days: int = RECENT_DAYS) -> None:
    logger.info('--- Phase 2: Match Card Sync (lookback=%dd, recent=%dd) ---', lookback_days, recent_days)
    played = get_played_fixtures(lookback_days=lookback_days)
    if not played:
        return

    fixture_ids = [f['fixture_id'] for f in played]
    sync_states = get_sync_state_map(fixture_ids)

    to_scrape = [f for f in played if _needs_scrape(sync_states.get(f['fixture_id'], {}), f.get('date', ''), recent_days)]

    by_team: Dict[str, List[dict]] = defaultdict(list)
    for f in to_scrape:
        try:
            team = _infer_source_team(f, sync_states.get(f['fixture_id'], {}))
            by_team[team].append(f)
        except Exception as exc:
            mark_scraped(f['fixture_id'], status='Error', error=str(exc))
            logger.error(str(exc))

    total_ok = total_err = 0
    for team, fixtures in by_team.items():
        try:
            session = login(team, HKHA_PASSWORD)
        except Exception as exc:
            for f in fixtures:
                mark_scraped(f['fixture_id'], status='Error', error=f'Login failed: {exc}')
                total_err += 1
            continue

        for f in fixtures:
            fid = f['fixture_id']
            try:
                result = get_match_card(session, fid)
                upsert_match_cards(result.get('players', []), fid, f.get('record_id'))
                mark_scraped(fid, status='Complete', match_record_id=f.get('record_id'))
                total_ok += 1
            except Exception as exc:
                mark_scraped(fid, status='Error', error=str(exc))
                total_err += 1
            time.sleep(_INTER_FIXTURE_DELAY)

        time.sleep(_INTER_TEAM_DELAY)

    logger.info('Phase 2 complete: %d synced, %d errors', total_ok, total_err)
