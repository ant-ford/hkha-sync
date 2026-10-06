"""
HKHA → Airtable / Supabase Sync Service

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
  SYNC_BACKEND        airtable (default) or supabase
  AIRTABLE_TOKEN      Airtable personal access token      (airtable)
  AIRTABLE_BASE_ID    Hockey Members base ID              (airtable)
  SUPABASE_URL        https://<ref>.supabase.co           (supabase)
  SUPABASE_SECRET_KEY The project's secret key            (supabase)
  SUPABASE_DRY_RUN    Optional: read, log writes, write nothing (supabase)
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
    from src.config.settings import (
        SYNC_BACKEND, AIRTABLE_TOKEN, AIRTABLE_BASE_ID, HKHA_PASSWORD, SUPABASE_URL, SUPABASE_SECRET_KEY,
    )
    if SYNC_BACKEND not in ('airtable', 'supabase'):
        raise EnvironmentError(f"SYNC_BACKEND must be 'airtable' or 'supabase', not {SYNC_BACKEND!r}")
    needed = [('HKHA_PASSWORD', HKHA_PASSWORD)]
    if SYNC_BACKEND == 'supabase':
        needed += [('SUPABASE_URL', SUPABASE_URL), ('SUPABASE_SECRET_KEY', SUPABASE_SECRET_KEY)]
    else:
        needed += [('AIRTABLE_TOKEN', AIRTABLE_TOKEN), ('AIRTABLE_BASE_ID', AIRTABLE_BASE_ID)]
    missing = [name for name, val in needed if not val]
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
    from src.config.settings import LOOKBACK_DAYS, RECENT_DAYS, SYNC_BACKEND, SUPABASE_DRY_RUN

    lookback = args.lookback if args.lookback is not None else LOOKBACK_DAYS
    log.info('Writing to %s%s', SYNC_BACKEND, ' (dry run: nothing is written)' if SYNC_BACKEND == 'supabase' and SUPABASE_DRY_RUN else '')

    # Supabase only: every run ends with a heartbeat for Eddy's health check
    # (src/supabase/heartbeat.py), with the errors logged along the way.
    errors = None
    if SYNC_BACKEND == 'supabase':
        from src.supabase.heartbeat import ErrorCounter
        errors = ErrorCounter()
        logging.getLogger().addHandler(errors)

    failure = None
    try:
        if args.job in ('fixtures', 'all'):
            log.info('=== Phase 1: Fixture Discovery (source=%s) ===', args.source)
            sync_fixtures.run(source=args.source)

        if args.job in ('cards', 'all'):
            if args.job == 'all':
                log.info('Pausing 5 s before Phase 2 …')
                time.sleep(5)
            log.info('=== Phase 2: Match Card Sync ===')
            sync_match_cards.run(lookback_days=lookback, recent_days=RECENT_DAYS)
    except Exception as exc:
        failure = exc
        raise
    finally:
        if errors is not None:
            from src.supabase.client import write_counts
            from src.supabase.heartbeat import record_run
            log.info('Supabase writes%s: %s', ' (not made)' if SUPABASE_DRY_RUN else '',
                     ', '.join(f'{t} {n}' for t, n in sorted(write_counts.items())) or 'none')
            logging.getLogger().removeHandler(errors)
            record_run(args.job, args.source, errors.count, failure)

    log.info('=== Sync complete ===')


if __name__ == '__main__':
    main()
    
