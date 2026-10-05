"""
public.umpire_duties in Eddy's database: every umpiring slot HKHA gives an
HKFC team, from the all-clubs fixture page (src/hkha/umpire_duties.py).
Eddy's umpires take them, and the Umpire Coordinator fills the gaps.

A slot is written only when HKHA changed something. A slot still to be
played that has left HKHA's list (the game moved to another date, or the
duty went to another club) is marked cancelled, never deleted, so anyone
already down for it can be told; if it comes back it is scheduled again.
"""
import logging
from datetime import datetime
from typing import Optional

from src.errors import StoreUnavailable
from src.hkha.fixture_fields import HK_TZ, parse_datetime

from .client import select, insert, update, eq

logger = logging.getLogger(__name__)

_COLUMNS = [
    'duty_key', 'match_date', 'time_tbc', 'division', 'venue',
    'home_team', 'away_team', 'slot', 'duty_team', 'status',
]


def _as_datetime(value) -> Optional[datetime]:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def _same(column: str, current, new) -> bool:
    if column == 'match_date':
        return _as_datetime(current) == _as_datetime(new)
    return current == new


def _row(duty: dict) -> Optional[dict]:
    when = parse_datetime(duty.get('date', ''), duty.get('time'))
    if when is None:
        return None
    return {
        'duty_key': duty['duty_key'],
        'match_date': when.isoformat(),
        'time_tbc': duty.get('time') in (None, '', 'TBC'),
        'division': duty.get('division') or None,
        'venue': duty.get('venue') or None,
        'home_team': duty['home_team'].strip(),
        'away_team': duty['away_team'].strip(),
        'slot': duty['slot'],
        'duty_team': duty['duty_team'],
        'status': 'rescheduled' if duty.get('match_status') == 'Rescheduled' else 'scheduled',
    }


def sync_umpire_duties(duties: Optional[list[dict]], now: Optional[datetime] = None) -> dict:
    """
    Brings umpire_duties in line with HKHA's list. `duties` is None when the
    page could not be read: nothing is then taken as removed.
    """
    counts = {'inserted': 0, 'updated': 0, 'cancelled': 0, 'unchanged': 0}
    if duties is None:
        logger.warning('Umpire duties: the all-clubs fixture page could not be read; nothing changed')
        return counts

    now = now or datetime.now(HK_TZ)
    stamp = now.isoformat()
    try:
        existing = select('umpire_duties', 'select=id,' + ','.join(_COLUMNS) + '&order=id')
    except Exception as exc:
        raise StoreUnavailable(f'Could not read the umpire duties: {exc}') from exc
    by_key = {r['duty_key']: r for r in existing}

    seen: set[str] = set()
    new_rows = []
    for duty in duties:
        row = _row(duty)
        if row is None:
            continue
        seen.add(row['duty_key'])
        have = by_key.get(row['duty_key'])
        if have is None:
            new_rows.append({**row, 'last_hkha_sync': stamp})
            continue
        patch = {c: v for c, v in row.items() if not _same(c, have.get(c), v)}
        if not patch:
            counts['unchanged'] += 1
            continue
        update('umpire_duties', f"id={eq(have['id'])}", {**patch, 'last_hkha_sync': stamp})
        counts['updated'] += 1

    if new_rows:
        insert('umpire_duties', new_rows)
        counts['inserted'] = len(new_rows)

    # Gone from HKHA's list. Only games still to come: once a game is
    # played HKHA may replace the duty team with the umpire's name. A page
    # that parsed to nothing is more likely changed than empty.
    if duties:
        for r in existing:
            when = _as_datetime(r.get('match_date'))
            if r['duty_key'] in seen or r.get('status') == 'cancelled' or when is None or when <= now:
                continue
            update('umpire_duties', f"id={eq(r['id'])}", {'status': 'cancelled', 'last_hkha_sync': stamp})
            counts['cancelled'] += 1

    logger.info(
        'Umpire duties: %d new, %d updated, %d cancelled, %d unchanged',
        counts['inserted'], counts['updated'], counts['cancelled'], counts['unchanged'],
    )
    return counts
