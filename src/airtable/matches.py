"""
Matches table operations.

Match Key is used to create fixtures before a HKHA Fixture Id exists.
Once a Fixture Id becomes available it becomes the authoritative identifier.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from .client import MATCHES_TABLE

logger = logging.getLogger(__name__)

_FIXTURE_ID_CACHE = None
_MATCH_KEY_CACHE = None


def _load_fixture_id_cache():
    global _FIXTURE_ID_CACHE, _MATCH_KEY_CACHE

    if _FIXTURE_ID_CACHE is not None:
        return _FIXTURE_ID_CACHE

    fixture_cache = {}
    match_cache = {}

    try:
        records = MATCHES_TABLE.all(fields=['Fixture Id', 'Match Key'])

        for record in records:
            fields = record.get('fields', {})

            fixture_id = fields.get('Fixture Id')
            if fixture_id:
                fixture_cache[str(fixture_id)] = record['id']

            match_key = fields.get('Match Key')
            if match_key:
                match_cache[match_key] = bool(fixture_id)

        logger.info('Loaded %s fixture ids into cache', len(fixture_cache))

    except Exception:
        logger.exception('Failed loading fixture id cache')

    _FIXTURE_ID_CACHE = fixture_cache
    _MATCH_KEY_CACHE = match_cache
    return fixture_cache


def _match_has_fixture_id(match_key: str) -> bool:
    _load_fixture_id_cache()
    return _MATCH_KEY_CACHE.get(match_key, False)


def _parse_datetime(date_str: str, time_str: str | None = None) -> Optional[str]:
    if not date_str:
        return None

    try:
        date_part = datetime.strptime(date_str.strip(), '%d/%m/%Y')

        if time_str and time_str != 'TBC':
            time_part = datetime.strptime(time_str.strip(), '%H:%M')
            dt = date_part.replace(hour=time_part.hour, minute=time_part.minute)
        else:
            dt = date_part

        return dt.strftime('%Y-%m-%dT%H:%M:%S.000')

    except ValueError:
        logger.warning('Could not parse datetime: %s %s', date_str, time_str)
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


def _match_key(match: dict) -> str:
    try:
        dt = datetime.strptime(match.get('date', ''), '%d/%m/%Y')
        date_part = dt.strftime('%Y-%m-%d')
    except ValueError:
        date_part = match.get('date', '')

    return '|'.join([date_part, match.get('home_team', '').strip(), match.get('away_team', '').strip()])


def upsert_match(match: dict) -> Optional[str]:
    home_score = _parse_score(match.get('home_score'))
    away_score = _parse_score(match.get('away_score'))

    is_played = home_score is not None and away_score is not None
    match_key = _match_key(match)

    fixture_id = match.get('fixture_id')

    # MenFixture records have no Fixture Id.
    # Once MCList has attached a Fixture Id, MenFixture must no longer
    # overwrite the authoritative record.
    if not fixture_id and _match_has_fixture_id(match_key):
        logger.debug('Skipping MenFixture update for %s because Fixture Id already exists', match_key)
        return None

    fields = {
        'Match Key': match_key,
        'Match Status': 'Played' if is_played else match.get('match_status', 'Scheduled'),
        'Last HKHA Sync': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
    }

    if fixture_id:
        fixture_id = str(fixture_id)
        fields['Fixture Id'] = fixture_id

    iso_datetime = _parse_datetime(match.get('date', ''), match.get('time'))
    if iso_datetime:
        fields['Date'] = iso_datetime

    mappings = {
        'division': 'Division',
        'home_team': 'Home Team',
        'away_team': 'Away Team',
        'venue': 'Venue',
        'umpire1': 'Ump 1',
        'umpire2': 'Ump 2',
    }

    for source_field, airtable_field in mappings.items():
        value = match.get(source_field)
        if value:
            fields[airtable_field] = value

    if home_score is not None:
        fields['Home Score'] = home_score

    if away_score is not None:
        fields['Away Score'] = away_score

    try:
        if fixture_id:
            cache = _load_fixture_id_cache()
            record_id = cache.get(fixture_id)

            if record_id:
                MATCHES_TABLE.update(record_id, fields)
                return record_id

        result = MATCHES_TABLE.batch_upsert(
            [{'fields': fields}],
            key_fields=['Match Key'],
        )

        records = result.get('records', []) if result else []

        if records and fixture_id:
            cache = _load_fixture_id_cache()
            cache[fixture_id] = records[0]['id']
            _MATCH_KEY_CACHE[match_key] = True

        return records[0]['id'] if records else None

    except Exception:
        logger.exception('Failed to upsert match %s', match_key)
        return None


def get_played_fixtures(lookback_days: int = 30) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

    formula = f"AND({{Match Status}}='Played',IS_AFTER({{Date}}, '{cutoff}'))"

    try:
        records = MATCHES_TABLE.all(
            formula=formula,
            fields=['Fixture Id', 'Date', 'Home Team', 'Away Team'],
        )
    except Exception as exc:
        logger.error('Failed to query played fixtures: %s', exc)
        return []

    fixtures = []

    for r in records:
        fields = r.get('fields', {})
        fixture_id = fields.get('Fixture Id')

        if fixture_id:
            fixtures.append({
                'fixture_id': fixture_id,
                'date': fields.get('Date', ''),
                'home_team': fields.get('Home Team', ''),
                'away_team': fields.get('Away Team', ''),
                'record_id': r['id'],
            })

    return fixtures