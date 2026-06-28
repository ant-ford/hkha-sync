from pyairtable import Api
from src.config.settings import AIRTABLE_TOKEN, AIRTABLE_BASE_ID

api = Api(AIRTABLE_TOKEN)
base = api.base(AIRTABLE_BASE_ID)

MATCHES_TABLE = base.table('Matches')
MATCH_CARDS_TABLE = base.table('Match Cards')
SYNC_STATE_TABLE = base.table('HKHA Sync State')
