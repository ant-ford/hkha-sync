"""
HKFC's umpiring duties: the Umpire 1 / Umpire 2 cells of the all-clubs
fixture page that name an HKFC team ("HKFC F"). Many are in games HKFC
doesn't play, which the HKFC-only page leaves out.

Each duty is one slot of one game, keyed "yyyy-mm-dd|home|away|slot" (the
match key plus the slot), so a change of duty team or kick-off time updates
the same slot.
"""
import re
from typing import Dict, Iterable, List

from src.hkha.fixture_fields import match_key

# "HKFC F", or "HKFC F - Name" once a name has been put in.
_HKFC_DUTY = re.compile(r'^(HKFC [A-Z])(?![A-Za-z0-9])')


def duty_team(cell: str) -> str | None:
    """The HKFC team a umpire cell gives the duty to, or None."""
    m = _HKFC_DUTY.match(re.sub(r'\s+', ' ', cell or '').strip())
    return m.group(1) if m else None


def duty_key(fixture: Dict, slot: int) -> str:
    return f'{match_key(fixture)}|{slot}'


def duty_slots(fixtures: Iterable[Dict]) -> List[Dict]:
    """
    One dict per HKFC duty: the fixture's fields plus slot, duty_team and
    duty_key. When HKHA lists a game twice for one date (a rescheduled row
    left in place), the scheduled row wins.
    """
    by_key: Dict[str, Dict] = {}
    for f in fixtures:
        for slot, column in ((1, 'umpire1'), (2, 'umpire2')):
            team = duty_team(f.get(column, ''))
            if not team:
                continue
            key = duty_key(f, slot)
            have = by_key.get(key)
            if have and have.get('match_status') != 'Rescheduled':
                continue
            by_key[key] = {**f, 'slot': slot, 'duty_team': team, 'duty_key': key}
    return list(by_key.values())
