# Easy Equities and Satrix Python Client

> [!WARNING]  
> Not actively maintained anymore.

Unofficial Python client for [Easy Equities](easyequities.io/) and 
[Satrix](satrix.co.za/). **Intended for personal use.**

Supports Python 3.13+.

[Pypi](https://pypi.org/project/easy-equities-client/)


## Installation

```
pip install easy-equities-client
```

## Features

Accounts:
- Get accounts for a user: `client.accounts.list()`
- Get account holdings: `client.accounts.holdings(account.id)`
- Get account valuations: `client.accounts.valuations(account.id)`
- Get account transactions: `client.accounts.transactions(account.id)`

Instruments:
- Get the historical prices for an instrument: 
  `client.instruments.historical_prices('EQU.ZA.SYGJP', Period.ONE_MONTH)`

Orders (buy/sell):
- `client.orders.buy_at_open(account_number, contract_code, amount=100)` — market order at next open
- `client.orders.place_order(account_number, contract_code, OrderType.LIMIT, limit_price=85, amount=100)` — limit or stop/break order
- `client.orders.recurring_order(account_number, contract_code, amount=50, frequency=OrderFrequency.MONTHLY, day=15)` — recurring investment
- `client.orders.sell(account_number, contract_code, shares=5)` — sell shares

> [!NOTE]
> The order placement API endpoints are served through `apigateway.openeasy.io` which uses AWS IAM (SigV4) authentication — not compatible with the OAuth2 Bearer JWT that this library uses. The orders module is fully structured and will work once the correct publicly-accessible endpoint is identified. All four order methods return `{"success": False, "message": "..."}` with a clear explanation when the endpoint is unavailable rather than raising an exception.

## Usage

```python
from easy_equities_client.clients import EasyEquitiesClient # or SatrixClient

client = EasyEquitiesClient()
client.login(username='your username', password='your password')

# List accounts
accounts = client.accounts.list()
"""
[
    Account(id='12345', name='EasyEquities ZAR', trading_currency_id='2'),
    Account(id='12346', name='TFSA', trading_currency_id='3'),
    ...
]
"""

# Get account holdings
holdings = client.accounts.holdings(accounts[0].id)
"""
[
    {
        "name": "CoreShares Global DivTrax ETF",
        "contract_code": "EQU.ZA.GLODIV",
        "purchase_value": "R2 000.00",
        "current_value": "R3 000.00",
        "current_price": "R15.50",
        "img": "https://resources.easyequities.co.za/logos/EQU.ZA.GLODIV.png",
        "view_url": "/AccountOverview/GetInstrumentDetailAction/?IsinCode=ZAE000254249",
        "isin": "ZAE000254249"
    },
    ...
]
"""
# Optionally include number of shares for each holding (creates another API call for each holding)
holdings = client.accounts.holdings(accounts[0].id, include_shares=True)
"""
[
    {
        "name": "CoreShares Global DivTrax ETF",
        "contract_code": "EQU.ZA.GLODIV",
        "purchase_value": "R2 000.00",
        "current_value": "R3 000.00",
        "current_price": "R15.50",
        "img": "https://resources.easyequities.co.za/logos/EQU.ZA.GLODIV.png",
        "view_url": "/AccountOverview/GetInstrumentDetailAction/?IsinCode=ZAE000254249",
        "isin": "ZAE000254249",
        "shares": "200.123"
    },
    ...
]
"""

# Get account valuations
valuations = client.accounts.valuations(accounts[0].id)
"""
{
    "TopSummary": {
        "AccountValue": 300000.50,
        "AccountCurrency": "ZAR",
        "AccountNumber": "EE123456-111111",
        "AccountName": "EasyEquities ZAR",
        "PeriodMovements": [
            {
                "ValueMoveLabel": "Profit & Loss Value",
                "ValueMove": "R5 000.00",
                "PercentageMoveLabel": "Profit & Loss",
                "PercentageMove": "15.00%",
                "PeriodMoveHeader": "Movement on Current Holdings:"
            }
        ]
    },
    "NetInterestOnCashItems": [
        {
            "Label": "Total Interest on Free Cash",
            "Value": "R10.55"
        },
        ...
    ],
    "AccrualSummaryItems": [
        {
            "Label": "Net Accrual",
            "Value": "R2.00"
        },
        ...
    ],
    ...
}
"""

# Get account transactions
transactions = client.accounts.transactions(accounts[0].id)
"""
[
    {
        "TransactionId": 0,
        "DebitCredit": 200.00,
        "Comment": "Account Balance Carried Forward",
        "TransactionDate": "2020-07-21T01:00:00",
        "LogId": 123456789,
        "ActionId": 0,
        "Action": "Account Balance Carried Forward",
        "ContractCode": ""
    },
        {
        "TransactionId": 0,
        "DebitCredit": 50.00,
        "Comment": "CoreShares Global DivTrax ETF-Foreign Dividends @15.00",
        "TransactionDate": "2020-11-19T14:30:00",
        "LogId": 123456790,
        "ActionId": 122,
        "Action": "Foreign Dividend",
        "ContractCode": "EQU.ZA.GLODIV"
    },
    ...
]
"""

# Get historical data for an equity/instrument
from easy_equities_client.instruments.types import Period
historical_prices = client.instruments.historical_prices('EQU.ZA.SYGJP', Period.ONE_MONTH)
"""
{
    "success": True,
    "currentPrice": 85.50,
    "instrument": { "InstrumentName": "Satrix MSCI Japan...", "ContractCode": "EQU.ZA.SYGJP", ... },
    "priceDate": "2024-07-21T01:05:00+00:00"
}
"""

# Place orders
from easy_equities_client.orders import OrderType, OrderFrequency

# Buy At Open — market order executed at next trading open
result = client.orders.buy_at_open(
    account_number=accounts[0].id,
    contract_code='EQU.ZA.SYGJP',
    amount=100.0          # invest $100 (or use shares=2.5 for a share-based order)
)
"""{"success": True, "raw": {...}}  or  {"success": False, "message": "..."}"""

# Place Order — limit or stop/break order
result = client.orders.place_order(
    account_number=accounts[0].id,
    contract_code='EQU.ZA.SYGJP',
    order_type=OrderType.LIMIT,   # or OrderType.STOP_BREAK
    limit_price=80.00,
    amount=100.0,
)

# Recurring investment — invest automatically on a schedule
result = client.orders.recurring_order(
    account_number=accounts[0].id,
    contract_code='EQU.ZA.SYGJP',
    amount=50.0,
    frequency=OrderFrequency.MONTHLY,
    day=15,
    annual_increase_pct=10.0,
)

# Sell a holding
result = client.orders.sell(
    account_number=accounts[0].id,
    contract_code='EQU.ZA.SYGJP',
    shares=2.5,           # or sell_all=True to close the position entirely
)
```

## Example Use Cases

### Show holdings total profits/losses

Run a script to show your holdings and their total profits/losses, e.g.  
[show_holdings_profit_loss.py](https://github.com/delenamalan/easy-equities-client/blob/master/examples/show_holdings_profit_loss.py).

![show_holdings_profit_loss.py example output](https://raw.githubusercontent.com/delenamalan/easy-equities-client/master/examples/show_holdings_profit_loss_example.png)

## Contributing

See [Contributing](./CONTRIBUTING.md)
