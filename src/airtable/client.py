"""
Airtable API client.

pyairtable's default retry (retry=True) already handles 429 responses
using the Retry-After header.  We pass our own Retry object here to
also catch transient 5xx errors and tune the backoff curve.

Rate limits (personal access tokens):
    5 requests/second per workspace.

Callers should add time.sleep(0.25) between consecutive batch calls
to stay safely under the limit without relying entirely on 429 recovery.
"""
from urllib3.util.retry import Retry

from pyairtable import Api

from src.config.settings import AIRTABLE_TOKEN, AIRTABLE_BASE_ID

_retry = Retry(
    total=8,
    backoff_factor=1,                       # 1 s, 2 s, 4 s, 8 s …
    status_forcelist=[429, 500, 502, 503, 504],
    respect_retry_after_header=True,
    allowed_methods=False,                  # retry on any HTTP method
)

api  = Api(AIRTABLE_TOKEN, retry=_retry, timeout=60)
base = api.base(AIRTABLE_BASE_ID)

MATCHES_TABLE    = base.table('Matches')
MATCH_CARDS_TABLE = base.table('Match Cards')
SYNC_STATE_TABLE  = base.table('HKHA Sync State')
