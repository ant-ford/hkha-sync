"""
Supabase client: PostgREST over requests, the same way Eddy's Worker talks
to the database.

Authentication is the project's secret key, sent only in the apikey header
(Supabase refuses a secret key in Authorization). The key belongs to the
service role, which bypasses RLS; every table has RLS on with no policies,
so nothing else can read them.

PostgREST answers at most 1000 rows per request, so select() pages with the
Range header until a page comes back short.

With SUPABASE_DRY_RUN set, reads go through and writes are only logged
(table and row count, never values), so a run can be compared against the
data before it is allowed to change anything.
"""
import logging
from typing import Iterable, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config.settings import SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_DRY_RUN

logger = logging.getLogger(__name__)

PAGE = 1000

# Writes: one per update, plus the rows of each insert, per table.
write_counts: dict[str, int] = {}


class SupabaseError(Exception):
    pass


def _session() -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=1,                       # 1 s, 2 s, 4 s …
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,
        allowed_methods=False,                  # retry on any HTTP method
    )
    s = requests.Session()
    s.mount('https://', HTTPAdapter(max_retries=retry))
    s.headers.update({
        'apikey': SUPABASE_SECRET_KEY or '',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    return s


_http = _session()
_root = f"{(SUPABASE_URL or '').rstrip('/')}/rest/v1"


def eq(value) -> str:
    """A value for an eq filter, safe in a query string."""
    return 'eq.' + quote(str(value), safe='')


def in_list(values: Iterable) -> str:
    """A value list for an in.(…) filter, each value quoted."""
    return 'in.(' + ','.join('"' + quote(str(v), safe='') + '"' for v in values) + ')'


def _call(method: str, path: str, *, json=None, headers: Optional[dict] = None):
    resp = _http.request(method, f'{_root}/{path}', json=json, headers=headers or {}, timeout=60)
    if not resp.ok:
        # PostgREST's message names the table or constraint, never row values.
        try:
            body = resp.json()
            message = body.get('message') or body.get('hint') or ''
        except ValueError:
            message = resp.text[:200]
        raise SupabaseError(f"Supabase {method} {path.split('?')[0]} failed ({resp.status_code}): {message}")
    return resp.json() if resp.text else None


def _count_write(table: str, n: int) -> None:
    write_counts[table] = write_counts.get(table, 0) + n


def select(table: str, query: str) -> list[dict]:
    """Every row matching a PostgREST query string (select=…&col=eq.…)."""
    rows: list[dict] = []
    start = 0
    while True:
        page = _call('GET', f'{table}?{query}', headers={
            'Range-Unit': 'items',
            'Range': f'{start}-{start + PAGE - 1}',
        }) or []
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        start += PAGE


def insert(table: str, rows: list[dict]) -> list[dict]:
    """Inserts rows (all with the same keys), returning them."""
    if not rows:
        return []
    _count_write(table, len(rows))
    if SUPABASE_DRY_RUN:
        logger.info('[dry run] would insert %d %s row(s)', len(rows), table)
        return [{**r, 'id': f'dry-run-{table}-{i}'} for i, r in enumerate(rows)]
    return _call('POST', table, json=rows, headers={'Prefer': 'return=representation'}) or []


def update(table: str, filter_: str, patch: dict) -> list[dict]:
    """Updates the rows matching filter_, returning them."""
    if not filter_:
        raise ValueError('update() needs a filter')
    _count_write(table, 1)
    if SUPABASE_DRY_RUN:
        logger.debug('[dry run] would update %s (%s): %s', table, filter_.split('=')[0], ', '.join(sorted(patch)))
        return [patch]
    return _call('PATCH', f'{table}?{filter_}', json=patch, headers={'Prefer': 'return=representation'}) or []


def delete(table: str, filter_: str) -> None:
    """Deletes the rows matching filter_. There is no delete-everything."""
    if not filter_:
        raise ValueError('delete() needs a filter')
    _count_write(table, 1)
    if SUPABASE_DRY_RUN:
        logger.info('[dry run] would delete from %s', table)
        return
    _call('DELETE', f'{table}?{filter_}')
