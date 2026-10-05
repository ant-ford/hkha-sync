"""
Offline tests for HKFC's umpiring duties: reading them from the all-clubs
fixture page, and keeping public.umpire_duties in step.

    python -m unittest discover -s tests
"""
import unittest
from datetime import datetime

from src.hkha.fixture_fields import HK_TZ
from src.hkha.men_fixture import parse_fixtures_html
from src.hkha.umpire_duties import duty_slots, duty_team

from test_supabase_backend import FakeDb, install, fresh


def _row(cls, div, time, venue, home, away, ump1, ump2, official='&nbsp;', cp='&nbsp;'):
    cells = [cp, div, time, venue, home, away, ump1, ump2, official]
    return '<tr>' + ''.join(f'<td class="{cls}"><div>{c}</div></td>' for c in cells) + '</tr>'


def _title(text):
    return (f'<tr><td colspan="9" class="title"><div>{text}<a name="x"></a></div>'
            '<div><a href="#">Top</a></div></td></tr>')


PAGE = (
    '<table class="standing"><tr>'
    + ''.join(f'<th><div>{h}</div></th>' for h in
              ['C/P', 'Div', 'Time', 'Venue', 'Home', 'Away', 'Umpire 1', 'Umpire 2', 'Match Official'])
    + '</tr>'
    + _title('Friday, 2 Oct 2026')
    + _row('odd', '5', '18:50', 'HV2', 'Valley D', 'HKJ C', 'Rhino A', 'HKFC E')
    + _row('even', '1', '20:30', 'HKFC', 'Valley A', 'HK Masters', 'CHOR Ming Yeung - 4335', 'HUI Yun Fung - 4733')
    + _title('Sunday, 4 Oct 2026')
    + _row('odd', '3', '09:00', 'HKFC', 'HKFC F', 'Elite B', 'HKFC D', 'Valley B')
    + _row('even', '1', '12:30', 'HKFC', 'HKFC C', 'Antlers B', 'Appointed', 'Appointed')
    + _row('odd', '4', 'TBC', 'KP', 'KCC D', 'RHOBA A', 'HKFC G', 'HKFC H')
    + '</table>'
)


class ParseTest(unittest.TestCase):
    def test_duty_team(self):
        self.assertEqual(duty_team('HKFC F'), 'HKFC F')
        self.assertEqual(duty_team('HKFC\xa0E - Gurcharan'), 'HKFC E')
        self.assertIsNone(duty_team('Valley B'))
        self.assertIsNone(duty_team('HKFCA'))
        self.assertIsNone(duty_team('Appointed'))
        self.assertIsNone(duty_team(''))

    def test_all_clubs_page_gives_every_hkfc_duty(self):
        fixtures = parse_fixtures_html(PAGE, hkfc_only=False)
        self.assertEqual(len(fixtures), 5)
        slots = duty_slots(fixtures)
        self.assertEqual(
            sorted(s['duty_key'] for s in slots),
            [
                '2026-10-02|Valley D|HKJ C|2',
                '2026-10-04|HKFC F|Elite B|1',
                '2026-10-04|KCC D|RHOBA A|1',
                '2026-10-04|KCC D|RHOBA A|2',
            ],
        )
        tbc = [s for s in slots if s['home_team'] == 'KCC D']
        self.assertEqual({s['duty_team'] for s in tbc}, {'HKFC G', 'HKFC H'})
        self.assertEqual(tbc[0]['time'], 'TBC')

    def test_a_changed_page_is_none_not_empty(self):
        self.assertIsNone(parse_fixtures_html('<table class="standing"><tr><th>Other</th></tr></table>'))
        self.assertIsNone(parse_fixtures_html('<p>Maintenance</p>'))

    def test_scheduled_row_wins_over_rescheduled_on_the_same_date(self):
        base = {'date': '11/10/2026', 'home_team': 'A', 'away_team': 'B', 'umpire1': 'HKFC F', 'umpire2': ''}
        slots = duty_slots([
            {**base, 'time': '09:00', 'match_status': 'Rescheduled'},
            {**base, 'time': '10:45', 'match_status': 'Scheduled'},
        ])
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]['time'], '10:45')


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=HK_TZ)


def duty(**over):
    base = {
        'date': '11/10/2026', 'time': '09:00', 'division': '3', 'venue': 'HKFC',
        'home_team': 'HKFC F', 'away_team': 'Elite B', 'umpire1': 'HKFC D', 'umpire2': '',
        'match_status': 'Scheduled',
    }
    return duty_slots([{**base, **over}])


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.m = fresh('src.supabase.umpire_duties')
        self.db = FakeDb({'umpire_duties': []})
        install(self.db, self.m)

    def rows(self):
        return self.db.tables['umpire_duties']

    def test_new_duty_is_inserted(self):
        counts = self.m.sync_umpire_duties(duty(), now=NOW)
        self.assertEqual(counts['inserted'], 1)
        row = self.rows()[0]
        self.assertEqual(row['duty_key'], '2026-10-11|HKFC F|Elite B|1')
        self.assertEqual(row['match_date'], '2026-10-11T09:00:00+08:00')
        self.assertEqual(row['duty_team'], 'HKFC D')
        self.assertEqual(row['status'], 'scheduled')
        self.assertFalse(row['time_tbc'])

    def test_unchanged_duty_is_not_written(self):
        self.m.sync_umpire_duties(duty(), now=NOW)
        self.db.writes.clear()
        counts = fresh_sync(self, duty())
        self.assertEqual(counts['unchanged'], 1)
        self.assertEqual(self.db.writes, [])

    def test_new_time_and_duty_team_update_the_slot(self):
        self.m.sync_umpire_duties(duty(), now=NOW)
        counts = fresh_sync(self, duty(time='10:45', umpire1='HKFC G'))
        self.assertEqual(counts['updated'], 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['duty_team'], 'HKFC G')
        self.assertEqual(self.rows()[0]['match_date'], '2026-10-11T10:45:00+08:00')

    def test_future_duty_gone_from_the_list_is_cancelled_and_comes_back(self):
        self.m.sync_umpire_duties(duty() + duty(home_team='KCC D', away_team='RHOBA A'), now=NOW)
        counts = fresh_sync(self, duty())
        self.assertEqual(counts['cancelled'], 1)
        gone = [r for r in self.rows() if r['home_team'] == 'KCC D'][0]
        self.assertEqual(gone['status'], 'cancelled')
        fresh_sync(self, duty() + duty(home_team='KCC D', away_team='RHOBA A'))
        self.assertEqual(gone['status'], 'scheduled')

    def test_played_duty_gone_from_the_list_is_kept(self):
        self.m.sync_umpire_duties(duty(date='04/10/2026'), now=NOW)
        counts = fresh_sync(self, duty())
        self.assertEqual(counts['cancelled'], 0)
        old = [r for r in self.rows() if r['duty_key'].startswith('2026-10-04')][0]
        self.assertEqual(old['status'], 'scheduled')

    def test_unreadable_or_empty_page_changes_nothing(self):
        self.m.sync_umpire_duties(duty(), now=NOW)
        self.db.writes.clear()
        fresh_sync(self, None)
        fresh_sync(self, [])
        self.assertEqual(self.db.writes, [])


def fresh_sync(test, duties):
    """A second run: a newly loaded module over the same fake database."""
    test.m = fresh('src.supabase.umpire_duties')
    install(test.db, test.m)
    return test.m.sync_umpire_duties(duties, now=NOW)


if __name__ == '__main__':
    unittest.main()
