"""
HKHA authentication.

Builds a requests.Session with a urllib3 HTTPAdapter that retries
on transient server errors (5xx, 429).  Login itself is also retried
with exponential backoff so a brief HKHA outage doesn't abort the run.
"""
import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config.settings import LOGIN_URL

logger = logging.getLogger(__name__)

# ── Retry strategy for the underlying transport ───────────────────────────────
_TRANSPORT_RETRY = Retry(
    total=6,
    backoff_factor=2,                          # 2 s, 4 s, 8 s, 16 s …
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=['GET', 'POST', 'HEAD'],
    raise_on_status=False,                     # let us inspect the response
)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}


def _make_session() -> requests.Session:
    """Return a new Session with retry configured on both https and http."""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_TRANSPORT_RETRY)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    session.headers.update(_HEADERS)
    return session


def login(username: str, password: str, max_attempts: int = 3) -> requests.Session:
    """
    Authenticate with HKHA and return a live session.

    Retries the POST itself (not just transport errors) up to
    *max_attempts* times with exponential backoff, in case the
    login page is temporarily slow to respond.

    Raises:
        RuntimeError: if all attempts fail.
    """
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            session = _make_session()
            resp = session.post(
                LOGIN_URL,
                data={'username': username, 'password': password, 'login': 'login'},
                timeout=30,
            )
            resp.raise_for_status()
            logger.info(f'Authenticated as {username}')
            return session

        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = 5 * (2 ** (attempt - 1))          # 5 s, 10 s, 20 s
                logger.warning(
                    f'Login failed for {username} '
                    f'(attempt {attempt}/{max_attempts}): {exc}. '
                    f'Retrying in {delay} s.'
                )
                time.sleep(delay)

    raise RuntimeError(
        f'Failed to log in as {username} after {max_attempts} attempts'
    ) from last_exc
    
