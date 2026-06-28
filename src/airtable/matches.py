from datetime import datetime
from .client import MATCHES_TABLE


def upsert_match(match):
    fields = {
        'Fixture Id': str(match['fixture_id']),
        'Date': match.get('date'),
        'Division': match.get('division'),
        'Home Team': match.get('home_team'),
        'Away Team': match.get('away_team'),
        'Home Score': match.get('home_score'),
        'Away Score': match.get('away_score'),
        'Venue': match.get('venue'),
        'Match Status': 'Played',
        'Last HKHA Sync': datetime.utcnow().isoformat(),
        'Source': 'HKHA Match Card'
    }
    MATCHES_TABLE.batch_upsert([{'fields': fields}], key_fields=['Fixture Id'])
