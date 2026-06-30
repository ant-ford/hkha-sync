# hkha-sync

HKHA → Airtable synchronisation service for HKFC men's hockey operations.

Scrapes the Hong Kong Hockey Association website and keeps the **Hockey Members** Airtable base up to date with:

- All current-season fixtures (scheduled and played)
- Historical fixtures from individual team accounts
- Match card data (player appearances, goals, cards, play-ups)

**Status:** `MenFixture.asp`, `MCList.asp` and `MCInfo.asp` have all been confirmed working end-to-end against live HKHA data.

---

## Architecture

### Data sources

| Source | Auth | What it provides |
|---|---|---|
| `MenFixture.asp` | None (public) | Current-season fixtures for all men's teams |
| `MCList.asp` | Per-team login | Team fixture lists — includes historical seasons and cup fixtures not on the public page |
| `MCInfo.asp` | Per-team login | Match card detail: player names, jersey numbers, goals, cards |

### Sync phases

```
Phase 1 — Fixture Discovery
  1a  MenFixture.asp (public)       → Matches table
  1b  MCList.asp × 8 team logins    → Matches table  (supplements 1a)

Phase 2 — Match Card Scraping
      MCInfo.asp (per played fixture)  → Match Cards table
                                        HKHA Sync State table
```

Phase 1 runs frequently (every 6 hours) to pick up new fixtures quickly.
Phase 2 runs daily and re-scrapes matches within the last 14 days in case
disciplinary records or late scores arrive.

### Deduplication

- **Across teams**: a `seen_fixture_ids` set is maintained across all MCList
  team scrapes. A fixture seen in team A's list is not re-upserted when found
  in team B's list.

- **Across sources**: MenFixture.asp rows have no Fixture Id. Each MenFixture
  fixture is upserted on a composite **Match Key** (`date | home team | away team`).
  Once MCList.asp supplies the authoritative Fixture Id for that same fixture,
  the Matches record is "promoted" — the Fixture Id is cached and used for all
  future updates, and MenFixture.asp is no longer allowed to overwrite that
  record (see `_match_has_fixture_id` in `src/airtable/matches.py`).

- **Incremental match cards**: the HKHA Sync State table tracks `Last Scraped`
  and `Sync Status` per fixture. Phase 2 skips fixtures that were successfully
  scraped more than 20 hours ago and are older than 14 days.

---

## Airtable tables

| Table | Purpose |
|---|---|
| `Matches` | One record per fixture (played and scheduled) |
| `Match Cards` | One record per player appearance per fixture |
| `HKHA Sync State` | Scrape status tracking, one record per fixture |

Upsert keys (as implemented in code):

| Table | Key field(s) | Notes |
|---|---|---|
| Matches | `Match Key` (`date\|home\|away`), promoted to `Fixture Id` once known | MenFixture rows have no Fixture Id and are keyed on `Match Key`. Once MCList attaches a Fixture Id, that record is updated directly via its cached Airtable record id rather than re-matched on `Match Key`. |
| Match Cards | `Fixture Id` + `Jersey Number` | Jersey Number is the de-duplication key per fixture, not player name. |
| HKHA Sync State | `Fixture Id` | |

---

## Repository structure

```
hkha-sync/
├── .github/workflows/
│   └── sync.yml               — Consolidated GitHub Actions workflow
│
├── src/
│   ├── main.py                — Entry point (CLI arguments)
│   │
│   ├── config/
│   │   ├── settings.py        — URLs, secrets (from env), sync constants
│   │   └── teams.py           — HKFC team names / HKHA login usernames
│   │
│   ├── hkha/
│   │   ├── auth.py            — Login with retry / backoff
│   │   ├── men_fixture.py     — MenFixture.asp public page scraper
│   │   ├── team_fixtures.py   — MCList.asp per-team scraper
│   │   ├── match_cards.py     — MCInfo.asp match card scraper
│   │   └── player_parser.py   — Player row text parser
│   │
│   ├── airtable/
│   │   ├── client.py          — pyairtable API client (with retry)
│   │   ├── matches.py         — Matches table CRUD
│   │   ├── match_cards.py     — Match Cards table upsert
│   │   └── sync_state.py      — HKHA Sync State table CRUD
│   │
│   └── jobs/
│       ├── sync_fixtures.py   — Phase 1 orchestration
│       └── sync_match_cards.py — Phase 2 orchestration
│
├── README.md
└── requirements.txt
```

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/ant-ford/hkha-sync.git
cd hkha-sync
pip install -r requirements.txt
```

### 2. Environment variables

All three are required at runtime. For local development, create `.env`:

```dotenv
AIRTABLE_TOKEN=patXXXXXXXXXXXXXX
AIRTABLE_BASE_ID=appG6amyHthm3Nnde
HKHA_PASSWORD=your_shared_hkha_password

# Optional — override sync windows
LOOKBACK_DAYS=30
RECENT_DAYS=14
```

Load with:

```bash
export $(cat .env | xargs)
```

### 3. GitHub Secrets

All three environment variables must be added to **Settings → Secrets and variables → Actions** in the repository:

| Secret name | Value |
|---|---|
| `AIRTABLE_TOKEN` | Airtable personal access token (starts with `pat`) |
| `AIRTABLE_BASE_ID` | `appG6amyHthm3Nnde` |
| `HKHA_PASSWORD` | Shared password for all HKFC team accounts on HKHA |

---

## Usage

### Run locally

```bash
# Full sync (fixture discovery + match cards)
python src/main.py

# Phase 1 only — all fixture sources
python src/main.py --job fixtures

# Phase 1a only — public MenFixture.asp (no HKHA login needed)
python src/main.py --job fixtures --source public

# Phase 1b only — MCList.asp per-team
python src/main.py --job fixtures --source mclist

# Phase 2 only — scrape match cards
python src/main.py --job cards

# Extended lookback (e.g. after the service has been down)
python src/main.py --job cards --lookback 60

# Debug logging to inspect raw HTML parsing
python src/main.py --job fixtures --source public --log-level DEBUG
```

### GitHub Actions

The workflow (`sync.yml`) runs automatically on three schedules:

| Schedule | Cron | Purpose |
|---|---|---|
| Every 6 hours | `0 */6 * * *` | Fixture discovery — picks up new fixtures quickly |
| Daily 19:30 UTC | `30 19 * * *` | Full sync — fixtures + match cards |
| Weekly Sunday 02:00 UTC | `0 2 * * 0` | Extended re-scrape (catches late updates) |

All three triggers run `python src/main.py --job all`, which is safe to run repeatedly (all writes are upserts).

**Manual trigger**: Go to **Actions → HKHA Sync → Run workflow** to trigger immediately with custom parameters (`job`, `source`, `lookback_days`, `log_level`).

---

## Testing procedure

Use this procedure when setting up the system for the first time or after a data reset. All three phases below have been verified to work against live HKHA data.

### Step 1 — Clear existing data

Delete all records from the **Matches** and **Match Cards** tables in Airtable. Leave **HKHA Sync State** as-is (it will be rebuilt). The simplest approach is to select all records in each Airtable view and delete them.

### Step 2 — Populate from the public page (no login)

```bash
python src/main.py --job fixtures --source public
```

Check Airtable: Matches should now contain current-season HKFC fixtures. These records have no `Fixture Id` yet (the public page doesn't expose one) and are keyed on `Match Key`. `Match Status` will be `Played` for completed matches, `Scheduled` for upcoming ones, or `Rescheduled` if HKHA has flagged the row as such.

### Step 3 — Add historical fixtures from team accounts

```bash
python src/main.py --job fixtures --source mclist
```

Verify in Airtable:
- The record count in Matches increases (historical fixtures added).
- Fixtures already synced in Step 2 are not duplicated — instead their `Fixture Id` field is filled in for the first time, "promoting" the existing `Match Key` record.
- **No duplicates** — once a record carries a `Fixture Id`, subsequent runs update it directly by Airtable record id.
- `Last HKHA Sync` is updated on existing records.

### Step 4 — Scrape match cards

```bash
python src/main.py --job cards
```

Check that Match Cards is now populated. Each HKFC player appearance should have:
- `Fixture Id` and `Match` (linked to the Matches record)
- `Team`, `Player Team` (different if playing up)
- `Captain`, `Goalkeeper`, `U21`, `VP` flags
- `Cards` (list) and `Goals Scored` if applicable
- `Jersey Number` — this is the de-duplication key per fixture

### Step 5 — Incremental sync test

1. Delete a small set of recent Match Card records (e.g. last 2–3 fixtures) directly in Airtable.
2. Edit the `Sync Status` in HKHA Sync State for those fixture IDs to `Error` (forces re-scrape).
3. Run: `python src/main.py --job cards`
4. Verify the deleted records are recreated without duplicates.

---

## Rate limits

### Airtable

Personal access tokens are limited to **5 requests/second per workspace**.

This service uses:
- `pyairtable`'s built-in retry (respects `Retry-After` on 429 responses)
- `time.sleep(0.25)` between consecutive batch upsert calls in `match_cards.py` (≈4 calls/sec maximum)

### HKHA

The service adds deliberate pauses between requests to avoid overloading the HKHA server:
- 2 seconds between team logins (Phase 1b)
- 0.5 seconds between match card fetches (Phase 2)
- Exponential backoff (3, 6, 12, 24 seconds) on HTTP errors in `match_cards.py`
- 5-second initial backoff on login failures, doubling per retry

---

## Troubleshooting

**`MenFixture.asp returned 0 HKFC fixtures`**

Run with `--log-level DEBUG` to see raw row parsing. The page column layout may have changed. Check the `_COL_*` constants at the top of `src/hkha/men_fixture.py` and adjust if necessary.

**`Login failed for MS HKFC X`**

Verify `HKHA_PASSWORD` is set correctly. The password is shared across all 8 team accounts. Check the HKHA website manually to confirm the account is active.

**`Sync Status = Error` records in HKHA Sync State**

Run `python src/main.py --job cards` — error fixtures are automatically retried. Check `Error Message` in Airtable for details. Common causes: HKHA downtime, network timeouts, or a match card page not yet published.

**Fixture IDs not matching between MenFixture.asp and MCList.asp**

This is expected: MenFixture.asp rows never carry a Fixture Id. They are keyed on `Match Key` (date + home + away). MCList.asp supplies the Fixture Id when it runs, and `_match_has_fixture_id()` in `src/airtable/matches.py` ensures MenFixture.asp can no longer overwrite that record once promoted.

---

## Season rollover

When HKHA publishes the new season's fixtures (typically August):

1. MenFixture.asp is updated automatically — the next scheduled run picks up new fixtures.
2. No code changes are needed — there is no hardcoded date filter.
3. Historical fixtures remain in Matches and Match Cards (they are never deleted by this service).

---

## Dependencies

| Package | Purpose |
|---|---|
| `requests` | HTTP client for HKHA scraping |
| `beautifulsoup4` | HTML parsing for fixture lists and match cards |
| `pyairtable` | Airtable API client with built-in retry |
| `python-dotenv` | Load `.env` file for local development |

---

## Legacy Make.com scenario

The `Get Match Cards` Make.com scenario previously handled match card scraping. This service is a complete replacement and has now been confirmed working for fixture discovery and match card scraping alike. Once this service has run successfully for a full cycle, deactivate the Make.com scenario to avoid double-writes to the Match Cards table.

Key improvements over the legacy scenario:

| Issue | Legacy Make.com | This service |
|---|---|---|
| Password | Hardcoded `123456` | Environment variable |
| Date filter | Hardcoded `>= 2026-05-01` | Dynamic — no filter needed |
| Future fixtures | Not supported | Supported via MenFixture.asp |
| Error handling | None | Retry / backoff + Sync State tracking |
| Duplicate prevention | None | `Match Key` → `Fixture Id` promotion + upsert keys |
| Player array cap | 18 players (hardcoded routes) | Unlimited (dynamic batching) |
| Session reuse | New login per team per fixture | One login per team per run |
