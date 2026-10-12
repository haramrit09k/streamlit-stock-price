# Stock Price Dashboard

A small Streamlit app for looking up the price history of ~11,700 US-listed stocks and ETFs.
Pick a company and see the latest trading day's figures, a closing-price chart with a
1M / 6M / 1Y / 5Y / Max range picker, and trading volume. Data comes from Yahoo Finance
via [yfinance](https://github.com/ranaroussi/yfinance).

- **Learn view:** plain-English explainers that use the company on screen: how to read the numbers and charts, and how people make decisions (business value, price patterns, news, risk, mindset), with live figures such as the biggest fall and the rise needed to recover from it. Hover the **?** icons for short explanations of each number.
- **Moving averages:** switch on the 50-day and 200-day averages on the price chart.
- **Search:** type a symbol or company name and press Enter; matches are ranked with exact symbols first.
- **Compare:** pick a second company to overlay both on one chart, rebased to 100 so growth is comparable.
- **Shareable links:** the URL keeps your selection, e.g. `?symbol=AAPL&compare=MSFT&range=5Y`, so you can send someone the exact view.

![Dashboard screenshot](screenshot.png)

### Run locally

```bash
pip install -r requirements.txt
streamlit run "Stock Price Dashboard.py"
```

### Updating the list of companies

`tickers.csv` is generated from Nasdaq's official symbol directories. To refresh it:

```bash
python scripts/update_tickers.py
```

### Python libraries used
- streamlit
- pandas
- yfinance
