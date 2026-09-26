"""
Matches table operations.

Match Key is used to create fixtures before a HKHA Fixture Id exists.
Once a Fixture Id becomes available it becomes the authoritative identifier.

A record with LOCK_FIELD ticked has been corrected by hand (typically a
placeholder fixture HKHA published before the teams or date were known).
The sync only fills that record's blank fields and never overwrites a
value that is already there.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from .client import MATCHES_TABLE

logger = logging.getLogger(__name__)

LOCK_FIELD = 'Lock HKHA Sync'

HK_TZ = timezone(timedelta(hours=8))

# Fields the sync may write, read back for locked records so we can tell
# which of them are still blank.
_SYNCED_FIELDS = [
    'Fixture Id', 'Match Key', 'Match Status', 'Date', 'Division',
    'Home Team', 'Away Team', 'Venue', 'Ump 1', 'Ump 2',
    'Home Score', 'Away Score',
]

_FIXTURE_ID_CACHE = None
_MATCH_KEY_CACHE = None
_LOCKED_RECORDS = None   # record id -> current fields
_LOCKED_BY_KEY = None    # match key -> record id


def _fetch_match_index() -> list[dict]:
    try:
        return MATCHES_TABLE.all(fields=_SYNCED_FIELDS + [LOCK_FIELD])
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 422:
            raise
        logger.warning(
            'Matches has no "%s" checkbox; hand-fixed fixtures are not protected', LOCK_FIELD,
        )
        return MATCHES_TABLE.all(fields=['Fixture Id', 'Match Key'])


def _record_match_keys(fields: dict) -> set[str]:
    """
    Match Keys a locked record answers to: the one it was created with, and
    one built from its corrected date and teams. The second lets HKHA's own
    corrected version of the fixture land on this record instead of
    creating a duplicate.
    """
    keys = set()

    if fields.get('Match Key'):
        keys.add(fields['Match Key'])

    date_val = fields.get('Date')
    home = (fields.get('Home Team') or '').strip()
    away = (fields.get('Away Team') or '').strip()

    if date_val and home and away:
        try:
            dt = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        except ValueError:
            return keys

        # The sync writes HK wall-clock times without an offset, while a date
        # typed into Airtable is stored as true HK time; accept either day.
        for day in {dt.astimezone(timezone.utc).date(), dt.astimezone(HK_TZ).date()}:
            keys.add('|'.join([day.isoformat(), home, away]))

    return keys


def _load_fixture_id_cache():
    global _FIXTURE_ID_CACHE, _MATCH_KEY_CACHE, _LOCKED_RECORDS, _LOCKED_BY_KEY

    if _FIXTURE_ID_CACHE is not None:
        return _FIXTURE_ID_CACHE

    fixture_cache = {}
    match_cache = {}
    locked_records = {}
    locked_by_key = {}

    try:
        records = _fetch_match_index()

        for record in records:
            fields = record.get('fields', {})

            fixture_id = fields.get('Fixture Id')
            if fixture_id:
                fixture_cache[str(fixture_id)] = record['id']

            match_key = fields.get('Match Key')
            if match_key:
                match_cache[match_key] = bool(fixture_id)

            if fields.get(LOCK_FIELD):
                locked_records[record['id']] = fields
                for key in _record_match_keys(fields):
                    locked_by_key[key] = record['id']

        logger.info(
            'Loaded %s fixture ids into cache, %s locked match(es)',
            len(fixture_cache),
            len(locked_records),
        )

    except Exception:
        logger.exception('Failed loading fixture id cache')

    _FIXTURE_ID_CACHE = fixture_cache
    _MATCH_KEY_CACHE = match_cache
    _LOCKED_RECORDS = locked_records
    _LOCKED_BY_KEY = locked_by_key
    return fixture_cache


def _locked_record_id(fixture_id: Optional[str], match_key: str) -> Optional[str]:
    cache = _load_fixture_id_cache()

    # A Fixture Id already held by a record decides which record this is.
    if fixture_id and fixture_id in cache:
        record_id = cache[fixture_id]
        return record_id if record_id in _LOCKED_RECORDS else None

    return _LOCKED_BY_KEY.get(match_key)


def _fill_locked_record(record_id: str, fields: dict) -> str:
    """Write only the fields the locked record still has blank."""
    current = _LOCKED_RECORDS[record_id]

    def blank(name):
        return current.get(name) in (None, '')

    updates = {
        name: value
        for name, value in fields.items()
        if name not in ('Match Key', 'Match Status', 'Last HKHA Sync', 'Home Score', 'Away Score')
        and blank(name)
    }

    # A result only counts as a pair, and it is what makes the match Played.
    if (
        'Home Score' in fields and 'Away Score' in fields
        and blank('Home Score') and blank('Away Score')
    ):
        updates['Home Score'] = fields['Home Score']
        updates['Away Score'] = fields['Away Score']
        updates['Match Status'] = 'Played'

    if not updates:
        logger.debug('Locked match %s: nothing blank to fill', record_id)
        return record_id

    updates['Last HKHA Sync'] = fields['Last HKHA Sync']
    MATCHES_TABLE.update(record_id, updates)
    current.update(updates)

    if 'Fixture Id' in updates:
        _FIXTURE_ID_CACHE[updates['Fixture Id']] = record_id

    logger.info('Locked match %s: filled %s', record_id, ', '.join(sorted(updates)))
    return record_id


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
        locked_id = _locked_record_id(fixture_id, match_key)
        if locked_id:
            return _fill_locked_record(locked_id, fields)

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