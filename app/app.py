import json
import os
import sys
from functools import wraps

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_cors import CORS

from easy_equities_client.clients import EasyEquitiesClient

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

_client_cache = {}


def get_client():
    if 'username' not in session:
        return None
    key = session['username']
    if key not in _client_cache:
        return None
    return _client_cache[key]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if get_client() is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/')
def index():
    if get_client():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            error = 'Username and password are required.'
        else:
            try:
                client = EasyEquitiesClient()
                client.login(username=username, password=password)
                _client_cache[username] = client
                session['username'] = username
                return redirect(url_for('dashboard'))
            except Exception as e:
                error = str(e)
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    username = session.pop('username', None)
    if username and username in _client_cache:
        del _client_cache[username]
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    client = get_client()
    accounts = client.accounts.list()
    overview = client.accounts._get_portfolio_overview(force_refresh=True)
    exchange_rates = overview.get('exchangeRates', {})
    total_nav = overview.get('totalNav', 'N/A')
    profit_loss = overview.get('profitLoss', 'N/A')
    profit_loss_pct = overview.get('profitLossPercent', 'N/A')
    return render_template(
        'dashboard.html',
        accounts=accounts,
        exchange_rates=exchange_rates,
        total_nav=total_nav,
        profit_loss=profit_loss,
        profit_loss_pct=profit_loss_pct,
        username=session['username'],
    )


@app.route('/account/<account_id>/holdings')
@login_required
def holdings(account_id):
    client = get_client()
    accounts = client.accounts.list()
    account = next((a for a in accounts if a.id == account_id), None)
    if not account:
        return redirect(url_for('dashboard'))
    holdings_list = client.accounts.holdings(account_id, include_shares=True)
    valuation = client.accounts.valuations(account_id)
    return render_template(
        'holdings.html',
        account=account,
        holdings=holdings_list,
        valuation=valuation,
        username=session['username'],
    )


@app.route('/account/<account_id>/transactions')
@login_required
def transactions(account_id):
    client = get_client()
    accounts = client.accounts.list()
    account = next((a for a in accounts if a.id == account_id), None)
    if not account:
        return redirect(url_for('dashboard'))
    txns = client.accounts.transactions(account_id)
    return render_template(
        'transactions.html',
        account=account,
        transactions=txns,
        username=session['username'],
    )


@app.route('/categories')
@login_required
def categories():
    client = get_client()
    import requests as req
    from easy_equities_client import constants
    r = client.session.get(
        constants.REST_API_BASE_URL.replace('/easyequities', '') + '/easyequities/investnow/instruments',
        timeout=20
    )
    instruments = r.json() if r.ok else []
    cats = {}
    for inst in instruments:
        group = inst.get('AssetGroup', 'Other')
        subgroup = inst.get('AssetSubGroup', '')
        if group not in cats:
            cats[group] = {'count': 0, 'subgroups': {}}
        cats[group]['count'] += 1
        if subgroup:
            cats[group]['subgroups'][subgroup] = cats[group]['subgroups'].get(subgroup, 0) + 1
    sorted_cats = dict(sorted(cats.items()))
    return render_template('categories.html', categories=sorted_cats, username=session['username'])


@app.route('/instruments')
@login_required
def instruments():
    client = get_client()
    query = request.args.get('q', '').strip()
    asset_group = request.args.get('group', '').strip()
    asset_subgroup = request.args.get('subgroup', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 50

    from easy_equities_client import constants
    url = constants.REST_API_BASE_URL.replace('/easyequities', '') + '/easyequities/investnow/instruments'
    params = {}
    if query:
        params['contractCode'] = query
    r = client.session.get(url, params=params, timeout=20)
    all_instruments = r.json() if r.ok else []

    if query:
        q = query.upper()
        all_instruments = [
            i for i in all_instruments
            if q in i.get('ContractCode', '').upper()
            or q in i.get('InstrumentName', '').upper()
            or q in i.get('ContributorSymbol', '').upper()
        ]
    if asset_group:
        all_instruments = [i for i in all_instruments if i.get('AssetGroup') == asset_group]
    if asset_subgroup:
        all_instruments = [i for i in all_instruments if i.get('AssetSubGroup') == asset_subgroup]

    total = len(all_instruments)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    paginated = all_instruments[(page - 1) * per_page: page * per_page]

    groups = sorted(set(i.get('AssetGroup', '') for i in (r.json() if r.ok else [])))

    return render_template(
        'instruments.html',
        instruments=paginated,
        query=query,
        asset_group=asset_group,
        asset_subgroup=asset_subgroup,
        page=page,
        total_pages=total_pages,
        total=total,
        groups=groups,
        username=session['username'],
    )


@app.route('/instruments/<path:contract_code>')
@login_required
def instrument_detail(contract_code):
    client = get_client()
    from easy_equities_client import constants
    url = (
        constants.REST_API_BASE_URL.replace('/easyequities', '')
        + f'/easyequities/investnow/instruments?contractCode={contract_code}'
    )
    r = client.session.get(url, timeout=15)
    instruments = r.json() if r.ok else []
    instrument = next((i for i in instruments if i.get('ContractCode') == contract_code), None)
    if not instrument:
        instrument = instruments[0] if instruments else None
    return render_template(
        'instrument_detail.html',
        instrument=instrument,
        contract_code=contract_code,
        username=session['username'],
    )


@app.route('/api/chart/<path:contract_code>')
@login_required
def api_chart(contract_code):
    period = request.args.get('period', '6mo')
    try:
        instrument = _get_instrument(contract_code)
        ticker_symbol = _resolve_ticker(instrument, contract_code)
        import yfinance as yf
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period=period)
        if hist.empty:
            return jsonify({'success': False, 'message': f'No data for {ticker_symbol}', 'ticker': ticker_symbol})
        chart_data = []
        for dt, row in hist.iterrows():
            chart_data.append({
                'date': dt.strftime('%Y-%m-%d'),
                'open': round(float(row['Open']), 4),
                'high': round(float(row['High']), 4),
                'low': round(float(row['Low']), 4),
                'close': round(float(row['Close']), 4),
                'volume': int(row['Volume']),
            })
        return jsonify({
            'success': True,
            'ticker': ticker_symbol,
            'contract_code': contract_code,
            'period': period,
            'data': chart_data,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/accounts')
@login_required
def api_accounts():
    client = get_client()
    accounts = client.accounts.list()
    return jsonify([{'id': a.id, 'name': a.name, 'currency_id': a.trading_currency_id} for a in accounts])


@app.route('/api/holdings/<account_id>')
@login_required
def api_holdings(account_id):
    client = get_client()
    holdings_list = client.accounts.holdings(account_id, include_shares=True)
    return jsonify(holdings_list)


@app.route('/api/instruments/search')
@login_required
def api_instruments_search():
    client = get_client()
    query = request.args.get('q', '').strip()
    from easy_equities_client import constants
    url = constants.REST_API_BASE_URL.replace('/easyequities', '') + '/easyequities/investnow/instruments'
    params = {'contractCode': query} if query else {}
    r = client.session.get(url, params=params, timeout=20)
    instruments = r.json() if r.ok else []
    if query:
        q = query.upper()
        instruments = [
            i for i in instruments
            if q in i.get('ContractCode', '').upper()
            or q in i.get('InstrumentName', '').upper()
        ]
    return jsonify(instruments[:30])


def _get_instrument(contract_code):
    client = get_client()
    from easy_equities_client import constants
    url = (
        constants.REST_API_BASE_URL.replace('/easyequities', '')
        + f'/easyequities/investnow/instruments?contractCode={contract_code}'
    )
    r = client.session.get(url, timeout=15)
    instruments = r.json() if r.ok else []
    return next((i for i in instruments if i.get('ContractCode') == contract_code), None)


def _resolve_ticker(instrument, contract_code):
    if instrument is None:
        return contract_code
    symbol = instrument.get('ContributorSymbol', '')
    exchange = instrument.get('Exchange', '').upper()
    market = instrument.get('Market', '').upper()
    sub_market = instrument.get('SubMarket', '').upper()

    if not symbol:
        symbol = contract_code

    if 'USA' in exchange or 'US EQUITIES' in sub_market or 'US ETF' in sub_market:
        return symbol
    elif 'JSE' in exchange or 'ZA' in exchange or 'SA EQUITIES' in sub_market or 'SOUTH AFRICA' in market:
        return f'{symbol}.JO'
    elif 'ASX' in exchange or 'AUSTRALIA' in market or 'AUS' in sub_market:
        return f'{symbol}.AX'
    elif 'LSE' in exchange or 'LONDON' in market or 'UK' in exchange:
        return f'{symbol}.L'
    elif 'CRYPTO' in exchange or 'DIGITAL' in exchange or instrument.get('AssetGroup', '').upper() == 'CRYPTO':
        return f'{symbol}-USD'
    else:
        return symbol


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
