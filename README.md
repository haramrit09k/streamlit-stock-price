# Stock Price Dashboard

A small Streamlit app for looking up the price history of ~3,000 US-listed companies.
Pick a company and see the latest trading day's figures, a closing-price chart with a
1M / 6M / 1Y / 5Y / Max range picker, and trading volume. Data comes from Yahoo Finance
via [yfinance](https://github.com/ranaroussi/yfinance).

- **Compare:** pick a second company to overlay both on one chart, rebased to 100 so growth is comparable.
- **Shareable links:** the URL keeps your selection, e.g. `?symbol=AAPL&compare=MSFT&range=5Y`, so you can send someone the exact view.

![Dashboard screenshot](screenshot.png)

### Run locally

```bash
pip install -r requirements.txt
streamlit run "Stock Price Dashboard.py"
```

### Python libraries used
- streamlit
- pandas
- yfinance
