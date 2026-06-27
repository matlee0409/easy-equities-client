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
    TWO_YEARS = "2y"
    FIVE_YEARS = "5y"
    MAX = "max"


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
    ExchangeID: int
    AssetGroup: str
    AssetSubGroup: str
    AssetType: str
    InstrumentType: str
    Market: str
    MarketID: int
    SubMarket: str
    SubMarketID: int
    TradingCurrency: str
    TradingCurrencyID: int
    ExchangeScalingFactor: int
    LastPrice: LastPrice
    ContributorSymbol: str
    ActiveData: int


class PricePoint(TypedDict):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class HistoricalPrices(TypedDict):
    success: bool
    contract_code: str
    instrument: Optional[InstrumentDetail]
    ticker: Optional[str]
    currentPrice: Optional[float]
    scalingFactor: Optional[int]
    priceDate: Optional[str]
    period: Optional[str]
    prices: List[PricePoint]
    message: Optional[str]


class Category(TypedDict):
    asset_group: str
    asset_sub_groups: List[str]
    count: int
