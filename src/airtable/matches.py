"""
Matches table operations.

Uses Match Key as the permanent Airtable upsert key.

Match Key format:
    YYYY-MM-DD|Home Team|Away Team

Fixture Id is treated as an optional HKHA identifier that may
arrive later from MCList.asp.

This allows:

    MenFixture.asp
        -> create fixture without Fixture Id

    MCList.asp
        -> update same fixture with Fixture Id

without creating duplicate Airtable records.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .client import MATCHES_TABLE

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _parse_datetime(
    date_str: str,
    time_str: str | None = None
) -> Optional[str]:
    """
    Convert:

        14/09/2025 + 14:15

    into

        2025-09-14T14:15:00.000Z

    Airtable stores UTC internally.
    HK hockey times are HKT (UTC+8).
    """

    if not date_str:
        return None

    try:
        date_part = datetime.strptime(
            date_str.strip(),
            '%d/%m/%Y'
        )

        if time_str and time_str != 'TBC':

            time_part = datetime.strptime(
                time_str.strip(),
                '%H:%M'
            )

            local_dt = date_part.replace(
                hour=time_part.hour,
                minute=time_part.minute
            )

        else:

            local_dt = date_part

        utc_dt = local_dt - timedelta(hours=8)

        return utc_dt.strftime(
            '%Y-%m-%dT%H:%M:%S.000Z'
        )

    except ValueError:
        logger.warning(
            "Could not parse datetime: %s %s",
            date_str,
            time_str,
        )
        return None


def _parse_score(val) -> Optional[int]:
    """
    Convert score value to integer.
    """
    if val is None:
        return None

    s = str(val).strip()

    if not s:
        return None

    try:
        return int(s)
    except ValueError:
        return None


def _match_key(match: dict) -> str:
    """
    Generate Match Key matching Airtable formula:

        YYYY-MM-DD|Home Team|Away Team
    """
    try:
        dt = datetime.strptime(match.get('date', ''), '%d/%m/%Y')
        date_part = dt.strftime('%Y-%m-%d')
    except ValueError:
        date_part = match.get('date', '')

    return '|'.join([
        date_part,
        match.get('home_team', '').strip(),
        match.get('away_team', '').strip(),
    ])


# ──────────────────────────────────────────────────────────────
# Upsert
# ──────────────────────────────────────────────────────────────

def upsert_match(match: dict) -> Optional[str]:
    """
    Create or update a match record.

    Upsert key:
        Match Key

    Returns:
        Airtable record id or None
    """
    home_score = _parse_score(match.get('home_score'))
    away_score = _parse_score(match.get('away_score'))

    is_played = (
        home_score is not None
        and away_score is not None
    )

    lookup_key = _match_key(match)

    fields = {
        'Match Key': lookup_key,
        'Match Status': 'Played' if is_played else 'Scheduled',
        'Last HKHA Sync': datetime.now(timezone.utc).strftime(
            '%Y-%m-%dT%H:%M:%S.000Z'
        ),
        'Source': 'HKHA Sync',
    }

    # Optional HKHA Fixture ID
    fixture_id = match.get('fixture_id')
    if fixture_id:
        fields['Fixture Id'] = str(fixture_id)

    iso_datetime = _parse_datetime(
        match.get('date', ''),
        match.get('time')
    )

    if iso_datetime:
        fields['Date'] = iso_datetime

    mappings = {
        'division': 'Division',
        'home_team': 'Home Team',
        'away_team': 'Away Team',
        'venue': 'Venue',
        'umpire1': 'Ump 1',
        'umpire2': 'Ump 2',
    }

    for source_field, airtable_field in mappings.items():
        value = match.get(source_field)
        if value:
            fields[airtable_field] = value

    if home_score is not None:
        fields['Home Score'] = home_score

    if away_score is not None:
        fields['Away Score'] = away_score

    try:
        result = MATCHES_TABLE.batch_upsert(
            [{'fields': fields}],
            key_fields=['Match Key'],
        )

        if result:
            logger.debug(
                "Upserted match %s",
                lookup_key
            )

            records = result.get("records", [])
            if records:
                return records[0]["id"]

        return None

    except Exception:
        logger.exception(
            "Failed to upsert match %s",
            fields.get('Match Key'),
        )

        return None


# ──────────────────────────────────────────────────────────────
# Match card scraping support
# ──────────────────────────────────────────────────────────────

def get_played_fixtures(lookback_days: int = 30) -> list[dict]:
    """
    Return recently played fixtures that have a Fixture Id.

    Phase 2 uses these to scrape MCInfo.asp.
    """
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=lookback_days)
    ).strftime('%Y-%m-%d')

    formula = (
        f"AND("
        f"{{Match Status}}='Played',"
        f"IS_AFTER({{Date}}, '{cutoff}')"
        f")"
    )

    try:
        records = MATCHES_TABLE.all(
            formula=formula,
            fields=[
                'Fixture Id',
                'Date',
                'Home Team',
                'Away Team',
            ],
        )

    except Exception as exc:
        logger.error(
            'Failed to query played fixtures: %s',
            exc,
        )
        return []

    fixtures = []

    for r in records:
        fields = r.get('fields', {})

        fixture_id = fields.get('Fixture Id')

        if not fixture_id:
            continue

        fixtures.append({
            'fixture_id': fixture_id,
            'date': fields.get('Date', ''),
            'home_team': fields.get('Home Team', ''),
            'away_team': fields.get('Away Team', ''),
            'record_id': r['id'],
        })

    return fixtures
