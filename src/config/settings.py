from os import getenv

HKHA_BASE_URL = 'https://www.hockey.org.hk'
LOGIN_URL = f'{HKHA_BASE_URL}/Login.asp'
MCLIST_URL = f'{HKHA_BASE_URL}/MCList.asp'
MCINFO_URL = f'{HKHA_BASE_URL}/MCInfo.asp'

AIRTABLE_TOKEN = getenv('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = getenv('AIRTABLE_BASE_ID')
HKHA_PASSWORD = getenv('HKHA_PASSWORD')
