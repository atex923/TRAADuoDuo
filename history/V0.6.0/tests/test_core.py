import unittest
import tempfile
import sqlite3
from contextlib import closing
from pathlib import Path
from copy import deepcopy
from datetime import date
from decimal import Decimal
from traaduoduo.domain import (CalendarContext, calculate_day, count_workdays,
    calculate_finish, BudgetItem, calculate_budget, money, normalize_code, resolve_parent, legacy_in_view, rate_amount)
from traaduoduo.store import ProjectStore
from traaduoduo.session import EditSession
from traaduoduo.migrations import migrate_new


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'project.db'
        self.payload = ProjectStore.create(self.path, '測試工程')
        self.store = ProjectStore(self.path)

    def test_roundtrip_backup_and_no_overwrite(self):
        basic = dict(self.payload['pages']['basic'], name='更新名稱')
        self.store.save({'basic': basic}, 0)
        self.assertEqual(self.store.load()['pages']['basic']['name'], '更新名稱')
        backup = Path(self.temp.name) / 'backup.db'
        self.store.backup(backup)
        self.assertEqual(ProjectStore(backup).load()['pages'], self.store.load()['pages'])
        with self.assertRaises(FileExistsError):
            ProjectStore.create(self.path)
        with self.assertRaises(FileExistsError):
            self.store.backup(backup)

    def test_concurrent_update_rejected(self):
        self.store.save({}, 0)
        with self.assertRaises(ValueError):
            self.store.save({'basic': {}}, 0)
        self.assertEqual(self.store.load()['pages']['basic']['name'], '測試工程')

    def test_transaction_rolls_back(self):
        basic = dict(self.payload['pages']['basic'], name='不應寫入')
        with self.assertRaises(ValueError):
            self.store.save({'basic': basic, 'bad': {}}, 0)
        self.assertEqual(self.store.load()['pages']['basic']['name'], '測試工程')
        self.assertEqual(self.store.load()['metadata']['revision'], '0')

    def test_unknown_database_and_future_schema_untouched(self):
        with self.store.connect() as connection:
            connection.execute('PRAGMA user_version=999')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.load()
        self.assertEqual(before, self.path.read_bytes())
        unrelated = Path(self.temp.name) / 'other.db'
        with closing(sqlite3.connect(unrelated)) as connection:
            connection.execute('CREATE TABLE personal(value)')
        with self.assertRaises(ValueError):
            ProjectStore(unrelated).load()

    def test_project_isolation(self):
        other = ProjectStore.create(Path(self.temp.name) / 'other.db', '另一工程')
        self.assertNotEqual(other['metadata']['project_id'], self.payload['metadata']['project_id'])

    def test_initial_migration_rollback(self):
        with closing(sqlite3.connect(':memory:')) as connection:
            with self.assertRaises(RuntimeError):
                with connection:
                    connection.execute('BEGIN IMMEDIATE')
                    migrate_new(connection)
                    raise RuntimeError('injected failure')
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertFalse(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                migrate_new(connection)
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 8)

    def test_edit_locks_undo_ten_and_saved_state(self):
        session = EditSession(self.payload['pages'])
        with self.assertRaises(ValueError):
            session.change('holidays', [])
        session.unlocked.add('basic')
        for i in range(15):
            session.change('basic', dict(session.pages['basic'], name=str(i)))
        self.assertEqual(len(session.history['basic']), 10)
        session.undo('basic')
        self.assertEqual(session.pages['basic']['name'], '13')
        self.assertFalse(session.history['holidays'])
        self.assertTrue(session.dirty())
        session.saved = deepcopy(session.pages)
        self.assertFalse(session.dirty())

    def test_validation_duplicate_dates_and_nonfinite(self):
        session = EditSession(self.payload['pages'])
        session.pages['weather'] = [['2026-09-23', 'NaN', '0', '']]
        with self.assertRaises(ValueError):
            session.validate()
        session.pages['weather'] = []
        session.pages['holidays'] = [['2026-09-23', 'a'], ['2026-09-23', 'b']]
        with self.assertRaises(ValueError):
            session.validate()


class CalendarTests(unittest.TestCase):
    def test_override_order(self):
        saturday = date(2026, 9, 26)
        context = CalendarContext()
        self.assertEqual(calculate_day(saturday, context)[0], 0)
        context.makeup.add(saturday)
        self.assertEqual(calculate_day(saturday, context)[0], 1)
        context.holidays.add(saturday)
        self.assertEqual(calculate_day(saturday, context)[0], 0)
        context.weather[saturday] = ('0', '0', '-1')
        self.assertIn('-1', calculate_day(saturday, context)[1])
        context.railway.add(saturday)
        self.assertIn('輸運', calculate_day(saturday, context)[1])

    def test_legacy_weather(self):
        day = date(2026, 9, 23)
        for morning, afternoon, expected in [('0', '0', '1'), ('0', '.5', '.5'),
                                             ('.5', '0', '0'), ('1', '1', '0')]:
            ctx = CalendarContext(weather={day: (morning, afternoon, '')})
            self.assertEqual(calculate_day(day, ctx)[0], Decimal(expected))

    def test_finish_inclusive_and_leap_year(self):
        ctx = CalendarContext()
        self.assertEqual(calculate_finish(date(2026, 9, 25), 2, ctx), date(2026, 9, 28))
        self.assertEqual(count_workdays(date(2024, 2, 28), date(2024, 3, 1), ctx), 3)
        ctx.mode = '日曆天'
        self.assertEqual(calculate_finish(date(2026, 9, 25), 2, ctx), date(2026, 9, 26))


class BudgetTests(unittest.TestCase):
    def test_parent_quantity_policy_is_explicit(self):
        for kind, expected in [('rollup', '30.00'), ('analysis', '60.00')]:
            values, trace = calculate_budget([BudgetItem('01', Decimal(2), kind=kind),
                BudgetItem('011', Decimal(3), Decimal(10))])
            self.assertEqual(values['01'], Decimal(expected))
            self.assertEqual(trace['01']['children'], ['011'])

    def test_hierarchy_not_row_order(self):
        values, _ = calculate_budget([BudgetItem('01101', Decimal(2), Decimal('1.25')),
                                      BudgetItem('0'), BudgetItem('011'), BudgetItem('01')])
        self.assertEqual(values['0'], Decimal('2.50'))
        self.assertEqual(normalize_code(' 0 a 1 '), '0A1')

    def test_duplicate_missing_and_cycle(self):
        for items in ([BudgetItem('01'), BudgetItem('01')],
                      [BudgetItem('01', parent_id='missing')],
                      [BudgetItem('a', parent_id='b'), BudgetItem('b', parent_id='a')]):
            with self.assertRaises(ValueError):
                calculate_budget(items)

    def test_rounding_and_rates(self):
        self.assertEqual(money('1.23495'), Decimal('1.24'))
        self.assertEqual(money('-1.235'), Decimal('-1.24'))
        self.assertEqual(rate_amount('100.10', '.05'), Decimal('5.01'))

    def test_legacy_prefix_profiles(self):
        codes = ['0', '01', '011', '01101', '011010']
        self.assertEqual(resolve_parent('0110101', codes), '011010')
        self.assertTrue(legacy_in_view('011', 'summary'))
        self.assertFalse(legacy_in_view('01101', 'summary'))
        self.assertTrue(legacy_in_view('01101', 'detail'))
        self.assertFalse(legacy_in_view('0', 'detail'))
        self.assertTrue(legacy_in_view('011011', 'analysis'))
        self.assertFalse(legacy_in_view('01101', 'analysis'))


if __name__ == '__main__':
    unittest.main()
