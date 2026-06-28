from datetime import datetime
from .client import SYNC_STATE_TABLE


def mark_scraped(fixture_id, status='Complete', error=None):
    fields = {
        'Fixture Id': str(fixture_id),
        'Last Scraped': datetime.utcnow().isoformat(),
        'Sync Status': status,
        'Error Message': error or ''
    }
    SYNC_STATE_TABLE.batch_upsert([{'fields': fields}], key_fields=['Fixture Id'])
