import yfinance as yf
import streamlit as st
import pandas as pd

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


tickers = load_tickers()

st.title("📈 Stock Price Dashboard")
st.caption("by [haramrit singh khurana](https://haramrit09k.github.io)")

labels = tickers['Label'].to_list()
default = labels.index('AAPL - Apple Inc.') if 'AAPL - Apple Inc.' in labels else 0
choice = st.selectbox('Select company', labels, index=default)
company = tickers[tickers['Label'] == choice].iloc[0]

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
range_choice = st.radio("Range", list(RANGES), index=2, horizontal=True)
days = RANGES[range_choice]
view = history if days is None else history[history.index >= history.index[-1] - pd.Timedelta(days=days)]

st.subheader("Closing price (USD)")
st.line_chart(view['Close'])

st.subheader("Volume")
st.bar_chart(view['Volume'])

with st.expander("Company details"):
    st.markdown(f"""
- **Company name:** {company['Company Name']}
- **Symbol:** {company['Symbol']}
- **Security name:** {company['Security Name']}
- **Market category:** {company['Market Category']}
- **Financial status:** {company['Financial Status']}
""")
