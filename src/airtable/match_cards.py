"""
Match Cards table operations.

Key responsibilities:
  - Map Python player dicts → Airtable field names / types
  - Inject Fixture Id and Match record link (fixes gaps from original code)
  - Split Cards into a list   (multipleSelects requires list, not string)
  - Auto-batch to 10 records per Airtable API call
  - Sleep between batches to respect the 5 req/s rate limit
"""
import logging
import time
from typing import Optional

from .client import MATCH_CARDS_TABLE

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10
_BATCH_SLEEP = 0.25     # seconds between batch calls → ≤ 4 calls/s


def _build_fields(player: dict, fixture_id: str, match_record_id: str) -> Optional[dict]:
    cards = player.get('Cards', [])
    if isinstance(cards, str):
        cards = [c.strip() for c in cards.split(',') if c.strip()]

    jersey = player.get('Jersey Number')
    if jersey is None:
        logger.warning(
            'Fixture %s: skipping player with no jersey number: %s',
            fixture_id, player.get('RawPlayerName'),
        )
        return None

    fields: dict = {
        'RawPlayerName': player.get('RawPlayerName', ''),
        'Fixture Id':    str(fixture_id),
        'Match':         [match_record_id],
        'Team':          player.get('Team', ''),
        'Player Team':   player.get('Player Team', ''),
        'Goals Scored':  player.get('Goals Scored') or 0,
        'Captain':       bool(player.get('Captain', False)),
        'Goalkeeper':    bool(player.get('Goalkeeper', False)),
        'U21':           bool(player.get('U21', False)),
        'VP':            bool(player.get('VP', False)),
        'Jersey Number': jersey,
    }
    if cards:
        fields['Cards'] = cards

    return {k: v for k, v in fields.items() if v is not None}


def _delete_removed_players(
    fixture_id: str,
    current_jerseys: set[int],
) -> int:
    """
    Delete Match Card records that no longer exist on the latest HKHA card.
    """

    existing = MATCH_CARDS_TABLE.all(
        formula=f"{{Fixture Id}}='{fixture_id}'"
    )

    to_delete = []

    for rec in existing:
        fields = rec.get('fields', {})
        jersey = fields.get('Jersey Number')

        if jersey not in current_jerseys:
            to_delete.append(rec['id'])

    if not to_delete:
        return 0

    MATCH_CARDS_TABLE.batch_delete(to_delete)

    logger.info(
        'Fixture %s: deleted %d stale player record(s)',
        fixture_id,
        len(to_delete),
    )

    return len(to_delete)


def upsert_match_cards(
    players: list[dict],
    fixture_id: str,
    match_record_id: str,
) -> None:
    """
    Upsert all players for one fixture to the Match Cards table.

    Args:
        players:          List of player dicts from get_match_card().
        fixture_id:       HKHA fixture ID string.
        match_record_id:  Airtable record ID for the parent Matches row.
    """
    if not players:
        logger.info(f'Fixture {fixture_id}: no players to upsert')
        return

    payload = [
        {'fields': _build_fields(p, fixture_id, match_record_id)}
        for p in players
        if (fields := _build_fields(p, fixture_id, match_record_id)) is not None
    ]

    total  = len(payload)
    batches = range(0, total, _BATCH_SIZE)

    for i in batches:
        batch = payload[i:i + _BATCH_SIZE]
        MATCH_CARDS_TABLE.batch_upsert(
            batch,
            key_fields=['Fixture Id', 'Jersey Number'],
        )
        logger.debug(
            f'Fixture {fixture_id}: upserted records {i + 1}–{min(i + _BATCH_SIZE, total)}'
        )
        if i + _BATCH_SIZE < total:
            time.sleep(_BATCH_SLEEP)

    # Build current jersey set from latest HKHA card
    current_jerseys = {
        p['Jersey Number']
        for p in players
        if p.get('Jersey Number') is not None
    }

    # Remove players no longer on the card
    _delete_removed_players(
        fixture_id,
        current_jerseys,
    )

    logger.info(f'Fixture {fixture_id}: upserted {total} player record(s)')

    
