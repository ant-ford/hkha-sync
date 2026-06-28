# HKHA Sync

HKHA to Airtable synchronization service for HKFC hockey operations.

## Jobs
- Future fixture sync
- Completed match sync
- Match card sync
- Recent refresh sync

## Repository Structure
.hkha-sync/
├── .github/
│   └── workflows/
│       ├── fixtures.yml
│       ├── matches.yml
│       └── refresh_recent.yml
│
├── src/
│   ├── airtable/
│   │   ├── client.py
│   │   ├── match_cards.py
│   │   ├── matches.py
│   │   └── sync_state.py
│   │
│   ├── config/
│   │   ├── settings.py
│   │   └── teams.py
│   │
│   ├── hkha/
│   │   ├── auth.py
│   │   ├── match_cards.py
│   │   ├── player_parser.py
│   │   └── team_fixtures.py
│   │
│   ├── jobs/
│   │   ├── sync_completed_matches.py
│   │   └── sync_match_cards.py
│   │
│   └── main.py
│
├── README.md
└── requirements.txt
