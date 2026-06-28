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
    NewsHeadline,
    NewsResult,
    NormalisedPoint,
    Period,
    PricePoint,
    ScreenerEntry,
    ScreenerResult,
    SearchMatch,
    SearchResult,
    TopMoverEntry,
    TopMoversResult,
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

    def top_movers(
        self,
        asset_group: str = "Equities",
        period: Period = Period.ONE_MONTH,
        n: int = 10,
        scan_limit: int = 200,
    ) -> TopMoversResult:
        """
        Rank instruments in an asset group by total return over a period and
        return the top N gainers and bottom N losers.

        All price data is fetched in a **single batch** ``yfinance.download()``
        call, so scanning hundreds of tickers takes roughly the same time as
        fetching one.

        Instruments are deduplicated by contract code before scanning. When the
        group contains more unique instruments than ``scan_limit``, the set is
        randomly sampled so the call stays responsive.

        :param asset_group: EasyEquities asset group to scan. One of:
            ``"Equities"``, ``"ETFs"``, ``"US ETFs"``, ``"Bonds"``,
            ``"Crypto"``, ``"Unit Trusts"``, ``"ETNs"``, ``"US ETNs"``,
            ``"Property"``. Default ``"Equities"``.
        :param period: Time period as a ``Period`` enum. Default
            ``Period.ONE_MONTH``.
        :param n: Number of top gainers **and** losers to return.
            Default ``10``.
        :param scan_limit: Maximum number of instruments to scan. When the
            group is larger than this the selection is sampled at random.
            Default ``200``. Raise to scan more; lower to return faster.
        :return: ``TopMoversResult`` dict containing:

            - ``success``     — True if any return data was obtained
            - ``asset_group`` — the group that was scanned
            - ``period``      — the period used
            - ``scanned``     — number of instruments actually fetched
            - ``gainers``     — list of up to N ``TopMoverEntry`` dicts,
              best performer first
            - ``losers``      — list of up to N ``TopMoverEntry`` dicts,
              worst performer first
            - ``message``     — error detail when ``success`` is False

            Each ``TopMoverEntry`` contains:
            ``contract_code``, ``name``, ``ticker``, ``asset_sub_group``,
            ``total_return_pct``, ``first_close``, ``last_close``,
            ``first_date``, ``last_date``.

        Example::

            from easy_equities_client.instruments.types import Period

            movers = client.instruments.top_movers(
                asset_group="US ETFs",
                period=Period.THREE_MONTHS,
                n=5,
            )
            print("Top gainers:")
            for g in movers["gainers"]:
                print(f"  {g['name']:40s}  {g['total_return_pct']:+.2f}%")

            print("Top losers:")
            for l in movers["losers"]:
                print(f"  {l['name']:40s}  {l['total_return_pct']:+.2f}%")
        """
        try:
            import random
            import yfinance as yf
        except ImportError:
            return {
                "success": False,
                "asset_group": asset_group,
                "period": period.value if isinstance(period, Period) else str(period),
                "scanned": 0,
                "gainers": [],
                "losers": [],
                "message": "yfinance is not installed. Install it with: pip install yfinance",
            }

        period_str = period.value if isinstance(period, Period) else str(period)
        yf_period = _PERIOD_MAP.get(period, period_str) if isinstance(period, Period) else period_str

        # --- 1. Fetch and deduplicate instruments for the group ---
        all_instruments = self._fetch_all_instruments()
        group_instruments = [
            i for i in all_instruments if i.get("AssetGroup") == asset_group
        ]
        # Deduplicate by contract code, keeping the first occurrence
        seen_codes: set = set()
        unique_instruments: List[InstrumentDetail] = []
        for inst in group_instruments:
            code = inst.get("ContractCode", "")
            if code and code not in seen_codes:
                seen_codes.add(code)
                unique_instruments.append(inst)

        if not unique_instruments:
            return {
                "success": False,
                "asset_group": asset_group,
                "period": period_str,
                "scanned": 0,
                "gainers": [],
                "losers": [],
                "message": (
                    f"No instruments found for asset group '{asset_group}'. "
                    f"Valid groups: Equities, ETFs, US ETFs, Bonds, Crypto, "
                    f"Unit Trusts, ETNs, US ETNs, Property."
                ),
            }

        # Sample if the group is larger than scan_limit
        if len(unique_instruments) > scan_limit:
            logger.info(
                f"top_movers: {len(unique_instruments)} unique instruments in '{asset_group}', "
                f"sampling {scan_limit}."
            )
            unique_instruments = random.sample(unique_instruments, scan_limit)

        # --- 2. Resolve Yahoo Finance tickers ---
        # ticker → (contract_code, instrument)
        ticker_map: Dict[str, tuple] = {}
        for inst in unique_instruments:
            ticker = _resolve_yahoo_ticker(inst)
            if ticker:
                ticker_map[ticker] = (inst.get("ContractCode", ""), inst)

        tickers = list(ticker_map.keys())

        if not tickers:
            return {
                "success": False,
                "asset_group": asset_group,
                "period": period_str,
                "scanned": 0,
                "gainers": [],
                "losers": [],
                "message": "Could not resolve any Yahoo Finance tickers for this asset group.",
            }

        # --- 3. Batch-download all tickers in one call ---
        logger.debug(f"top_movers: batch-downloading {len(tickers)} tickers (period={yf_period})")
        try:
            raw = yf.download(
                tickers=tickers,
                period=yf_period,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            return {
                "success": False,
                "asset_group": asset_group,
                "period": period_str,
                "scanned": 0,
                "gainers": [],
                "losers": [],
                "message": f"yfinance batch download failed: {exc}",
            }

        if raw.empty:
            return {
                "success": False,
                "asset_group": asset_group,
                "period": period_str,
                "scanned": 0,
                "gainers": [],
                "losers": [],
                "message": "No price data returned by Yahoo Finance for any ticker in this group.",
            }

        # --- 4. Extract Close prices — handle single vs. multi ticker layout ---
        import pandas as pd

        if isinstance(raw.columns, pd.MultiIndex):
            # Multi-ticker: columns are (metric, ticker)
            close_df = raw["Close"] if "Close" in raw.columns.get_level_values(0) else pd.DataFrame()
        else:
            # Single ticker: columns are plain metric names
            if "Close" in raw.columns:
                close_df = raw[["Close"]].rename(columns={"Close": tickers[0]})
            else:
                close_df = pd.DataFrame()

        if close_df.empty:
            return {
                "success": False,
                "asset_group": asset_group,
                "period": period_str,
                "scanned": 0,
                "gainers": [],
                "losers": [],
                "message": "Could not extract Close price data from the downloaded result.",
            }

        # Drop columns (tickers) that are entirely NaN
        close_df = close_df.dropna(axis=1, how="all")

        # --- 5. Calculate total return per ticker ---
        entries: List[TopMoverEntry] = []
        for ticker in close_df.columns:
            col = close_df[ticker].dropna()
            if len(col) < 2:
                continue

            first_close = float(col.iloc[0])
            last_close = float(col.iloc[-1])
            if first_close == 0:
                continue

            total_return_pct = round(((last_close - first_close) / first_close) * 100, 4)
            contract_code, inst = ticker_map.get(str(ticker), ("", {}))
            first_date = col.index[0].strftime("%Y-%m-%d")
            last_date = col.index[-1].strftime("%Y-%m-%d")

            entries.append({
                "contract_code": contract_code,
                "name": inst.get("InstrumentName", ticker) if inst else str(ticker),
                "ticker": str(ticker),
                "asset_sub_group": inst.get("AssetSubGroup", "") if inst else "",
                "total_return_pct": total_return_pct,
                "first_close": round(first_close, 6),
                "last_close": round(last_close, 6),
                "first_date": first_date,
                "last_date": last_date,
            })

        if not entries:
            return {
                "success": False,
                "asset_group": asset_group,
                "period": period_str,
                "scanned": len(tickers),
                "gainers": [],
                "losers": [],
                "message": (
                    "Price data was downloaded but no instruments had enough "
                    "data points to calculate a return."
                ),
            }

        # --- 6. Sort and slice ---
        entries.sort(key=lambda e: e["total_return_pct"], reverse=True)
        gainers = entries[:n]
        losers = list(reversed(entries[-n:]))  # worst first

        return {
            "success": True,
            "asset_group": asset_group,
            "period": period_str,
            "scanned": len(entries),
            "gainers": gainers,
            "losers": losers,
            "message": None,
        }

    def screener(
        self,
        asset_group: str = "Equities",
        period: Period = Period.ONE_MONTH,
        min_return: Optional[float] = None,
        max_return: Optional[float] = None,
        sub_group: Optional[str] = None,
        scan_limit: int = 200,
    ) -> ScreenerResult:
        """
        Filter instruments by return thresholds and sub-group, returning every
        match sorted best-to-worst by total return over the period.

        Uses a single ``yfinance.download()`` batch call for all tickers, so
        scanning hundreds of instruments adds no extra latency beyond one call.

        :param asset_group: EasyEquities asset group to search within. One of:
            ``"Equities"``, ``"ETFs"``, ``"US ETFs"``, ``"Bonds"``,
            ``"Crypto"``, ``"Unit Trusts"``, ``"ETNs"``, ``"US ETNs"``,
            ``"Property"``. Default ``"Equities"``.
        :param period: Time period as a ``Period`` enum. Default
            ``Period.ONE_MONTH``.
        :param min_return: Inclusive lower bound on total return percentage.
            E.g. ``5.0`` keeps only instruments up ≥ 5 %. ``None`` = no lower
            bound.
        :param max_return: Inclusive upper bound on total return percentage.
            E.g. ``-5.0`` keeps only instruments down ≥ 5 %. ``None`` = no
            upper bound.
        :param sub_group: Filter by ``AssetSubGroup`` (case-insensitive
            substring match). E.g. ``"Technology"`` matches
            ``"Technology Hardware & Equipment"`` and
            ``"Technology Software & Services"``. ``None`` = all sub-groups.
        :param scan_limit: Maximum instruments to scan before sampling.
            Default ``200``.
        :return: ``ScreenerResult`` dict containing:

            - ``success``        — True if matches were found
            - ``asset_group``    — group searched
            - ``asset_sub_group`` — sub_group filter applied (or None)
            - ``period``         — period used
            - ``min_return``     — lower bound applied (or None)
            - ``max_return``     — upper bound applied (or None)
            - ``scanned``        — total instruments with price data evaluated
            - ``matched``        — number passing all filters
            - ``matches``        — list of ``ScreenerEntry`` dicts, sorted
              best-to-worst by ``total_return_pct``
            - ``message``        — detail when ``success`` is False

            Each ``ScreenerEntry`` contains:
            ``contract_code``, ``name``, ``ticker``, ``asset_group``,
            ``asset_sub_group``, ``total_return_pct``, ``first_close``,
            ``last_close``, ``first_date``, ``last_date``.

        Examples::

            from easy_equities_client.instruments.types import Period

            # All US ETFs that gained more than 5 % in the last month
            result = client.instruments.screener(
                asset_group="US ETFs",
                period=Period.ONE_MONTH,
                min_return=5.0,
            )

            # SA equities in Technology down between 5 % and 20 % over 3 months
            result = client.instruments.screener(
                asset_group="Equities",
                period=Period.THREE_MONTHS,
                min_return=-20.0,
                max_return=-5.0,
                sub_group="Technology",
            )

            for match in result["matches"]:
                print(
                    f"{match['total_return_pct']:+.2f}%  "
                    f"{match['ticker']:10s}  {match['name']}"
                )
        """
        try:
            import random
            import yfinance as yf
            import pandas as pd
        except ImportError:
            return {
                "success": False,
                "asset_group": asset_group,
                "asset_sub_group": sub_group,
                "period": period.value if isinstance(period, Period) else str(period),
                "min_return": min_return,
                "max_return": max_return,
                "scanned": 0,
                "matched": 0,
                "matches": [],
                "message": "yfinance is not installed. Install it with: pip install yfinance",
            }

        period_str = period.value if isinstance(period, Period) else str(period)
        yf_period = _PERIOD_MAP.get(period, period_str) if isinstance(period, Period) else period_str

        def _fail(msg: str) -> ScreenerResult:
            return {
                "success": False,
                "asset_group": asset_group,
                "asset_sub_group": sub_group,
                "period": period_str,
                "min_return": min_return,
                "max_return": max_return,
                "scanned": 0,
                "matched": 0,
                "matches": [],
                "message": msg,
            }

        # --- 1. Fetch instruments, apply sub_group filter, deduplicate ---
        all_instruments = self._fetch_all_instruments()

        candidate_instruments = [
            i for i in all_instruments
            if i.get("AssetGroup") == asset_group
        ]

        if sub_group:
            sub_lower = sub_group.lower()
            candidate_instruments = [
                i for i in candidate_instruments
                if sub_lower in i.get("AssetSubGroup", "").lower()
            ]

        # Deduplicate by contract code, keeping the first occurrence
        seen_codes: set = set()
        unique_instruments: List[InstrumentDetail] = []
        for inst in candidate_instruments:
            code = inst.get("ContractCode", "")
            if code and code not in seen_codes:
                seen_codes.add(code)
                unique_instruments.append(inst)

        if not unique_instruments:
            msg = f"No instruments found for asset_group='{asset_group}'"
            if sub_group:
                msg += f", sub_group='{sub_group}'"
            msg += (
                ". Valid asset groups: Equities, ETFs, US ETFs, Bonds, Crypto, "
                "Unit Trusts, ETNs, US ETNs, Property."
            )
            return _fail(msg)

        # Sample if necessary
        if len(unique_instruments) > scan_limit:
            logger.info(
                f"screener: {len(unique_instruments)} unique instruments, "
                f"sampling {scan_limit}."
            )
            unique_instruments = random.sample(unique_instruments, scan_limit)

        # --- 2. Resolve Yahoo tickers, build ticker → instrument map ---
        ticker_map: Dict[str, tuple] = {}
        for inst in unique_instruments:
            ticker = _resolve_yahoo_ticker(inst)
            if ticker and ticker not in ticker_map:
                ticker_map[ticker] = (inst.get("ContractCode", ""), inst)

        tickers = list(ticker_map.keys())
        if not tickers:
            return _fail("Could not resolve any Yahoo Finance tickers for this filter.")

        # --- 3. Batch-download all tickers ---
        logger.debug(f"screener: batch-downloading {len(tickers)} tickers (period={yf_period})")
        try:
            raw = yf.download(
                tickers=tickers,
                period=yf_period,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            return _fail(f"yfinance batch download failed: {exc}")

        if raw.empty:
            return _fail("No price data returned by Yahoo Finance for any ticker in this filter.")

        # --- 4. Extract Close prices ---
        if isinstance(raw.columns, pd.MultiIndex):
            close_df = raw["Close"] if "Close" in raw.columns.get_level_values(0) else pd.DataFrame()
        else:
            if "Close" in raw.columns:
                close_df = raw[["Close"]].rename(columns={"Close": tickers[0]})
            else:
                close_df = pd.DataFrame()

        if close_df.empty:
            return _fail("Could not extract Close price data from the downloaded result.")

        close_df = close_df.dropna(axis=1, how="all")

        # --- 5. Calculate return per ticker and apply filters ---
        all_entries: List[ScreenerEntry] = []
        for ticker in close_df.columns:
            col = close_df[ticker].dropna()
            if len(col) < 2:
                continue

            first_close = float(col.iloc[0])
            last_close = float(col.iloc[-1])
            if first_close == 0:
                continue

            total_return_pct = round(((last_close - first_close) / first_close) * 100, 4)
            contract_code, inst = ticker_map.get(str(ticker), ("", {}))

            all_entries.append({
                "contract_code": contract_code,
                "name": inst.get("InstrumentName", ticker) if inst else str(ticker),
                "ticker": str(ticker),
                "asset_group": inst.get("AssetGroup", asset_group) if inst else asset_group,
                "asset_sub_group": inst.get("AssetSubGroup", "") if inst else "",
                "total_return_pct": total_return_pct,
                "first_close": round(first_close, 6),
                "last_close": round(last_close, 6),
                "first_date": col.index[0].strftime("%Y-%m-%d"),
                "last_date": col.index[-1].strftime("%Y-%m-%d"),
            })

        scanned = len(all_entries)

        # Apply return filters
        matches = all_entries
        if min_return is not None:
            matches = [e for e in matches if e["total_return_pct"] >= min_return]
        if max_return is not None:
            matches = [e for e in matches if e["total_return_pct"] <= max_return]

        # Sort best to worst
        matches.sort(key=lambda e: e["total_return_pct"], reverse=True)

        return {
            "success": True,
            "asset_group": asset_group,
            "asset_sub_group": sub_group,
            "period": period_str,
            "min_return": min_return,
            "max_return": max_return,
            "scanned": scanned,
            "matched": len(matches),
            "matches": matches,
            "message": None,
        }

    def search(
        self,
        query: str,
        asset_group: Optional[str] = None,
        top: int = 10,
    ) -> SearchResult:
        """
        Search all EasyEquities instruments by name or contract code using
        fuzzy matching. No external dependencies — uses Python's built-in
        ``difflib``.

        Scoring rules (applied to both the instrument name and contract code,
        best score wins):

        1. **Exact match** (case-insensitive) → 1.0
        2. **Starts-with** → 0.9
        3. **Contains** (whole query as substring) → 0.75
        4. **Token overlap** — fraction of query words found in the name → up
           to 0.7 (scaled by coverage)
        5. **difflib fuzzy ratio** → up to 0.6 (scaled)

        Results are deduplicated by contract code, filtered to ``score > 0``,
        and returned sorted best-first.

        :param query: Free-text search string. Examples: ``"Tesla"``,
            ``"TSLA"``, ``"ARK"``, ``"Satrix S&P 500"``.
        :param asset_group: Optional filter to limit results to one asset group,
            e.g. ``"US ETFs"`` or ``"Equities"``. Default ``None`` (all groups).
        :param top: Maximum number of results to return. Default ``10``.
        :return: ``SearchResult`` dict:

            - ``query``   — original query string
            - ``total``   — number of matches returned
            - ``results`` — list of ``SearchMatch`` dicts, sorted best-first

            Each ``SearchMatch`` contains:
            ``contract_code``, ``name``, ``ticker``, ``asset_group``,
            ``asset_sub_group``, ``score`` (0–1, higher = better match).

        Examples::

            hits = client.instruments.search("Tesla")
            for h in hits["results"]:
                print(h["score"], h["name"], h["ticker"])

            # Limit to a specific asset group
            hits = client.instruments.search("ARK", asset_group="US ETFs")

            # Get the contract code for a known ticker
            hits = client.instruments.search("NVDA")
            code = hits["results"][0]["contract_code"]
        """
        import difflib

        q = query.strip()
        q_lower = q.lower()
        q_tokens = q_lower.split()

        def _score(text: str) -> float:
            t = text.lower()
            # 1. Exact
            if t == q_lower:
                return 1.0
            # 2. Starts-with
            if t.startswith(q_lower):
                return 0.9
            # 3. Contains substring
            if q_lower in t:
                return 0.75
            # 4. Token overlap
            if q_tokens:
                hit_count = sum(1 for tok in q_tokens if tok in t)
                if hit_count:
                    coverage = hit_count / len(q_tokens)
                    return 0.4 + 0.3 * coverage
            # 5. difflib fuzzy
            ratio = difflib.SequenceMatcher(None, q_lower, t).ratio()
            if ratio > 0.4:
                return ratio * 0.6
            return 0.0

        all_instruments = self._fetch_all_instruments()

        # Optionally restrict to one asset group
        if asset_group:
            all_instruments = [
                i for i in all_instruments
                if i.get("AssetGroup") == asset_group
            ]

        # Deduplicate by contract code AND resolved Yahoo ticker.
        # The same instrument can appear with several contract codes for
        # different trading currencies, all resolving to the same Yahoo ticker.
        seen_codes: set = set()
        seen_tickers: set = set()
        unique: List[InstrumentDetail] = []
        for inst in all_instruments:
            code = inst.get("ContractCode", "")
            ticker = _resolve_yahoo_ticker(inst)
            if not code:
                continue
            if code in seen_codes:
                continue
            if ticker and ticker in seen_tickers:
                continue
            seen_codes.add(code)
            if ticker:
                seen_tickers.add(ticker)
            unique.append(inst)

        scored: List[SearchMatch] = []
        for inst in unique:
            name = inst.get("InstrumentName", "")
            code = inst.get("ContractCode", "")
            ticker = _resolve_yahoo_ticker(inst)

            # Score against name, contract code, and Yahoo ticker — take best
            best = max(
                _score(name),
                _score(code),
                _score(ticker) if ticker else 0.0,
            )
            if best <= 0.0:
                continue

            scored.append({
                "contract_code": code,
                "name": name,
                "ticker": ticker or "",
                "asset_group": inst.get("AssetGroup", ""),
                "asset_sub_group": inst.get("AssetSubGroup", ""),
                "score": round(best, 4),
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:top]

        return {
            "query": q,
            "total": len(results),
            "results": results,
        }

    def news(
        self,
        contract_code_or_ticker: str,
        max_results: int = 10,
    ) -> NewsResult:
        """
        Fetch recent news headlines for an instrument via Google News RSS.

        Accepts either a contract code (e.g. ``"EQU5.JO"``) or a Yahoo-style
        ticker (e.g. ``"TSLA"``, ``"NVDA"``). When the instrument is found in
        the EasyEquities catalogue the full company name is used as the search
        query for better headline relevance; otherwise the raw input is used.

        No API key or external package required — uses only Python stdlib
        (``urllib`` and ``xml.etree.ElementTree``).

        :param contract_code_or_ticker: Contract code or ticker to look up.
        :param max_results: Maximum number of headlines to return. Default 10.
        :return: ``NewsResult`` dict:

            - ``instrument``  — resolved instrument name (or raw input)
            - ``query``       — search string sent to Google News
            - ``total``       — number of headlines returned
            - ``headlines``   — list of ``NewsHeadline`` dicts
            - ``message``     — error detail when fetch fails

            Each ``NewsHeadline`` contains:
            ``title``, ``source``, ``published`` (RFC-2822 string), ``url``.

        Examples::

            result = client.instruments.news("TSLA")
            result = client.instruments.news("EQU5.JO")
            result = client.instruments.news("NVDA", max_results=5)

            for h in result["headlines"]:
                print(h["published"], h["source"])
                print(" ", h["title"])
                print(" ", h["url"])
        """
        import urllib.request
        import urllib.parse
        import xml.etree.ElementTree as ET
        import re

        raw = contract_code_or_ticker.strip()

        # --- 1. Resolve instrument name from catalogue ---
        instrument_name = raw
        try:
            all_instruments = self._fetch_all_instruments()
            raw_upper = raw.upper()
            raw_lower = raw.lower()
            for inst in all_instruments:
                code = inst.get("ContractCode", "").upper()
                ticker = (_resolve_yahoo_ticker(inst) or "").upper()
                if code == raw_upper or ticker == raw_upper:
                    instrument_name = inst.get("InstrumentName", raw)
                    break
        except Exception:
            pass  # fall back to raw input as search query

        # Build Google News RSS query: instrument name + "stock" for equities,
        # just the name for ETFs/Crypto.
        search_query = instrument_name
        query_encoded = urllib.parse.quote(search_query)
        url = (
            f"https://news.google.com/rss/search"
            f"?q={query_encoded}"
            f"&hl=en-US&gl=US&ceid=US:en"
        )

        # --- 2. Fetch RSS feed ---
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; EasyEquitiesClient/1.0)"
                    )
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_bytes = resp.read()
        except Exception as exc:
            return {
                "instrument": instrument_name,
                "query": search_query,
                "total": 0,
                "headlines": [],
                "message": f"Failed to fetch Google News RSS: {exc}",
            }

        # --- 3. Parse RSS XML ---
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            return {
                "instrument": instrument_name,
                "query": search_query,
                "total": 0,
                "headlines": [],
                "message": f"Failed to parse RSS XML: {exc}",
            }

        ns = {"media": "http://search.yahoo.com/mrss/"}
        items = root.findall(".//item")
        headlines: List[NewsHeadline] = []

        for item in items[:max_results]:
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            source_el = item.find("source")

            title = title_el.text or "" if title_el is not None else ""
            link = link_el.text or "" if link_el is not None else ""
            published = pub_el.text or "" if pub_el is not None else ""
            source = source_el.text or "" if source_el is not None else ""

            # Google News RSS titles include " - Source Name" at the end;
            # strip it so the title is clean (we already capture source separately).
            if source and title.endswith(f" - {source}"):
                title = title[: -(len(source) + 3)]

            # Google News wraps links in a redirect; extract the real URL
            # from the href attribute of <link> when present, otherwise keep as-is.
            real_url = link
            google_redirect = re.search(r"url=([^&]+)", link)
            if google_redirect:
                real_url = urllib.parse.unquote(google_redirect.group(1))

            headlines.append({
                "title": title.strip(),
                "source": source.strip(),
                "published": published.strip(),
                "url": real_url.strip(),
            })

        return {
            "instrument": instrument_name,
            "query": search_query,
            "total": len(headlines),
            "headlines": headlines,
            "message": None,
        }
