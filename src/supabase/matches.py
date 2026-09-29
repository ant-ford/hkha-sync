"""
public.matches in Eddy's database: the same rules as the Airtable Matches
table (src/airtable/matches.py).

A fixture is created on its match key (date|home|away) before HKHA gives it
a Fixture Id; once it has one, the Fixture Id decides which row it is, and
MenFixture.asp (which has no Fixture Id) no longer writes to it.

A row with lock_hkha_sync set was corrected by hand. The sync only fills its
blank columns and never overwrites a value already there.

Unlike Airtable, a row is written only when HKHA changed something, so
last_hkha_sync is when the sync last changed the row, and updated_at is not
bumped on every run.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.hkha.fixture_fields import HK_TZ, parse_datetime, parse_score, match_key as build_match_key

from .client import select, insert, update, eq

logger = logging.getLogger(__name__)

# Columns the sync writes (besides last_hkha_sync).
_SYNCED = [
    'fixture_id', 'match_key', 'match_status', 'match_date', 'division',
    'home_team', 'away_team', 'venue', 'ump_1', 'ump_2',
    'home_score', 'away_score',
]

# From the source fixture dict to the column; written only when HKHA has a value.
_TEXT_COLUMNS = {
    'division': 'division',
    'home_team': 'home_team',
    'away_team': 'away_team',
    'venue': 'venue',
    'umpire1': 'ump_1',
    'umpire2': 'ump_2',
}

_rows: Optional[dict[str, dict]] = None      # id -> row as last read or written
_by_fixture: dict[str, str] = {}             # fixture id -> id
_by_key: dict[str, str] = {}                 # match key -> id
_locked_by_key: dict[str, str] = {}          # any key a locked row answers to -> id


def _as_datetime(value) -> Optional[datetime]:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def _same(column: str, current, new) -> bool:
    if column in ('match_date', 'last_hkha_sync'):
        return _as_datetime(current) == _as_datetime(new)
    return current == new


def _blank(value) -> bool:
    return value is None or value == ''


def _locked_keys(row: dict) -> set[str]:
    """
    Keys a locked row answers to: the one it was created with, and one from
    its corrected date and teams, so HKHA's own corrected version of the
    fixture lands on it rather than creating a duplicate.
    """
    keys = set()
    if row.get('match_key'):
        keys.add(row['match_key'])
    when = _as_datetime(row.get('match_date'))
    home = (row.get('home_team') or '').strip()
    away = (row.get('away_team') or '').strip()
    if when and home and away:
        keys.add('|'.join([when.astimezone(HK_TZ).date().isoformat(), home, away]))
    return keys


def _index(row: dict) -> None:
    _rows[row['id']] = row
    if row.get('fixture_id'):
        _by_fixture[str(row['fixture_id'])] = row['id']
    if row.get('match_key'):
        _by_key[row['match_key']] = row['id']
    if row.get('lock_hkha_sync'):
        for key in _locked_keys(row):
            _locked_by_key[key] = row['id']


def _load() -> dict[str, dict]:
    global _rows
    if _rows is not None:
        return _rows
    _rows = {}
    for row in select('matches', 'select=id,lock_hkha_sync,' + ','.join(_SYNCED) + '&order=id'):
        _index(row)
    logger.info(
        'Loaded %d match(es), %d with a fixture id, %d locked',
        len(_rows), len(_by_fixture), sum(1 for r in _rows.values() if r.get('lock_hkha_sync')),
    )
    return _rows


def _locked_row_id(fixture_id: Optional[str], key: str) -> Optional[str]:
    _load()
    # A Fixture Id already held by a row decides which row this is.
    if fixture_id and fixture_id in _by_fixture:
        row_id = _by_fixture[fixture_id]
        return row_id if _rows[row_id].get('lock_hkha_sync') else None
    return _locked_by_key.get(key)


def _write(row_id: str, patch: dict, now: str) -> None:
    patch = {**patch, 'last_hkha_sync': now}
    update('matches', f'id={eq(row_id)}', patch)
    _rows[row_id].update(patch)
    _index(_rows[row_id])


def _fill_locked(row_id: str, values: dict, now: str) -> str:
    """Write only the columns the locked row still has blank."""
    current = _rows[row_id]

    patch = {
        column: value
        for column, value in values.items()
        if column not in ('match_key', 'match_status', 'home_score', 'away_score')
        and _blank(current.get(column))
    }

    # A result only counts as a pair, and it is what makes the match Played.
    if (
        'home_score' in values and 'away_score' in values
        and _blank(current.get('home_score')) and _blank(current.get('away_score'))
    ):
        patch['home_score'] = values['home_score']
        patch['away_score'] = values['away_score']
        patch['match_status'] = 'Played'

    if not patch:
        logger.debug('Locked match %s: nothing blank to fill', row_id)
        return row_id

    _write(row_id, patch, now)
    logger.info('Locked match %s: filled %s', row_id, ', '.join(sorted(patch)))
    return row_id


def upsert_match(match: dict) -> Optional[str]:
    """Create or update one fixture from MenFixture.asp or MCList.asp; returns the row id."""
    home_score = parse_score(match.get('home_score'))
    away_score = parse_score(match.get('away_score'))
    is_played = home_score is not None and away_score is not None
    key = build_match_key(match)
    fixture_id = str(match['fixture_id']) if match.get('fixture_id') else None

    try:
        rows = _load()

        # MenFixture rows have no Fixture Id. Once MCList has attached one,
        # MenFixture no longer writes to that row.
        if not fixture_id and key in _by_key and rows[_by_key[key]].get('fixture_id'):
            logger.debug('Skipping MenFixture update for %s because Fixture Id already exists', key)
            return None

        values: dict = {
            'match_key': key,
            'match_status': 'Played' if is_played else match.get('match_status', 'Scheduled'),
        }
        if fixture_id:
            values['fixture_id'] = fixture_id

        when = parse_datetime(match.get('date', ''), match.get('time'))
        if when:
            values['match_date'] = when.isoformat()

        for source, column in _TEXT_COLUMNS.items():
            if match.get(source):
                values[column] = match[source]

        if home_score is not None:
            values['home_score'] = home_score
        if away_score is not None:
            values['away_score'] = away_score

        now = datetime.now(timezone.utc).isoformat()

        locked_id = _locked_row_id(fixture_id, key)
        if locked_id:
            return _fill_locked(locked_id, values, now)

        row_id = (_by_fixture.get(fixture_id) if fixture_id else None) or _by_key.get(key)
        if row_id:
            current = rows[row_id]
            patch = {c: v for c, v in values.items() if not _same(c, current.get(c), v)}
            if patch:
                _write(row_id, patch, now)
                logger.debug('Match %s: updated %s', row_id, ', '.join(sorted(patch)))
            return row_id

        created = insert('matches', [{**values, 'last_hkha_sync': now}])
        if not created:
            return None
        _index({'lock_hkha_sync': False, **values, **created[0]})
        logger.info('Match %s: created (%s)', created[0]['id'], key)
        return created[0]['id']

    except Exception:
        logger.exception('Failed to upsert match %s', key)
        return None


def get_played_fixtures(lookback_days: int = 30) -> list[dict]:
    """Played fixtures with a Fixture Id from the last lookback_days, for Phase 2."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()

    try:
        rows = select(
            'matches',
            'select=id,fixture_id,match_date,home_team,away_team'
            f'&match_status=eq.Played&match_date=gt.{cutoff}&fixture_id=not.is.null&order=match_date',
        )
    except Exception as exc:
        logger.error('Failed to query played fixtures: %s', exc)
        return []

    return [
        {
            'fixture_id': r['fixture_id'],
            'date': r.get('match_date') or '',
            'home_team': r.get('home_team') or '',
            'away_team': r.get('away_team') or '',
            'record_id': r['id'],
        }
        for r in rows
    ]
