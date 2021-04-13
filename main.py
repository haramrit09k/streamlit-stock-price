import yfinance as yf
import streamlit as st
import pandas as pd

tickers = pd.read_csv('tickers.csv')
symbols = tickers['Symbol'].to_list()
names = tickers['Company Name'].to_list()
result = list(symbols[i]+' - '+names[i] for i in range(len(names)))

st.write("""
# Simple Stock Price App
## {by haramrit singh khurana}
""")

# tickerSymbol = "GOOGL"
# tickerSymbol = st.text_input('Enter ticker')
tickerSymbol = st.selectbox('Enter ticker', result)

st.write("""
Shown are the stock closing price and volume of ** 
"""  + names[result.index(tickerSymbol)] + "**: ")

st.write("""
### Details:
- Company Name :
""",names[result.index(tickerSymbol)], """
- Symbol  :
""",symbols[result.index(tickerSymbol)], """
- Security Name  :
""",tickers['Security Name'][result.index(tickerSymbol)] , """
- Market Category  :
""",tickers['Market Category'][result.index(tickerSymbol)], """
- Test Issue  :
""",tickers['Test Issue'][result.index(tickerSymbol)] , """
- Financial Status  :
""",tickers['Financial Status'][result.index(tickerSymbol)], """
- Round Lot Size  :
""",tickers['Round Lot Size'][result.index(tickerSymbol)])

tickerData = yf.Ticker(symbols[result.index(tickerSymbol)])

tickerDf = tickerData.history(period='1d', start='2010-5-31', end='2020-5-31')

st.line_chart(tickerDf.Close)
st.line_chart(tickerDf.Volume)