import yfinance as yf
import streamlit as st
import pandas as pd
from datetime import date

# concatenate names and symbols and store in another list
# which will be used for populating the selection box
tickers = pd.read_csv('tickers.csv')
symbols = tickers['Symbol'].to_list()
names = tickers['Company Name'].to_list()
result = list(symbols[i]+' - '+names[i] for i in range(len(names)))

# get today's date
today = date.today()
d1 = today.strftime("%A, %B %d, %Y") # YYYY-mm-dd

st.write("""
# Simple Stock Price App
## { by haramrit singh khurana }
""")

# tickerSymbol = "GOOGL"
# tickerSymbol = st.text_input('Enter ticker')
tickerSymbol = st.selectbox('Select company', result)

tickerData = yf.Ticker(symbols[result.index(tickerSymbol)])

tickerDf = tickerData.history(period='max')
tickerDfToday = tickerData.history(period='1d')

if tickerDfToday.empty:
    df2 = {'Open': ['No data found'], 'Close': ['No data found'], 'High': ['No data found'], 'Low': ['No data found'], 'Volume': ['No data found'], 'Dividends': ['No data found']}
    tickerDfToday = df2
    
st.text(tickerDfToday)

st.write("""
### """ + symbols[result.index(tickerSymbol)] + """
#### """ + names[result.index(tickerSymbol)])

# display today's prices
st.write("""
### Today (""",d1,"""):
- Opening Price :
""",tickerDfToday['Open'][0], """
- Closing Price  :
""",tickerDfToday['Close'][0], """
- High  :
""",tickerDfToday['High'][0] , """
- Low  :
""",tickerDfToday['Low'][0], """
- Volume  :
""",tickerDfToday['Volume'][0] , """
- Dividends  :
""",tickerDfToday['Dividends'][0])

# display company details
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
""",tickers['Financial Status'][result.index(tickerSymbol)])

st.line_chart(tickerDf.High)
st.line_chart(tickerDf.Low)

st.line_chart(tickerDf.Open)
st.line_chart(tickerDf.Close)

st.line_chart(tickerDf.Volume)
st.line_chart(tickerDf.Dividends)

# st.line_chart(tickerDf.Stock)
st.line_chart(tickerDf['Stock Splits'])
