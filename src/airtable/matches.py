"""
Matches table operations.

Handles date-format conversion (DD/MM/YYYY → ISO 8601),
score parsing (string → int | None), and the Airtable field
schema for the Matches table.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .client import MATCHES_TABLE

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> Optional[str]:
    if not date_str or not date_str.strip():
        return None
    try:
        d = datetime.strptime(date_str.strip(), '%d/%m/%Y')
        return d.strftime('%Y-%m-%dT00:00:00.000Z')
    except ValueError:
        logger.warning(f'Could not parse date: {date_str!r}')
        return None


def _parse_score(val) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _composite_key(match: dict) -> str:
    return '|'.join([
        match.get('date', ''),
        match.get('home_team', ''),
        match.get('away_team', ''),
    ])


def upsert_match(match: dict) -> Optional[str]:
    home_score = _parse_score(match.get('home_score'))
    away_score = _parse_score(match.get('away_score'))
    is_played = home_score is not None and away_score is not None

    fixture_id = match.get('fixture_id')

    fields = {
        'Match Status': 'Played' if is_played else 'Scheduled',
        'Last HKHA Sync': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        'Source': 'HKHA Sync',
        'Fixture Lookup Key': str(fixture_id) if fixture_id else _composite_key(match),
    }

    if fixture_id:
        fields['Fixture Id'] = str(fixture_id)

    iso_date = _parse_date(match.get('date', ''))
    if iso_date:
        fields['Date'] = iso_date

    for key, col in [('division', 'Division'), ('home_team', 'Home Team'), ('away_team', 'Away Team'), ('venue', 'Venue')]:
        val = match.get(key)
        if val:
            fields[col] = val

    if home_score is not None:
        fields['Home Score'] = home_score
    if away_score is not None:
        fields['Away Score'] = away_score

    result = MATCHES_TABLE.batch_upsert(
        [{'fields': fields}],
        key_fields=['Fixture Lookup Key'],
    )

    return result[0]['id'] if result else None


def get_played_fixtures(lookback_days: int = 30) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    formula = f"AND({{Match Status}} = 'Played',IS_AFTER({{Date}}, '{cutoff}'))"

    try:
        records = MATCHES_TABLE.all(formula=formula, fields=['Fixture Id', 'Date', 'Home Team', 'Away Team'])
    except Exception as exc:
        logger.error(f'Failed to query played fixtures: {exc}')
        return []

    return [{
        'fixture_id': r['fields'].get('Fixture Id', ''),
        'date': r['fields'].get('Date', ''),
        'home_team': r['fields'].get('Home Team', ''),
        'away_team': r['fields'].get('Away Team', ''),
        'record_id': r['id'],
    } for r in records if r['fields'].get('Fixture Id')]