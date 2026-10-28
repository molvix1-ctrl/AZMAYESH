"""Synthetic symbols only; no real-world price or recommendation."""
from datetime import datetime, timedelta
from bot import TEHRAN


def fixture():
    now = datetime.now(TEHRAN).replace(microsecond=0)
    rows, histories = [], {}
    for code, symbol, amplitude in [(1, 'آزمایشی‌آرام', .003), (2, 'آزمایشی‌پرنوسان', .035)]:
        price, history = 1000., []
        for i in range(21):
            price *= 1.007 + (amplitude if i % 2 == 0 else -amplitude)
            history.append({'dEven': int((now - timedelta(days=21-i)).strftime('%Y%m%d')),
                            'pClosing': price, 'qTotTran5J': 20_000_000,
                            'qTotCap': price * 20_000_000})
        histories[code] = history
        rows.append({'insCode': code, 'lVal18AFC': symbol,
                     'dEven': int(now.strftime('%Y%m%d')), 'hEven': int(now.strftime('%H%M%S')),
                     'pClosing': price * 1.01, 'pDrCotVal': price * 1.011,
                     'qTotTran5J': 25_000_000, 'qTotCap': price * 25_000_000,
                     'pMeDem': price, 'pMeOf': price * 1.002,
                     'qTitMeDem': 10000, 'qTitMeOf': 10000})
    return rows, histories, now
