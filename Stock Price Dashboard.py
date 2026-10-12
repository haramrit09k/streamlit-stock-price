import yfinance as yf
import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Stock Price Dashboard", page_icon="📈", layout="centered")

RANGES = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 365 * 5, "Max": None}
VIEWS = ["Price", "Learn"]
RANGE_WORDS = {"1M": "the last month", "6M": "the last 6 months", "1Y": "the last year",
               "5Y": "the last 5 years", "Max": "its full history"}

# Plain-English explanations shown as hover tooltips (the "?" icons)
HELP = {
    "close": "The price of the last trade of the day. Most charts and performance figures use closing prices. "
             "The coloured number is the change from the previous trading day's close.",
    "open": "The price of the first trade of the day. It can differ from the previous close because of news "
            "or trading that happened after the market closed.",
    "high": "The highest price the stock traded at during the day.",
    "low": "The lowest price the stock traded at during the day. The gap between High and Low shows how much "
           "the price moved that day.",
    "volume": "How many shares changed hands during the day. Volume that is much higher than usual often "
              "goes along with news.",
    "dividends": "A payment some companies make to shareholders, per share. \\$0.00 usually means no dividend "
                 "was paid on this day, not that the company never pays one.",
    "range": "How far back the charts look. The percentage change is measured from the first to the last "
             "day in this range, so it ignores everything that happened in between.",
    "price_chart": "Each point is one day's closing price. The vertical axis does not start at zero, so small "
                   "moves can look big: check the numbers on the axis. Past prices are adjusted for stock splits and "
                   "dividends, so a 2-for-1 split does not show up as a sudden 50% drop.",
    "volume_chart": "Each bar is one day's trading volume: the number of shares traded that day.",
    "ma": "A moving average is the average closing price over the last 50 or 200 days, recalculated every day. "
          "It smooths out day-to-day noise. It is built from past prices, so it always lags the price.",
    "worst": "The largest drop from a peak to a later low during this range.",
    "recover": "How much the price would have to rise from that low to get back to the earlier peak. "
               "A 50% fall needs a 100% rise.",
    "typical": "The average size of the daily price change in this range, whether up or down.",
    "growth": "Both lines start at 100 on the same day, so you can compare how much each grew regardless of "
              "its share price. See the Learn view for more.",
    "compare": "Overlay a second company or fund. Comparing helps separate a company's own performance from "
               "the market's: try SPY, an ETF that tracks the S&P 500 (about 500 large US companies).",
}


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


def compact(n):
    """37,855,000 -> '37.9M'"""
    for suffix, size in (('B', 1e9), ('M', 1e6), ('K', 1e3)):
        if abs(n) >= size:
            return f"{n / size:.1f}{suffix}"
    return f"{n:,.0f}"


def risk_summary(close):
    """Biggest fall from a peak, the rise needed to recover it, and the average daily move (None if too short)."""
    if len(close) < 3:
        return None
    peak = close.cummax()
    drawdown = close / peak - 1
    low_date = drawdown.idxmin()
    out = {'worst': drawdown.min() * 100, 'typical': close.pct_change().abs().mean() * 100}
    if out['worst'] < 0:
        out['low_date'] = low_date
        out['peak_date'] = close[:low_date].idxmax()
        out['recover'] = (peak[low_date] / close[low_date] - 1) * 100
    return out


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


def company_picker(title, key, initial='', help=None):
    """Search box plus a list of ranked matches. Returns the chosen company row, or None."""
    if f'{key}_query' not in st.session_state:
        st.session_state[f'{key}_query'] = initial
    query = st.text_input(title, key=f'{key}_query', help=help,
                          placeholder='Type a symbol or company name, then press Enter')
    if not query.strip():
        return None
    hits = search_companies(query)
    if hits.empty:
        st.warning(f'No company matches "{query}".')
        return None
    if len(hits) == 1 or hits.iloc[0]['Symbol'].lower() == query.strip().lower():
        return hits.iloc[0]  # one match, or an exact symbol: nothing to choose between
    # the key includes the query so each new search starts on its best match
    pick = st.selectbox('Did you mean (best match first)', hits['Label'].tolist(), key=f"{key}_pick_{query.strip().lower()}")
    return hits[hits['Label'] == pick].iloc[0]


st.title("📈 Stock Price Dashboard")
st.caption("by [haramrit singh khurana](https://haramrit09k.github.io)")

# Pick the starting company, range, comparison and view from the URL
# (?symbol=AAPL&compare=MSFT&range=1Y&view=learn) so views can be shared. Set at the start of every run
# for widgets that are not on screen in the current view; widgets that are on screen keep their own state.
if 'range' not in st.session_state:
    r = st.query_params.get('range')
    st.session_state.range = r if r in RANGES else '1Y'
if 'view' not in st.session_state:
    v = st.query_params.get('view', '').title()
    st.session_state.view = v if v in VIEWS else 'Price'
start_symbol = st.query_params.get('symbol')
start_symbol = start_symbol if start_symbol in symbols else 'AAPL'
start_compare = st.query_params.get('compare')
start_compare = start_compare if start_compare in symbols else ''

company = company_picker('Search for a company', 'company', start_symbol,
                         help="A ticker symbol is the short code a company trades under (AAPL for Apple). "
                              "You can search by symbol or by name.")
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

# ---- the always-visible header: what it is and today's numbers ----
latest = history.iloc[-1]
kind = ("An ETF (exchange-traded fund) holds many investments, such as the companies in an index, and trades "
        "like a single stock." if company['Type'] == 'ETF' else "A stock is a share in a single company.")
st.caption(f"{company['Exchange']} · {company['Type']} · "
           f"Latest trading day: {history.index[-1].strftime('%A, %B %d, %Y')}",
           help=f"Listed as: {company['Security Name']}. {kind}")

change = None
if len(history) > 1:
    change = latest['Close'] - history['Close'].iloc[-2]
    change_pct = change / history['Close'].iloc[-2] * 100

# prices on the first row, activity on the second, on one 4-column grid so everything lines up
price_cols = st.columns(4)
price_cols[0].metric("Close", f"${latest['Close']:,.2f}",
                     None if change is None else f"{change:+.2f} ({change_pct:+.2f}%)", help=HELP['close'])
price_cols[1].metric("Open", f"${latest['Open']:,.2f}", help=HELP['open'])
price_cols[2].metric("High", f"${latest['High']:,.2f}", help=HELP['high'])
price_cols[3].metric("Low", f"${latest['Low']:,.2f}", help=HELP['low'])
activity_cols = st.columns(4)
activity_cols[0].metric("Volume", compact(latest['Volume']),
                        help=f"{HELP['volume']} Exact number on this day: {latest['Volume']:,.0f}.")
activity_cols[1].metric("Dividends", f"${latest['Dividends']:,.2f}", help=HELP['dividends'])

# ---- one switch for the three kinds of content, so the first screen stays focused ----
view = st.segmented_control("View", VIEWS, key='view', label_visibility='collapsed') or 'Price'
if view == 'Price':
    st.query_params.pop('view', None)
else:
    st.query_params['view'] = view.lower()

# the chart range is shared by the Price and Learn views
if view == 'Price':
    range_choice = st.radio("Range", list(RANGES), horizontal=True, key='range', help=HELP['range'])
else:
    range_choice = st.session_state.range
days = RANGES[range_choice]
st.query_params['range'] = range_choice
window = history if days is None else history[history.index >= history.index[-1] - pd.Timedelta(days=days)]


def price_view():
    # optional second company; collapsed until someone wants it (or the link already has one)
    with st.expander("➕ Compare with another company",
                     expanded=bool(st.session_state.get('compare_query', start_compare))):
        other = company_picker('Company to compare', 'compare', start_compare, help=HELP['compare'])

    if other is not None and other['Symbol'] == company['Symbol']:
        st.info("Pick a different company to compare.")
        other = None
    elif other is not None:
        other_history = load_history(other['Symbol'])
        if other_history is None:
            other = None
        elif other_history.empty:
            st.warning(f"No price data found for {other['Symbol']}, so it can't be compared.")
            other = None

    if other is not None:
        # rebase both to 100 at the start so growth is comparable, using only the days both traded
        closes = pd.concat({company['Symbol']: history['Close'], other['Symbol']: other_history['Close']},
                           axis=1, sort=True)
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
        st.subheader(f"Growth of 100: {company['Symbol']} vs {other['Symbol']}", help=HELP['growth'])
        end = closes.iloc[-1] / closes.iloc[0] * 100
        st.caption(f"Both start at 100 on {closes.index[0].strftime('%b %d, %Y')}, so \\$100 in {company['Symbol']} "
                   f"would now be about \\${end[company['Symbol']]:,.0f} and \\$100 in {other['Symbol']} about "
                   f"\\${end[other['Symbol']]:,.0f}. Change over this range: "
                   f"{' · '.join(change_text(closes[c], c) for c in closes)}")
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
        title_col, toggle_col = st.columns([3, 2], vertical_alignment='center')
        title_col.subheader("Closing price (USD)", help=HELP['price_chart'])
        show_ma = toggle_col.toggle("Moving averages", key='ma', help=HELP['ma'])
        move = change_text(window['Close'])
        if move:
            st.caption(f"Change over this range: {move} "
                       f"({window.index[0].strftime('%b %d, %Y')} to {window.index[-1].strftime('%b %d, %Y')})")
        lines = pd.DataFrame({'Close': window['Close']})
        if show_ma:
            for n in (50, 200):
                lines[f'{n}-day average'] = history['Close'].rolling(n).mean().loc[window.index]
        data = lines.rename_axis('Date').reset_index().melt('Date', var_name='Line', value_name='Price').dropna()
        # let the y-axis fit the data instead of starting at 0, so price moves are visible
        price_chart = alt.Chart(data).mark_line().encode(
            x=alt.X('Date:T', title=None),
            y=alt.Y('Price:Q', scale=alt.Scale(zero=False), title=None),
            color=alt.Color('Line:N', title=None, legend=alt.Legend(orient='top') if show_ma else None,
                            scale=alt.Scale(domain=['Close', '50-day average', '200-day average'],
                                            range=['#0068c9', '#ff8c00', '#8e44ad'])),
            tooltip=[alt.Tooltip('Date:T'), 'Line:N', alt.Tooltip('Price:Q', format='$.2f')],
        )
        st.altair_chart(price_chart)
        if show_ma:
            where = []
            for n in (50, 200):
                avg = history['Close'].rolling(n).mean().iloc[-1]
                if pd.notna(avg):
                    pct = (latest['Close'] / avg - 1) * 100
                    where.append(f"{abs(pct):.1f}% {'above' if pct >= 0 else 'below'} its {n}-day average")
            if where:
                st.caption("The latest close is " + " and ".join(where) + ". Averages lag the price, so this "
                           "describes what has already happened, not what comes next.")

    st.subheader(f"{company['Symbol']} volume", help=HELP['volume_chart'])
    st.bar_chart(window['Volume'])


def learn_view():
    st.caption("Short explainers that use the company you're looking at. They describe how things work; "
               "they are not recommendations to buy or sell anything.")

    st.subheader("Reading this page")
    st.markdown("""
- **Open, High, Low, Close.** Each trading day has four prices: the first trade, the highest, the lowest and
  the last trade. Hover over the **?** next to any number for a short explanation.
- **Percent change.** Going from \\$100 to \\$133 is +33%. "Change over this range" compares the first and last
  day only; it says nothing about the ups and downs in between.
- **The chart's axis does not start at zero.** That makes trends easy to see but exaggerates small moves, so
  read the numbers on the axis, not just the shape of the line.
- **Growth of 100.** A \\$20 share and a \\$500 share can't be compared directly, so when you compare two companies
  both lines start at 100 on the same day: 150 means up 50% since then, 80 means down 20%. Comparing with a
  market fund such as SPY shows whether a stock did better or worse than the market.
- **Stock or ETF?** A stock is a share in one company. An ETF holds many investments, such as the 500 companies
  in the S&P 500, and trades like a single stock.
- **What a price chart can't tell you:** whether a company is well run or fairly priced. That takes things like
  earnings, debt and news. Past performance does not predict future results.
""")

    st.subheader("How people make decisions")
    st.markdown("Nobody can tell you what a price will do next. What people do is look at the same company "
                "through different lenses, and most mix several. Here are the main ones.")
    fundamental, technical, news, risk, mindset = st.tabs(
        ["Business value", "Price patterns", "News & economy", "Risk", "Mindset"])

    with fundamental:
        st.markdown("""
**The question:** what is this business worth, and is the price above or below that?

**What people look at:** growth in sales and profit, debt, cash flow, and how strong the competition is.
Also ratios such as **price-to-earnings (P/E)**: the share price divided by the profit per share, a rough
measure of how much investors pay for each \\$1 of profit.

**Usual time frame:** months to years.

**Limits:** "worth" is an estimate. Two analysts can read the same numbers and disagree, and a price can stay
far from any estimate for a long time.
""")
    with technical:
        st.markdown("""
**The question:** what have the price and trading volume been doing, and what might that say about what other
buyers and sellers will do next?

**What people look at:** trends, price levels where a stock has repeatedly paused (called *support* and
*resistance*), unusual volume, and moving averages. Switch on **Moving averages** in the Price view to see
two common ones.

**Names you'll hear:** a *golden cross* is when the short average (50-day) rises above the long one (200-day);
a *death cross* is the reverse. Both are widely watched.

**Limits:** moving averages use past prices, so they lag. Patterns are easy to spot in hindsight, and studies
of them show mixed results.
""")
    with news:
        st.markdown("""
**The question:** what is changing in the world that affects this company, or the whole market?

**What people look at:** earnings reports, interest-rate decisions, inflation, new regulation, product launches.

**Expectations matter:** prices tend to move on surprises. If everyone expected good news and it arrives, the
price can still fall.

**Limits:** by the time news is public, much of it may already be reflected in the price.
""")
    with risk:
        st.markdown("**How much could go wrong?** Many people treat this as important as what to hold. "
                    f"Here is what {company['Symbol']} did over {RANGE_WORDS[range_choice]} "
                    "(change the period with the Range control in the Price view):")
        stats = risk_summary(window['Close'])
        if stats:
            r1, r2, r3 = st.columns(3)
            r1.metric("Biggest fall", f"{stats['worst']:.0f}%", help=HELP['worst'])
            r2.metric("Rise needed to recover", f"+{stats['recover']:.0f}%" if 'recover' in stats else "None",
                      help=HELP['recover'])
            r3.metric("Typical daily move", f"±{stats['typical']:.1f}%", help=HELP['typical'])
            if 'low_date' in stats:
                st.caption(f"The biggest fall ran from a high on {stats['peak_date'].strftime('%b %d, %Y')} to a low on "
                           f"{stats['low_date'].strftime('%b %d, %Y')}.")
        st.markdown("""
Ideas people use to manage risk:
- **Diversification:** spreading money across many holdings so one bad result doesn't sink everything.
- **Position size:** how much of your money sits in a single holding.
- **An exit plan:** deciding in advance when you would sell, such as to limit a loss, or because the reason
  for holding no longer applies.
- **Time frame:** money you will need soon is in a different position from money you won't touch for years.
""")
    with mindset:
        st.markdown("""
Decisions are shaped by habits of thought as much as by numbers:
- **Loss aversion:** losses tend to feel worse than equal gains feel good, which can lead people to hold
  losers too long and sell winners too soon.
- **Fear of missing out:** buying because a price is rising and everyone is talking about it.
- **Recency bias:** assuming what just happened will keep happening.
- **Confirmation bias:** noticing only the information that agrees with what you already believe.

Many people choose low-cost, broad index funds partly to avoid having to make these calls. Research generally
finds that consistently beating the market is hard, especially after costs.
""")


if view == 'Price':
    price_view()
else:
    learn_view()

st.caption("For learning only, not financial advice. Prices come from Yahoo Finance and may be delayed or contain errors.")
