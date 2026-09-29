from os import getenv
from dotenv import load_dotenv

load_dotenv()

# ── HKHA URLs ────────────────────────────────────────────────────────────────
HKHA_BASE_URL = 'https://www.hockey.org.hk'
LOGIN_URL     = f'{HKHA_BASE_URL}/Login.asp'
MCLIST_URL    = f'{HKHA_BASE_URL}/MCList.asp'
MCINFO_URL    = f'{HKHA_BASE_URL}/MCInfo.asp'

# ── Where the sync writes ────────────────────────────────────────────────────
# 'airtable' (the Hockey Members base) or 'supabase' (Eddy's database, from
# the October 2026 switch-over). One run writes to one of them.
SYNC_BACKEND = (getenv('SYNC_BACKEND') or 'airtable').strip().lower()

# Supabase only: read everything, log what would be written, write nothing.
SUPABASE_DRY_RUN = (getenv('SUPABASE_DRY_RUN') or '').strip().lower() in ('1', 'true', 'yes', 'on')

# ── Secrets (injected via environment / GitHub Secrets) ───────────────────────
AIRTABLE_TOKEN   = getenv('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = getenv('AIRTABLE_BASE_ID')
HKHA_PASSWORD    = getenv('HKHA_PASSWORD')

# The project URL (https://<ref>.supabase.co) and its secret key (sb_secret_…),
# which belongs to the service role.
SUPABASE_URL        = getenv('SUPABASE_URL')
SUPABASE_SECRET_KEY = getenv('SUPABASE_SECRET_KEY')

# ── Sync window ───────────────────────────────────────────────────────────────
# Look back this many days when querying Matches for cards to scrape.
LOOKBACK_DAYS = int(getenv('LOOKBACK_DAYS', '30'))

# Re-scrape a fixture that already has status=Complete if it is within
# this many days (scores / disciplinary records can arrive late).
RECENT_DAYS = int(getenv('RECENT_DAYS', '14'))
