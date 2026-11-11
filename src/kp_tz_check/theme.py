"""Общий вид страниц. Не меняет расчёты и статусы."""

from __future__ import annotations

import streamlit as st


_CSS = """
<style>
  .stApp {
    background: #f6f3ec;
    color: #1c1915;
  }
  [data-testid="stHeader"] {
    background: transparent;
  }
  .block-container {
    padding-top: 1.4rem;
    padding-bottom: 3rem;
    max-width: 1120px;
  }
  h1 {
    letter-spacing: -0.03em;
    font-weight: 650;
    margin-bottom: 0.15rem;
  }
  [data-testid="stCaptionContainer"] {
    color: #5e584f;
  }
  [data-testid="stSidebar"] {
    background: #fbf9f4;
    border-right: 1px solid #e4ddd2;
  }
  [data-testid="stSidebarNav"] a {
    border-radius: 8px;
  }
  [data-testid="stSidebarNav"] a[aria-current="page"] {
    background: #e5f0ec;
    color: #1f4d45;
  }
  div[data-testid="stMetric"] {
    background: #fffdf8;
    border: 1px solid #e6e0d6;
    border-radius: 14px;
    padding: 0.7rem 0.85rem 0.35rem;
  }
  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #fffdf8;
    border-color: #e6e0d6 !important;
    border-radius: 14px;
  }
  button[data-testid="stBaseButton-primary"] {
    background: #1f4d45;
    border-color: #1f4d45;
  }
  button[data-testid="stBaseButton-primary"]:hover {
    background: #173b35;
    border-color: #173b35;
  }
  [data-testid="stDataFrame"] {
    border: 1px solid #e6e0d6;
    border-radius: 12px;
    overflow: hidden;
  }
</style>
"""


def apply_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
