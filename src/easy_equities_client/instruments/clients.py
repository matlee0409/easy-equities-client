import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from easy_equities_client import constants
from easy_equities_client.instruments.types import (
    Category,
    CompareResult,
    HistoricalPrices,
    InstrumentComparison,
    InstrumentDetail,
    NormalisedPoint,
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

    def compare(
        self,
        contract_codes: List[str],
        period: Period = Period.ONE_YEAR,
    ) -> CompareResult:
        """
        Fetch historical price data for multiple instruments in parallel and
        normalise every series to a common base of 100 for side-by-side comparison.

        Normalisation uses the **earliest date that appears in all successful
        series** as the base date (value = 100). Every subsequent close price is
        then expressed as a percentage of that base close::

            normalised_value = (close / base_close) * 100

        So a value of 110 means +10 % since the base date, and 85 means -15 %.

        All network calls are made concurrently (one thread per instrument) so
        the total wall-clock time is roughly the same as a single
        ``historical_prices`` call regardless of how many codes are requested.

        :param contract_codes: List of EasyEquities contract codes, e.g.
            ``["EQU.US.AAPL", "EQU.US.MSFT", "EQU.ZA.SYGJP"]``.
        :param period: Time period as a ``Period`` enum value. Default
            ``Period.ONE_YEAR``.
        :return: ``CompareResult`` dict containing:

            - ``success``     — True if at least one instrument returned data
            - ``period``      — the period string used
            - ``base_date``   — date all series are indexed from (value = 100)
            - ``dates``       — sorted union of all dates across all series
            - ``instruments`` — list of ``InstrumentComparison`` dicts, one per
              code, each with:

              - ``contract_code``    — the requested code
              - ``name``             — instrument name from EasyEquities
              - ``ticker``           — Yahoo Finance ticker used
              - ``success``          — False if no price data was available
              - ``message``          — error detail when ``success`` is False
              - ``prices``           — raw ``PricePoint`` list (OHLCV)
              - ``normalised``       — ``[{"date": str, "value": float}, ...]``
                base-100 series aligned to ``base_date``
              - ``total_return_pct`` — percentage change from base date to last
                data point (e.g. ``15.3`` means +15.3 %), or ``None`` on failure

            - ``message``     — top-level note if no instruments succeeded

        Example::

            from easy_equities_client.instruments.types import Period

            result = client.instruments.compare(
                ["EQU.US.AAPL", "EQU.US.MSFT", "EQU.ZA.SYGJP"],
                Period.ONE_YEAR,
            )

            print("Base date:", result["base_date"])
            for inst in result["instruments"]:
                if inst["success"]:
                    print(
                        inst["name"],
                        f"total return: {inst['total_return_pct']:+.2f}%"
                    )
                    for point in inst["normalised"]:
                        print(point["date"], point["value"])
        """
        if not contract_codes:
            return {
                "success": False,
                "period": period.value if isinstance(period, Period) else str(period),
                "base_date": None,
                "dates": [],
                "instruments": [],
                "message": "No contract codes provided.",
            }

        period_str = period.value if isinstance(period, Period) else str(period)

        # --- Fetch all instruments in parallel ---
        raw_results: Dict[str, HistoricalPrices] = {}

        def _fetch(code: str) -> tuple:
            return code, self.historical_prices(code, period)

        with ThreadPoolExecutor(max_workers=min(len(contract_codes), 8)) as executor:
            futures = {executor.submit(_fetch, code): code for code in contract_codes}
            for future in as_completed(futures):
                code, result = future.result()
                raw_results[code] = result

        # --- Build a date→close map per successful instrument ---
        series: Dict[str, Dict[str, float]] = {}
        for code, result in raw_results.items():
            if result["success"] and result["prices"]:
                series[code] = {p["date"]: p["close"] for p in result["prices"]}

        # --- Find the earliest date shared by ALL successful instruments ---
        base_date: Optional[str] = None
        all_dates_union: List[str] = []

        if series:
            # Each instrument's sorted date list
            date_sets = [set(d.keys()) for d in series.values()]
            # Intersection — dates present in every series
            common_dates = sorted(date_sets[0].intersection(*date_sets[1:]))
            base_date = common_dates[0] if common_dates else None

            # Union of all dates for the top-level dates list
            union: set = set()
            for d in date_sets:
                union |= d
            all_dates_union = sorted(union)

        # --- Normalise each series to base = 100 at base_date ---
        def _normalise(code: str) -> List[NormalisedPoint]:
            if code not in series or base_date is None:
                return []
            date_close = series[code]
            base_close = date_close.get(base_date)
            if not base_close:
                return []
            points: List[NormalisedPoint] = []
            for date in sorted(date_close.keys()):
                if date >= base_date:
                    points.append({
                        "date": date,
                        "value": round((date_close[date] / base_close) * 100, 4),
                    })
            return points

        # --- Assemble InstrumentComparison per code (preserve input order) ---
        comparisons: List[InstrumentComparison] = []
        for code in contract_codes:
            result = raw_results[code]
            normalised = _normalise(code)
            total_return: Optional[float] = None
            if normalised:
                total_return = round(normalised[-1]["value"] - 100, 4)

            inst_detail = result.get("instrument") or {}
            comparisons.append({
                "contract_code": code,
                "name": inst_detail.get("InstrumentName", code) if inst_detail else code,
                "ticker": result.get("ticker"),
                "success": result["success"] and bool(normalised),
                "message": result.get("message"),
                "prices": result.get("prices", []),
                "normalised": normalised,
                "total_return_pct": total_return,
            })

        any_success = any(c["success"] for c in comparisons)
        return {
            "success": any_success,
            "period": period_str,
            "base_date": base_date,
            "dates": all_dates_union,
            "instruments": comparisons,
            "message": None if any_success else "No price data could be fetched for any of the requested instruments.",
        }
