# pyeasyequities

Unofficial Python client for [Easy Equities](https://easyequities.io/) and [Satrix](https://satrix.co.za/).

**Intended for personal use. Supports Python 3.8+.**

[![PyPI](https://img.shields.io/pypi/v/pyeasyequities)](https://pypi.org/project/pyeasyequities/)

---

## Installation

```bash
pip install pyeasyequities
```

---

## Quick Start

```python
from easy_equities_client.clients import EasyEquitiesClient
# For Satrix accounts: from easy_equities_client.clients import SatrixClient

client = EasyEquitiesClient()
client.login(username='your_username', password='your_password')
```

---

## Accounts

### List accounts

```python
accounts = client.accounts.list()
# [Account(id='EE3237137-15547214', name='EasyEquities USD', trading_currency_id='2'), ...]
```

### Holdings

```python
holdings = client.accounts.holdings(accounts[0].id)
# [
#   {
#     "name": "CoreShares Global DivTrax ETF",
#     "contract_code": "EQU.ZA.GLODIV",
#     "purchase_value": "ZAR 2000.0",
#     "current_value": "ZAR 3000.0",
#     "current_price": "ZAR 15.5",
#     "img": "https://...",
#     "isin": "ZAE000254249",
#     "shares": "200.123",
#     "profit_loss_value": 1000.0,
#     "profit_loss_percentage": 50.0
#   },
#   ...
# ]
```

### Valuations

```python
val = client.accounts.valuations(accounts[0].id)
# {
#   "accountNumber": "EE3237137-15547214",
#   "productName": "EasyEquities USD",
#   "currencyCode": "USD",
#   "totalInvestmentHoldingsValue": 12345.67,
#   "InvestmentTypesAndManagers": { "types": [...], "managers": [...] },
#   "AccrualIncomeSummaryItems": [...],
#   "AccrualExpenseSummaryItems": [...],
#   "CostsSummaryItems": [...],
#   "costsTotal": 12.5
# }
```

### Transactions

```python
transactions = client.accounts.transactions(accounts[0].id)
# [
#   {
#     "Action": "Foreign Dividend",
#     "DebitCredit": 50.00,
#     "Comment": "CoreShares Global DivTrax ETF - Foreign Dividends @15.00",
#     "TransactionDate": "2023-11-19T14:30:00",
#     "ContractCode": "EQU.ZA.GLODIV"
#   },
#   ...
# ]
```

### Transactions for a date range

```python
from datetime import date

txns = client.accounts.transactions_for_period(
    accounts[0].id,
    start_date=date(2024, 1, 1),
    end_date=date(2024, 6, 30),
)
```

### NAV chart (portfolio value over time)

```python
from easy_equities_client.instruments.types import Period

chart = client.accounts.nav_chart(accounts[0].id, period=Period.THREE_MONTHS)
# {
#   "success": True,
#   "account_id": "EE3237137-15547214",
#   "period": "3mo",
#   "data": [{"date": "2024-04-01", "nav": 10234.56}, ...],
#   "message": None
# }

if chart["success"]:
    for point in chart["data"]:
        print(point["date"], point["nav"])
```

---

## Instruments

All instrument methods use the `Period` enum:

```python
from easy_equities_client.instruments.types import Period

Period.ONE_WEEK       # 1 week
Period.ONE_MONTH      # 1 month
Period.THREE_MONTHS   # 3 months
Period.SIX_MONTHS     # 6 months
Period.ONE_YEAR       # 1 year
Period.TWO_YEARS      # 2 years
Period.FIVE_YEARS     # 5 years
Period.MAX            # All available history
```

### Historical prices (OHLCV)

```python
prices = client.instruments.historical_prices('EQU.ZA.SYGJP', Period.ONE_MONTH)
# {
#   "success": True,
#   "contract_code": "EQU.ZA.SYGJP",
#   "ticker": "STX500.JO",
#   "currentPrice": 85.50,
#   "period": "1mo",
#   "prices": [
#     {"date": "2024-06-01", "open": 84.0, "high": 86.5, "low": 83.2, "close": 85.5, "volume": 12000},
#     ...
#   ],
#   "message": None
# }

for bar in prices["prices"]:
    print(bar["date"], bar["close"])
```

### Browse categories

```python
categories = client.instruments.categories()
# [
#   {"asset_group": "US ETFs", "count": 119, "asset_sub_groups": ["Technology", "Healthcare", ...]},
#   {"asset_group": "Equities", "count": 5241, "asset_sub_groups": [...]},
#   ...
# ]

for cat in categories:
    print(cat["asset_group"], cat["count"])
```

### List instruments (filter by group / sub-group)

```python
instruments = client.instruments.list(asset_group='US ETFs')
instruments = client.instruments.list(asset_group='Equities', asset_sub_group='Technology')
# [{"InstrumentName": "...", "ContractCode": "...", "AssetGroup": "...", ...}, ...]
```

**Valid asset groups:** `"Equities"`, `"ETFs"`, `"US ETFs"`, `"Bonds"`, `"Crypto"`, `"Unit Trusts"`, `"ETNs"`, `"US ETNs"`, `"Property"`

### Search by name or ticker (fuzzy)

```python
results = client.instruments.search("Tesla")
results = client.instruments.search("NVDA")
results = client.instruments.search("ARK", asset_group="US ETFs")
results = client.instruments.search("Satrix S&P 500", top=5)

# {
#   "query": "Tesla",
#   "total": 10,
#   "results": [
#     {"score": 1.0, "ticker": "TSLA", "name": "Tesla Inc",
#      "contract_code": "TSLA", "asset_group": "Equities", "asset_sub_group": "..."},
#     ...
#   ]
# }

for hit in results["results"]:
    print(f'{hit["score"]:.2f}  {hit["ticker"]:12s}  {hit["name"]}')
```

Scoring: exact match → 1.0 · starts-with → 0.9 · contains → 0.75 · token overlap → up to 0.7 · fuzzy → up to 0.6.
No external dependencies — uses Python's built-in `difflib`.

### Compare instruments (base-100 normalised)

```python
result = client.instruments.compare(
    contract_codes=['EQU.ZA.SYGJP', 'NVDA', 'ARKK'],
    period=Period.ONE_YEAR,
)
# {
#   "success": True,
#   "period": "1Y",
#   "base_date": "2023-06-28",
#   "instruments": [
#     {
#       "contract_code": "NVDA",
#       "name": "Nvidia Corp",
#       "ticker": "NVDA",
#       "total_return_pct": 185.4,
#       "normalised": [{"date": "2023-06-28", "value": 100.0}, ...]
#     },
#     ...
#   ]
# }

for inst in result["instruments"]:
    print(f'{inst["total_return_pct"]:+.2f}%  {inst["name"]}')
```

### Top movers (gainers & losers)

```python
movers = client.instruments.top_movers(
    asset_group='US ETFs',
    period=Period.ONE_MONTH,
    n=5,
    scan_limit=200,   # max instruments to scan
)
# {
#   "success": True,
#   "asset_group": "US ETFs",
#   "period": "1mo",
#   "scanned": 119,
#   "gainers": [{"ticker": "ARKG", "name": "ARK Genomic Revolution ETF",
#                "total_return_pct": 29.23, ...}, ...],
#   "losers":  [{"ticker": "TAN",  "name": "Invesco Solar ETF",
#                "total_return_pct": -19.37, ...}, ...]
# }

print("Top gainers:")
for g in movers["gainers"]:
    print(f'  {g["total_return_pct"]:+.2f}%  {g["ticker"]}  {g["name"]}')

print("Top losers:")
for l in movers["losers"]:
    print(f'  {l["total_return_pct"]:+.2f}%  {l["ticker"]}  {l["name"]}')
```

### Screener (filter by return range & sub-group)

```python
# All US ETFs that gained ≥ 5% last month
result = client.instruments.screener(
    asset_group='US ETFs',
    period=Period.ONE_MONTH,
    min_return=5.0,
)

# SA equities in Technology down 5–20% over 3 months
result = client.instruments.screener(
    asset_group='Equities',
    period=Period.THREE_MONTHS,
    min_return=-20.0,
    max_return=-5.0,
    sub_group='Technology',
)
# {
#   "success": True,
#   "scanned": 200,
#   "matched": 9,
#   "matches": [
#     {"ticker": "ARKG", "name": "ARK Genomic Revolution ETF",
#      "total_return_pct": 29.23, "asset_sub_group": "Healthcare", ...},
#     ...
#   ]
# }

for m in result["matches"]:
    print(f'{m["total_return_pct"]:+.2f}%  {m["ticker"]}  {m["name"]}')
```

| Parameter | Type | Description |
|---|---|---|
| `asset_group` | `str` | Asset group to search (see valid values above) |
| `period` | `Period` | Time period for return calculation |
| `min_return` | `float` or `None` | Minimum return % (inclusive). e.g. `5.0` = ≥ 5% |
| `max_return` | `float` or `None` | Maximum return % (inclusive). e.g. `-5.0` = ≤ -5% |
| `sub_group` | `str` or `None` | Case-insensitive sub-group filter (substring match) |
| `scan_limit` | `int` | Max instruments to scan, default `200` |

### News headlines

```python
news = client.instruments.news("TSLA")
news = client.instruments.news("NVDA", max_results=5)
news = client.instruments.news("ARKK")

# {
#   "instrument": "Tesla Inc",
#   "query": "Tesla Inc",
#   "total": 10,
#   "headlines": [
#     {
#       "title": "Tesla Settles Lawsuit Over Deadly Crash",
#       "source": "Bloomberg",
#       "published": "Fri, 26 Jun 2026 12:00:15 GMT",
#       "url": "https://..."
#     },
#     ...
#   ]
# }

for h in news["headlines"]:
    print(f'[{h["source"]}] {h["published"]}')
    print(f'  {h["title"]}')
    print(f'  {h["url"]}')
```

Accepts a contract code (e.g. `"EQU.ZA.SYGJP"`) or a ticker (e.g. `"TSLA"`). Resolves to the full instrument name for better headline relevance. Uses Google News RSS — no API key required.

---

## Notes

- **Historical prices, top movers, screener, and compare** use [yfinance](https://github.com/ranaroussi/yfinance) to fetch market data. No EasyEquities API key is needed for these.
- **News** uses the free Google News RSS feed. No API key needed.
- **Search** uses Python's built-in `difflib`. No external dependencies.
- This is an **unofficial** client. EasyEquities may change their API at any time.
- Order placement (buy/sell) is **not supported** — the trading endpoints are behind AWS IAM authentication which is not accessible with a Bearer JWT.

---

## Contributing

See [Contributing](./CONTRIBUTING.md)

## License

MIT
