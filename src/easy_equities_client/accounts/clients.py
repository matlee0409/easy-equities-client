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


class AccountsClient(Client):
    def __init__(self, base_url: str = "", session: Session = None):
        super().__init__(base_url, session)
        self._portfolio_cache: Optional[Dict] = None

    def _get_portfolio_overview(self, force_refresh: bool = False) -> Dict:
        """
        Fetch and cache the REST API portfolio overview.
        Returns the full response dict from /portfolios/v3/portfolio-overview.
        """
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
        Return valuation data for the given account.

        Returns a dict with keys mapped from the REST API portfolio overview
        response for the matching account.
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
        Gets transactions for the given account via the REST API.
        """
        url = (
            constants.REST_API_BASE_URL
            + constants.REST_TRANSACTIONS_PATH
            + f"?accountNumber={account_id}"
        )
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def transactions_for_period(
        self, account_id: str, start_date: date, end_date: date
    ) -> List[TransactionForPeriod]:
        """
        Gets transactions for a given period via the REST API.

        Returns transactions ordered in reverse chronological order (newest to oldest).
        """
        transactions: List[Any] = []

        current_start = start_date
        current_end = min(end_date, current_start + timedelta(days=90))

        while current_start < end_date:
            logger.debug(f"Current start: {current_start}, Current end: {current_end}")

            url = (
                constants.REST_API_BASE_URL
                + constants.REST_TRANSACTIONS_PATH
                + f"?accountNumber={account_id}"
                f"&startDate={current_start.isoformat()}"
                f"&endDate={current_end.isoformat()}"
            )
            response = self.session.get(url)
            new_transactions = response.json() if response.status_code == 200 else []
            transactions = list(new_transactions) + transactions

            current_start = current_end + timedelta(days=1)
            current_end = min(end_date, current_start + timedelta(days=90))

        return transactions

    def holdings(self, account_id: str, include_shares: bool = False) -> List[Holding]:
        """
        Get an account's holdings/stocks from the REST API portfolio overview.

        :param account_id: String account ID (accountNumber).
        :param include_shares: Included for backward compatibility; shares data is
            already present in the REST API response as 'units'.
        """
        self._portfolio_cache = None
        acc = self._find_account(account_id)
        if acc is None:
            raise ValueError(f"Account '{account_id}' not found in portfolio overview.")

        holdings: List[Holding] = []
        currency = acc.get("currencyCode", "")

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
