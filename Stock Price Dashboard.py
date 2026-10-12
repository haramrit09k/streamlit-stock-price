import yfinance as yf
import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Stock Price Dashboard", page_icon="📈", layout="centered")

RANGES = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 365 * 5, "Max": None}


@st.cache_data
def load_tickers():
    df = pd.read_csv('tickers.csv')
    df['Label'] = df['Symbol'] + ' - ' + df['Company Name']
    return df


class NoPriceData(Exception):
    pass


@st.cache_data(ttl=3600)
def _download_history(symbol):
    history = yf.Ticker(symbol).history(period='max')
    if history.empty:
        # raising keeps a failed or empty reply out of the cache, so a Yahoo hiccup doesn't stick for an hour
        raise NoPriceData(symbol)
    return history


def load_history(symbol):
    """Price history; an empty frame if Yahoo has none for the symbol; None if Yahoo could not be reached."""
    try:
        return _download_history(symbol)
    except NoPriceData:
        return pd.DataFrame()
    except Exception:
        st.error("Couldn't reach Yahoo Finance right now. Please try again in a minute.")
        return None


def change_text(series, symbol=None):
    """Percent change from the first to the last value, coloured green/red (None if not enough data)."""
    if len(series) < 2 or series.iloc[0] == 0:
        return None
    pct = (series.iloc[-1] / series.iloc[0] - 1) * 100
    colour = 'green' if pct >= 0 else 'red'
    return f"{symbol + ' ' if symbol else ''}:{colour}[{pct:+,.1f}%]"


tickers = load_tickers()
symbols = set(tickers['Symbol'])


def search_companies(query, limit=25):
    """Best matches first: exact symbol, symbol prefix, name prefix, symbol contains, name contains.
    (Streamlit's built-in selectbox search does not favour exact symbols once the list is this long.)"""
    q = query.strip().lower()
    sym = tickers['Symbol'].str.lower()
    name = tickers['Company Name'].str.lower()
    rank = pd.Series(9, index=tickers.index)  # 9 = no match; later lines overwrite with better ranks
    rank[name.str.contains(q, regex=False)] = 4
    rank[sym.str.contains(q, regex=False)] = 3
    rank[name.str.startswith(q)] = 2
    rank[sym.str.startswith(q)] = 1
    rank[sym == q] = 0
    hits = tickers[rank < 9].assign(rank=rank[rank < 9], is_etf=lambda d: d['Type'] == 'ETF')
    return hits.sort_values(['rank', 'is_etf', 'Symbol']).head(limit)


def company_picker(title, key, initial=''):
    """Search box plus a list of ranked matches. Returns the chosen company row, or None."""
    if f'{key}_query' not in st.session_state:
        st.session_state[f'{key}_query'] = initial
    query = st.text_input(title, key=f'{key}_query',
                          placeholder='Type a symbol or company name, then press Enter')
    if not query.strip():
        return None
    hits = search_companies(query)
    if hits.empty:
        st.warning(f'No company matches "{query}".')
        return None
    if len(hits) == 1:
        return hits.iloc[0]
    # the key includes the query so each new search starts on its best match
    pick = st.selectbox('Matches, best first', hits['Label'].tolist(), key=f"{key}_pick_{query.strip().lower()}")
    return hits[hits['Label'] == pick].iloc[0]

st.title("📈 Stock Price Dashboard")
st.caption("by [haramrit singh khurana](https://haramrit09k.github.io)")

# Pick the starting company, range and comparison from the URL (?symbol=AAPL&compare=MSFT&range=1Y)
# so views can be shared. Only set once per session, so later widget changes are not overwritten.
if 'range' not in st.session_state:
    r = st.query_params.get('range')
    st.session_state.range = r if r in RANGES else '1Y'
start_symbol = st.query_params.get('symbol')
start_symbol = start_symbol if start_symbol in symbols else 'AAPL'
start_compare = st.query_params.get('compare')
start_compare = start_compare if start_compare in symbols else ''

company = company_picker('Search for a company', 'company', start_symbol)
if company is None:
    st.info("Enter a symbol or company name above to get started.")
    st.stop()
# keep the URL in sync with the selection so it can be copied and shared
st.query_params['symbol'] = company['Symbol']

history = load_history(company['Symbol'])
if history is None:
    st.stop()

st.subheader(f"{company['Symbol']} · {company['Company Name']}")

if history.empty:
    st.warning("No price data found for this company.")
    st.stop()

# latest trading day, compared with the one before it
latest = history.iloc[-1]
st.caption(f"Latest trading day: {history.index[-1].strftime('%A, %B %d, %Y')}")

change = None
if len(history) > 1:
    change = latest['Close'] - history['Close'].iloc[-2]
    change_pct = change / history['Close'].iloc[-2] * 100

col1, col2, col3, col4 = st.columns(4)
col1.metric("Close", f"${latest['Close']:,.2f}",
            None if change is None else f"{change:+.2f} ({change_pct:+.2f}%)")
col2.metric("Open", f"${latest['Open']:,.2f}")
col3.metric("High", f"${latest['High']:,.2f}")
col4.metric("Low", f"${latest['Low']:,.2f}")

col5, col6 = st.columns(2)
col5.metric("Volume", f"{latest['Volume']:,.0f}")
col6.metric("Dividends", f"${latest['Dividends']:,.2f}")

# one price chart with a time range, instead of one chart per column
range_choice = st.radio("Range", list(RANGES), horizontal=True, key='range')
days = RANGES[range_choice]
st.query_params['range'] = range_choice
view = history if days is None else history[history.index >= history.index[-1] - pd.Timedelta(days=days)]

other = company_picker('Compare with (optional)', 'compare', start_compare)

# optional second company, drawn on the same chart
if other is not None:
    if other['Symbol'] == company['Symbol']:
        st.info("Pick a different company to compare.")
        other = None
    else:
        other_history = load_history(other['Symbol'])
        if other_history is None:
            other = None
        elif other_history.empty:
            st.warning(f"No price data found for {other['Symbol']}, so it can't be compared.")
            other = None

if other is not None:
    # rebase both to 100 at the start so growth is comparable, using only the days both traded
    closes = pd.concat({company['Symbol']: history['Close'], other['Symbol']: other_history['Close']}, axis=1, sort=True)
    closes.index = closes.index.tz_localize(None)
    closes = closes.dropna()
    if days is not None:
        closes = closes[closes.index >= closes.index[-1] - pd.Timedelta(days=days)]
    st.query_params['compare'] = other['Symbol']
else:
    st.query_params.pop('compare', None)

if other is not None and closes.empty:
    st.warning("These two companies have no trading days in common.")
elif other is not None:
    st.subheader(f"Growth of 100: {company['Symbol']} vs {other['Symbol']}")
    st.caption(f"Both rebased to 100 on {closes.index[0].strftime('%B %d, %Y')}. "
               f"Change over this range: {' · '.join(change_text(closes[c], c) for c in closes)}")
    growth = (closes / closes.iloc[0] * 100).rename_axis('Date').reset_index().melt(
        'Date', var_name='Symbol', value_name='Value')
    growth_chart = alt.Chart(growth).mark_line().encode(
        x=alt.X('Date:T', title=None),
        y=alt.Y('Value:Q', scale=alt.Scale(zero=False), title=None),
        color=alt.Color('Symbol:N', title=None),
        tooltip=[alt.Tooltip('Date:T'), 'Symbol:N', alt.Tooltip('Value:Q', format='.1f')],
    )
    st.altair_chart(growth_chart)
else:
    st.subheader("Closing price (USD)")
    move = change_text(view['Close'])
    if move:
        st.caption(f"Change over this range: {move} "
                   f"({view.index[0].strftime('%b %d, %Y')} to {view.index[-1].strftime('%b %d, %Y')})")
    # let the y-axis fit the data instead of starting at 0, so price moves are visible
    price_chart = alt.Chart(view['Close'].reset_index()).mark_line().encode(
        x=alt.X('Date:T', title=None),
        y=alt.Y('Close:Q', scale=alt.Scale(zero=False), title=None),
        tooltip=[alt.Tooltip('Date:T'), alt.Tooltip('Close:Q', format='$.2f')],
    )
    st.altair_chart(price_chart)

st.subheader(f"{company['Symbol']} volume")
st.bar_chart(view['Volume'])

with st.expander("Company details"):
    st.markdown(f"""
- **Company name:** {company['Company Name']}
- **Symbol:** {company['Symbol']}
- **Security name:** {company['Security Name']}
- **Exchange:** {company['Exchange']}
- **Type:** {company['Type']}
""")
