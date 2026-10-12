"""Layout helpers.

metric_grid puts a group of metrics in a grid that wraps to fit the screen (for example 4 + 2 across on a desktop
and 2 + 2 + 2 on a phone) instead of Streamlit's default of stacking every column into one tall list on a phone.
That needs a newer Streamlit (a horizontal container that wraps, and a width for st.metric); on an older one it
falls back to plain columns, so the app works either way.
"""
import inspect

import streamlit as st


def supports_wrapping_row():
    return ("horizontal" in inspect.signature(st.container).parameters
            and "width" in inspect.signature(st.metric).parameters)


def metric_grid(items, width=160, per_row=4):
    """items: list of dicts with the st.metric arguments (label, value, and optionally delta, help, delta_color).
    width: pixel width of each metric in the wrapping grid. per_row: how many per row in the fallback."""
    if supports_wrapping_row():
        with st.container(horizontal=True, wrap=True, gap="small"):
            for item in items:
                st.metric(width=width, **item)
        return
    for start in range(0, len(items), per_row):
        row = items[start:start + per_row]
        for column, item in zip(st.columns(per_row), row):
            column.metric(**item)
