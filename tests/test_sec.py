"""Tests for sec.py with canned SEC responses (no network).  Run:  python -m pytest tests"""
import io
import os
import sys
import urllib.error

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sec  # noqa: E402


def fact(start, end, val, filed, form="10-K"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def facts(**concepts):
    return {"facts": {"us-gaap": {name: {"units": {unit: entries}} for name, (unit, entries) in concepts.items()}}}


def fetch_returning(data):
    return lambda url: data


def test_annual_values_only_not_quarters_or_other_forms():
    data = facts(Revenues=("USD", [
        fact("2024-01-01", "2024-12-31", 100, "2025-02-01"),                 # full year: kept
        fact("2024-10-01", "2024-12-31", 30, "2025-02-01"),                  # one quarter: ignored
        fact("2025-01-01", "2025-03-31", 25, "2025-05-01", form="10-Q"),     # a 10-Q: ignored
    ]), NetIncomeLoss=("USD", [fact("2024-01-01", "2024-12-31", 10, "2025-02-01")]))
    table = sec.annual_financials(1, fetch_returning(data))
    assert list(table["Revenue"]) == [100] and list(table["Net income"]) == [10]
    assert table["Net margin"].iloc[0] == pytest.approx(10.0)


def test_a_later_filing_replaces_an_earlier_one_for_the_same_year():
    data = facts(Revenues=("USD", [fact("2024-01-01", "2024-12-31", 100, "2025-02-01"),
                                   fact("2024-01-01", "2024-12-31", 105, "2026-02-01")]))  # restated
    assert sec.annual_financials(1, fetch_returning(data))["Revenue"].iloc[0] == 105


def test_revenue_concepts_are_tried_in_order_and_merged_across_years():
    data = facts(
        RevenueFromContractWithCustomerExcludingAssessedTax=("USD", [fact("2024-01-01", "2024-12-31", 200, "2025-02-01")]),
        Revenues=("USD", [fact("2023-01-01", "2023-12-31", 150, "2024-02-01"),
                          fact("2024-01-01", "2024-12-31", 999, "2025-02-01")]))  # older concept name for 2023 only
    table = sec.annual_financials(1, fetch_returning(data))
    assert list(table["Revenue"]) == [150, 200]  # 2024 comes from the preferred concept, 2023 from the other
    assert table["Revenue growth"].iloc[1] == pytest.approx(33.333, abs=0.01)


def test_keeps_only_the_latest_years():
    entries = [fact(f"{y}-01-01", f"{y}-12-31", y, f"{y + 1}-02-01") for y in range(2015, 2025)]
    table = sec.annual_financials(1, fetch_returning(facts(Revenues=("USD", entries))), years=5)
    assert list(table.index.year) == [2020, 2021, 2022, 2023, 2024]


def test_missing_lines_are_simply_absent():
    table = sec.annual_financials(1, fetch_returning(facts(NetIncomeLoss=("USD", [fact("2024-01-01", "2024-12-31", 5, "2025-02-01")]))))
    assert "Revenue" not in table and "Diluted EPS" not in table and "Net margin" not in table


def test_no_us_gaap_data_means_none():
    assert sec.annual_financials(1, fetch_returning({"facts": {"ifrs-full": {}}})) is None
    assert sec.annual_financials(1, fetch_returning(facts(SomethingElse=("USD", [])))) is None


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO())


def raiser(error):
    def fetch(url):
        raise error
    return fetch


def test_a_404_means_no_data_but_other_failures_raise():
    assert sec.annual_financials(1, raiser(http_error(404))) is None
    for code in (429, 503):
        with pytest.raises(urllib.error.HTTPError):
            sec.annual_financials(1, raiser(http_error(code)))
    with pytest.raises(urllib.error.URLError):
        sec.annual_financials(1, raiser(urllib.error.URLError("down")))


def test_ticker_map():
    data = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}, "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "B"}}
    assert sec.ticker_map(fetch_returning(data)) == {"AAPL": 320193, "BRK-B": 1067983}


def test_recent_filings_keeps_reports_labels_them_and_builds_links():
    recent = {"form": ["4", "8-K", "10-Q", "144", "10-K"],
              "items": ["", "2.02,9.01", "", "", ""],
              "filingDate": ["2026-10-08", "2026-08-01", "2026-07-30", "2026-07-01", "2025-11-01"],
              "accessionNumber": ["a", "0000320193-26-000001", "0000320193-26-000002", "c", "0000320193-25-000003"],
              "primaryDocument": ["f4.xml", "ex99.htm", "q.htm", "x", "k.htm"]}
    out = sec.recent_filings(320193, fetch_returning({"filings": {"recent": recent}}))
    assert [f["form"] for f in out] == ["8-K", "10-Q", "10-K"]          # forms 4 and 144 are left out
    assert out[0]["about"] == "results of operations"                      # 9.01 (exhibits) is not interesting
    assert out[1]["label"] == "Quarterly report"
    assert out[0]["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/ex99.htm"


def test_recent_filings_respects_the_limit():
    n = 12
    recent = {"form": ["10-Q"] * n, "items": [""] * n, "filingDate": ["2026-01-01"] * n,
              "accessionNumber": [f"0-0-{i}" for i in range(n)], "primaryDocument": ["d.htm"] * n}
    assert len(sec.recent_filings(1, fetch_returning({"filings": {"recent": recent}}), limit=5)) == 5


def test_configured_depends_only_on_the_user_agent_setting(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert not sec.configured()
    monkeypatch.setenv("SEC_USER_AGENT", "   ")
    assert not sec.configured()
    monkeypatch.setenv("SEC_USER_AGENT", "Some Project contact@example.com")
    assert sec.configured()


def test_explain_says_what_to_check_and_never_includes_the_contact(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Secret Project private.person@example.com")
    forbidden = urllib.error.HTTPError("https://data.sec.gov/x.json", 403, "Forbidden", {}, io.BytesIO())
    text = sec.explain(forbidden)
    assert "403" in text and "https://data.sec.gov/x.json" in text and "SEC_USER_AGENT" in text
    assert "private.person" not in text and "Secret Project" not in text
    assert "rate limited" in sec.explain(urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO()))
    assert "URLError" in sec.explain(urllib.error.URLError("name resolution failed"))
