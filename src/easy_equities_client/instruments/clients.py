import logging
from typing import List, Optional

from easy_equities_client import constants
from easy_equities_client.instruments.types import HistoricalPrices, InstrumentDetail, Period
from easy_equities_client.types import Client

logger = logging.getLogger(__name__)


class InstrumentsClient(Client):
    def historical_prices(self, contract_code: str, period: Period) -> HistoricalPrices:
        """
        Fetch the latest price and metadata for a given instrument.

        Uses the REST investnow/instruments endpoint which returns current price
        data and instrument metadata. Historical price series (chart data) are not
        currently available via the REST API — the period parameter is accepted for
        forward compatibility.

        :param contract_code: Contract code for the instrument, e.g. "EQU.ZA.SYGJP"
        :param period: Time period (accepted for API compatibility; price series not yet available).
        :return: HistoricalPrices dict with success, instrument metadata, and current price.
        """
        url = (
            constants.REST_API_BASE_URL.replace("/easyequities", "")
            + "/easyequities/investnow/instruments"
            + f"?contractCode={contract_code}"
        )
        response = self.session.get(url, timeout=15)
        response.raise_for_status()

        instruments: List[InstrumentDetail] = response.json()
        match: Optional[InstrumentDetail] = None
        for inst in instruments:
            if inst.get("ContractCode") == contract_code:
                match = inst
                break

        if match is None:
            logger.warning(f"Instrument '{contract_code}' not found in investnow instruments list.")
            return {"success": False, "instrument": None, "currentPrice": None, "scalingFactor": None, "priceDate": None}

        last_price = match.get("LastPrice", {})
        raw_value = last_price.get("Value", 0)
        scaling = match.get("ExchangeScalingFactor", 100)
        current_price = raw_value / scaling if scaling else raw_value

        return {
            "success": True,
            "instrument": match,
            "currentPrice": current_price,
            "scalingFactor": scaling,
            "priceDate": last_price.get("OriginalDateUpdated"),
        }

    def search(self, query: str) -> List[InstrumentDetail]:
        """
        Search for instruments by name or contract code.

        :param query: Search string (matched against contract code and instrument name).
        :return: List of matching InstrumentDetail dicts.
        """
        url = (
            constants.REST_API_BASE_URL.replace("/easyequities", "")
            + f"/easyequities/investnow/instruments?contractCode={query}"
        )
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        instruments: List[InstrumentDetail] = response.json()
        q = query.upper()
        return [
            inst for inst in instruments
            if q in inst.get("ContractCode", "").upper()
            or q in inst.get("InstrumentName", "").upper()
        ]
