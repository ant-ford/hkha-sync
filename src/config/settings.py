from os import getenv
from dotenv import load_dotenv

load_dotenv()

# ── HKHA URLs ────────────────────────────────────────────────────────────────
HKHA_BASE_URL = 'https://www.hockey.org.hk'
LOGIN_URL     = f'{HKHA_BASE_URL}/Login.asp'
MCLIST_URL    = f'{HKHA_BASE_URL}/MCList.asp'
MCINFO_URL    = f'{HKHA_BASE_URL}/MCInfo.asp'

# ── Secrets (injected via environment / GitHub Secrets) ───────────────────────
AIRTABLE_TOKEN   = getenv('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = getenv('AIRTABLE_BASE_ID')
HKHA_PASSWORD    = getenv('HKHA_PASSWORD')

# ── Sync window ───────────────────────────────────────────────────────────────
# Look back this many days when querying Matches for cards to scrape.
LOOKBACK_DAYS = int(getenv('LOOKBACK_DAYS', '30'))

# Re-scrape a fixture that already has status=Complete if it is within
# this many days (scores / disciplinary records can arrive late).
RECENT_DAYS = int(getenv('RECENT_DAYS', '14'))
