"""
Offline tests for the Supabase backend: PostgREST is replaced by an
in-memory fake, so no network or secrets are needed.

    python -m unittest discover -s tests
"""
import importlib
import itertools
import unittest
from urllib.parse import unquote

from src.supabase import client as supabase_client


class FakeDb:
    """Just enough PostgREST: eq / in / not.is.null filters, and the writes."""

    def __init__(self, tables):
        self.tables = {name: [dict(r) for r in rows] for name, rows in tables.items()}
        self.writes = []
        self._ids = itertools.count(1)

    @staticmethod
    def _filters(query):
        out = []
        for part in query.split('&'):
            col, _, cond = part.partition('=')
            if col in ('select', 'order') or not cond:
                continue
            out.append((col, cond))
        return out

    @staticmethod
    def _match(row, filters):
        for col, cond in filters:
            value = row.get(col)
            if cond.startswith('eq.'):
                if str(value) != unquote(cond[3:]):
                    return False
            elif cond.startswith('in.('):
                wanted = [unquote(v.strip('"')) for v in cond[4:-1].split(',')]
                if str(value) not in wanted:
                    return False
            elif cond == 'not.is.null':
                if value is None:
                    return False
            elif cond.startswith('gt.'):
                if value is None or str(value) <= cond[3:]:
                    return False
            else:
                raise AssertionError(f'unsupported filter {col}={cond}')
        return True

    def select(self, table, query):
        return [dict(r) for r in self.tables.get(table, []) if self._match(r, self._filters(query))]

    def insert(self, table, rows):
        self.writes.append(('insert', table, len(rows)))
        created = []
        for r in rows:
            row = {'id': f'{table}-{next(self._ids)}', **r}
            self.tables.setdefault(table, []).append(row)
            created.append(dict(row))
        return created

    def update(self, table, filter_, patch):
        self.writes.append(('update', table, tuple(sorted(patch))))
        hit = [r for r in self.tables.get(table, []) if self._match(r, self._filters(filter_))]
        for r in hit:
            r.update(patch)
        return [dict(r) for r in hit]

    def delete(self, table, filter_):
        self.writes.append(('delete', table))
        self.tables[table] = [r for r in self.tables.get(table, []) if not self._match(r, self._filters(filter_))]


def install(fake, *modules):
    for m in modules:
        for name in ('select', 'insert', 'update', 'delete'):
            if hasattr(m, name):
                setattr(m, name, getattr(fake, name))


def fresh(module_name):
    """A newly loaded module, so its caches start empty."""
    return importlib.reload(importlib.import_module(module_name))


def fixture(**over):
    base = {
        'date': '03/10/2026', 'time': '14:30',
        'home_team': 'HKFC A', 'away_team': 'Valley A',
        'division': 'Premier', 'venue': 'HKFC',
        'home_score': '', 'away_score': '',
        'match_status': 'Scheduled',
    }
    return {**base, **over}


class MatchesTest(unittest.TestCase):
    def setUp(self):
        self.m = fresh('src.supabase.matches')
        self.db = FakeDb({'matches': []})
        install(self.db, self.m)

    def test_new_fixture_is_inserted_in_hong_kong_time(self):
        row_id = self.m.upsert_match(fixture())
        self.assertIsNotNone(row_id)
        row = self.db.tables['matches'][0]
        self.assertEqual(row['match_key'], '2026-10-03|HKFC A|Valley A')
        self.assertEqual(row['match_date'], '2026-10-03T14:30:00+08:00')
        self.assertEqual(row['match_status'], 'Scheduled')
        self.assertIn('last_hkha_sync', row)

    def test_unchanged_fixture_is_not_written_again(self):
        self.db.tables['matches'] = [{
            'id': 'm1', 'lock_hkha_sync': False, 'fixture_id': None,
            'match_key': '2026-10-03|HKFC A|Valley A', 'match_status': 'Scheduled',
            # As PostgREST returns it: the same instant, in UTC.
            'match_date': '2026-10-03T06:30:00+00:00',
            'division': 'Premier', 'home_team': 'HKFC A', 'away_team': 'Valley A',
            'venue': 'HKFC', 'ump_1': None, 'ump_2': None, 'home_score': None, 'away_score': None,
        }]
        self.assertEqual(self.m.upsert_match(fixture()), 'm1')
        self.assertEqual(self.db.writes, [])

    def test_fixture_id_promotes_the_match_key_row_and_then_wins(self):
        self.m.upsert_match(fixture())
        row_id = self.m.upsert_match(fixture(fixture_id='9001', umpire1='SMITH John'))
        self.assertEqual(len(self.db.tables['matches']), 1)
        row = self.db.tables['matches'][0]
        self.assertEqual(row['id'], row_id)
        self.assertEqual(row['fixture_id'], '9001')
        self.assertEqual(row['ump_1'], 'SMITH John')

        # MenFixture no longer writes to a row that has a Fixture Id.
        writes = len(self.db.writes)
        self.assertIsNone(self.m.upsert_match(fixture(venue='Somewhere else')))
        self.assertEqual(len(self.db.writes), writes)
        self.assertEqual(row['venue'], 'HKFC')

    def test_a_result_makes_the_match_played(self):
        self.m.upsert_match(fixture(fixture_id='9001'))
        self.m.upsert_match(fixture(fixture_id='9001', home_score='3', away_score='1'))
        row = self.db.tables['matches'][0]
        self.assertEqual((row['home_score'], row['away_score'], row['match_status']), (3, 1, 'Played'))

    def test_locked_row_only_has_blanks_filled(self):
        self.db.tables['matches'] = [{
            'id': 'm1', 'lock_hkha_sync': True, 'fixture_id': None,
            'match_key': '2026-09-01|TBC|TBC', 'match_status': 'Scheduled',
            'match_date': '2026-10-03T06:30:00+00:00',
            'division': 'Premier', 'home_team': 'HKFC A', 'away_team': 'Valley A',
            'venue': 'Hand-fixed venue', 'ump_1': None, 'ump_2': None, 'home_score': None, 'away_score': None,
        }]
        # HKHA's corrected version: same date and teams, found through the locked row's own values.
        row_id = self.m.upsert_match(fixture(fixture_id='9001', venue='HKHA venue', umpire1='SMITH John',
                                             home_score='2', away_score='2'))
        self.assertEqual(row_id, 'm1')
        self.assertEqual(len(self.db.tables['matches']), 1)
        row = self.db.tables['matches'][0]
        self.assertEqual(row['venue'], 'Hand-fixed venue')
        self.assertEqual(row['match_key'], '2026-09-01|TBC|TBC')
        self.assertEqual((row['fixture_id'], row['ump_1']), ('9001', 'SMITH John'))
        self.assertEqual((row['home_score'], row['away_score'], row['match_status']), (2, 2, 'Played'))

    def test_played_fixtures_for_phase_two(self):
        self.db.tables['matches'] = [
            {'id': 'a', 'fixture_id': '1', 'match_status': 'Played', 'match_date': '2999-01-01T00:00:00+00:00',
             'home_team': 'HKFC A', 'away_team': 'X'},
            {'id': 'b', 'fixture_id': None, 'match_status': 'Played', 'match_date': '2999-01-01T00:00:00+00:00'},
            {'id': 'c', 'fixture_id': '3', 'match_status': 'Scheduled', 'match_date': '2999-01-01T00:00:00+00:00'},
            {'id': 'd', 'fixture_id': '4', 'match_status': 'Played', 'match_date': '2000-01-01T00:00:00+00:00'},
        ]
        played = self.m.get_played_fixtures(30)
        self.assertEqual([(f['fixture_id'], f['record_id']) for f in played], [('1', 'a')])


def player(jersey, name, **over):
    return {
        'RawPlayerName': name, 'Jersey Number': jersey, 'Team': 'HKFC A', 'Player Team': 'HKFC A',
        'Goals Scored': 0, 'Cards': [], 'Captain': False, 'Goalkeeper': False, 'U21': False, 'VP': False,
        **over,
    }


class MatchCardsTest(unittest.TestCase):
    def setUp(self):
        self.c = fresh('src.supabase.match_cards')
        self.db = FakeDb({'match_cards': []})
        install(self.db, self.c)

    def test_card_is_inserted_then_left_alone(self):
        self.c.upsert_match_cards([player(7, 'SMITH John'), player(1, 'JONES Mike', Goalkeeper=True)], '9001', 'm1')
        self.assertEqual(self.db.writes, [('insert', 'match_cards', 2)])
        row = next(r for r in self.db.tables['match_cards'] if r['jersey_number'] == 1)
        self.assertTrue(row['goalkeeper'])
        self.assertEqual((row['fixture_id'], row['match_id'], row['cards']), ('9001', 'm1', []))
        self.assertNotIn('person_id', row)

        self.db.writes.clear()
        self.c.upsert_match_cards([player(7, 'SMITH John'), player(1, 'JONES Mike', Goalkeeper=True)], '9001', 'm1')
        self.assertEqual(self.db.writes, [])

    def test_changes_are_written_and_stale_players_removed(self):
        self.c.upsert_match_cards([player(7, 'SMITH John', Cards=['Y2']), player(9, 'LEE Sam')], '9001', 'm1')
        for r in self.db.tables['match_cards']:
            r['person_id'] = f'person-{r["jersey_number"]}'   # as the database trigger would link them
        self.db.writes.clear()

        self.c.upsert_match_cards([player(7, 'SMITH John', **{'Goals Scored': 2}), player(10, 'WONG Ka')], '9001', 'm1')

        rows = {r['jersey_number']: r for r in self.db.tables['match_cards']}
        self.assertEqual(sorted(rows), [7, 10])
        self.assertEqual((rows[7]['goals_scored'], rows[7]['cards']), (2, []))   # withdrawn card cleared
        self.assertEqual(rows[7]['person_id'], 'person-7')                        # link kept
        self.assertIn(('update', 'match_cards', ('cards', 'goals_scored')), self.db.writes)

    def test_a_new_name_on_a_jersey_drops_the_old_link(self):
        self.c.upsert_match_cards([player(7, 'SMITH John')], '9001', 'm1')
        self.db.tables['match_cards'][0]['person_id'] = 'person-smith'
        self.c.upsert_match_cards([player(7, 'CHAN Tai Man')], '9001', 'm1')
        row = self.db.tables['match_cards'][0]
        self.assertEqual(row['raw_player_name'], 'CHAN Tai Man')
        self.assertIsNone(row['person_id'])

    def test_other_fixtures_are_untouched(self):
        self.db.tables['match_cards'] = [{'id': 'other', 'fixture_id': '1234', 'jersey_number': 7}]
        self.c.upsert_match_cards([player(7, 'SMITH John')], '9001', 'm1')
        self.assertTrue(any(r['id'] == 'other' for r in self.db.tables['match_cards']))


class SyncStateTest(unittest.TestCase):
    def setUp(self):
        self.s = fresh('src.supabase.sync_state')
        self.db = FakeDb({'hkha_sync_state': [
            {'id': 's1', 'fixture_id': '9001', 'sync_status': 'Complete',
             'last_scraped': '2026-09-29T03:27:35+00:00', 'source_team': 'MS HKFC A'},
        ]})
        install(self.db, self.s)

    def test_map_uses_the_airtable_field_names(self):
        state = self.s.get_sync_state_map(['9001', '9002'])
        self.assertEqual(list(state), ['9001'])
        self.assertEqual(state['9001']['Sync Status'], 'Complete')
        self.assertEqual(state['9001']['Source Team'], 'MS HKFC A')

    def test_mark_scraped_updates_or_inserts(self):
        self.s.mark_scraped('9001', status='Error', error='HKHA down')
        self.s.mark_scraped('9002', status='Complete', match_record_id='m2')
        rows = {r['fixture_id']: r for r in self.db.tables['hkha_sync_state']}
        self.assertEqual((rows['9001']['sync_status'], rows['9001']['error_message']), ('Error', 'HKHA down'))
        self.assertEqual((rows['9002']['sync_status'], rows['9002']['match_id']), ('Complete', 'm2'))
        self.assertTrue(rows['9002']['match_card_imported'])


class ClientTest(unittest.TestCase):
    def test_filters_quote_their_values(self):
        self.assertEqual(supabase_client.eq('2026-10-03|HKFC A|Valley A'), 'eq.2026-10-03%7CHKFC%20A%7CValley%20A')
        self.assertEqual(supabase_client.in_list(['1', 'a,b']), 'in.("1","a%2Cb")')


if __name__ == '__main__':
    unittest.main()
