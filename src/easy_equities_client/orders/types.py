import sys
from enum import Enum
from typing import Optional

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


class OrderType(Enum):
    LIMIT = "LimitOrder"
    STOP_BREAK = "StopOrder"


class OrderFrequency(Enum):
    MONTHLY = "Monthly"
    QUARTERLY = "Quarterly"
    ANNUALLY = "Annually"


class BuyAtOpenOrder(TypedDict, total=False):
    contractCode: str
    accountNumber: str
    investmentAmount: Optional[float]
    numberOfShares: Optional[float]
    tradingCurrencyId: Optional[int]


class PlaceOrder(TypedDict, total=False):
    contractCode: str
    accountNumber: str
    orderType: str
    limitPrice: float
    investmentAmount: Optional[float]
    numberOfShares: Optional[float]
    tradingCurrencyId: Optional[int]


class RecurringOrder(TypedDict, total=False):
    contractCode: str
    accountNumber: str
    recurringAmount: float
    annualIncreasePercentage: float
    feeInclusive: bool
    frequency: str
    day: int
    tradingCurrencyId: Optional[int]


class SellOrder(TypedDict, total=False):
    contractCode: str
    accountNumber: str
    numberOfShares: Optional[float]
    sellAll: Optional[bool]
    tradingCurrencyId: Optional[int]


class OrderResult(TypedDict, total=False):
    success: bool
    orderId: Optional[str]
    message: Optional[str]
    raw: Optional[dict]
