import copy
import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from bot import Bot, DataError
from demo import fixture
from fundamentals import assess, combine


def statement(today):
    return dict(published_at=(today-timedelta(days=10)).isoformat(),
                period_end=(today-timedelta(days=40)).isoformat(),
                source_url='https://www.codal.ir/Reports/example', comparable_yoy=True,
                revenue=120, revenue_yoy=100, net_profit=15, net_profit_yoy=10,
                operating_cash_flow=14, total_debt=30, equity=60, eps_ttm=200, peers_pe=8)


class FundamentalTests(unittest.TestCase):
    def setUp(self):
        self.today = date.today()
        self.record = statement(self.today)
        self.pick = dict(last=1200, category='low', score=5)

    def test_growth_ratios_and_combination(self):
        result = combine(self.pick, self.record, self.today)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['fundamental']['revenue_growth'], .2)
        self.assertEqual(result['fundamental']['pe'], 6)
        self.assertGreater(result['score'], 5)

    def test_missing_stale_future_untrusted_incomparable(self):
        changes = ({'published_at': '2000-01-01'},
                   {'published_at': (self.today+timedelta(days=1)).isoformat()},
                   {'source_url': 'https://evil.test/report'}, {'comparable_yoy': False},
                   {'eps_ttm': float('nan')}, {'equity': 0}, {'net_profit_yoy': -1})
        for change in changes:
            with self.subTest(change=change):
                self.assertIsNone(assess(dict(self.record, **change), self.today))
        self.assertIsNone(assess({}, self.today))

    def test_profit_deterioration_never_becomes_high_risk_pick(self):
        record = dict(self.record, net_profit=5)
        self.assertIsNone(combine(dict(self.pick, category='high'), record, self.today))

    def test_conservative_group_stricter(self):
        record = dict(self.record, total_debt=90)
        self.assertIsNone(combine(self.pick, record, self.today))
        self.assertIsNotNone(combine(dict(self.pick, category='high'), record, self.today))

    @patch.dict(os.environ, {}, clear=True)
    def test_persian_command_missing_source_is_explicit(self):
        bot = Bot('fake')
        self.assertIn('تنظیم نشده', bot.answer('  تحلیل  '))
        self.assertIn('رشد مثبت', bot.answer('قوانین'))

    @patch.dict(os.environ, {'FUNDAMENTALS_URL': 'https://data.example.test/feed'}, clear=True)
    @patch('bot.daily_history')
    @patch('bot.market_watch')
    @patch('bot.get_json')
    def test_full_persian_combined_report(self, fetch, market, history):
        rows, histories, now = fixture()
        market.return_value = rows
        history.side_effect = histories.__getitem__
        record = statement(now.date())
        fetch.return_value = {'schema_version': 1, 'symbols': {
            row['lVal18AFC']: copy.deepcopy(record) for row in rows}}
        report = Bot('fake').answer('تحلیل')
        self.assertIn('دلیل بنیادی', report)
        self.assertIn('دلیل تکنیکال', report)
        self.assertIn('آزمایشیآرام', report)
        self.assertIn('آزمایشیپرنوسان', report)
        fetch.return_value = {'schema_version': 1, 'symbols': {}}
        report = Bot('fake').answer('تحلیل')
        self.assertNotIn('• آزمایشی', report)

    @patch.dict(os.environ, {'FUNDAMENTALS_URL': 'https://data.example.test/feed'}, clear=True)
    @patch('bot.get_json', return_value={'wrong': []})
    def test_invalid_provider_refused(self, _):
        with self.assertRaises(DataError):
            Bot('fake').answer('تحلیل')


if __name__ == '__main__':
    unittest.main()
