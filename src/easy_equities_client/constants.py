from enum import Enum


class CustomEnum(Enum):
    @classmethod
    def values(cls):
        return [p.value for p in cls.__members__.values()]


class Platform(CustomEnum):
    EASY_EQUITIES_ZA = "EasyEquitiesZA"
    SATRIX = "Satrix"


# --- Platform frontend URLs ---
# The old platform.easyequities.io now redirects to portfolio-overview.apps.easyequities.io.
EASY_EQUITIES_BASE_PLATFORM_URL = "https://portfolio-overview.apps.easyequities.io"
SATRIX_BASE_PLATFORM_URL = "https://platform.satrixnow.co.za"

# Sign-in entry point — still used to start the OAuth2 PKCE flow.
PLATFORM_SIGN_IN_PATH = "/Account/SignIn"

# --- Identity server (OAuth2/OIDC provider) ---
IDENTITY_BASE_URL = "https://identity.openeasy.io"
IDENTITY_SIGN_IN_PATH = "/Account/Login"
IDENTITY_OAUTH_CALLBACK_PATH = "/connect/authorize/callback"

# --- REST API (new platform backend, replaces old HTML-scraped endpoints) ---
REST_API_BASE_URL = "https://rest.synatic.openeasy.io/easyequities"
REST_PORTFOLIO_OVERVIEW_PATH = "/portfolios/v3/portfolio-overview"
REST_NAV_CHART_PATH = "/portfolios/nav_chart_data/{period}"
REST_TRANSACTIONS_PATH = "/portfolios/transactions"

# --- Legacy constants (kept for backward compatibility with existing tests) ---
# These endpoints no longer respond correctly on the live platform.
PLATFORM_ACCOUNT_OVERVIEW_PATH = "/AccountOverview"
PLATFORM_CAN_USE_ACCOUNT_PATH = "/Menu/CanUseSelectedAccount"
PLATFORM_UPDATE_CURRENCY_PATH = "/Menu/UpdateCurrency"
PLATFORM_ACCOUNT_VALUATIONS_PATH = "/AccountOverview/GetTrustAccountValuations"
PLATFORM_HOLDINGS_PATH = "/AccountOverview/GetHoldingsView?stockViewCategoryId=12"
PLATFORM_TRANSACTIONS_PATH = "/TransactionHistory/GetTransactions"
PLATFORM_TRANSACTIONS_SEARCH_PATH_NEXT_PAGE = "/TransactionHistory/SearchWithPage?StartDate={start_date}&EndDate={end_date}&PageNumber={page_number}"
PLATFORM_GET_CHART_DATA_PATH = "/Equity/GetChartDataByContractCode"

RE_AMOUNT_PATTERN = (
    r"(?P<symbol>\-)?\s*(?P<currency>[^\s|\d])\s*(?P<value>(?:\d+|.)*)\s*"
)
