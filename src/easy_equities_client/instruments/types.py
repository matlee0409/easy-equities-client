import sys
from enum import Enum
from typing import List, Optional

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


class Period(Enum):
    ONE_WEEK = "1W"
    ONE_MONTH = "1mo"
    THREE_MONTHS = "3mo"
    SIX_MONTHS = "6mo"
    ONE_YEAR = "1Y"


class LastPrice(TypedDict):
    Value: float
    DateUpdated: str
    OriginalDateUpdated: str


class InstrumentDetail(TypedDict):
    InstrumentID: int
    ContractCode: str
    InstrumentName: str
    ISINCode: str
    Exchange: str
    AssetGroup: str
    AssetSubGroup: str
    AssetType: str
    Market: str
    TradingCurrency: str
    ExchangeScalingFactor: int
    LastPrice: LastPrice


class HistoricalPrices(TypedDict):
    success: bool
    instrument: Optional[InstrumentDetail]
    currentPrice: Optional[float]
    scalingFactor: Optional[int]
    priceDate: Optional[str]
