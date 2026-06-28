from .client import MATCH_CARDS_TABLE


def upsert_match_cards(records):
    payload=[]
    for r in records:
        payload.append({'fields': r})
    if payload:
        MATCH_CARDS_TABLE.batch_upsert(payload, key_fields=['Fixture Id','RawPlayerName'])
