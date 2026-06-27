import base64
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from requests import Session

from easy_equities_client import constants
from easy_equities_client.accounts.types import (
    Account,
    Holding,
    Transaction,
    TransactionForPeriod,
    Valuation,
)
from easy_equities_client.types import Client

logger = logging.getLogger(__name__)

_API_GW_TRANSACTION_PATHS = [
    "/transaction-history-provider/api/v1/transactions",
    "/transaction-history-provider/v1/transactions",
    "/easytrader/api/TransactionHistory/transactions",
    "/easytrader/api/Transactions/account-transactions",
]


class AccountsClient(Client):
    def __init__(self, base_url: str = "", session: Session = None):
        super().__init__(base_url, session)
        self._portfolio_cache: Optional[Dict] = None

    def _get_portfolio_overview(self, force_refresh: bool = False) -> Dict:
        """Fetch and cache the REST API portfolio overview."""
        if self._portfolio_cache is None or force_refresh:
            response = self.session.get(
                constants.REST_API_BASE_URL + constants.REST_PORTFOLIO_OVERVIEW_PATH
            )
            response.raise_for_status()
            self._portfolio_cache = response.json()
        return self._portfolio_cache

    def _find_account(self, account_id: str) -> Optional[Dict]:
        """Return the investmentAccount dict matching account_id (accountNumber)."""
        overview = self._get_portfolio_overview()
        for acc in overview.get("investmentAccounts", []):
            if acc.get("accountNumber") == account_id:
                return acc
        return None

    def _decode_image_uri(self, image_uri: str) -> str:
        """Decode base64-encoded image URI to a plain URL."""
        try:
            return base64.b64decode(image_uri).decode("utf-8")
        except Exception:
            return image_uri

    def list(self) -> List[Account]:
        """Return all investment accounts for the authenticated user."""
        overview = self._get_portfolio_overview()
        accounts = []
        for acc in overview.get("investmentAccounts", []):
            accounts.append(
                Account(
                    id=acc["accountNumber"],
                    name=acc["productName"],
                    trading_currency_id=str(acc.get("productId", "")),
                )
            )
        return accounts

    def valuations(self, account_id: str) -> Valuation:
        """
        Return valuation data for the given account from the REST API portfolio overview.

        :param account_id: Account number string (e.g. 'EE3237137-15547214').
        """
        self._portfolio_cache = None
        acc = self._find_account(account_id)
        if acc is None:
            raise ValueError(f"Account '{account_id}' not found in portfolio overview.")

        aggregates = acc.get("aggregates", [])
        accruals = acc.get("accruals", [])
        costs = acc.get("costs", {})

        investment_types = next(
            (a for a in aggregates if a.get("aggregateName") == "Investment Type"), {}
        )
        managers = next(
            (a for a in aggregates if a.get("aggregateName") == "Manager"), {}
        )
        income_accruals = next(
            (a for a in accruals if a.get("accrualName") == "Income"), {}
        )
        expense_accruals = next(
            (a for a in accruals if a.get("accrualName") == "Expense"), {}
        )

        return {
            "accountNumber": acc.get("accountNumber"),
            "productName": acc.get("productName"),
            "currencyCode": acc.get("currencyCode"),
            "totalInvestmentHoldingsValue": acc.get("totalInvestmentHoldingsValue"),
            "InvestmentTypesAndManagers": {
                "types": investment_types.get("items", []),
                "managers": managers.get("items", []),
            },
            "AccrualIncomeSummaryItems": income_accruals.get("items", []),
            "AccrualExpenseSummaryItems": expense_accruals.get("items", []),
            "CostsSummaryItems": costs.get("items", []) if isinstance(costs, dict) else [],
            "costsTotal": costs.get("costsTotal", 0) if isinstance(costs, dict) else 0,
        }

    def transactions(self, account_id: str) -> List[Transaction]:
        """
        Fetch transactions for the given account.

        Tries multiple known API Gateway transaction endpoints. Returns an empty
        list if the account has no transactions or the endpoint is unavailable.

        :param account_id: Account number string (e.g. 'EE3237137-15547214').
        """
        gw = constants.API_GATEWAY_BASE_URL
        headers = {
            "Origin": "https://portfolio-overview.apps.easyequities.io",
            "Referer": "https://portfolio-overview.apps.easyequities.io/",
            "Accept": "application/json, text/plain, */*",
        }

        for path in _API_GW_TRANSACTION_PATHS:
            url = gw + path
            params = {"accountNumber": account_id}
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    logger.info(f"Transactions fetched from {path}: {len(data)} records")
                    return data if isinstance(data, list) else data.get("transactions", [])
                elif r.status_code == 404:
                    # Empty result set — account exists but no transactions
                    logger.debug(f"No transactions at {path} (404)")
                    return []
                else:
                    logger.debug(f"Transaction endpoint {path} returned {r.status_code}")
            except Exception as exc:
                logger.debug(f"Transaction endpoint {path} error: {exc}")

        # No endpoint worked — return empty list with a warning
        logger.warning(
            f"Could not fetch transactions for account '{account_id}'. "
            "The transaction history API endpoint may have changed. "
            "Check constants.API_GW_TRANSACTIONS_PATH for the latest URL."
        )
        return []

    def transactions_for_period(
        self, account_id: str, start_date: date, end_date: date
    ) -> List[TransactionForPeriod]:
        """
        Fetch transactions for a given date range.

        :param account_id: Account number string.
        :param start_date: Start of the period (inclusive).
        :param end_date: End of the period (inclusive).
        """
        gw = constants.API_GATEWAY_BASE_URL
        headers = {
            "Origin": "https://portfolio-overview.apps.easyequities.io",
            "Referer": "https://portfolio-overview.apps.easyequities.io/",
            "Accept": "application/json, text/plain, */*",
        }
        transactions: List[Any] = []
        current_start = start_date
        current_end = min(end_date, current_start + timedelta(days=90))

        while current_start <= end_date:
            logger.debug(f"Fetching transactions {current_start} → {current_end}")
            fetched = False

            for path in _API_GW_TRANSACTION_PATHS:
                url = gw + path
                params = {
                    "accountNumber": account_id,
                    "startDate": current_start.isoformat(),
                    "endDate": current_end.isoformat(),
                }
                try:
                    r = self.session.get(url, params=params, headers=headers, timeout=15)
                    if r.status_code == 200:
                        batch = r.json()
                        if isinstance(batch, list):
                            transactions = batch + transactions
                        fetched = True
                        break
                    elif r.status_code == 404:
                        fetched = True
                        break
                except Exception as exc:
                    logger.debug(f"transactions_for_period error at {path}: {exc}")

            if not fetched:
                logger.warning(
                    f"Could not fetch transactions for period {current_start}–{current_end}. "
                    "Transaction API endpoint may have changed."
                )

            current_start = current_end + timedelta(days=1)
            current_end = min(end_date, current_start + timedelta(days=90))

        return transactions

    def nav_chart(self, account_id: str, period: str = "1mo") -> dict:
        """
        Return the portfolio NAV (Net Asset Value) chart data for the given account.

        The EasyEquities REST API endpoint ``/portfolios/nav_chart_data/{period}``
        returns an empty response for accounts with no trading history. For accounts
        that have holdings and transactions, it returns time-series NAV data.

        Supported period strings: ``"1W"``, ``"1mo"``, ``"3mo"``, ``"6mo"``, ``"1Y"``

        :param account_id: Account number string (e.g. 'EE3237137-15547214').
        :param period: Time period string. Default ``"1mo"``.
        :return: Dict with:
            - ``success``    — True if chart data is available
            - ``account_id`` — the requested account
            - ``period``     — the requested period
            - ``data``       — list of ``{"date": str, "nav": float}`` points,
              empty if the account has no trade history
            - ``message``    — explanation if no data is available

        Example::

            chart = client.accounts.nav_chart("EE3237137-15547214", period="3mo")
            if chart["success"]:
                for point in chart["data"]:
                    print(point["date"], point["nav"])
            else:
                print(chart["message"])
        """
        url = constants.REST_API_BASE_URL + f"/portfolios/nav_chart_data/{period}"
        headers = {
            "Origin": "https://portfolio-overview.apps.easyequities.io",
            "Referer": "https://portfolio-overview.apps.easyequities.io/",
            "Accept": "application/json, text/plain, */*",
        }
        try:
            r = self.session.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            raw = r.json()
        except Exception as exc:
            return {
                "success": False,
                "account_id": account_id,
                "period": period,
                "data": [],
                "message": f"Request failed: {exc}",
            }

        if not raw:
            return {
                "success": False,
                "account_id": account_id,
                "period": period,
                "data": [],
                "message": (
                    "No NAV chart data returned. This account has no trading history "
                    "yet — NAV chart data is only available for accounts with completed "
                    "buy/sell transactions."
                ),
            }

        points = []
        if isinstance(raw, list):
            for entry in raw:
                date = entry.get("Date") or entry.get("date") or entry.get("x")
                nav = entry.get("Nav") or entry.get("nav") or entry.get("y") or entry.get("Value")
                if date and nav is not None:
                    points.append({"date": str(date)[:10], "nav": float(nav)})
        elif isinstance(raw, dict):
            for key in ("data", "Data", "points", "Points", "series", "Series"):
                if key in raw and isinstance(raw[key], list):
                    for entry in raw[key]:
                        date = entry.get("Date") or entry.get("date") or entry.get("x")
                        nav = entry.get("Nav") or entry.get("nav") or entry.get("y") or entry.get("Value")
                        if date and nav is not None:
                            points.append({"date": str(date)[:10], "nav": float(nav)})
                    break

        return {
            "success": True,
            "account_id": account_id,
            "period": period,
            "data": points,
            "message": None,
        }

    def holdings(self, account_id: str, include_shares: bool = False) -> List[Holding]:
        """
        Get an account's holdings from the REST API portfolio overview.

        :param account_id: Account number string (e.g. 'EE3237137-15547214').
        :param include_shares: Included for backward compatibility; share units are
            already present in the REST API response as 'units'.
        """
        self._portfolio_cache = None
        acc = self._find_account(account_id)
        if acc is None:
            raise ValueError(f"Account '{account_id}' not found in portfolio overview.")

        currency = acc.get("currencyCode", "")
        holdings: List[Holding] = []

        for asset in acc.get("assets", []):
            image_uri = asset.get("imageUri", "")
            img_url = self._decode_image_uri(image_uri) if image_uri else ""

            holding: Holding = {
                "name": asset.get("assetName", ""),
                "contract_code": asset.get("contractCode", ""),
                "purchase_value": f"{currency} {asset.get('purchaseValue', 0)}",
                "current_value": f"{currency} {asset.get('currentValue', 0)}",
                "current_price": f"{currency} {asset.get('currentPrice', 0)}",
                "img": img_url,
                "view_url": "",
                "isin": asset.get("assetCode", ""),
                "shares": str(asset.get("units", "")),
                "profit_loss_value": asset.get("profitLossValue", 0),
                "profit_loss_percentage": asset.get("profitLossPercentage", 0),
            }
            holdings.append(holding)

        return holdings
