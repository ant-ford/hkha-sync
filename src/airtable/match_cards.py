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


def _build_fields(player: dict, fixture_id: str, match_record_id: str) -> dict:
    """Map one player dict to Airtable Match Cards field names."""
    # Cards: player_parser returns a list; guard against legacy string values
    cards = player.get('Cards', [])
    if isinstance(cards, str):
        cards = [c.strip() for c in cards.split(',') if c.strip()]

    fields: dict = {
        'RawPlayerName': player.get('RawPlayerName', ''),
        'Fixture Id':    str(fixture_id),
        'Match':         [match_record_id],        # multipleRecordLinks → Matches
        'Team':          player.get('Team', ''),
        'Player Team':   player.get('Player Team', ''),
        'Goals Scored':  player.get('Goals Scored') or 0,
        'Captain':       bool(player.get('Captain', False)),
        'Goalkeeper':    bool(player.get('Goalkeeper', False)),
        'U21':           bool(player.get('U21', False)),
        'VP':            bool(player.get('VP', False)),
    }

    jersey = player.get('Jersey Number')
    if jersey is not None:
        fields['Jersey Number'] = jersey

    if cards:
        fields['Cards'] = cards      # multipleSelects: list[str]

    # Strip out any None values to avoid overwriting with null
    return {k: v for k, v in fields.items() if v is not None}


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
    ]

    total  = len(payload)
    batches = range(0, total, _BATCH_SIZE)

    for i in batches:
        batch = payload[i:i + _BATCH_SIZE]
        MATCH_CARDS_TABLE.batch_upsert(
            batch,
            key_fields=['Fixture Id', 'RawPlayerName'],
        )
        logger.debug(
            f'Fixture {fixture_id}: upserted records {i + 1}–{min(i + _BATCH_SIZE, total)}'
        )
        if i + _BATCH_SIZE < total:
            time.sleep(_BATCH_SLEEP)

    logger.info(f'Fixture {fixture_id}: upserted {total} player record(s)')
    
