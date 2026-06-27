import base64
import hashlib
import os
import re
import urllib.parse
from typing import Optional

from requests import Session

from easy_equities_client import constants
from easy_equities_client.accounts.clients import AccountsClient
from easy_equities_client.instruments.clients import InstrumentsClient
from easy_equities_client.types import Client

_CLIENT_ID = "fa4d2622bc1e45a7be79395d941e2548"
_REDIRECT_URI = "https://portfolio-overview.apps.easyequities.io/auth/callback"
_SCOPES = (
    "openid platform profile api_gateway user_profile_api static_data_api "
    "easy_protect_api easy_lending_api thrive_api easy_trader_api portfolio_api "
    "auto_refica_api registration_api easy_loyalty_api transaction_history_provider_api"
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and its S256 code_challenge."""
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _random_token(n: int = 32) -> str:
    return base64.urlsafe_b64encode(os.urandom(n)).rstrip(b"=").decode()


class PlatformClient(Client):
    """
    Generic client for EasyEquities / Satrix platforms.

    Authentication uses a direct HTTP implementation of the OAuth2 PKCE flow
    against identity.openeasy.io — no browser or Playwright required.
    After a successful login the Bearer token is stored in the session headers
    so that all subsequent calls are lightweight authenticated HTTP requests.
    """

    def __init__(self, base_url: str, session: Session = None):
        super().__init__(base_url, session)
        self.accounts = AccountsClient(base_url, self.session)
        self.instruments = InstrumentsClient(base_url, self.session)

    def login(self, username: str, password: str) -> bool:
        """
        Login via direct HTTP — no browser required.

        Implements the OAuth2 PKCE flow:
          1. Generate PKCE code_verifier / code_challenge.
          2. GET /connect/authorize — identity server stores the PKCE state
             and redirects to its own login page (we follow the redirect to
             get the anti-forgery token and ReturnUrl).
          3. POST username to /Account/Login (first step of the two-step UI).
          4. POST password to /Account/Login (second step).
          5. Follow the redirect chain back to the platform callback URL,
             which contains the authorization code.
          6. POST to /connect/token to exchange the code for a Bearer JWT.
          7. Store the Bearer token in the requests.Session headers.

        :param username: EasyEquities username.
        :param password: EasyEquities password.
        :return: True if successfully logged in.
        :raises Exception: if login fails (wrong credentials, bot block, etc.).
        """
        s = self.session
        s.headers.update({"User-Agent": _USER_AGENT})

        # --- Step 1: Generate PKCE pair ---
        code_verifier, code_challenge = _pkce_pair()
        nonce = _random_token(24)
        state = _random_token(24)

        # --- Step 2: Hit /connect/authorize to start the PKCE flow ---
        auth_params = {
            "client_id": _CLIENT_ID,
            "redirect_uri": _REDIRECT_URI,
            "response_type": "code",
            "scope": _SCOPES,
            "nonce": nonce,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = constants.IDENTITY_BASE_URL + "/connect/authorize"
        r = s.get(auth_url, params=auth_params, allow_redirects=True)
        if r.status_code not in (200, 302):
            raise Exception(f"Authorize step failed: HTTP {r.status_code}")

        login_page_url = r.url
        login_page_body = r.text

        # Extract the anti-forgery token and ReturnUrl from the login page
        csrf_match = re.search(
            r'<input name="__RequestVerificationToken"[^>]+value="([^"]+)"',
            login_page_body,
        )
        return_url_match = re.search(
            r'<input[^>]+name="ReturnUrl"[^>]+value="([^"]+)"',
            login_page_body,
        )
        if not csrf_match:
            raise Exception(
                "Could not find anti-forgery token on the login page. "
                "EasyEquities may have updated their login flow or is blocking requests."
            )

        csrf_token = csrf_match.group(1)
        return_url = (
            html_unescape(return_url_match.group(1)) if return_url_match else ""
        )

        # --- Step 3: POST credentials in one request ---
        # The two-step UI (username then password) is pure JavaScript — the
        # "Continue" button just reveals the password field client-side.
        # The actual form submission sends username + password together in
        # a single POST with IsUsernameProvided=False.
        identity_login_url = constants.IDENTITY_BASE_URL + constants.IDENTITY_SIGN_IN_PATH
        login_data = {
            "__RequestVerificationToken": csrf_token,
            "ReturnUrl": return_url,
            "ClientIdForProperties": _CLIENT_ID,
            "Username": username,
            "IsUsernameProvided": "False",
            "Password": password,
            "button": "login",
            "Response": "",
        }
        r3 = s.post(
            identity_login_url,
            data=login_data,
            headers={"Referer": login_page_url},
            allow_redirects=False,
        )

        # --- Step 5: Follow redirects to the callback URL ---
        # After a successful password POST the server redirects back to the
        # platform callback with ?code=...&state=...
        auth_code: Optional[str] = None
        redirect_url = r3.headers.get("Location", "")

        if not redirect_url:
            # Check if we're still on the login page (bad password)
            body3 = r3.text
            error_el = re.search(
                r'id="error-message-container"[^>]*>(.*?)</div>',
                body3,
                re.DOTALL,
            )
            error_msg = error_el.group(1).strip() if error_el else ""
            raise Exception(
                "Login failed — no redirect after password submission. "
                + (f"Server message: {error_msg}" if error_msg else
                   "Check your username and password.")
            )

        # Follow redirects until we reach the callback or find the code
        max_redirects = 10
        current_url = redirect_url
        for _ in range(max_redirects):
            parsed = urllib.parse.urlparse(current_url)
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                auth_code = params["code"][0]
                break

            if not current_url.startswith("http"):
                current_url = constants.IDENTITY_BASE_URL + current_url

            r_step = s.get(current_url, allow_redirects=False)
            next_loc = r_step.headers.get("Location", "")
            if not next_loc:
                break
            current_url = next_loc

        if not auth_code:
            raise Exception(
                "OAuth2 flow did not return an authorization code. "
                "EasyEquities may be blocking automated logins."
            )

        # --- Step 6: Exchange code for Bearer token ---
        token_data = {
            "grant_type": "authorization_code",
            "client_id": _CLIENT_ID,
            "code": auth_code,
            "redirect_uri": _REDIRECT_URI,
            "code_verifier": code_verifier,
        }
        r_token = s.post(
            constants.IDENTITY_BASE_URL + "/connect/token",
            data=token_data,
        )
        if r_token.status_code != 200:
            raise Exception(
                f"Token exchange failed: HTTP {r_token.status_code} — {r_token.text[:200]}"
            )

        token_json = r_token.json()
        access_token = token_json.get("access_token")
        if not access_token:
            raise Exception(f"No access_token in token response: {token_json}")

        # --- Step 7: Store Bearer token in session ---
        s.headers["Authorization"] = f"Bearer {access_token}"
        return True


def html_unescape(s: str) -> str:
    """Unescape HTML entities in a string (e.g. &#x2F; -> /)."""
    import html
    return html.unescape(s)


class EasyEquitiesClient(PlatformClient):
    """
    Client to interact with EasyEquities.
    """

    def __init__(self, base_url: str = constants.EASY_EQUITIES_BASE_PLATFORM_URL):
        return super().__init__(base_url)


class SatrixClient(PlatformClient):
    """
    Client to interact with Satrix.
    """

    def __init__(self, base_url: str = constants.SATRIX_BASE_PLATFORM_URL):
        return super().__init__(base_url)
