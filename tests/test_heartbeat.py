"""
The run's heartbeat for Eddy's health check. Offline: insert() is faked.

    python -m unittest discover -s tests
"""
import importlib
import logging
import unittest

from src.supabase import client as supabase_client


class HeartbeatTest(unittest.TestCase):
    def setUp(self):
        self.hb = importlib.reload(importlib.import_module('src.supabase.heartbeat'))
        self.rows = []
        self.hb.insert = lambda table, rows: self.rows.append((table, rows)) or rows
        supabase_client.write_counts.clear()

    def test_a_good_run_is_ok_with_its_counts(self):
        supabase_client.write_counts['matches'] = 3
        self.hb.record_run('all', 'all', 2)
        [(table, [row])] = self.rows
        self.assertEqual(table, 'heartbeats')
        self.assertEqual(row['job'], 'hkha-sync')
        self.assertTrue(row['ok'])
        self.assertEqual(row['detail'], {'job': 'all', 'source': 'all', 'errors': 2, 'writes': {'matches': 3}})

    def test_a_run_that_stopped_is_not_ok(self):
        self.hb.record_run('cards', 'all', 0, RuntimeError('x' * 500))
        row = self.rows[0][1][0]
        self.assertFalse(row['ok'])
        self.assertTrue(row['detail']['failure'].startswith('RuntimeError: x'))
        self.assertLessEqual(len(row['detail']['failure']), 300)

    def test_a_failed_write_never_raises(self):
        def boom(table, rows):
            raise supabase_client.SupabaseError('down')
        self.hb.insert = boom
        with self.assertLogs('src.supabase.heartbeat', level='WARNING'):
            self.hb.record_run('all', 'all', 0)

    def test_error_counter_counts_errors_only(self):
        counter = self.hb.ErrorCounter()
        log = logging.getLogger('test.heartbeat.counter')
        log.addHandler(counter)
        try:
            log.warning('not counted')
            log.error('one')
            log.critical('two')
        finally:
            log.removeHandler(counter)
        self.assertEqual(counter.count, 2)


if __name__ == '__main__':
    unittest.main()
