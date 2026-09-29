"""
public.hkha_sync_state in Eddy's database: one row per fixture, recording
when its match card was last scraped and whether that worked.

get_sync_state_map() answers with the Airtable field names ('Sync Status',
'Last Scraped', 'Source Team'), so the Phase 2 job reads either backend the
same way.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .client import select, insert, update, eq, in_list

logger = logging.getLogger(__name__)

_QUERY_BATCH = 100   # fixture ids per in.(…) filter, to keep the URL short


def get_sync_state_map(fixture_ids: List[str]) -> Dict[str, dict]:
    """Return {fixture_id: state} for the given fixture IDs."""
    result: Dict[str, dict] = {}

    for i in range(0, len(fixture_ids), _QUERY_BATCH):
        batch = fixture_ids[i:i + _QUERY_BATCH]
        try:
            rows = select(
                'hkha_sync_state',
                'select=id,fixture_id,sync_status,last_scraped,source_team'
                f'&fixture_id={in_list(batch)}&order=id',
            )
        except Exception as exc:
            logger.error('Sync state batch query failed: %s', exc)
            continue
        for r in rows:
            result[r['fixture_id']] = {
                'Fixture Id': r['fixture_id'],
                'Sync Status': r.get('sync_status'),
                'Last Scraped': r.get('last_scraped') or '',
                'Source Team': r.get('source_team'),
                '_record_id': r['id'],
            }

    logger.debug('Sync state map: %d/%d fixtures found', len(result), len(fixture_ids))
    return result


def mark_scraped(
    fixture_id: str,
    status: str = 'Complete',
    error: Optional[str] = None,
    match_record_id: Optional[str] = None,
) -> None:
    """
    Record a match card scrape attempt.

    Args:
        fixture_id:       HKHA fixture ID.
        status:           'Complete' or 'Error'.
        error:            Error message string (Error status only).
        match_record_id:  public.matches id of the fixture.
    """
    fields: dict = {
        'last_scraped':  datetime.now(timezone.utc).isoformat(),
        'sync_status':   status,
        'error_message': error or '',
    }
    if status == 'Complete':
        fields['match_card_imported'] = True
    if match_record_id:
        fields['match_id'] = match_record_id

    try:
        if not update('hkha_sync_state', f'fixture_id={eq(fixture_id)}', fields):
            insert('hkha_sync_state', [{'fixture_id': str(fixture_id), **fields}])
    except Exception as exc:
        logger.error('Failed to write sync state for %s: %s', fixture_id, exc)
