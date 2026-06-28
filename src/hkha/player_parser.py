"""
Parse a single player row from HKHA match-card HTML.

The raw text of each <div class="team"> looks like:
    * 7 - SMITH John (U21) Y2
    # 1 - JONES Mike <b class="playerteam">MS HKFC B</b>

Prefixes:  * = captain,  # = goalkeeper
"""
import re
from typing import Optional

_CARD_RE = re.compile(r'\b([YR][1-7])\b')


def parse_player_row(raw_text: str) -> dict:
    """
    Parse a player div's text into a structured dict.

    Returns:
        RawPlayerName (str)   – name as printed on the card
        Jersey Number (int|None)
        Captain       (bool)
        Goalkeeper    (bool)
        U21           (bool)
        VP            (bool)
        Cards         (list[str])  – e.g. ['Y2', 'R1']
        Goals Scored  (int)        – always 0 here; overwritten by caller
    """
    text: str = ' '.join(raw_text.split())

    captain: bool   = text.startswith('*')
    goalkeeper: bool = text.startswith('#')
    u21: bool       = '(u21)' in text.lower()
    vp: bool        = '(vp)' in text.lower()
    cards: list[str] = _CARD_RE.findall(text)

    # Strip role markers and status flags before extracting name / jersey
    cleaned = (
        text
        .replace('*', '')
        .replace('#', '')
        .replace('(U21)', '')
        .replace('(u21)', '')
        .replace('(VP)', '')
        .replace('(vp)', '')
        .strip()
    )

    jersey: Optional[int] = None
    name: str = cleaned

    parts = cleaned.split('-', 1)
    if len(parts) == 2:
        try:
            jersey = int(parts[0].strip())
            name   = parts[1].strip()
        except ValueError:
            pass   # no leading jersey number; keep name = cleaned

    return {
        'RawPlayerName': name,
        'Jersey Number': jersey,
        'Captain':       captain,
        'Goalkeeper':    goalkeeper,
        'U21':           u21,
        'VP':            vp,
        'Cards':         cards,          # already a list – ready for multipleSelects
        'Goals Scored':  0,
    }
    
