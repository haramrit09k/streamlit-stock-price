import datetime as dt
import logging
import os
import re

import yfinance as yf
import streamlit as st
import pandas as pd
import altair as alt

import ai
import sec

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")  # no-op if already set up


st.set_page_config(page_title="Stock Price Dashboard", page_icon="📈", layout="centered")


log = logging.getLogger("stockdash")


@st.cache_resource(show_spinner=False)
def log_setup():
    """Runs once per server process (not on every page interaction): what is installed and what is switched on.
    Secrets are never logged; the SEC contact is only reported as set or not set."""
    import platform
    from importlib import metadata

    def version(package):
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return "NOT INSTALLED"
    log.info("Starting: python %s, streamlit %s, yfinance %s, pandas %s, anthropic %s", platform.python_version(),
             version("streamlit"), version("yfinance"), version("pandas"), version("anthropic"))
    log.info("Companies list: %d symbols loaded from tickers.csv", len(load_tickers()))
    log.info("Financials view: %s", "on (SEC_USER_AGENT is set)" if sec.configured() else "off (SEC_USER_AGENT is not set)")
    log.info("AI summaries: %s", ai.describe_setup())



RANGES = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 365 * 5, "Max": None}
# The Financials view needs the SEC_USER_AGENT environment variable (see sec.py); without it the view is hidden.
VIEWS = ["Price", "News", "Financials", "Learn"] if sec.configured() else ["Price", "News", "Learn"]
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
    "revenue": "Everything the company sold during the year, before any costs are taken out. Also called sales.",
    "net_income": "What is left after all costs, interest and taxes: the company's profit for the year. "
                  "A negative number is a loss.",
    "eps": "Diluted earnings per share: net income divided by the number of shares, counting shares that could "
           "be created from options and similar. It is the profit \"per share\".",
    "margin": "Net income as a percentage of revenue: how much of each dollar of sales the company kept as profit.",
    "cash_flow": "Cash the business generated from its operations. It can differ from profit, for example when "
                 "customers pay late.",
    "compare": "Overlay a second company or fund. Comparing helps separate a company's own performance from "
               "the market's: try SPY, an ETF that tracks the S&P 500 (about 500 large US companies).",
}

# Kinds of news, matched in order against the headline. Each: label, pattern, what it is, questions people ask.
NEWS_KINDS = [
    ("Analyst opinion",
     r"\b(price target|upgrades?|downgrades?|analysts?|rating|initiates|maintains|reiterates"
     r"|outperform|underperform)\b",
     "An analyst's view, not a fact. Analysts often disagree, and targets are often revised after the price has "
     "already moved.",
     ["Is the target above or below today's price, and by how much?",
      "Has this analyst changed their view, or just repeated it?",
      "Did the price already move before the note came out?"]),
    ("Earnings & results",
     r"\b(earnings|quarterly|q[1-4]|guidance|outlook|results)\b",
     "Companies report their results every three months. Prices often move on whether the results beat or miss "
     "what analysts expected, not on the results alone.",
     ["Did the results beat or miss what was expected?",
      "What does the company say about the next quarter or year (its \"guidance\")?",
      "Is any gain a one-off, or does it look repeatable?"]),
    ("Deal or partnership",
     r"\b(acquires?|acquired|acquisition|merger|buyout|takeover|stake|partnership)\b",
     "A company buying, selling, investing in or partnering with another. The announced benefits are the "
     "company's own account of it.",
     ["How big is the deal compared with the company?",
      "Is it paid for with cash, new shares or debt?",
      "Does it need approval from regulators, and could it fall through?"]),
    ("Legal & regulatory",
     r"\b(lawsuit|sues?|sued|probe|investigation|antitrust|fines?|fined|regulators?|ruling|settlement)\b",
     "Legal and regulatory events can take years to play out, and early headlines often change as facts emerge.",
     ["How large could the cost be compared with the company's size?",
      "Is it a one-off, or part of a pattern?",
      "How far along is it: an allegation, a ruling, or a settlement?"]),
    ("Leadership",
     r"\b(steps? down|stepping (?:down|aside)|resign\w*|appoint\w*|successor|transition|names? new (?:ceo|cfo))\b",
     "A change in who runs the company. Planned handovers and sudden exits tend to mean different things.",
     ["Was it planned, or sudden?",
      "Who takes over, and what is their track record?",
      "What reason did the company give?"]),
]
ROUNDUP = ("Market roundup",
           "Mentions many companies at once, so this one may be a small part of the story.",
           ["How much of it is actually about this company?",
            "Is it reporting something that happened, or listing ideas?"])
OTHER_NEWS = ("General news", "News that doesn't fit a common type.",
              ["What exactly happened, and what is just commentary?"])
ANY_NEWS_QUESTIONS = ["Is this new information, or already widely known?",
                      "Is it a fact (something happened) or an opinion (someone thinks)?",
                      "How big is it compared with the whole company?",
                      "Does it change the company's future, or only today's mood?"]


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
        log.info("Yahoo has no price data for %s (delisted, or not a symbol Yahoo knows)", symbol)
        return pd.DataFrame()
    except Exception as error:
        log.warning("Yahoo price history FAILED for %s: %s: %s", symbol, type(error).__name__, str(error)[:200])
        st.error("Couldn't reach Yahoo Finance right now. Please try again in a minute.")
        return None


def change_text(series, symbol=None):
    """Percent change from the first to the last value, coloured green/red (None if not enough data)."""
    if len(series) < 2 or series.iloc[0] == 0:
        return None
    pct = (series.iloc[-1] / series.iloc[0] - 1) * 100
    colour = 'green' if pct >= 0 else 'red'
    return f"{symbol + ' ' if symbol else ''}:{colour}[{pct:+,.1f}%]"


class NoNews(Exception):
    pass


@st.cache_data(ttl=900)
def _download_news(symbol):
    items = yf.Search(symbol, news_count=20).news
    # keep headlines that mention this company, newest first
    items = sorted((n for n in items if symbol in (n.get('relatedTickers') or [])),
                   key=lambda n: n['providerPublishTime'], reverse=True)
    if not items:
        raise NoNews(symbol)  # raising keeps an empty or failed reply out of the cache
    return items[:8]


def load_news(symbol):
    """Recent headlines; an empty list if there are none; None if Yahoo could not be reached."""
    try:
        return _download_news(symbol)
    except NoNews:
        log.info("Yahoo returned no headlines that mention %s", symbol)
        return []
    except Exception as error:
        log.warning("Yahoo news FAILED for %s: %s: %s", symbol, type(error).__name__, str(error)[:200])
        return None


def md_escape(text):
    """Headlines are untrusted text: stop them turning into markdown or math."""
    return re.sub(r"([\\`*_{}\[\]()#+!|$<>~])", r"\\\1", text)


def time_ago(timestamp):
    then = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
    minutes = int((dt.datetime.now(dt.timezone.utc) - then).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 1)}m ago"
    if minutes < 24 * 60:
        return f"{minutes // 60}h ago"
    if minutes < 7 * 24 * 60:
        return f"{minutes // (24 * 60)}d ago"
    return then.strftime('%b %d')


def news_kind(item):
    """(label, what it is, questions) for a headline."""
    if len(item.get('relatedTickers') or []) >= 4:
        return ROUNDUP
    for label, pattern, what, questions in NEWS_KINDS:
        if re.search(pattern, item['title'], re.IGNORECASE):
            return label, what, questions
    return OTHER_NEWS


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
log_setup()


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


@st.cache_data(ttl=86400)
def sec_ciks():
    return sec.ticker_map()


@st.cache_data(ttl=6 * 3600)
def sec_financials(cik):
    return sec.annual_financials(cik)  # None (cached) means the SEC has no data; failures raise and are not cached


@st.cache_data(ttl=3600)
def sec_filings(cik):
    return sec.recent_filings(cik)


def money(value, unit_prefix=''):
    """391040000000 -> '$391.0B'"""
    sign = '-' if value < 0 else ''
    value = abs(value)
    for suffix, size in (('B', 1e9), ('M', 1e6), ('K', 1e3)):
        if value >= size:
            return f"{sign}{unit_prefix}${value / size:,.1f}{suffix}"
    return f"{sign}{unit_prefix}${value:,.0f}"


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


AI_SESSION_LIMIT = _int_env('AI_SESSION_LIMIT', 3)  # summaries one visitor can ask for per visit
AI_MESSAGES = {'budget': "The daily limit for AI summaries has been reached.",
               'refused': "The AI couldn't summarise these headlines.",
               'too_long': "The AI summary didn't finish.",
               'bad_output': "The AI summary came back in an unusable form.",
               'error': "The AI summary isn't available right now."}


@st.cache_data(ttl=3600, show_spinner=False)
def ai_summary(symbol, name, headlines):
    """Cached per set of headlines, so repeat clicks (by anyone) cost nothing. Failures raise and are not cached."""
    return ai.summarise(symbol, name, list(headlines))


def show_ai_summary(result, items):
    def cites(numbers):
        links = [f"[{n}]({items[n - 1]['link']})" if items[n - 1].get('link', '').startswith('https://') else str(n)
                 for n in numbers]
        return f" ({', '.join(links)})"

    bull, bear = st.columns(2)
    for column, title, key in ((bull, "🐂 What bulls are saying", 'bull'), (bear, "🐻 What bears are saying", 'bear')):
        with column.container(border=True):
            st.markdown(f"**{title}**")
            if not result[key]:
                st.markdown(":gray[The headlines don't make a clear case for this side.]")
            for point in result[key]:
                st.markdown(f"- {md_escape(point['point'])}{cites(point['headlines'])}")
    if result['unclear']:
        st.markdown(f"**What the headlines don't tell us:** {md_escape(result['unclear'])}")
    st.caption("Written by an AI from the headlines above only, so it can miss context or be wrong. It describes "
               "arguments; it is not advice. The numbers in brackets link to the headlines it used.")


def dollars(value):
    """-7.42 -> '-$7.42'"""
    return f"{'-' if value < 0 else ''}${abs(value):,.2f}"


def financials_view():
    try:
        cik = sec_ciks().get(company['Symbol'])
        table = sec_financials(cik) if cik else None
    except Exception as error:
        log.warning("SEC financials FAILED for %s: %s", company['Symbol'], sec.explain(error))
        st.error("Couldn't load data from the SEC right now. Please try again in a minute.")
        return
    if table is None:
        log.info("SEC has no financial data for %s (%s)", company['Symbol'],
                 "not in the SEC's company list" if not cik else f"CIK {cik}: a fund or a filer without US-GAAP data")
        st.info(f"The SEC's financial data isn't available for {company['Symbol']}. Funds such as ETFs, and many "
                "companies based outside the US, file different reports.")
        return

    st.caption(f"Figures from the annual reports (10-K) that {company['Company Name']} files with the SEC, in US "
               "dollars. They are shown as reported, without adjustment.")
    last = table.iloc[-1]
    st.markdown(f"**Fiscal year ended {table.index[-1].strftime('%B %d, %Y')}**")
    cols = st.columns(3)
    if 'Revenue' in table:
        growth = last.get('Revenue growth')
        cols[0].metric("Revenue", money(last['Revenue']), None if pd.isna(growth) else f"{growth:+.1f}% vs year before",
                       help=HELP['revenue'])
    if 'Net income' in table:
        margin = last.get('Net margin')
        cols[1].metric("Net income", money(last['Net income']),
                       None if pd.isna(margin) else f"{margin:.1f}% of revenue", delta_color='off', help=HELP['net_income'])
    if 'Diluted EPS' in table and pd.notna(last['Diluted EPS']):
        cols[2].metric("Earnings per share", dollars(last['Diluted EPS']), help=HELP['eps'])

    chart_columns = [c for c in ('Revenue', 'Net income') if c in table]
    if chart_columns:
        big = table[chart_columns].abs().max().max() >= 1e9
        divisor, unit = (1e9, 'B') if big else (1e6, 'M')
        st.subheader("Year by year")
        bars = (table[chart_columns] / divisor).rename_axis('Year').reset_index().melt(
            'Year', var_name='Line', value_name='Amount')
        bars['Year'] = bars['Year'].dt.strftime('%Y')
        st.altair_chart(alt.Chart(bars).mark_bar().encode(
            x=alt.X('Year:N', title=None, axis=alt.Axis(labelAngle=0)),
            xOffset='Line:N',
            y=alt.Y('Amount:Q', title=f"US$ {'billions' if big else 'millions'}"),
            color=alt.Color('Line:N', title=None, scale=alt.Scale(domain=['Revenue', 'Net income'],
                                                                 range=['#8ec5ff', '#0068c9'])),
            tooltip=['Year:N', 'Line:N', alt.Tooltip('Amount:Q', format=',.1f', title=f"US${unit}")],
        ))

    with st.expander("All the figures, and what each line means"):
        shown = table.rename_axis('Fiscal year end')
        shown.index = shown.index.strftime('%b %d, %Y')
        formatted = pd.DataFrame(index=shown.index)
        for column in shown:
            if column in ('Net margin', 'Revenue growth'):
                formatted[column] = shown[column].map(lambda v: '' if pd.isna(v) else f"{v:+.1f}%" if column == 'Revenue growth' else f"{v:.1f}%")
            elif column == 'Diluted EPS':
                formatted[column] = shown[column].map(lambda v: '' if pd.isna(v) else dollars(v))
            else:
                formatted[column] = shown[column].map(lambda v: '' if pd.isna(v) else money(v))
        st.dataframe(formatted.T)
        st.markdown(f"""
- **Revenue:** {HELP['revenue']}
- **Net income:** {HELP['net_income']}
- **Diluted EPS:** {HELP['eps']}
- **Operating cash flow:** {HELP['cash_flow']}
- **Net margin:** {HELP['margin']}
- **Revenue growth:** how much revenue changed compared with the year before.
""")

    st.subheader("Recent filings")
    try:
        filings = sec_filings(cik)
    except Exception as error:
        log.warning("SEC filings list FAILED for %s: %s", company['Symbol'], sec.explain(error))
        filings = []
        st.caption("Couldn't load the list of filings right now.")
    for item in filings:
        about = f" · about {item['about']}" if item['about'] else ''
        st.markdown(f"[{item['form']} · {item['label']}]({item['url']})  \n"
                    f":gray[Filed {pd.Timestamp(item['date']).strftime('%b %d, %Y')}{about}]")
    st.markdown(f"[All of {company['Symbol']}'s filings on SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar?"
                f"action=getcompany&CIK={cik}&owner=include&count=40)")
    st.caption("Open a filing to read the original. The Learn view explains what each part means.")


def news_view():
    st.caption(f"Recent headlines that mention {company['Symbol']}, from Yahoo Finance. A headline is a "
               "starting point, not a conclusion.")
    items = load_news(company['Symbol'])
    if items is None:
        st.error("Couldn't load headlines from Yahoo Finance right now. Please try again in a minute.")
        return
    if not items:
        st.info(f"No recent headlines found for {company['Symbol']}.")
        return

    for number, item in enumerate(items, 1):
        title = md_escape(item['title'])
        link = item.get('link', '')
        headline = f"[{title}]({link})" if link.startswith('https://') else title
        # headline and its source line in one block, so they read as a single item; numbered so summaries can cite them
        st.markdown(f"{number}. {headline}  \n:gray[{md_escape(item.get('publisher', 'Unknown source'))} · "
                    f"{time_ago(item['providerPublishTime'])} · {news_kind(item)[0]}]")

    # optional AI summary of what each side is saying, only when a key is configured and someone asks for it
    shown_ai, ai_note = False, None
    if ai.configured():
        st.subheader("What bulls and bears are saying")
        st.caption("An AI reads the headlines above and sums up the arguments each side could make, citing the "
                   "headlines it used. It sees only these headlines, so it can't know more than they say.")
        headlines = tuple((i['title'], i.get('publisher', '')) for i in items)
        saved_key = f"ai_{company['Symbol']}"
        if st.button("Summarise the headlines", key=f"ai_button_{company['Symbol']}"):
            if st.session_state.get('ai_used', 0) >= AI_SESSION_LIMIT:
                log.info("AI summary: %s requested but this visitor has used all %d summaries for the visit "
                         "(AI_SESSION_LIMIT)", company['Symbol'], AI_SESSION_LIMIT)
                ai_note = "You've used all the AI summaries for this visit."
            else:
                st.session_state['ai_used'] = st.session_state.get('ai_used', 0) + 1
                calls_before = ai.fresh_calls
                try:
                    with st.spinner("Reading the headlines..."):
                        st.session_state[saved_key] = {'headlines': headlines,
                                                       'result': ai_summary(company['Symbol'], company['Company Name'], headlines)}
                    if ai.fresh_calls == calls_before:
                        log.info("AI summary: served %s from the cache (no model call, nothing counted)", company['Symbol'])
                except ai.AiUnavailable as unavailable:
                    log.info("AI summary: shown to the visitor as unavailable (%s) for %s; see the lines above for why",
                             unavailable.reason, company['Symbol'])
                    ai_note = AI_MESSAGES.get(unavailable.reason, AI_MESSAGES['error'])
        saved = st.session_state.get(saved_key)
        if ai_note:
            st.info(ai_note if saved and saved['headlines'] == headlines else
                    f"{ai_note} Here is a hand-written example of reading a headline both ways instead.")
        if saved and saved['headlines'] == headlines:
            show_ai_summary(saved['result'], items)
            shown_ai = True

    st.subheader("Read it both ways")
    st.markdown("The same headline can support opposite conclusions." +
                ("" if shown_ai else " Here is an illustration with a made-up company:"))
    with st.expander("Example with a made-up company", expanded=not shown_ai):
        with st.container(border=True):
            st.markdown("**Acme Corp beats earnings estimates but lowers its full-year outlook**")
            bull, bear = st.columns(2)
            bull.markdown("**🐂 A positive reading**\n\nResults beat expectations, so the business is doing well "
                          "right now. Companies sometimes set a cautious outlook so they can beat it later. If the "
                          "price had already fallen, the bad news may already be reflected in it.")
            bear.markdown("**🐻 A negative reading**\n\nManagement knows the business better than anyone, so a lower "
                          "outlook suggests slower sales or rising costs ahead. This quarter may be as good as it "
                          "gets, and markets tend to care more about the future than the past.")
        st.caption("Neither reading is \"right\". What helps is the questions: how far below expectations is the new "
                   "outlook, is the cause a one-off or lasting, and how did the price react?")

    st.subheader("Try it on a real headline")
    pick = st.selectbox("Pick a headline", range(len(items)), key=f"news_pick_{company['Symbol']}",
                        format_func=lambda i: items[i]['title'][:100])
    label, what, questions = news_kind(items[pick])
    with st.container(border=True):
        st.markdown(f"**Topic (guessed from the wording): {label}.** {md_escape(what)}")
        st.markdown("**Questions people ask about this topic:**\n" + "\n".join(f"- {q}" for q in questions))
        st.markdown("**Questions for any headline:**\n" + "\n".join(f"- {q}" for q in ANY_NEWS_QUESTIONS))
    st.caption("Try writing down one reason someone could read it positively and one negatively, and what "
               "would change your mind. There is no single right answer.")


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

    st.subheader("Reading company reports")
    st.markdown("Companies publish far more than a share price. These guides cover the main documents and what "
                "to look at first.")
    if 'Financials' in VIEWS:
        st.markdown("The **Financials** view shows this company's real figures and its latest filings.")
    if company['Type'] == 'Stock':
        st.markdown(f"See {company['Symbol']}'s real filings on "
                    f"[SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                    f"&CIK={company['Symbol']}&owner=include&count=40), the SEC's free public database. "
                    "Companies based outside the US usually file different forms (such as a 20-F in place of "
                    "a 10-K).")
    else:
        st.markdown(f"{company['Symbol']} is an ETF. ETFs publish different documents from companies, mainly a "
                    "prospectus and regular fund reports, so the guides below apply to the companies it holds.")
    with st.expander("The annual report (10-K)"):
        st.markdown("""
Filed once a year with the SEC by US-listed companies, and audited. Four parts are worth knowing:
- **Business:** what the company does and how it makes money. Start here.
- **Risk Factors:** what could go wrong, in the company's own words. Much of it is standard wording, so the
  useful part is what is *new* compared with last year.
- **Management's Discussion (MD&A):** management explaining *why* the numbers changed. Often the most readable part.
- **Financial Statements and notes:** the numbers themselves (see below) and the fine print on debt and unusual items.
""")
    with st.expander("The quarterly report (10-Q) and the 8-K"):
        st.markdown("""
- **10-Q:** a shorter, unaudited update filed after each of the first three quarters. It uses the same
  statements as the 10-K. Compare a quarter with the *same quarter last year*, because many businesses have
  busy and quiet seasons.
- **8-K:** a short notice filed within days of an important event, such as results, a new CEO, or an acquisition.
  Results are usually attached as a press release.
""")
    with st.expander("The three financial statements"):
        st.markdown("""
- **Income statement:** what happened *over a period*. Sales (revenue), minus costs, leaves profit (net income).
  Look at whether sales and profit are growing, and whether profit is growing as fast as sales.
- **Balance sheet:** a snapshot of one day. What the company owns (assets) and what it owes (liabilities); the
  difference is the owners' share. Look at how much debt there is compared with cash.
- **Cash flow statement:** the cash that actually moved in and out. A company can report a profit and still run
  short of cash, which is why this statement is read alongside the income statement.
""")
    with st.expander("The earnings call"):
        st.markdown("""
After each quarter's results, management usually hosts a call for analysts. Recordings or transcripts are
normally on the company's investor-relations website.
- **Prepared remarks** come first: polished, and management's own account of the quarter.
- **The Q&A** follows, and is less scripted. Many people pay most attention to what analysts keep asking about,
  and to which questions get a direct answer.
- **Things listeners watch:** any change to guidance, which measures management talks about more or less than
  before, and how this call compares with the last one.

A call is a source of information, not an independent check: management is presenting its own view.
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

The **News** view has live headlines and an example of reading one both ways.
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
elif view == 'News':
    news_view()
elif view == 'Financials':
    financials_view()
else:
    learn_view()

st.caption("For learning only, not financial advice. Prices come from Yahoo Finance and may be delayed or contain errors.")
