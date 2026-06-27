---
name: EasyEquities API Architecture
description: Key facts about EasyEquities new API architecture, auth, and what works/doesn't work
---

# EasyEquities New API Architecture

## Working (Bearer JWT OK)
- Login: OAuth2 PKCE against `identity.openeasy.io` — `client_id=fa4d2622bc1e45a7be79395d941e2548`, `redirect_uri=https://portfolio-overview.apps.easyequities.io/auth/callback`
- REST API proxy: `rest.synatic.openeasy.io/easyequities` — all portfolio and instrument reads
  - `/portfolios/v3/portfolio-overview` — account list
  - `/investnow/instruments?contractCode=X` — instrument details + last price
  - `/investnow/themes`, `/investnow/trading_currencies`, `/investnow/ancillary`, `/investnow/usertradingcurrencies/`
  - `/investnow/customise_preference/{id}/{type}` (POST), `/investnow/search` (POST, always 204)
  - `/transaction-history-provider/...` (transactions, see accounts/clients.py for multi-path)

## Blocked (Bearer JWT fails)
- `apigateway.openeasy.io/synatic/v1/*` → AWS IAM (SigV4) auth error — cannot use Bearer JWT
- `apigateway.openeasy.io/api/*` → 403 Forbidden
- `platform.easyequities.io/InvestNow/BuyAtOpen|PlaceOrder|RecurringOrder` → HTTP 200 but serves 404 HTML page (old platform removed these)

## Order Placement (NOT YET WORKING)
The invest-now web app (`invest-now.apps.easyequities.io`) has NO buy/sell POST calls.
It navigates to the old platform for orders, which now returns 404.
The actual order API uses `apigateway.openeasy.io` with AWS IAM auth (not Bearer JWT accessible).
- The `investnow` service name IS valid on the synatic proxy, but only has read endpoints
- All tried order paths return "Path not found" (404) on the synatic proxy

**Why:** EasyEquities moved order placement to `apigateway.openeasy.io` which uses AWS IAM. The OAuth2 Bearer JWT doesn't work against that gateway. The mobile app probably uses embedded API keys for SigV4.

**How to apply:** If implementing orders, try the synatic proxy paths first (they're the right pattern) and handle the "Path not found" 404 gracefully. The OrdersClient does this with multi-path fallback.

## Key Client IDs
- Portfolio overview app: `fa4d2622bc1e45a7be79395d941e2548`
- Invest-now app: `58af25d07a934c67b65aa8c159f1c1c2`, scope includes `invest_now_api`

## Invest-Now App URL Config Object (`ae`)
Defined in `chunk-X27KMJHQ.js` — `ae.easyApiBaseUrl = k.appSettings.restSynaticBaseUrl = "https://rest.synatic.openeasy.io/easyequities"`
