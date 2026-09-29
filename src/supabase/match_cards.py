"""
public.match_cards in Eddy's database: one row per HKFC player appearance,
keyed per fixture by jersey number, as in the Airtable Match Cards table.

Each fixture's card is compared with the rows already stored: new players
are inserted, changed rows updated, and players no longer on the card
deleted. Rows that did not change are not written.

person_id is not set here. The database links a card to the one person
whose Registered Name matches raw_player_name (the match_cards_link_person
trigger). A link set by hand is kept, unless HKHA later puts a different
name against that jersey number.
"""
import logging

from .client import select, insert, update, delete, eq, in_list

logger = logging.getLogger(__name__)

_COLUMNS = [
    'raw_player_name', 'team', 'player_team', 'jersey_number', 'goals_scored',
    'cards', 'captain', 'goalkeeper', 'u21', 'vp', 'fixture_id', 'match_id',
]


def _row(player: dict, fixture_id: str, match_id: str) -> dict:
    cards = player.get('Cards', [])
    if isinstance(cards, str):
        cards = [c.strip() for c in cards.split(',') if c.strip()]

    return {
        'raw_player_name': player.get('RawPlayerName', ''),
        'team':            player.get('Team', ''),
        'player_team':     player.get('Player Team', ''),
        'jersey_number':   player['Jersey Number'],
        'goals_scored':    player.get('Goals Scored') or 0,
        # Always written, so a card HKHA later withdraws is cleared.
        'cards':           list(cards),
        'captain':         bool(player.get('Captain', False)),
        'goalkeeper':      bool(player.get('Goalkeeper', False)),
        'u21':             bool(player.get('U21', False)),
        'vp':              bool(player.get('VP', False)),
        'fixture_id':      str(fixture_id),
        'match_id':        match_id,
    }


def upsert_match_cards(players: list[dict], fixture_id: str, match_record_id: str) -> None:
    """
    Make the stored card for one fixture match the latest HKHA card.

    Args:
        players:          List of player dicts from get_match_card().
        fixture_id:       HKHA fixture ID string.
        match_record_id:  public.matches id of the fixture.
    """
    if not players:
        logger.info(f'Fixture {fixture_id}: no players to upsert')
        return

    wanted: dict[int, dict] = {}
    for p in players:
        if p.get('Jersey Number') is None:
            logger.warning(
                'Fixture %s: skipping player with no jersey number: %s',
                fixture_id, p.get('RawPlayerName'),
            )
            continue
        if p['Jersey Number'] in wanted:
            logger.warning('Fixture %s: jersey %s appears twice; the last one is kept', fixture_id, p['Jersey Number'])
        wanted[p['Jersey Number']] = _row(p, fixture_id, match_record_id)

    existing = select('match_cards', f'select=id,{",".join(_COLUMNS)}&fixture_id={eq(fixture_id)}&order=id')

    stored: dict[int, dict] = {}
    duplicates: list[str] = []
    for r in existing:
        if r['jersey_number'] in stored:
            duplicates.append(r['id'])
        else:
            stored[r['jersey_number']] = r

    new_rows = [row for jersey, row in wanted.items() if jersey not in stored]
    changed = 0
    for jersey, row in wanted.items():
        current = stored.get(jersey)
        if current is None:
            continue
        patch = {c: v for c, v in row.items() if current.get(c) != v}
        if 'raw_player_name' in patch:
            # A different player now wears this number: drop the old link so
            # the database links the new name.
            patch['person_id'] = None
        if patch:
            update('match_cards', f'id={eq(current["id"])}', patch)
            changed += 1

    if new_rows:
        insert('match_cards', new_rows)

    stale = [r['id'] for jersey, r in stored.items() if jersey not in wanted] + duplicates
    if stale:
        delete('match_cards', f'id={in_list(stale)}')
        logger.info('Fixture %s: deleted %d stale player record(s)', fixture_id, len(stale))

    logger.info(
        'Fixture %s: %d player(s) on the card, %d new, %d changed',
        fixture_id, len(wanted), len(new_rows), changed,
    )
