"""Load local configuration; independent from any chat or cloud environment."""
import json
import os
from pathlib import Path


def load_settings(path=Path('.state/settings.json')):
    if not path.exists():
        return
    settings = json.loads(path.read_text(encoding='utf-8'))
    allowed = {'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'FUNDAMENTALS_URL',
               'FUNDAMENTALS_FILE', 'BOT_PUBLIC', 'REPORT_MODE'}
    if not isinstance(settings, dict):
        raise ValueError('Invalid settings')
    for key, value in settings.items():
        if key in allowed and isinstance(value, str) and value:
            os.environ.setdefault(key, value)


if __name__ == '__main__':
    try:
        load_settings()
        from bot import main, DataError
        main()
    except KeyboardInterrupt:
        print('Stopped.')
    except Exception:
        # Never display arbitrary exceptions: they may include credential URLs.
        print('Startup or runtime failed. Check settings and run doctor.py. Secret values were not logged.')
        raise SystemExit(1) from None
