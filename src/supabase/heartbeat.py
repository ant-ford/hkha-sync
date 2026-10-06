"""
public.heartbeats in Eddy's database: one row per sync run, which Eddy's
daily health check reads (worker/src/systemHealth.ts in Squad-Selection).
It flags a sync that hasn't run for a day, a failed run, and a match day
with no good run since the match ended.

GitHub turns off scheduled workflows in a public repository after 60 days
without activity, so the sync could stop without failing anywhere; a stale
heartbeat is how that shows up.

Never raises: a run's result never depends on its heartbeat.
"""
import logging
from typing import Optional

from .client import insert, write_counts

logger = logging.getLogger(__name__)

JOB = 'hkha-sync'


class ErrorCounter(logging.Handler):
    """Counts ERROR (and worse) log records during a run."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


def record_run(job: str, source: str, errors: int, failure: Optional[BaseException] = None) -> None:
    """One heartbeat: ok unless the run stopped on an exception."""
    detail = {
        'job': job,
        'source': source,
        'errors': errors,
        'writes': dict(sorted(write_counts.items())),
    }
    if failure is not None:
        # Exception text from this code and PostgREST names tables, not values.
        detail['failure'] = f'{type(failure).__name__}: {failure}'[:300]
    try:
        insert('heartbeats', [{'job': JOB, 'ok': failure is None, 'detail': detail}])
    except Exception as exc:
        logger.warning('Heartbeat not recorded: %s', exc)
