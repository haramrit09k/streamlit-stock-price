"""Rebuild tickers.csv from Nasdaq's official symbol directories.

    python scripts/update_tickers.py

Sources (updated daily by Nasdaq Trader):
  https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt   (Nasdaq-listed)
  https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt    (NYSE, NYSE Arca, NYSE American, Cboe, ...)

Keeps common stocks, ADRs and ETFs. Drops test issues, warrants, rights, SPAC units, preferreds
and debt. Symbols use Yahoo Finance's style (BRK.B -> BRK-B) because that is
what yfinance expects.
"""
import io
import re
import urllib.request

import pandas as pd

BASE = "https://www.nasdaqtrader.com/dynamic/SymDir/"
OUT = "tickers.csv"

NASDAQ_TIERS = {"Q": "Nasdaq Global Select", "G": "Nasdaq Global Market", "S": "Nasdaq Capital Market"}
OTHER_EXCHANGES = {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX",
                   "V": "IEX", "M": "NYSE Chicago", "F": "TXSE"}

# security names that are not plain shares of a company or fund
NOT_SHARES = re.compile(
    r"\bWarrants?\b|\bRights?\b|\bUnits,|- Units$|(?<!Common )Units$|Preferred|Cumulative"
    r"|\bNotes?\b|\bDebentures?\b|\d%|\bSubordinated\b|\bSenior\b|Trust Securities|Capital Securities"
)
# symbol suffixes for units / warrants / rights (class shares like BRK.B are a single letter and are kept)
NOT_COMMON_SUFFIX = re.compile(r"\.(?:U|UN|W|WS|WT|R|RT|RW|WI)$")
# trailing description of the share class, e.g. "Agilent Technologies, Inc. Common Stock"
SHARE_CLASS_TAIL = re.compile(
    r"\s+(Class [A-Z]\s+)?(Common Stock|Ordinary Shares?|Common Shares?|Common Units?|Capital Stock"
    r"|American Depositary (Shares|Receipts?)|Depositary Shares|Shares of Beneficial Interest)\b.*$",
    re.IGNORECASE,
)


def fetch(name):
    with urllib.request.urlopen(BASE + name, timeout=60) as response:
        text = response.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(text), sep="|", dtype=str, keep_default_na=False)
    return df[~df.iloc[:, 0].str.startswith("File Creation Time")]


def company_name(security_name, is_etf):
    if is_etf:
        return security_name.strip()
    name = security_name.split(" - ")[0]
    return SHARE_CLASS_TAIL.sub("", name).strip()


def build():
    nasdaq = fetch("nasdaqlisted.txt")
    other = fetch("otherlisted.txt")

    a = pd.DataFrame({
        "Symbol": nasdaq["Symbol"],
        "Security Name": nasdaq["Security Name"],
        "Exchange": nasdaq["Market Category"].map(NASDAQ_TIERS).fillna("Nasdaq"),
        "ETF": nasdaq["ETF"],
        "Test Issue": nasdaq["Test Issue"],
    })
    b = pd.DataFrame({
        "Symbol": other["ACT Symbol"],
        "Security Name": other["Security Name"],
        "Exchange": other["Exchange"].map(OTHER_EXCHANGES).fillna(other["Exchange"]),
        "ETF": other["ETF"],
        "Test Issue": other["Test Issue"],
    })
    df = pd.concat([a, b], ignore_index=True)
    raw = len(df)

    df = df[df["Test Issue"] != "Y"]
    df = df[~df["Symbol"].str.contains(r"\$")]
    df = df[~df["Symbol"].str.contains(NOT_COMMON_SUFFIX)]
    df = df[~df["Security Name"].str.contains(NOT_SHARES)]

    df["Security Name"] = df["Security Name"].str.strip()
    df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)
    df["Type"] = df["ETF"].map({"Y": "ETF"}).fillna("Stock")
    df["Company Name"] = [company_name(n, t == "ETF") for n, t in zip(df["Security Name"], df["Type"])]

    df = df.drop_duplicates("Symbol").sort_values("Symbol")
    print(f"{raw} listed -> {len(df)} kept ({(df['Type'] == 'ETF').sum()} ETFs)")
    return df[["Symbol", "Company Name", "Security Name", "Exchange", "Type"]]


if __name__ == "__main__":
    build().to_csv(OUT, index=False)
    print(f"wrote {OUT}")
