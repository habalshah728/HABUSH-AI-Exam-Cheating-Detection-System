"""Shared Streamlit CSS styles and UI helper formatters."""

import streamlit as st


def apply_custom_styles() -> None:
    """Inject consistent navy/card styling matching the proposal mockups."""
    st.markdown(
        """
        <style>
        /* Main background */
        .stApp {
            background-color: #F4F7FA;
        }
        /* Sidebar styling */
        section[data-testid="stSidebar"] {
            background-color: #1B365D;
        }
        section[data-testid="stSidebar"] * {
            color: #F1F5F9 !important;
        }
        section[data-testid="stSidebar"] .stRadio label {
            padding: 8px 12px;
            border-radius: 6px;
            margin-bottom: 2px;
        }
        /* KPI cards */
        .kpi-card {
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 16px 18px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
        }
        .kpi-label {
            font-size: 0.82rem;
            color: #64748B;
            margin-bottom: 6px;
            font-weight: 500;
        }
        .kpi-value {
            font-size: 1.85rem;
            font-weight: 700;
            color: #1B365D;
            line-height: 1.1;
        }
        .kpi-value-alert {
            color: #C53030;
        }
        /* Option cards */
        .option-card {
            background: #FFFFFF;
            border: 1px solid #CBD5E1;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 10px;
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.05);
        }
        .option-title {
            font-size: 1.08rem;
            font-weight: 700;
            color: #1B365D;
            margin-bottom: 4px;
        }
        .option-sub {
            font-size: 0.88rem;
            color: #475569;
        }
        /* Risk badges */
        .risk-high {
            color: #C53030;
            font-weight: 700;
        }
        .risk-medium {
            color: #D97706;
            font-weight: 700;
        }
        .risk-low {
            color: #059669;
            font-weight: 700;
        }
        /* Live alert card */
        .alert-item {
            background: #FFFBEB;
            border-left: 4px solid #D97706;
            border-radius: 6px;
            padding: 10px 12px;
            margin-bottom: 8px;
        }
        .alert-item-high {
            background: #FEF2F2;
            border-left: 4px solid #DC2626;
        }
        .alert-title {
            font-weight: 700;
            font-size: 0.9rem;
            color: #1E293B;
        }
        .alert-meta {
            font-size: 0.78rem;
            color: #64748B;
        }
        .disclaimer-note {
            font-size: 0.82rem;
            color: #64748B;
            font-style: italic;
            margin-top: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    total = max(0, int(seconds))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"
