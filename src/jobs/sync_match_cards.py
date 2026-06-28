from src.hkha.match_cards import get_match_card
from src.airtable.match_cards import upsert_match_cards
from src.airtable.sync_state import mark_scraped


def sync_fixture(session, fixture_id):
    try:
        result = get_match_card(session, fixture_id)

        players = result.get("players", [])

        if players:
            upsert_match_cards(players)

        mark_scraped(fixture_id, status="Complete")

    except Exception as exc:
        mark_scraped(fixture_id, status="Error", error=str(exc))
        raise
        
