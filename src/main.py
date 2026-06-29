"""
HKHA → Airtable Sync Service

Usage
─────
  # Full sync (both phases, both sources)
  python src/main.py

  # Phase 1: fixture discovery only
  python src/main.py --job fixtures

  # Phase 1a: public MenFixture.asp only  ← use this for initial testing
  python src/main.py --job fixtures --source public

  # Phase 1b: MCList.asp per-team only
  python src/main.py --job fixtures --source mclist

  # Phase 2: match card scraping only
  python src/main.py --job cards

  # Extended lookback (e.g. after a gap in running)
  python src/main.py --job cards --lookback 60

Environment variables (all required unless noted)
─────────────────────────────────────────────────
  AIRTABLE_TOKEN      Airtable personal access token
  AIRTABLE_BASE_ID    Hockey Members base ID
  HKHA_PASSWORD       Shared password for all HKFC HKHA team accounts
  LOOKBACK_DAYS       How many days back to query for match cards (default: 30)
  RECENT_DAYS         Re-scrape window for complete fixtures (default: 14)
"""
import argparse
import logging
import sys
import time


def _setup_logging(level: str = 'INFO') -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%SZ',
        stream=sys.stdout,
        force=True,
    )


def _validate_env() -> None:
    from src.config.settings import AIRTABLE_TOKEN, AIRTABLE_BASE_ID, HKHA_PASSWORD
    missing = [
        name for name, val in [
            ('AIRTABLE_TOKEN',   AIRTABLE_TOKEN),
            ('AIRTABLE_BASE_ID', AIRTABLE_BASE_ID),
            ('HKHA_PASSWORD',    HKHA_PASSWORD),
        ]
        if not val
    ]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='HKHA → Airtable sync service',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        '--job',
        choices=['fixtures', 'cards', 'all'],
        default='all',
        help='Which sync phase to run (default: all)',
    )
    p.add_argument(
        '--source',
        choices=['public', 'mclist', 'all'],
        default='all',
        help='Fixture source for --job fixtures (default: all)',
    )
    p.add_argument(
        '--lookback',
        type=int,
        default=None,
        help='Override LOOKBACK_DAYS for match card scraping',
    )
    p.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging verbosity (default: INFO)',
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    _setup_logging(args.log_level)
    log = logging.getLogger('main')

    try:
        _validate_env()
    except EnvironmentError as exc:
        logging.critical(str(exc))
        sys.exit(1)

    # Import jobs after env validation so import-time Airtable client
    # doesn't blow up with missing token.
    from src.jobs import sync_fixtures, sync_match_cards
    from src.config.settings import LOOKBACK_DAYS, RECENT_DAYS

    lookback = args.lookback if args.lookback is not None else LOOKBACK_DAYS

    if args.job in ('fixtures', 'all'):
        log.info('=== Phase 1: Fixture Discovery (source=%s) ===', args.source)
        sync_fixtures.run(source=args.source)

    if args.job in ('cards', 'all'):
        if args.job == 'all':
            log.info('Pausing 5 s before Phase 2 …')
            time.sleep(5)
        log.info('=== Phase 2: Match Card Sync ===')
        sync_match_cards.run(lookback_days=lookback, recent_days=RECENT_DAYS)

    log.info('=== Sync complete ===')


if __name__ == '__main__':
    main()
    
