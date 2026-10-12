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


@st.cache_data(ttl=3600)
def load_history(symbol):
    return yf.Ticker(symbol).history(period='max')


def change_text(series, symbol=None):
    """Percent change from the first to the last value, coloured green/red (None if not enough data)."""
    if len(series) < 2 or series.iloc[0] == 0:
        return None
    pct = (series.iloc[-1] / series.iloc[0] - 1) * 100
    colour = 'green' if pct >= 0 else 'red'
    return f"{symbol + ' ' if symbol else ''}:{colour}[{pct:+,.1f}%]"


tickers = load_tickers()

st.title("📈 Stock Price Dashboard")
st.caption("by [haramrit singh khurana](https://haramrit09k.github.io)")

label_of = dict(zip(tickers['Symbol'], tickers['Label']))
labels = list(label_of.values())

# Pick the starting company and range from the URL (?symbol=AAPL&range=1Y) so views can be shared.
# Only set once per session, so later widget changes are not overwritten.
if 'company' not in st.session_state:
    st.session_state.company = label_of.get(st.query_params.get('symbol'), label_of.get('AAPL', labels[0]))
if 'range' not in st.session_state:
    r = st.query_params.get('range')
    st.session_state.range = r if r in RANGES else '1Y'
if 'compare' not in st.session_state:
    st.session_state.compare = label_of.get(st.query_params.get('compare'))

choice = st.selectbox('Select company', labels, key='company')
company = tickers[tickers['Label'] == choice].iloc[0]
# keep the URL in sync with the selection so it can be copied and shared
st.query_params['symbol'] = company['Symbol']

history = load_history(company['Symbol'])

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

compare_choice = st.selectbox('Compare with (optional)', labels, index=None, key='compare',
                              placeholder='Type a symbol or company name')

# optional second company, drawn on the same chart
other = None
if compare_choice:
    other = tickers[tickers['Label'] == compare_choice].iloc[0]
    if other['Symbol'] == company['Symbol']:
        st.info("Pick a different company to compare.")
        other = None
    else:
        other_history = load_history(other['Symbol'])
        if other_history.empty:
            st.warning(f"No price data found for {other['Symbol']}, so it can't be compared.")
            other = None

if other is not None:
    # rebase both to 100 at the start so growth is comparable, using only the days both traded
    closes = pd.concat({company['Symbol']: history['Close'], other['Symbol']: other_history['Close']}, axis=1)
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
- **Market category:** {company['Market Category']}
- **Financial status:** {company['Financial Status']}
""")
