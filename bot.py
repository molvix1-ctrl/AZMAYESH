"""Persian equity research bot. Python 3.11+, standard library only."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from fundamentals import combine

TEHRAN = ZoneInfo('Asia/Tehran')
TSETMC = 'https://cdn.tsetmc.com/api/'
CODAL = 'https://search.codal.ir/api/search/v2/q'


class DataError(Exception):
    pass


def normalize(text):
    return str(text).replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', '').strip()


def get_json(url, payload=None, timeout=25):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=data, headers={
        'User-Agent': 'AzmayeshResearchBot/0.1', 'Accept': 'application/json',
        'Content-Type': 'application/json',
    })
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except Exception:
        # urllib exceptions can include the Telegram token in their URL.
        raise DataError('دریافت داده ناموفق بود؛ شبکه، مجوز منبع و قالب پاسخ را بررسی کنید.') from None


def market_watch():
    query = urlencode({'market': 0, 'industrialGroup': '', 'paperTypes[0]': 1,
                       'showTraded': 'false', 'withBestLimits': 'true'})
    data = get_json(TSETMC + 'ClosingPrice/GetMarketWatch?' + query)
    rows = data.get('marketwatch') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise DataError('قالب دیده‌بان TSETMC شناخته نشد؛ اتصال نیاز به تطبیق دارد.')
    return rows


def daily_history(ins_code):
    data = get_json(TSETMC + 'ClosingPrice/GetClosingPriceDailyList/' + str(int(ins_code)) + '/0')
    rows = data.get('closingPriceDaily') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise DataError('قالب سابقهٔ TSETMC شناخته نشد.')
    return rows


def fresh(row, now):
    """Only accept snapshots within ten minutes, never replay yesterday's picks."""
    try:
        stamp = datetime.strptime(str(int(row['dEven'])) + f"{int(row['hEven']):06}",
                                  '%Y%m%d%H%M%S').replace(tzinfo=TEHRAN)
        return 0 <= (now - stamp).total_seconds() <= 600
    except (KeyError, ValueError, TypeError):
        return False


def evaluate(row, history, now):
    """Heuristic screen, not an expected-return or probability model."""
    if not fresh(row, now):
        return None
    try:
        today = int(now.strftime('%Y%m%d'))
        by_date = {int(h['dEven']): h for h in history if int(h['dEven']) < today
                   and float(h['pClosing']) > 0 and float(h['qTotTran5J']) > 0}
        past = [by_date[d] for d in sorted(by_date)][-21:]
        if len(past) < 21:
            return None
        if (now.date() - datetime.strptime(str(int(past[-1]['dEven'])), '%Y%m%d').date()).days > 7:
            return None
        prices = [float(h['pClosing']) for h in past]
        returns = [b / a - 1 for a, b in zip(prices, prices[1:])]
        # Unadjusted corporate actions can look like trading opportunities.
        if any(abs(r) > .15 for r in returns):
            return None
        close, last = float(row['pClosing']), float(row['pDrCotVal'])
        volume, value = float(row['qTotTran5J']), float(row['qTotCap'])
        average_value = statistics.mean(float(h['qTotCap']) for h in past[-20:])
        if not all(math.isfinite(v) and v > 0 for v in (close, last, volume, value, average_value)):
            return None
        # 10 billion IRR minimum both today and on average; research default.
        if min(value, average_value) < 10_000_000_000:
            return None
        # Require two-sided executable quotes. Skip locked queues / invalid quotes.
        bid, ask = float(row['pMeDem']), float(row['pMeOf'])
        if not (0 < bid <= ask and float(row['qTitMeDem']) > 0 and float(row['qTitMeOf']) > 0):
            return None
        spread = (ask - bid) / ((ask + bid) / 2)
        if spread > .01:
            return None
        volatility = statistics.stdev(returns)
        momentum = close / prices[-5] - 1
        volume_ratio = volume / statistics.mean(float(h['qTotTran5J']) for h in past[-20:])
        if momentum <= 0 or close < statistics.mean(prices[-20:]):
            return None
        if volatility <= .02 and spread <= .005:
            category = 'low'
        elif volatility > .02:
            category = 'high'
        else:
            return None
        score = 100 * momentum + min(volume_ratio, 3) + math.log10(average_value / 1e9) - 100 * spread
        if category == 'low':
            score -= 100 * volatility
        values = (momentum, volatility, volume_ratio, spread, score)
        if not all(math.isfinite(v) for v in values):
            return None
        return dict(symbol=normalize(row['lVal18AFC']), category=category, score=score,
                    momentum=momentum, volatility=volatility, volume_ratio=volume_ratio,
                    spread=spread, value=value, last=last, timestamp=int(row['hEven']),
                    date=int(row['dEven']), ma20=statistics.mean(prices[-20:]))
    except (KeyError, ValueError, TypeError, statistics.StatisticsError, OverflowError):
        return None


def scan(rows, history_loader, now=None):
    now = now or datetime.now(TEHRAN)
    eligible = [r for r in rows if fresh(r, now)]
    # Bounded API work: rank by traded value first, then fetch up to 40 histories.
    def value(row):
        try:
            n = float(row.get('qTotCap', 0))
            return n if math.isfinite(n) else 0
        except (TypeError, ValueError):
            return 0
    candidates = sorted(eligible, key=value, reverse=True)[:40]
    errors = []
    def one(row):
        try:
            return evaluate(row, history_loader(row['insCode']), now)
        except (DataError, KeyError, ValueError):
            errors.append(1)
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [r for r in pool.map(one, candidates) if r]
    return sorted(results, key=lambda r: r['score'], reverse=True), len(candidates), len(errors)


def format_report(results, checked, errors, demo=False, category=None):
    title = '🧪 دادهٔ ساختگی — فقط نمایش عملکرد' if demo else 'دیده‌بان پژوهشی معاملات روزانه'
    lines = [title, datetime.now(TEHRAN).strftime('%Y-%m-%d %H:%M تهران'),
             f'دامنه: حداکثر ۴۰ نماد پُرمعامله | بررسی: {checked} | خطای سابقه: {errors}']
    for key, label in [('high', '۱) ریسک بالا / فرصت نوسان بیشتر'),
                       ('low', '۲) ریسک پایین‌تر / نوسان کمتر')]:
        if category and category != key:
            continue
        lines.append('\n' + label)
        picks = [p for p in results if p['category'] == key][:5]
        if not picks:
            lines.append('نامزد واجد شرایط با دادهٔ تازه یافت نشد.')
        for p in picks:
            lines.append(f"• {p['symbol']} | آخرین: {p['last']:,.0f} ریال\n"
                         f"روند ۵جلسه‌ای: {p['momentum']:+.1%} | نوسان روزانه: {p['volatility']:.1%}\n"
                         f"حجم نسبت به میانگین روز کامل: {p['volume_ratio']:.2f} | فاصله خریدوفروش: {p['spread']:.2%}\n"
                         f"ارزش معاملات: {p['value']/1e9:.1f} میلیارد ریال | ساعت داده: {p['timestamp']:06}")
            lines.append('دلیل تکنیکال: روند پنج‌جلسه‌ای مثبت و قیمت بالاتر از میانگین ۲۰جلسه است؛ '
                         'این یعنی جهت اخیر صعودی بوده، نه تضمین ادامهٔ صعود.\n'
                         'نقدشوندگی: ارزش معاملات و فاصلهٔ خریدوفروش از فیلتر عبور کرده‌اند؛ '
                         'فاصله کمتر معمولاً هزینهٔ ورودوخروج را کمتر می‌کند.\n'
                         + ('ریسک: نوسان تاریخی بالاتر از ۲٪؛ امکان زیان سریع‌تر هم بیشتر است.'
                            if p['category'] == 'high' else
                            'ریسک: نوسان تاریخی حداکثر ۲٪ و فاصله قیمت حداکثر نیم درصد؛ ریسک آینده می‌تواند تغییر کند.'))
            if 'fundamental' in p:
                f = p['fundamental']
                lines.append(f"دلیل بنیادی: رشد فروش {f['revenue_growth']:+.1%} و سود {f['profit_growth']:+.1%} نسبت به دوره مشابه.\n"
                             f"کیفیت سود: جریان نقد عملیاتی/سود {f['cash_quality']:.2f}؛ نسبت بالاتر یعنی پشتوانه نقدی بیشتر سود.\n"
                             f"بدهی/حقوق صاحبان سهام {f['debt_equity']:.2f}؛ نسبت بالاتر یعنی اهرم بیشتر.\n"
                             f"P/E سهم {f['pe']:.1f} در برابر میانه هم‌گروه {f['peers_pe']:.1f}؛ ارزانی به‌تنهایی دلیل خرید نیست.\n"
                             f"پایان دوره: {f['period_end']} | انتشار: {f['published_at']}\n{f['source_url']}")
    lines.extend(['\nمنبع رتبه‌بندی: TSETMC؛ اطلاعیه‌های کدال با /codal نماد.',
                  'بورسیک و تیندکس هنوز متصل نیستند. تحلیل خودکار متن اطلاعیه انجام نمی‌شود.',
                  'رتبهٔ پژوهشی؛ سود روزانه یا هفتگی را پیش‌بینی یا تضمین نمی‌کند. '
                  'ریسک پایین‌تر به معنی بدون زیان نیست. کارمزد، لغزش، صف و توقف می‌توانند نتیجه را تغییر دهند. '
                  'روش هنوز بک‌تست نشده؛ حجم ابتدای بازار با روز کامل قابل مقایسه نیست.'])
    return '\n'.join(lines)


def codal_report(symbol):
    symbol = normalize(symbol)
    if not symbol or len(symbol) > 40:
        return 'نمونه: /codal فولاد'
    data = get_json(CODAL + '?' + urlencode({'PageNumber': 1, 'Symbol': symbol, 'search': 'true'}))
    if not isinstance(data, dict) or not isinstance(data.get('Letters'), list):
        raise DataError('قالب پاسخ کدال شناخته نشد.')
    lines = [f'اطلاعیه‌های کدال: {symbol} — بدون تحلیل اثر بر قیمت']
    for row in data['Letters'][:5]:
        if normalize(row.get('Symbol', '')) != symbol:
            continue
        link = urljoin('https://www.codal.ir/', str(row.get('Url', '')))
        if not link.startswith('https://www.codal.ir/'):
            link = 'https://www.codal.ir/'
        lines.append(f"• {str(row.get('Title', ''))[:300]}\n{str(row.get('PublishDateTime', ''))[:50]}\n{link}")
    if len(lines) == 1:
        lines.append('اطلاعیه‌ای برای این نماد در پاسخ منبع پیدا نشد.')
    return '\n'.join(lines)


HELP = ('دیده‌بان پژوهشی سهام ایران\n/scan هر دو دسته\n/high ریسک بالا\n/low ریسک پایین‌تر\n'
        'تحلیل — بررسی ترکیبی بنیادی و تکنیکال با دلیل\nقوانین — توضیح روش\n'
        '/codal نماد — اطلاعیه‌های کدال\n/status وضعیت منابع\n/sources لینک و وضعیت منابع\n'
        'تمرکز: غربال روزانه با روند ۵جلسه‌ای؛ این بات سفارش خریدوفروش ثبت نمی‌کند.')


class Bot:
    def __init__(self, token, allowed_chat=None):
        self.token = token
        self.allowed_chat = allowed_chat
        self.cache = None
        self.cache_at = 0

    def combined_analysis(self):
        """Strict combined mode: missing financials must never become a buy thesis."""
        source = os.environ.get('FUNDAMENTALS_URL')
        path = os.environ.get('FUNDAMENTALS_FILE')
        if source:
            if not source.startswith('https://'):
                raise DataError('منبع بنیادی باید HTTPS باشد.')
            records = get_json(source)
        elif path:
            try:
                records = json.loads(Path(path).read_text())
            except (OSError, ValueError):
                raise DataError('دادهٔ بنیادی قابل خواندن نیست.') from None
        else:
            return ('تحلیل ترکیبی فعلاً ممکن نیست: منبع ارقام صورت‌های مالی تنظیم نشده است.\n'
                    'برای ارائه پیشنهاد بنیادی، رشد فروش و سود، جریان نقد، بدهی، EPS و ارزش‌گذاری '
                    'با تاریخ و لینک گزارش لازم است. عنوان اطلاعیه جای این داده‌ها را نمی‌گیرد.\n'
                    '/scan فقط غربال تکنیکال آموزشی است. با «قوانین» روش را ببینید.')
        if not isinstance(records, dict) or records.get('schema_version') != 1 or not isinstance(records.get('symbols'), dict):
            raise DataError('قالب منبع بنیادی معتبر نیست؛ قرارداد fundamentals.example.json را بررسی کنید.')
        symbols = {normalize(key): value for key, value in records['symbols'].items()}
        results, checked, errors = scan(market_watch(), daily_history)
        combined = []
        missing = 0
        for pick in results:
            record = symbols.get(pick['symbol'])
            enriched = combine(pick, record, datetime.now(TEHRAN).date()) if isinstance(record, dict) else None
            if enriched:
                combined.append(enriched)
            else:
                missing += 1
        combined.sort(key=lambda p: p['score'], reverse=True)
        return ('تحلیل ترکیبی بنیادی + تکنیکال\n'
                f'حذف به‌علت فقدان/کهنگی داده یا عدم احراز قواعد بنیادی: {missing}\n'
                + format_report(combined, checked, errors))

    def api(self, method, payload):
        data = get_json(f'https://api.telegram.org/bot{self.token}/{method}', payload, timeout=45)
        if not isinstance(data, dict) or not data.get('ok'):
            raise DataError('تلگرام درخواست را نپذیرفت؛ تنظیمات و دسترسی را بررسی کنید.')
        return data['result']

    def answer(self, text):
        if normalize(text) in ('تحلیل', '/analysis'):
            return self.combined_analysis()
        if normalize(text) in ('قوانین', '/rules'):
            return ('۱. فقط داده تازه و نماد نقدشونده با سفارش دوطرفه.\n'
                    '۲. روند مثبت پنج جلسه و قیمت بالای میانگین ۲۰جلسه.\n'
                    '۳. بنیادی: رشد مثبت فروش و سود دوره مشابه، جریان نقد مثبت، اهرم و P/E کنترل‌شده.\n'
                    '۴. گروه آرام‌تر: نوسان ≤۲٪، بدهی/حقوق ≤۱، نقد عملیاتی/سود ≥۰٫۸ و P/E ≤هم‌گروه.\n'
                    '۵. گروه پرنوسان: نوسان >۲٪، بدهی/حقوق ≤۲ و P/E ≤۱٫۵ برابر هم‌گروه.\n'
                    '۶. داده ناقص، قدیمی یا نامعتبر یعنی حذف؛ درصد احتمال رشد بدون بک‌تست اعلام نمی‌شود.\n'
                    '۷. افق بررسی روزانه با روند پنج‌جلسه‌ای است؛ بنیادی زمینه مالی است، نه زمان‌بندی قطعی.\n'
                    '۸. دلایل، زمان و منبع همراه نتیجه می‌آید؛ سود تضمین‌شده یا سهم بدون ریسک نداریم.')
        parts = text.strip().split(maxsplit=1)
        command = parts[0].split('@')[0] if parts else ''
        if command in ('/scan', '/high', '/low'):
            now = datetime.now(TEHRAN)
            expired = self.cache and any(not fresh({'dEven': r['date'], 'hEven': r['timestamp']}, now)
                                            for r in self.cache[0])
            if not self.cache or expired or time.monotonic() - self.cache_at > 60:
                self.cache = scan(market_watch(), daily_history)
                self.cache_at = time.monotonic()
            return format_report(*self.cache, category={'/high': 'high', '/low': 'low'}.get(command))
        if command == '/codal':
            return codal_report(parts[1] if len(parts) == 2 else '')
        if command == '/status':
            return ('TSETMC و کدال: اتصال هنگام درخواست؛ اعتبارسنجی زنده در این محیط هنوز انجام نشده.\n'
                    'بورسیک و تیندکس: آدرس مشخص؛ اتصال داده هنوز پیاده‌سازی نشده.\n'
                    'اگر داده بیش از ۱۰ دقیقه قدیمی باشد نامزد جدید نمایش داده نمی‌شود.')
        if command == '/sources':
            return ('TSETMC: https://www.tsetmc.com/ — دریافت داده هنگام اسکن، اتصال زنده تأیید نشده\n'
                    'کدال: https://www.codal.ir/ — دریافت اطلاعیه با /codal، اتصال زنده تأیید نشده\n'
                    'بورسیک: https://bourseek.ir/ — اتصال داده هنوز پیاده‌سازی نشده\n'
                    'تیندکس: https://tindex.app/ — اتصال داده هنوز پیاده‌سازی نشده')
        return HELP

    def run(self, state_path):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        offset = int(state_path.read_text()) if state_path.exists() else 0
        self.api('getMe', {})  # Fail early on invalid credentials, without logging token.
        print('Bot started (long polling).', flush=True)
        while True:
            try:
                for update in self.api('getUpdates', {'offset': offset, 'timeout': 30,
                                                       'allowed_updates': ['message']}):
                    msg = update.get('message', {})
                    chat_id = msg.get('chat', {}).get('id')
                    if chat_id is not None and (not self.allowed_chat or str(chat_id) == self.allowed_chat):
                        try:
                            answer = self.answer(msg.get('text', ''))
                        except DataError as exc:
                            answer = str(exc) + '\nدادهٔ ساختگی جایگزین دادهٔ زنده نمی‌شود.'
                        for start in range(0, len(answer), 3500):
                            self.api('sendMessage', {'chat_id': chat_id, 'text': answer[start:start+3500]})
                    offset = int(update['update_id']) + 1
                    temp = state_path.with_suffix('.tmp')
                    temp.write_text(str(offset))
                    temp.replace(state_path)
            except DataError:
                print('Service request failed; retrying in 10 seconds.', flush=True)
                time.sleep(10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan', action='store_true', help='Print a live report without Telegram')
    parser.add_argument('--demo', action='store_true', help='Use synthetic fixtures, never live picks')
    args = parser.parse_args()
    if args.demo:
        from demo import fixture
        rows, history, now = fixture()
        print(format_report(*scan(rows, lambda code: history[code], now), demo=True))
    elif args.scan:
        print(format_report(*scan(market_watch(), daily_history)))
    else:
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not token:
            parser.error('TELEGRAM_BOT_TOKEN تنظیم نشده؛ توکن را در چت یا مخزن قرار ندهید.')
        Bot(token, os.environ.get('TELEGRAM_CHAT_ID')).run(Path('.state/offset'))


if __name__ == '__main__':
    try:
        main()
    except DataError as exc:
        raise SystemExit(str(exc)) from None
