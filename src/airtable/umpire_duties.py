"""
Umpire duties live only in Eddy's database (src/supabase/umpire_duties.py);
the Airtable base has no table for them.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def sync_umpire_duties(duties: Optional[list[dict]], now=None) -> dict:
    logger.info('Umpire duties: not kept in Airtable; skipped')
    return {}
