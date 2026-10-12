"""Company financials and filings from the SEC's free EDGAR APIs.

The SEC requires every program that calls it to identify itself, so set the SEC_USER_AGENT environment
variable to something like  "My Dashboard me@example.com"  (a name and a contact address). Without it,
configured() is False and the app hides the Financials view.

The functions take a `fetch` argument (url -> parsed JSON) so they can be tested without the network.
"""
import json
import os
import urllib.error
import urllib.request

import pandas as pd

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

# (label, XBRL concepts in order of preference, unit). Companies use different concept names for revenue.
METRICS = [
    ("Revenue", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                 "RevenueFromContractWithCustomerIncludingAssessedTax"], "USD"),
    ("Net income", ["NetIncomeLoss"], "USD"),
    ("Diluted EPS", ["EarningsPerShareDiluted"], "USD/shares"),
    ("Operating cash flow", ["NetCashProvidedByUsedInOperatingActivities"], "USD"),
]

FORM_LABELS = {
    "10-K": "Annual report", "10-K/A": "Annual report (amended)",
    "10-Q": "Quarterly report", "10-Q/A": "Quarterly report (amended)",
    "8-K": "Current report (an event or results)",
    "20-F": "Annual report (foreign company)", "6-K": "Update (foreign company)",
}
# the most common 8-K item numbers, in plain words
ITEM_LABELS = {
    "1.01": "a material agreement", "1.02": "an agreement ended", "2.01": "an acquisition or sale completed",
    "2.02": "results of operations", "2.03": "new debt", "3.02": "shares sold", "5.02": "a leadership change",
    "5.07": "shareholder vote results", "7.01": "a public disclosure", "8.01": "other events",
}


def user_agent():
    return os.environ.get("SEC_USER_AGENT", "").strip()


def configured():
    return bool(user_agent())


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent(), "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def ticker_map(fetch=fetch_json):
    """{ticker: cik} for every company the SEC lists."""
    return {row["ticker"]: int(row["cik_str"]) for row in fetch(TICKERS_URL).values()}


def annual_financials(cik, fetch=fetch_json, years=5):
    """One row per fiscal year (index = fiscal year end) with the METRICS columns that exist for the company,
    plus 'Net margin' and 'Revenue growth' in percent. None if the company has no US-GAAP annual data (funds,
    many foreign filers). Network failures raise."""
    try:
        gaap = fetch(FACTS_URL.format(cik=cik))["facts"]["us-gaap"]
    except KeyError:  # no US-GAAP facts: funds, many foreign companies
        return None
    except urllib.error.HTTPError as error:
        if error.code == 404:  # the SEC has no financial data for this filer
            return None
        raise  # anything else (rate limit, outage) is a failure, not "no data"
    columns = {}
    for label, concepts, unit in METRICS:
        values = {}  # fiscal year end -> value
        for concept in concepts:  # an earlier concept in the list wins for the same year
            latest = {}  # fiscal year end -> (filed date, value); a later filing (e.g. a restatement) replaces an earlier one
            for entry in gaap.get(concept, {}).get("units", {}).get(unit, []):
                if not entry.get("form", "").startswith("10-K") or "start" not in entry:
                    continue
                days = (pd.Timestamp(entry["end"]) - pd.Timestamp(entry["start"])).days
                if 350 <= days <= 380 and (entry["end"] not in latest or entry["filed"] > latest[entry["end"]][0]):
                    latest[entry["end"]] = (entry["filed"], entry["val"])
            for end, (_, value) in latest.items():
                values.setdefault(end, value)
        if values:
            columns[label] = values
    if "Revenue" not in columns and "Net income" not in columns:
        return None
    table = pd.DataFrame(columns).sort_index().tail(years)
    table.index = pd.to_datetime(table.index)
    if "Revenue" in table and "Net income" in table:
        table["Net margin"] = table["Net income"] / table["Revenue"] * 100
    if "Revenue" in table:
        table["Revenue growth"] = table["Revenue"].pct_change() * 100
    return table


def recent_filings(cik, fetch=fetch_json, limit=8):
    """The latest annual and quarterly reports and 8-Ks: dicts with form, label, date, about and url."""
    recent = fetch(SUBMISSIONS_URL.format(cik=cik))["filings"]["recent"]
    out = []
    for i, form in enumerate(recent["form"]):
        if form not in FORM_LABELS:
            continue
        items = [ITEM_LABELS[n] for n in recent["items"][i].split(",") if n in ITEM_LABELS]
        out.append({
            "form": form,
            "label": FORM_LABELS[form],
            "date": recent["filingDate"][i],
            "about": ", ".join(items),
            "url": DOCUMENT_URL.format(cik=cik, accession=recent["accessionNumber"][i].replace("-", ""),
                                       document=recent["primaryDocument"][i]),
        })
        if len(out) == limit:
            break
    return out


def explain(error):
    """A one-line, secret-free description of a failed SEC request, with what to check. (The User-Agent value,
    which contains a contact address, is never included.)"""
    if isinstance(error, urllib.error.HTTPError):
        hint = {403: "the SEC rejects requests without a proper SEC_USER_AGENT (a project name plus a contact address)",
                429: "rate limited: too many requests too quickly",
                404: "the SEC has no such record"}.get(error.code, "unexpected response")
        return f"HTTP {error.code} from {error.url}: {hint}"
    return f"{type(error).__name__}: {str(error)[:200]}"
