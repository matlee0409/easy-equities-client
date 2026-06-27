import logging
from typing import Dict, List, Optional

from easy_equities_client import constants
from easy_equities_client.instruments.types import (
    Category,
    HistoricalPrices,
    InstrumentDetail,
    Period,
    PricePoint,
)
from easy_equities_client.types import Client

logger = logging.getLogger(__name__)

_PERIOD_MAP = {
    Period.ONE_WEEK: "1wk",
    Period.ONE_MONTH: "1mo",
    Period.THREE_MONTHS: "3mo",
    Period.SIX_MONTHS: "6mo",
    Period.ONE_YEAR: "1y",
    Period.TWO_YEARS: "2y",
    Period.FIVE_YEARS: "5y",
    Period.MAX: "max",
}

_INSTRUMENTS_URL = (
    "https://rest.synatic.openeasy.io/easyequities/investnow/instruments"
)


def _resolve_yahoo_ticker(instrument: InstrumentDetail) -> str:
    """
    Map an EasyEquities instrument to its Yahoo Finance ticker symbol.

    Uses ContributorSymbol plus exchange/market/asset-type information to
    append the correct Yahoo Finance market suffix.

    Suffix mapping:
      USA / US Equities / US ETFs / US ETNs  →  bare symbol  (e.g. AAPL)
      JSE / SA / ZA                           →  symbol.JO   (e.g. SYGJP.JO)
      ASX / Australia                         →  symbol.AX
      LSE / London                            →  symbol.L
      Crypto / Digital Assets                 →  symbol-USD
      Everything else                         →  bare symbol (best-effort)
    """
    symbol = instrument.get("ContributorSymbol", "") or instrument.get("ContractCode", "")
    exchange = instrument.get("Exchange", "").upper()
    sub_market = instrument.get("SubMarket", "").upper()
    asset_group = instrument.get("AssetGroup", "").upper()
    asset_type = instrument.get("AssetType", "").upper()
    market = instrument.get("Market", "").upper()
    contract_code = instrument.get("ContractCode", "").upper()

    # US — check before ZA to avoid false positives
    if (
        "USA" in exchange
        or "US EQUIT" in exchange
        or "US ETF" in exchange
        or "US ETN" in exchange
        or "NYSE" in exchange
        or "NASDAQ" in exchange
        or "US ETF" in asset_group
        or "US ETN" in asset_group
        or ".US." in contract_code
    ):
        return symbol

    # South Africa / JSE
    if (
        "JSE" in exchange
        or exchange.startswith("ZA")
        or sub_market.startswith("ZA")
        or "SA EQUIT" in asset_type
        or "SA ETF" in asset_type
        or "SA ETN" in asset_type
        or "SA BOND" in asset_type
        or "SA UNIT" in asset_type
        or "EQUITIES (SA)" in market
        or ".ZA." in contract_code
    ):
        return f"{symbol}.JO"

    # Australia
    if (
        "ASX" in exchange
        or "AUSTRALIA" in market
        or "AUS" in exchange
        or ".AU." in contract_code
    ):
        return f"{symbol}.AX"

    # London / UK
    if (
        "LSE" in exchange
        or "LONDON" in market
        or "UK" in exchange
        or ".UK." in contract_code
    ):
        return f"{symbol}.L"

    # Crypto
    if (
        "CRYPTO" in asset_group
        or "DIGITAL" in asset_group
        or "CRYPTO" in exchange
        or "DIGITAL" in exchange
    ):
        return f"{symbol}-USD"

    logger.debug(
        f"Unknown exchange '{exchange}' / sub_market '{sub_market}' / "
        f"asset_type '{asset_type}' for {symbol} — using bare symbol"
    )
    return symbol


class InstrumentsClient(Client):

    def _fetch_all_instruments(self, contract_code_filter: str = "") -> List[InstrumentDetail]:
        """Fetch all instruments from the investnow endpoint."""
        params = {}
        if contract_code_filter:
            params["contractCode"] = contract_code_filter
        response = self.session.get(_INSTRUMENTS_URL, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def _fetch_instrument(self, contract_code: str) -> Optional[InstrumentDetail]:
        """Fetch a single instrument by exact contract code."""
        instruments = self._fetch_all_instruments(contract_code_filter=contract_code)
        for inst in instruments:
            if inst.get("ContractCode") == contract_code:
                return inst
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list(self, asset_group: str = "", asset_sub_group: str = "") -> List[InstrumentDetail]:
        """
        List all available instruments, optionally filtered by category.

        :param asset_group: Filter by AssetGroup, e.g. "Equities", "ETFs", "Crypto",
            "Bonds", "Unit Trusts", "Property", "US ETFs", "US ETNs", "ETNs".
        :param asset_sub_group: Filter by AssetSubGroup, e.g. "Technology Hardware & Equipment".
        :return: List of InstrumentDetail dicts.

        Example::

            instruments = client.instruments.list()
            etfs = client.instruments.list(asset_group="ETFs")
            tech = client.instruments.list(asset_group="Equities", asset_sub_group="Technology Hardware & Equipment")
        """
        instruments = self._fetch_all_instruments()
        if asset_group:
            instruments = [i for i in instruments if i.get("AssetGroup") == asset_group]
        if asset_sub_group:
            instruments = [i for i in instruments if i.get("AssetSubGroup") == asset_sub_group]
        return instruments

    def categories(self) -> List[Category]:
        """
        Return all available investment categories (AssetGroups) with their
        sub-groups and instrument counts.

        :return: List of Category dicts, each with:
            - ``asset_group``     — top-level group name (e.g. "ETFs")
            - ``asset_sub_groups`` — sorted list of sub-group names
            - ``count``           — total instruments in this group

        Example::

            cats = client.instruments.categories()
            for cat in cats:
                print(cat['asset_group'], cat['count'], cat['asset_sub_groups'])
        """
        instruments = self._fetch_all_instruments()
        groups: Dict[str, Dict] = {}
        for inst in instruments:
            group = inst.get("AssetGroup", "Other")
            sub = inst.get("AssetSubGroup", "")
            if group not in groups:
                groups[group] = {"count": 0, "sub_groups": set()}
            groups[group]["count"] += 1
            if sub:
                groups[group]["sub_groups"].add(sub)

        result: List[Category] = []
        for group, data in sorted(groups.items()):
            result.append({
                "asset_group": group,
                "asset_sub_groups": sorted(data["sub_groups"]),
                "count": data["count"],
            })
        return result

    def search(self, query: str) -> List[InstrumentDetail]:
        """
        Search for instruments by name, ticker symbol, or contract code.

        :param query: Search string matched case-insensitively against contract code,
            instrument name, and contributor symbol (ticker).
        :return: List of matching InstrumentDetail dicts.

        Example::

            results = client.instruments.search("Apple")
            results = client.instruments.search("AAPL")
            results = client.instruments.search("EQU.US.AAPL")
        """
        instruments = self._fetch_all_instruments(contract_code_filter=query)
        q = query.upper()
        return [
            inst for inst in instruments
            if q in inst.get("ContractCode", "").upper()
            or q in inst.get("InstrumentName", "").upper()
            or q in inst.get("ContributorSymbol", "").upper()
        ]

    def historical_prices(self, contract_code: str, period: Period = Period.ONE_MONTH) -> HistoricalPrices:
        """
        Return historical OHLCV price data for an instrument.

        The EasyEquities REST API does not expose historical price series.
        This method fetches the instrument metadata from EasyEquities and then
        retrieves the price history from Yahoo Finance using the instrument's
        ``ContributorSymbol`` (ticker) resolved to the correct Yahoo Finance
        market suffix based on the exchange.

        :param contract_code: EasyEquities contract code, e.g. ``"EQU.US.AAPL"``
            or ``"EQU.ZA.SYGJP"``.
        :param period: Time period as a ``Period`` enum value. Supported values:
            ``Period.ONE_WEEK``, ``Period.ONE_MONTH``, ``Period.THREE_MONTHS``,
            ``Period.SIX_MONTHS``, ``Period.ONE_YEAR``, ``Period.TWO_YEARS``,
            ``Period.FIVE_YEARS``, ``Period.MAX``.
        :return: ``HistoricalPrices`` dict containing:
            - ``success``      — True if price data was retrieved
            - ``contract_code`` — the requested contract code
            - ``instrument``   — full instrument metadata from EasyEquities
            - ``ticker``       — Yahoo Finance ticker used for the price lookup
            - ``currentPrice`` — latest closing price (scaled)
            - ``scalingFactor`` — EasyEquities price scaling factor
            - ``priceDate``    — timestamp of the EasyEquities last-price update
            - ``period``       — period string used for the Yahoo Finance query
            - ``prices``       — list of ``PricePoint`` dicts (date, open, high, low, close, volume)
            - ``message``      — error description if ``success`` is False

        Example::

            from easy_equities_client.instruments.types import Period

            result = client.instruments.historical_prices("EQU.US.AAPL", Period.ONE_YEAR)
            if result["success"]:
                for point in result["prices"]:
                    print(point["date"], point["close"])

            # SA stock
            result = client.instruments.historical_prices("EQU.ZA.SYGJP", Period.SIX_MONTHS)
        """
        try:
            import yfinance as yf
        except ImportError:
            return {
                "success": False,
                "contract_code": contract_code,
                "instrument": None,
                "ticker": None,
                "currentPrice": None,
                "scalingFactor": None,
                "priceDate": None,
                "period": period.value if isinstance(period, Period) else str(period),
                "prices": [],
                "message": (
                    "yfinance is not installed. "
                    "Install it with: pip install yfinance"
                ),
            }

        instrument = self._fetch_instrument(contract_code)
        period_str = period.value if isinstance(period, Period) else str(period)
        yf_period = _PERIOD_MAP.get(period, period_str) if isinstance(period, Period) else period_str

        if instrument is None:
            logger.warning(f"Instrument '{contract_code}' not found.")
            return {
                "success": False,
                "contract_code": contract_code,
                "instrument": None,
                "ticker": None,
                "currentPrice": None,
                "scalingFactor": None,
                "priceDate": None,
                "period": period_str,
                "prices": [],
                "message": f"Instrument '{contract_code}' not found in EasyEquities.",
            }

        last_price = instrument.get("LastPrice", {})
        raw_value = last_price.get("Value", 0)
        scaling = instrument.get("ExchangeScalingFactor", 100)
        current_price = raw_value / scaling if scaling else raw_value
        ticker_symbol = _resolve_yahoo_ticker(instrument)

        logger.debug(f"Fetching Yahoo Finance data for {ticker_symbol} (period={yf_period})")
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period=yf_period)

        if hist.empty:
            logger.warning(
                f"No Yahoo Finance data for ticker '{ticker_symbol}'. "
                f"The EasyEquities ContributorSymbol may not map to a valid Yahoo Finance ticker."
            )
            return {
                "success": False,
                "contract_code": contract_code,
                "instrument": instrument,
                "ticker": ticker_symbol,
                "currentPrice": current_price,
                "scalingFactor": scaling,
                "priceDate": last_price.get("OriginalDateUpdated"),
                "period": period_str,
                "prices": [],
                "message": (
                    f"No price history found on Yahoo Finance for ticker '{ticker_symbol}'. "
                    f"The instrument may not be available via Yahoo Finance."
                ),
            }

        prices: List[PricePoint] = []
        for dt, row in hist.iterrows():
            prices.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 6),
                "high": round(float(row["High"]), 6),
                "low": round(float(row["Low"]), 6),
                "close": round(float(row["Close"]), 6),
                "volume": int(row["Volume"]),
            })

        return {
            "success": True,
            "contract_code": contract_code,
            "instrument": instrument,
            "ticker": ticker_symbol,
            "currentPrice": prices[-1]["close"] if prices else current_price,
            "scalingFactor": scaling,
            "priceDate": last_price.get("OriginalDateUpdated"),
            "period": period_str,
            "prices": prices,
            "message": None,
        }
