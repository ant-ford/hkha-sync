"""
HKHA fixture values as both backends store them: the match key, the kick-off
time and the scores.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

HK_TZ = timezone(timedelta(hours=8))


def parse_datetime(date_str: str, time_str: str | None = None) -> Optional[datetime]:
    """HKHA's dd/mm/yyyy and HH:MM as a Hong Kong time, or None if unreadable."""
    if not date_str:
        return None

    try:
        date_part = datetime.strptime(date_str.strip(), '%d/%m/%Y')

        if time_str and time_str != 'TBC':
            time_part = datetime.strptime(time_str.strip(), '%H:%M')
            dt = date_part.replace(hour=time_part.hour, minute=time_part.minute)
        else:
            dt = date_part

        return dt.replace(tzinfo=HK_TZ)

    except ValueError:
        logger.warning('Could not parse datetime: %s %s', date_str, time_str)
        return None


def parse_score(val) -> Optional[int]:
    if val is None:
        return None

    s = str(val).strip()
    if not s:
        return None

    try:
        return int(s)
    except ValueError:
        return None


def match_key(match: dict) -> str:
    """'yyyy-mm-dd|home|away', the key a fixture has before HKHA gives it a Fixture Id."""
    try:
        dt = datetime.strptime(match.get('date', ''), '%d/%m/%Y')
        date_part = dt.strftime('%Y-%m-%d')
    except ValueError:
        date_part = match.get('date', '')

    return '|'.join([date_part, match.get('home_team', '').strip(), match.get('away_team', '').strip()])
