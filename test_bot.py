import copy
import unittest
from datetime import timedelta
from unittest.mock import patch

from bot import Bot, DataError, codal_report, evaluate, format_report, scan
from demo import fixture


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.history, self.now = fixture()

    def test_two_distinct_risk_groups(self):
        results, checked, errors = scan(self.rows, self.history.__getitem__, self.now)
        self.assertEqual({r['category'] for r in results}, {'high', 'low'})
        self.assertEqual((checked, errors), (2, 0))
        self.assertEqual(len({r['symbol'] for r in results}), 2)

    def test_stale_and_future_quotes_never_recommended(self):
        row = self.rows[0]
        self.assertIsNone(evaluate(row, self.history[1], self.now + timedelta(minutes=11)))
        self.assertIsNone(evaluate(row, self.history[1], self.now - timedelta(minutes=1)))

    def test_insufficient_history_and_price_discontinuity(self):
        self.assertIsNone(evaluate(self.rows[0], self.history[1][:10], self.now))
        history = copy.deepcopy(self.history[1])
        history[-1]['pClosing'] *= 2
        self.assertIsNone(evaluate(self.rows[0], history, self.now))

    def test_locked_queue_and_illiquidity(self):
        row = dict(self.rows[0], qTitMeOf=0)
        self.assertIsNone(evaluate(row, self.history[1], self.now))
        row = dict(self.rows[0], qTotCap=1_000_000)
        self.assertIsNone(evaluate(row, self.history[1], self.now))

    def test_invalid_numeric_data(self):
        for field in ('pClosing', 'qTotCap', 'pMeOf'):
            row = dict(self.rows[0], **{field: float('nan')})
            self.assertIsNone(evaluate(row, self.history[1], self.now))

    def test_history_failures_reported_without_fabrication(self):
        def broken(_):
            raise DataError('offline')
        results, checked, errors = scan(self.rows, broken, self.now)
        self.assertEqual((results, checked, errors), ([], 2, 2))
        report = format_report(results, checked, errors)
        self.assertIn('یافت نشد', report)

    def test_filter_and_demo_label(self):
        results, checked, errors = scan(self.rows, self.history.__getitem__, self.now)
        report = format_report(results, checked, errors, demo=True, category='low')
        self.assertIn('دادهٔ ساختگی', report)
        self.assertNotIn('آزمایشیپرنوسان', report)
        self.assertIn('آزمایشیآرام', report)


class IntegrationTests(unittest.TestCase):
    @patch('bot.get_json')
    def test_codal_normalizes_symbol_and_rejects_foreign_link(self, fetch):
        fetch.return_value = {'Letters': [
            {'Symbol': 'كگل', 'Title': 'گزارش آزمایشی', 'Url': 'https://example.com/evil'},
            {'Symbol': 'دیگر', 'Title': 'گزارش نامرتبط'}]}
        report = codal_report('کگل')
        self.assertIn('گزارش آزمایشی', report)
        self.assertNotIn('example.com', report)
        self.assertNotIn('نامرتبط', report)

    @patch('bot.daily_history')
    @patch('bot.market_watch')
    def test_command_pipeline_and_cache(self, market, history):
        rows, histories, _ = fixture()
        market.return_value = rows
        history.side_effect = histories.__getitem__
        bot = Bot('test-not-a-token')
        self.assertIn('آزمایشیآرام', bot.answer('/low'))
        self.assertIn('آزمایشیپرنوسان', bot.answer('/high@ResearchBot'))
        market.assert_called_once()

    @patch('bot.get_json')
    def test_telegram_payload_contract(self, fetch):
        fetch.return_value = {'ok': True, 'result': {'id': 1}}
        self.assertEqual(Bot('dummy').api('getMe', {}), {'id': 1})
        fetch.return_value = {'ok': False}
        with self.assertRaises(DataError):
            Bot('dummy').api('getMe', {})


if __name__ == '__main__':
    unittest.main()
