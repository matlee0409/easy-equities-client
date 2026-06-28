# Easy Equities and Satrix Python Client

Unofficial Python client for [Easy Equities](https://easyequities.io/) and [Satrix](https://satrix.co.za/). **Intended for personal use.**

Supports Python 3.8+.

[PyPI](https://pypi.org/project/easyequities-client/)

## Installation

```
pip install easyequities-client
```

## Features

**Accounts**
- List accounts: `client.accounts.list()`
- Holdings (with optional share counts): `client.accounts.holdings(account_id)`
- Valuations: `client.accounts.valuations(account_id)`
- Transactions: `client.accounts.transactions(account_id)`
- NAV chart (portfolio value over time): `client.accounts.nav_chart(account_id, period)`

**Instruments**
- Historical OHLCV prices: `client.instruments.historical_prices(contract_code, period)`
- Browse by category: `client.instruments.categories()`
- List & filter by group/sub-group: `client.instruments.list(asset_group, asset_sub_group)`
- Compare instruments (base-100 normalised): `client.instruments.compare(contract_codes, period)`
- Top movers (gainers & losers): `client.instruments.top_movers(asset_group, period, n)`
- Screener (filter by return range & sub-group): `client.instruments.screener(asset_group, period, min_return, max_return, sub_group)`
- Search by name or ticker (fuzzy): `client.instruments.search(query)`
- Recent news headlines: `client.instruments.news(contract_code_or_ticker)`

## Usage

```python
from easy_equities_client.clients import EasyEquitiesClient  # or SatrixClient

client = EasyEquitiesClient()
client.login(username='your username', password='your password')

# ── Accounts ─────────────────────────────────────────────────────────────────

accounts = client.accounts.list()
# [Account(id='12345', name='EasyEquities ZAR', trading_currency_id='2'), ...]

holdings = client.accounts.holdings(accounts[0].id)
# [{"name": "CoreShares Global DivTrax ETF", "contract_code": "EQU.ZA.GLODIV",
#   "purchase_value": "R2 000.00", "current_value": "R3 000.00", ...}, ...]

holdings = client.accounts.holdings(accounts[0].id, include_shares=True)
# includes "shares": "200.123" on each entry

valuations = client.accounts.valuations(accounts[0].id)
# {"TopSummary": {"AccountValue": 300000.50, "AccountCurrency": "ZAR", ...}, ...}

transactions = client.accounts.transactions(accounts[0].id)
# [{"Action": "Foreign Dividend", "DebitCredit": 50.00, "ContractCode": "EQU.ZA.GLODIV", ...}, ...]

from easy_equities_client.instruments.types import Period
nav = client.accounts.nav_chart(accounts[0].id, Period.ONE_YEAR)
# {"success": True, "period": "1y", "data_points": [...], "message": None}

# ── Historical prices ─────────────────────────────────────────────────────────

prices = client.instruments.historical_prices('EQU.ZA.SYGJP', Period.ONE_MONTH)
# {"success": True, "currentPrice": 85.50, "timeSeries": [{"date": "...", "open": ..., "close": ...}, ...]}

# ── Browse categories ─────────────────────────────────────────────────────────

categories = client.instruments.categories()
# [{"asset_group": "US ETFs", "count": 119, "sub_groups": [...]}, ...]

instruments = client.instruments.list(asset_group='US ETFs', asset_sub_group='Technology')
# [{"InstrumentName": "...", "ContractCode": "...", ...}, ...]

# ── Compare instruments ───────────────────────────────────────────────────────

result = client.instruments.compare(['EQU.ZA.SYGJP', 'NVDA', 'ARKK'], Period.ONE_YEAR)
for name, series in result['series'].items():
    print(name, series[-1])  # last normalised value (base 100)
for name, ret in result['total_return_pct'].items():
    print(name, f'{ret:+.2f}%')

# ── Top movers ────────────────────────────────────────────────────────────────

movers = client.instruments.top_movers(asset_group='US ETFs', period=Period.ONE_MONTH, n=5)
for g in movers['gainers']:
    print(f"{g['total_return_pct']:+.2f}%  {g['ticker']}  {g['name']}")
for l in movers['losers']:
    print(f"{l['total_return_pct']:+.2f}%  {l['ticker']}  {l['name']}")

# ── Screener ──────────────────────────────────────────────────────────────────

# All US ETFs that gained ≥ 5 % last month
result = client.instruments.screener(
    asset_group='US ETFs',
    period=Period.ONE_MONTH,
    min_return=5.0,
)

# SA equities in Technology down between 5 % and 20 % over 3 months
result = client.instruments.screener(
    asset_group='Equities',
    period=Period.THREE_MONTHS,
    min_return=-20.0,
    max_return=-5.0,
    sub_group='Technology',
)

for m in result['matches']:
    print(f"{m['total_return_pct']:+.2f}%  {m['ticker']}  {m['name']}")

# ── Search ────────────────────────────────────────────────────────────────────

hits = client.instruments.search('Tesla')
hits = client.instruments.search('NVDA')
hits = client.instruments.search('ARK', asset_group='US ETFs')
for h in hits['results']:
    print(h['score'], h['ticker'], h['name'], h['contract_code'])

# ── News ──────────────────────────────────────────────────────────────────────

news = client.instruments.news('TSLA')
news = client.instruments.news('NVDA', max_results=5)
for h in news['headlines']:
    print(h['published'], f"[{h['source']}]")
    print(' ', h['title'])
    print(' ', h['url'])
```

## Periods

```python
from easy_equities_client.instruments.types import Period

Period.ONE_WEEK
Period.ONE_MONTH
Period.THREE_MONTHS
Period.SIX_MONTHS
Period.ONE_YEAR
Period.TWO_YEARS
Period.FIVE_YEARS
Period.MAX
```

## Asset Groups

Valid values for `asset_group` in `list()`, `top_movers()`, and `screener()`:

`"Equities"`, `"ETFs"`, `"US ETFs"`, `"Bonds"`, `"Crypto"`, `"Unit Trusts"`, `"ETNs"`, `"US ETNs"`, `"Property"`

## Notes

- Historical prices, top movers, screener, and compare use [yfinance](https://github.com/ranaroussi/yfinance) to fetch market data — no EasyEquities API key needed for those.
- News uses the free Google News RSS feed — no API key needed.
- The `search()` method uses Python's built-in `difflib` — no external deps.
- This is an unofficial client. EasyEquities may change their API at any time.

## Contributing

See [Contributing](./CONTRIBUTING.md)
