import shutil
from urllib.parse import urlparse

from requests import Session

from easy_equities_client import constants
from easy_equities_client.accounts.clients import AccountsClient
from easy_equities_client.instruments.clients import InstrumentsClient
from easy_equities_client.types import Client

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--headless=new",
]


def _find_chromium() -> str:
    """Return the path to a usable Chromium/Chrome binary."""
    for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError(
        "No Chromium/Chrome binary found. "
        "Install Chromium (e.g. via system packages) before using this client."
    )


class PlatformClient(Client):
    """
    Generic client for EasyEquities / Satrix platforms.

    Authentication uses the OpenID Connect / OAuth2 PKCE flow via
    identity.openeasy.io. Because the identity server employs JavaScript-based
    bot detection, login is performed via a headless Chromium browser
    (Playwright). After a successful login the Bearer token and session cookies
    are transferred to a regular requests.Session so that all subsequent calls
    are lightweight HTTP requests.
    """

    def __init__(self, base_url, session: Session = None):
        super().__init__(base_url, session)
        self.accounts = AccountsClient(base_url, self.session)
        self.instruments = InstrumentsClient(base_url, self.session)

    def login(self, username: str, password: str) -> bool:
        """
        Login to the platform using a headless browser to complete the OAuth2
        PKCE flow, then transfer the Bearer token and session cookies to the
        underlying requests.Session.

        Flow:
          1. Open platform /Account/SignIn in headless Chromium — platform
             generates a PKCE code_verifier/challenge and stores it in its
             own session, then redirects to the identity server login page.
          2. Fill in username and click "Continue" (two-step UI).
          3. Fill in password and click "Login".
          4. Wait for the OAuth2 callback to complete and the browser to
             land on the EasyEquities portfolio page.
          5. Capture the Bearer JWT from the first REST API request the SPA
             makes to rest.synatic.openeasy.io.
          6. Copy all browser cookies + the Bearer token into the
             requests.Session so subsequent HTTP calls are authenticated.

        :param username: EasyEquities / Satrix username.
        :param password: EasyEquities / Satrix password.
        :return: True if successfully logged in.
        :raises RuntimeError: if Chromium is not found.
        :raises Exception: if login fails or times out.
        """
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        chromium_path = _find_chromium()

        bearer_token: list[str] = []

        def _capture_token(request) -> None:
            if "rest.synatic.openeasy.io" in request.url and not bearer_token:
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    bearer_token.append(auth)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=chromium_path,
                args=_CHROMIUM_ARGS,
                headless=True,
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.on("request", _capture_token)

            try:
                # Step 1: Navigate to platform sign-in (triggers PKCE + redirect to identity server)
                page.goto(
                    self._url(constants.PLATFORM_SIGN_IN_PATH),
                    wait_until="networkidle",
                    timeout=30_000,
                )

                # Step 2: Fill username and click Continue (two-step login UI)
                page.fill('input[name="Username"]', username)
                page.click('#continueButton')

                # Step 3: Wait for password field, fill it in
                page.wait_for_selector('input[name="Password"]:visible', timeout=10_000)
                page.fill('input[name="Password"]', password)

                # Step 4: Submit and wait for the portfolio page
                page.click('#SignIn')

                try:
                    page.wait_for_url("**easyequities.io/**", timeout=20_000)
                    page.wait_for_function(
                        "() => !window.location.pathname.includes('/auth/callback') "
                        "&& !window.location.host.includes('identity')",
                        timeout=15_000,
                    )
                    # Let the SPA fire its initial API calls so we can capture the token
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except PWTimeout:
                    current_url = page.url
                    if "identity" in current_url or "login" in current_url.lower():
                        error_el = page.query_selector('[id="error-message-container"]')
                        error_msg = error_el.inner_text().strip() if error_el else ""
                        raise Exception(
                            "Login failed — still on the identity server page. "
                            + (f"Server message: {error_msg}" if error_msg else
                               "Check your username and password.")
                        )
                    raise

                # Step 5: Transfer cookies and Bearer token to the requests.Session
                for cookie in context.cookies():
                    self.session.cookies.set(
                        cookie["name"],
                        cookie["value"],
                        domain=cookie.get("domain", "").lstrip("."),
                    )

                if bearer_token:
                    self.session.headers["Authorization"] = bearer_token[0]

            finally:
                context.close()
                browser.close()

        return True


class EasyEquitiesClient(PlatformClient):
    """
    Client to interact with EasyEquities.
    Sign-in starts at https://platform.easyequities.io/Account/SignIn which
    redirects through the OAuth2 flow and lands on
    https://portfolio-overview.apps.easyequities.io.
    """

    def __init__(self, base_url: str = constants.EASY_EQUITIES_BASE_PLATFORM_URL):
        return super().__init__(base_url)


class SatrixClient(PlatformClient):
    """
    Client to interact with Satrix.
    """

    def __init__(self, base_url: str = constants.SATRIX_BASE_PLATFORM_URL):
        return super().__init__(base_url)
