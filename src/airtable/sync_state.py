"""
HKHA Sync State table operations.

Tracks which fixtures have been scraped, when, via which team account,
and whether the scrape succeeded or errored.

Schema (key fields):
  Fixture Id          singleLineText  – upsert key
  Match               recordLink      – link to Matches table
  Source Team         singleSelect    – which HKHA login found this fixture
  Last Scraped        dateTime
  Match Card Imported checkbox
  Sync Status         singleSelect    – Complete | Error
  Error Message       multilineText
"""
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .client import SYNC_STATE_TABLE

logger = logging.getLogger(__name__)

_QUERY_BATCH = 30    # max fixture IDs per OR() formula
_BATCH_SLEEP = 0.25  # seconds between Airtable API calls


# ── Read ─────────────────────────────────────────────────────────────────────

def get_sync_state_map(fixture_ids: List[str]) -> Dict[str, dict]:
    """
    Return {fixture_id: fields} for the given fixture IDs.

    Uses batched OR() formulas to avoid hitting Airtable formula
    length limits when there are many fixtures.
    """
    if not fixture_ids:
        return {}

    result: Dict[str, dict] = {}

    for i in range(0, len(fixture_ids), _QUERY_BATCH):
        batch = fixture_ids[i:i + _QUERY_BATCH]
        # Quote fixture IDs to handle any special characters
        conditions = [f"{{Fixture Id}} = '{fid}'" for fid in batch]
        formula = f"OR({', '.join(conditions)})"

        try:
            records = SYNC_STATE_TABLE.all(formula=formula)
            for r in records:
                fid = r['fields'].get('Fixture Id')
                if fid:
                    result[fid] = {**r['fields'], '_record_id': r['id']}
        except Exception as exc:
            logger.error('Sync state batch query failed: %s', exc)

        if i + _QUERY_BATCH < len(fixture_ids):
            time.sleep(_BATCH_SLEEP)

    logger.debug('Sync state map: %d/%d fixtures found', len(result), len(fixture_ids))
    return result


# ── Write ─────────────────────────────────────────────────────────────────────

def mark_fixture_discovered(
    fixture_id: str,
    source_team: Optional[str] = None,
    match_record_id: Optional[str] = None,
) -> None:
    """
    Seed the sync state when a fixture is first discovered in Phase 1.

    Only sets Source Team and Match link.  Does NOT overwrite Sync Status
    so that subsequent scrape state (Complete / Error) is preserved.
    """
    fields: dict = {'Fixture Id': str(fixture_id)}

    if source_team:
        fields['Source Team'] = source_team
    if match_record_id:
        fields['Match'] = [match_record_id]

    try:
        SYNC_STATE_TABLE.batch_upsert(
            [{'fields': fields}],
            key_fields=['Fixture Id'],
        )
    except Exception as exc:
        # Non-fatal: source team missing won't block card scraping
        logger.warning('Could not seed sync state for %s: %s', fixture_id, exc)


def mark_scraped(
    fixture_id: str,
    status: str = 'Complete',
    error: Optional[str] = None,
    match_record_id: Optional[str] = None,
) -> None:
    """
    Update the sync state after a match card scrape attempt.

    Args:
        fixture_id:       HKHA fixture ID.
        status:           'Complete' or 'Error'.
        error:            Error message string (Error status only).
        match_record_id:  Airtable record ID for the Matches row.
    """
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    fields: dict = {
        'Fixture Id':   str(fixture_id),
        'Last Scraped': now,
        'Sync Status':  status,
        'Error Message': error or '',
    }

    if status == 'Complete':
        fields['Match Card Imported'] = True

    if match_record_id:
        fields['Match'] = [match_record_id]

    try:
        SYNC_STATE_TABLE.batch_upsert(
            [{'fields': fields}],
            key_fields=['Fixture Id'],
        )
    except Exception as exc:
        logger.error('Failed to write sync state for %s: %s', fixture_id, exc)
        