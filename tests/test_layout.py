"""Tests for layout.metric_grid in both modes (wrapping grid and the plain-columns fallback).  Run:  python -m pytest tests"""
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import layout  # noqa: E402


def script():
    import layout as L
    L.metric_grid([
        dict(label="Close", value="$10.00", delta="+1.00 (+11.11%)", help="last price"),
        dict(label="Open", value="$9.00"),
        dict(label="High", value="$11.00"),
        dict(label="Low", value="$8.00"),
        dict(label="Volume", value="1.0M", help="shares"),
        dict(label="Net income", value="$5.0B", delta="20% of revenue", delta_color="off"),
    ])


@pytest.fixture(params=[True, False], ids=["wrapping grid", "plain columns"])
def run(request, monkeypatch):
    monkeypatch.setattr(layout, "supports_wrapping_row", lambda: request.param)
    return AppTest.from_function(script, default_timeout=30).run()


def test_every_metric_is_shown_in_either_mode(run):
    assert not run.exception
    assert [m.label for m in run.metric] == ["Close", "Open", "High", "Low", "Volume", "Net income"]
    assert [m.value for m in run.metric][:2] == ["$10.00", "$9.00"]


def test_delta_help_and_colour_options_are_passed_through(run):
    by = {m.label: m for m in run.metric}
    assert by["Close"].delta == "+1.00 (+11.11%)" and by["Close"].help == "last price"
    assert by["Volume"].help == "shares"
    assert by["Net income"].proto.color != by["Close"].proto.color   # delta_color="off" (grey) differs from the default
    assert by["Open"].delta is None or by["Open"].delta == ""


def test_the_real_app_runs_in_both_modes(monkeypatch):
    for mode in (True, False):
        monkeypatch.setattr(layout, "supports_wrapping_row", lambda mode=mode: mode)
        for query in ({}, {"view": "learn"}):
            at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "Stock Price Dashboard.py"), default_timeout=90)
            for k, v in query.items():
                at.query_params[k] = v
            at.run()
            assert not at.exception, (mode, query)
            assert len(at.metric) >= 6, (mode, query, len(at.metric))
