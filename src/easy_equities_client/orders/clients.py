import logging
from typing import Optional

from requests import Session

from easy_equities_client import constants
from easy_equities_client.orders.types import (
    OrderFrequency,
    OrderResult,
    OrderType,
)
from easy_equities_client.types import Client

logger = logging.getLogger(__name__)

_INVESTNOW_BUY_PATHS = [
    "/investnow/buy-at-open",
    "/investnow/buy",
    "/investnow/orders/buy-at-open",
    "/investnow/orders/buy",
    "/investnow/once-off",
]

_INVESTNOW_PLACE_ORDER_PATHS = [
    "/investnow/place-order",
    "/investnow/limit-order",
    "/investnow/orders/place-order",
    "/investnow/orders/limit",
]

_INVESTNOW_RECURRING_PATHS = [
    "/investnow/recurring-order",
    "/investnow/recurring",
    "/investnow/orders/recurring",
]

_INVESTNOW_SELL_PATHS = [
    "/investnow/sell",
    "/investnow/sell-order",
    "/investnow/orders/sell",
    "/investnow/orders/sell-order",
]


def _post_to_paths(session: Session, base_url: str, paths: list, payload: dict) -> dict:
    """
    Try POST to each path in order, return the first successful JSON response.
    Returns {'success': False, 'message': ...} if all paths fail.
    """
    last_status = None
    last_text = ""
    for path in paths:
        url = base_url + path
        try:
            r = session.post(url, json=payload, timeout=20)
            last_status = r.status_code
            last_text = r.text[:300]
            if r.status_code in (200, 201, 202):
                try:
                    data = r.json()
                except Exception:
                    data = {"raw_response": r.text}
                logger.info(f"Order accepted at {path}: {r.status_code}")
                return {"success": True, "raw": data}
            elif r.status_code == 400:
                try:
                    err = r.json()
                except Exception:
                    err = {"message": r.text[:200]}
                logger.debug(f"Order validation error at {path}: {err}")
                return {"success": False, "message": str(err), "raw": err}
            else:
                logger.debug(f"Order endpoint {path} returned {r.status_code}")
        except Exception as exc:
            logger.debug(f"Order endpoint {path} error: {exc}")

    msg = (
        f"Order placement failed — no endpoint accepted the request "
        f"(last status: {last_status}, last response: {last_text}). "
        "The EasyEquities order API endpoint may have changed. "
        "Please check constants.REST_API_BASE_URL for the latest URL."
    )
    logger.warning(msg)
    return {"success": False, "message": msg}


class OrdersClient(Client):
    """
    Client for placing buy, sell, and recurring orders on EasyEquities.

    Supports three order types shown in the EasyEquities invest screen:
      - Buy At Open  : market order executed at the next open price.
      - Place Order  : limit order (buy only when price ≤ set price) or
                       stop/break order (buy only when price ≥ set price).
      - Recurring    : automated recurring investment on a set schedule.
    And selling existing holdings.
    """

    def __init__(self, base_url: str = "", session: Session = None):
        super().__init__(base_url, session)

    def _api_base(self) -> str:
        return constants.REST_API_BASE_URL

    def buy_at_open(
        self,
        account_number: str,
        contract_code: str,
        amount: Optional[float] = None,
        shares: Optional[float] = None,
        trading_currency_id: Optional[int] = None,
    ) -> OrderResult:
        """
        Place a 'Buy At Open' (once-off market) order.

        The order executes at the next market open price. Specify either
        ``amount`` (in the account currency) **or** ``shares`` (number of
        shares to purchase).

        :param account_number: Account ID, e.g. 'EE3237137-15547214'.
        :param contract_code:  Instrument contract code, e.g. 'EQU.ZA.SYGJP'.
        :param amount:         Investment amount in the account's currency.
        :param shares:         Number of shares to buy (alternative to amount).
        :param trading_currency_id: Override the trading currency ID.
        :return: OrderResult dict with ``success`` bool and optional ``message``.
        :raises ValueError: if neither amount nor shares is provided.
        """
        if amount is None and shares is None:
            raise ValueError("Provide either 'amount' or 'shares'.")

        payload: dict = {
            "contractCode": contract_code,
            "accountNumber": account_number,
        }
        if amount is not None:
            payload["investmentAmount"] = amount
        if shares is not None:
            payload["numberOfShares"] = shares
        if trading_currency_id is not None:
            payload["tradingCurrencyId"] = trading_currency_id

        return _post_to_paths(self.session, self._api_base(), _INVESTNOW_BUY_PATHS, payload)

    def place_order(
        self,
        account_number: str,
        contract_code: str,
        order_type: OrderType,
        limit_price: float,
        amount: Optional[float] = None,
        shares: Optional[float] = None,
        trading_currency_id: Optional[int] = None,
    ) -> OrderResult:
        """
        Place a limit or stop/break order.

        - **Limit Order** (``OrderType.LIMIT``): buy only when the ask price is
          *less than or equal to* the set price.
        - **Stop/Break Order** (``OrderType.STOP_BREAK``): buy only when the ask
          price is *greater than or equal to* the set price.

        :param account_number:  Account ID.
        :param contract_code:   Instrument contract code.
        :param order_type:      ``OrderType.LIMIT`` or ``OrderType.STOP_BREAK``.
        :param limit_price:     The target price that triggers the order.
        :param amount:          Investment amount in the account's currency.
        :param shares:          Number of shares (alternative to amount).
        :param trading_currency_id: Override the trading currency ID.
        :return: OrderResult dict.
        :raises ValueError: if neither amount nor shares is provided.
        """
        if amount is None and shares is None:
            raise ValueError("Provide either 'amount' or 'shares'.")

        payload: dict = {
            "contractCode": contract_code,
            "accountNumber": account_number,
            "orderType": order_type.value,
            "limitPrice": limit_price,
        }
        if amount is not None:
            payload["investmentAmount"] = amount
        if shares is not None:
            payload["numberOfShares"] = shares
        if trading_currency_id is not None:
            payload["tradingCurrencyId"] = trading_currency_id

        return _post_to_paths(self.session, self._api_base(), _INVESTNOW_PLACE_ORDER_PATHS, payload)

    def recurring_order(
        self,
        account_number: str,
        contract_code: str,
        amount: float,
        frequency: OrderFrequency,
        day: int,
        annual_increase_pct: float = 10.0,
        fee_inclusive: bool = False,
        trading_currency_id: Optional[int] = None,
    ) -> OrderResult:
        """
        Set up a recurring investment order.

        Recurring orders invest a fixed amount at a regular interval
        (monthly, quarterly, or annually) on a chosen day of the month.

        :param account_number:     Account ID.
        :param contract_code:      Instrument contract code.
        :param amount:             Recurring investment amount in account currency.
        :param frequency:          ``OrderFrequency.MONTHLY``, ``QUARTERLY``, or ``ANNUALLY``.
        :param day:                Day of the month to invest (1–28).
        :param annual_increase_pct: Annual percentage increase to the amount (default 10 %).
        :param fee_inclusive:       If True, the amount *includes* transaction fees.
                                    If False (default), fees are added on top.
        :param trading_currency_id: Override the trading currency ID.
        :return: OrderResult dict.
        :raises ValueError: if day is out of the 1–28 range.
        """
        if not 1 <= day <= 28:
            raise ValueError("Day must be between 1 and 28.")

        payload: dict = {
            "contractCode": contract_code,
            "accountNumber": account_number,
            "recurringAmount": amount,
            "annualIncreasePercentage": annual_increase_pct,
            "feeInclusive": fee_inclusive,
            "frequency": frequency.value,
            "day": day,
        }
        if trading_currency_id is not None:
            payload["tradingCurrencyId"] = trading_currency_id

        return _post_to_paths(self.session, self._api_base(), _INVESTNOW_RECURRING_PATHS, payload)

    def sell(
        self,
        account_number: str,
        contract_code: str,
        shares: Optional[float] = None,
        sell_all: bool = False,
        trading_currency_id: Optional[int] = None,
    ) -> OrderResult:
        """
        Sell an existing holding.

        Specify either ``shares`` (number of shares to sell) **or** set
        ``sell_all=True`` to sell the entire position.

        :param account_number:  Account ID.
        :param contract_code:   Instrument contract code.
        :param shares:          Number of shares to sell.
        :param sell_all:        If True, sell the entire holding.
        :param trading_currency_id: Override the trading currency ID.
        :return: OrderResult dict.
        :raises ValueError: if neither shares nor sell_all is specified.
        """
        if shares is None and not sell_all:
            raise ValueError("Provide either 'shares' or set sell_all=True.")

        payload: dict = {
            "contractCode": contract_code,
            "accountNumber": account_number,
        }
        if shares is not None:
            payload["numberOfShares"] = shares
        if sell_all:
            payload["sellAll"] = True
        if trading_currency_id is not None:
            payload["tradingCurrencyId"] = trading_currency_id

        return _post_to_paths(self.session, self._api_base(), _INVESTNOW_SELL_PATHS, payload)
