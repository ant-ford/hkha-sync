"""
The store the sync writes to, chosen by SYNC_BACKEND: the Airtable base, or
Eddy's Supabase database. Both offer the same functions, and only the chosen
one is imported, so a run needs only that backend's secrets.
"""
from src.config.settings import SYNC_BACKEND

if SYNC_BACKEND == 'supabase':
    from src.supabase.matches import upsert_match, get_played_fixtures
    from src.supabase.match_cards import upsert_match_cards
    from src.supabase.sync_state import get_sync_state_map, mark_scraped
    from src.supabase.umpire_duties import sync_umpire_duties
elif SYNC_BACKEND == 'airtable':
    from src.airtable.matches import upsert_match, get_played_fixtures
    from src.airtable.match_cards import upsert_match_cards
    from src.airtable.sync_state import get_sync_state_map, mark_scraped
    from src.airtable.umpire_duties import sync_umpire_duties
else:
    raise ValueError(f"SYNC_BACKEND must be 'airtable' or 'supabase', not {SYNC_BACKEND!r}")

__all__ = ['upsert_match', 'get_played_fixtures', 'upsert_match_cards', 'get_sync_state_map', 'mark_scraped',
           'sync_umpire_duties']
