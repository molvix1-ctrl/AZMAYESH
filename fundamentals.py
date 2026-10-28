"""Validated input contract for financial statements; never infer numbers from titles."""
import math
from datetime import date
from urllib.parse import urlparse


def assess(record, today):
    """Return auditable rule outcomes, or None for incomplete/incomparable inputs.

    Revenue/profit are same-duration, same-currency, same-consolidation YoY.
    Cash flow, profit, debt and equity are from the same statement period.
    Ratios are intentionally conservative research defaults, not forecasts.
    """
    try:
        published = date.fromisoformat(record['published_at'])
        period = date.fromisoformat(record['period_end'])
        if not (0 <= (today - published).days <= 150 and
                0 <= (published - period).days <= 180 and
                (today - period).days <= 240):
            return None
        source = urlparse(record['source_url'])
        if source.scheme != 'https' or source.hostname not in ('codal.ir', 'www.codal.ir'):
            return None
        if record.get('comparable_yoy') is not True:
            return None
        fields = ('revenue', 'revenue_yoy', 'net_profit', 'net_profit_yoy',
                  'operating_cash_flow', 'total_debt', 'equity', 'eps_ttm', 'peers_pe')
        values = {}
        for field in fields:
            raw = record[field]
            if isinstance(raw, bool):
                return None
            values[field] = float(raw)
        if not all(math.isfinite(x) for x in values.values()):
            return None
        if min(values['revenue'], values['revenue_yoy'], values['net_profit'],
               values['net_profit_yoy'], values['equity'], values['eps_ttm'], values['peers_pe']) <= 0:
            return None
        if values['total_debt'] < 0:
            return None
        revenue_growth = values['revenue'] / values['revenue_yoy'] - 1
        profit_growth = values['net_profit'] / values['net_profit_yoy'] - 1
        cash_quality = values['operating_cash_flow'] / values['net_profit']
        debt_equity = values['total_debt'] / values['equity']
        return dict(revenue_growth=revenue_growth, profit_growth=profit_growth,
                    cash_quality=cash_quality, debt_equity=debt_equity,
                    eps_ttm=values['eps_ttm'], peers_pe=values['peers_pe'],
                    source_url=record['source_url'], published_at=published.isoformat(),
                    period_end=period.isoformat())
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def combine(pick, record, today):
    result = assess(record, today)
    if result is None:
        return None
    pe = pick['last'] / result['eps_ttm']
    # Fundamental weakness excludes a candidate, even from the high-risk group.
    if (result['revenue_growth'] <= 0 or result['profit_growth'] <= 0 or
            result['cash_quality'] <= 0 or result['debt_equity'] > 2 or
            pe > result['peers_pe'] * 1.5):
        return None
    if pick['category'] == 'low' and (result['cash_quality'] < .8 or
                                      result['debt_equity'] > 1 or pe > result['peers_pe']):
        return None
    bonus = (min(result['revenue_growth'], .5) + min(result['profit_growth'], .5)
             + min(result['cash_quality'], 1) - result['debt_equity'] / 4)
    return dict(pick, fundamental=dict(result, pe=pe), score=pick['score'] + bonus)
