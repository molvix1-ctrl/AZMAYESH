"""Read-only source checks; no Telegram messages or trades are sent."""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from launcher import load_settings


def check(url, expected=None):
    try:
        with urlopen(Request(url, headers={'User-Agent': 'AzmayeshResearchBot/0.2'}), timeout=20) as response:
            if expected:
                data = json.load(response)
                if not isinstance(data, dict) or not isinstance(data.get(expected), list):
                    return 'REACHABLE, but API schema mismatch'
                return f'API OK, {len(data[expected])} rows (not strategy validation)'
            return f'HTTP {response.status}, homepage only; NOT a data integration'
    except HTTPError as exc:
        return f'FAILED: HTTP {exc.code} (authorization, throttling or source response)'
    except URLError as exc:
        if '403' in str(exc.reason):
            return 'FAILED: proxy CONNECT denied with HTTP 403; check active network policy'
        return 'FAILED: connection or TLS error (no credentials logged)'
    except (ValueError, TypeError, OSError):
        return 'FAILED: invalid JSON, response or connection error'


def main():
    load_settings()
    from bot import TSETMC, CODAL, Bot
    for name, url, key in [
        ('TSETMC', TSETMC+'ClosingPrice/GetMarketWatch?market=0&paperTypes%5B0%5D=1&withBestLimits=true', 'marketwatch'),
        ('Codal', CODAL+'?PageNumber=1&Symbol=%D9%81%D9%88%D9%84%D8%A7%D8%AF', 'Letters'),
        ('Bourseek', 'https://bourseek.ir/', None), ('Tindex', 'https://tindex.app/', None),
    ]:
        print(name + ': ' + check(url, key), flush=True)
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if token:
        try:
            result = Bot(token).api('getMe', {})
            print('Telegram: getMe OK, @' + str(result.get('username', '')))
        except Exception:
            print('Telegram: FAILED (token was not logged)')
    else:
        print('Telegram: NOT TESTED, token missing')


if __name__ == '__main__':
    main()
