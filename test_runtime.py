import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from bot import Bot, DataError, scan
from demo import fixture
from launcher import load_settings


class LatestSessionTests(unittest.TestCase):
    def test_after_hours_uses_last_session_and_excludes_same_day_history(self):
        rows, histories, now = fixture()
        tomorrow = now + timedelta(days=1)
        # A history endpoint can include the same session as the quote.
        for code in histories:
            histories[code].append(dict(histories[code][-1], dEven=rows[0]['dEven'],
                                        pClosing=1))
        results, checked, errors = scan(rows, histories.__getitem__, tomorrow, mode='latest')
        self.assertEqual((len(results), checked, errors), (2, 2, 0))
        live, _, _ = scan(rows, histories.__getitem__, tomorrow, mode='live')
        self.assertEqual(live, [])

    def test_no_mixing_dates_no_older_than_seven_days(self):
        rows, histories, now = fixture()
        rows[1]['dEven'] = int((now-timedelta(days=1)).strftime('%Y%m%d'))
        _, checked, _ = scan(rows, histories.__getitem__, now, mode='latest')
        self.assertEqual(checked, 1)
        _, checked, _ = scan(rows, histories.__getitem__, now+timedelta(days=8), mode='latest')
        self.assertEqual(checked, 0)

    def test_bad_mode_refused(self):
        with self.assertRaises(DataError):
            scan([], lambda _: [], mode='unknown')


class RuntimeTests(unittest.TestCase):
    @patch('bot.time.sleep')
    def test_network_recovery_at_startup_without_losing_offset(self, sleep):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'offset'
            path.write_text('12')
            client = Bot('fake', '123')
            with patch.object(client, 'api', side_effect=[DataError('offline'), {'id': 1}, KeyboardInterrupt]) as api:
                with self.assertRaises(KeyboardInterrupt):
                    client.run(path)
            sleep.assert_called_once_with(10)
            self.assertEqual(api.call_args_list[-1].args[1]['offset'], 12)
            self.assertEqual(path.read_text(), '12')

    @patch.dict(os.environ, {}, clear=True)
    def test_private_bot_requires_explicit_owner(self):
        with self.assertRaises(DataError):
            Bot('fake').run(Path('not-created/offset'))
        self.assertFalse(Path('not-created').exists())

    @patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'injected'}, clear=True)
    def test_local_settings_preserve_environment_and_ignore_unrelated_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            path.write_text(json.dumps({'TELEGRAM_BOT_TOKEN': 'local', 'TELEGRAM_CHAT_ID': '123',
                                        'REPORT_MODE': 'latest', 'UNRELATED': 'ignored'}))
            load_settings(path)
            self.assertEqual(os.environ['TELEGRAM_BOT_TOKEN'], 'injected')
            self.assertEqual(os.environ['TELEGRAM_CHAT_ID'], '123')
            self.assertNotIn('UNRELATED', os.environ)


if __name__ == '__main__':
    unittest.main()
