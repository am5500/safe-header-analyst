"""
theme.py
─────────────────────────────────────────────
Visual theme, i18n strings, and Streamlit session-state bootstrapping —
ported verbatim from the original dashboard so the "beautiful UI" stays
unchanged, per the spec's explicit instruction to preserve the existing
look. The only behavioral change here vs. the original file: the Groq
API key is now read from the environment instead of being hardcoded and
pre-filled into session state (see init_session_state below).
"""

from __future__ import annotations

import os
import uuid

import streamlit as st


def inject_global_css() -> None:
    """Inject the full dark-theme CSS block. Call once per page load."""
    st.markdown("""
<style>
/* ── Google Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap');

/* ── Root palette — DARK ONLY ── */
:root {
    --bg:        #080a0f;
    --surface:   #0e1117;
    --card:      #13161f;
    --card2:     #181d2a;
    --border:    rgba(255,255,255,0.065);
    --border2:   rgba(255,255,255,0.12);
    --accent1:   #4f8ef7;
    --accent2:   #a78bfa;
    --accent3:   #34d399;
    --accent4:   #f59e0b;
    --text:      #e8edf5;
    --text2:     #c4cdd8;
    --muted:     #556070;
    --danger:    #f87171;
    --radius:    16px;
    --radius-sm: 10px;
    --shadow:    0 8px 40px rgba(0,0,0,0.6);
    --shadow-sm: 0 2px 12px rgba(0,0,0,0.4);
    --glow1:     0 0 30px rgba(79,142,247,0.08);
    --font-scale: 1;
}

/* ── Display modes ── */
body.mode-compact { --font-scale: 0.88; }
body.mode-large   { --font-scale: 1.13; }

/* ── Base ── */
html, body, .stApp {
    background: var(--bg) !important;
    font-family: 'Inter', sans-serif;
    color: var(--text);
    font-size: calc(15px * var(--font-scale));
    scroll-behavior: smooth;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border);
    transition: width .35s cubic-bezier(.4,0,.2,1), transform .35s cubic-bezier(.4,0,.2,1);
}
[data-testid="stSidebar"] * { color: var(--text) !important; }
[data-testid="stSidebar"] .stMarkdown p { font-size: 14px !important; }
[data-testid="stSidebar"] label { font-size: 13px !important; color: var(--muted) !important; }
[data-testid="stSidebar"] .stSelectbox > div > div,
[data-testid="stSidebar"] .stMultiSelect > div > div {
    background: var(--card2) !important;
    border-color: var(--border2) !important;
    border-radius: 8px !important;
    font-size: 13px !important;
}
[data-testid="stSidebar"] .stDownloadButton button,
[data-testid="stSidebar"] .stButton button {
    font-size: 13px !important;
    border-radius: 8px !important;
}

/* ── Sidebar collapse button ── */
[data-testid="collapsedControl"] {
    background: var(--card2) !important;
    border: 1px solid var(--border2) !important;
    border-radius: 0 10px 10px 0 !important;
    color: var(--accent1) !important;
    transition: background .2s, box-shadow .2s;
    box-shadow: 2px 0 12px rgba(0,0,0,0.4);
}
[data-testid="collapsedControl"]:hover {
    background: rgba(79,142,247,0.15) !important;
    box-shadow: 2px 0 20px rgba(79,142,247,0.2);
}

/* ── Hide default header ── */
header[data-testid="stHeader"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* ── Sticky dashboard header ── */
.sticky-header {
    position: sticky;
    top: 0;
    z-index: 999;
    background: rgba(8,10,15,0.92);
    backdrop-filter: blur(24px) saturate(180%);
    -webkit-backdrop-filter: blur(24px) saturate(180%);
    padding: .75rem 0 .6rem;
    margin: 0 -1rem;
    padding-left: 1rem;
    padding-right: 1rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1.5rem;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: #1e2535; border-radius: 3px; }

/* ── Glass card ── */
.glass-card {
    background: rgba(19,22,31,0.85);
    border: 1px solid var(--border2);
    border-radius: var(--radius);
    padding: 1.5rem 1.75rem;
    box-shadow: var(--shadow), var(--glow1);
    backdrop-filter: blur(20px) saturate(180%);
    -webkit-backdrop-filter: blur(20px) saturate(180%);
    transition: border-color .3s, box-shadow .3s;
}
.glass-card:hover {
    border-color: rgba(79,142,247,0.3);
    box-shadow: var(--shadow), 0 0 40px rgba(79,142,247,0.12);
}

/* ══════════════════════════════════════════
   KPI CARDS
══════════════════════════════════════════ */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 2.5rem;
}
.kpi-card {
    background: linear-gradient(135deg, rgba(24,29,42,0.95) 0%, rgba(19,22,31,0.95) 100%);
    border: 1px solid var(--border2);
    border-radius: var(--radius);
    padding: 1.5rem 1.6rem 1.3rem;
    position: relative;
    overflow: hidden;
    box-shadow: var(--shadow-sm), inset 0 1px 0 rgba(255,255,255,0.06);
    transition: transform .25s, box-shadow .25s, border-color .25s;
    cursor: default;
}
.kpi-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 16px 50px rgba(0,0,0,0.55), 0 0 40px rgba(79,142,247,0.1);
    border-color: rgba(79,142,247,0.35);
}
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--accent-color, #4f8ef7), transparent);
    border-radius: var(--radius) var(--radius) 0 0;
}
.kpi-card::after {
    content: '';
    position: absolute;
    top: -30px; right: -30px;
    width: 90px; height: 90px;
    border-radius: 50%;
    background: var(--accent-color, #4f8ef7);
    opacity: 0.06;
    pointer-events: none;
}
.kpi-top-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: .85rem;
}
.kpi-icon {
    font-size: 1.35rem;
    line-height: 1;
    opacity: 0.85;
}
.kpi-trend {
    font-size: .78rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 99px;
    letter-spacing: .02em;
    display: inline-flex;
    align-items: center;
    gap: 3px;
}
.kpi-trend-up   { background: rgba(52,211,153,0.15); color: #34d399; }
.kpi-trend-down { background: rgba(248,113,113,0.15); color: #f87171; }
.kpi-trend-neu  { background: rgba(100,116,139,0.15); color: #94a3b8; }
.kpi-label {
    font-size: .72rem;
    font-weight: 700;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: .55rem;
}
.kpi-value {
    font-size: calc(2.1rem * var(--font-scale));
    font-weight: 800;
    color: var(--text);
    line-height: 1.05;
    font-family: 'DM Mono', monospace;
    letter-spacing: -.02em;
}
.kpi-sub {
    font-size: .74rem;
    color: var(--muted);
    margin-top: .45rem;
    border-top: 1px solid var(--border);
    padding-top: .45rem;
}

/* ── KPI animated counter ── */
@keyframes countUp {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
}
.kpi-value { animation: countUp .5s ease both; }
.kpi-card:nth-child(2) .kpi-value { animation-delay: .05s; }
.kpi-card:nth-child(3) .kpi-value { animation-delay: .10s; }
.kpi-card:nth-child(4) .kpi-value { animation-delay: .15s; }
.kpi-card:nth-child(5) .kpi-value { animation-delay: .20s; }
.kpi-card:nth-child(6) .kpi-value { animation-delay: .25s; }
.kpi-card:nth-child(7) .kpi-value { animation-delay: .30s; }
.kpi-card:nth-child(8) .kpi-value { animation-delay: .35s; }

/* ══════════════════════════════════════════
   SECTION HEADERS
══════════════════════════════════════════ */
.section-head {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 2.8rem 0 1.4rem;
    position: relative;
}
.section-head::before {
    content: '';
    position: absolute;
    bottom: -8px;
    left: 0;
    width: 40px;
    height: 2px;
    background: var(--accent1);
    border-radius: 99px;
    opacity: 0.6;
}
.section-head-icon {
    font-size: 1.2rem;
    line-height: 1;
}
.section-head h2 {
    font-size: calc(1.25rem * var(--font-scale));
    font-weight: 700;
    color: var(--text);
    margin: 0;
    letter-spacing: -.01em;
}
.section-pill {
    font-size: .67rem;
    font-weight: 700;
    letter-spacing: .09em;
    text-transform: uppercase;
    padding: 3px 11px;
    border-radius: 99px;
    background: rgba(79,142,247,0.12);
    color: var(--accent1);
    border: 1px solid rgba(79,142,247,0.22);
}

.divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 3rem 0;
    position: relative;
}
.divider::after {
    content: '';
    position: absolute;
    top: -1px; left: 0;
    width: 80px; height: 1px;
    background: linear-gradient(90deg, rgba(79,142,247,0.5), transparent);
}

/* ── Dashboard title ── */
.dash-title {
    font-size: calc(2.2rem * var(--font-scale));
    font-weight: 800;
    letter-spacing: -.03em;
    background: linear-gradient(120deg, #e8edf5 0%, var(--accent1) 60%, var(--accent2) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.15;
}
.dash-sub {
    color: var(--muted);
    font-size: .95rem;
    margin-top: .35rem;
    font-weight: 400;
}

.header-badges-row {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: .65rem;
}
.hbadge {
    font-size: .68rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 99px;
    background: rgba(79,142,247,0.08);
    border: 1px solid rgba(79,142,247,0.18);
    color: var(--accent1);
    letter-spacing: .03em;
}
.hbadge-green {
    background: rgba(52,211,153,0.08);
    border-color: rgba(52,211,153,0.2);
    color: #34d399;
}
.hbadge-purple {
    background: rgba(167,139,250,0.08);
    border-color: rgba(167,139,250,0.2);
    color: var(--accent2);
}
.hbadge-amber {
    background: rgba(245,158,11,0.08);
    border-color: rgba(245,158,11,0.2);
    color: var(--accent4);
}

.meta-row {
    display: flex;
    gap: 8px;
    margin-top: 1rem;
    flex-wrap: wrap;
}
.meta-badge {
    font-size: .77rem;
    font-weight: 500;
    padding: 5px 14px;
    border-radius: 99px;
    background: var(--card2);
    border: 1px solid var(--border);
    color: var(--muted);
    letter-spacing: .01em;
}
.meta-badge span { color: var(--text2); font-weight: 700; }

.meta-info-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
    margin-top: 1rem;
}
.meta-info-item {
    background: var(--card2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: .8rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 4px;
}
.meta-info-label {
    font-size: .65rem;
    font-weight: 700;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
}
.meta-info-value {
    font-size: .92rem;
    font-weight: 600;
    color: var(--text2);
    font-family: 'DM Mono', monospace;
}

.insight-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
}
.insight-card {
    background: var(--card2);
    border: 1px solid var(--border2);
    border-radius: var(--radius);
    padding: 1.25rem 1.4rem;
    display: flex;
    gap: 14px;
    align-items: flex-start;
    box-shadow: var(--shadow-sm);
    transition: border-color .25s, transform .25s, box-shadow .25s;
    position: relative;
    overflow: hidden;
}
.insight-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: var(--accent2);
    opacity: 0.5;
}
.insight-card:hover {
    border-color: rgba(167,139,250,0.35);
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(0,0,0,0.4), 0 0 20px rgba(167,139,250,0.08);
}
.insight-icon {
    font-size: 1.8rem;
    line-height: 1;
    flex-shrink: 0;
    margin-top: 2px;
}
.insight-title {
    font-size: .72rem;
    font-weight: 700;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .09em;
    margin-bottom: .3rem;
}
.insight-body {
    font-size: .92rem;
    color: var(--text2);
    line-height: 1.5;
}
.insight-value-highlight {
    font-family: 'DM Mono', monospace;
    font-weight: 700;
    color: var(--accent1);
    font-size: 1rem;
    display: block;
    margin-top: 4px;
}

.upload-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3.5rem 2.5rem;
    border: 2px dashed rgba(79,142,247,0.25);
    border-radius: var(--radius);
    background: linear-gradient(135deg, rgba(19,22,31,0.9) 0%, rgba(13,15,20,0.9) 100%);
    text-align: center;
    margin: 2rem auto;
    max-width: 580px;
    box-shadow: var(--shadow);
    transition: border-color .3s;
}
.upload-wrapper:hover { border-color: rgba(79,142,247,0.5); }
.upload-icon { font-size: 3.5rem; margin-bottom: 1.2rem; }
.upload-title { font-size: 1.3rem; font-weight: 700; color: var(--text); }
.upload-sub { font-size: .9rem; color: var(--muted); margin-top: .5rem; line-height: 1.5; }

.js-plotly-plot { border-radius: var(--radius); overflow: hidden; }

div[data-testid="stFileUploader"] { color: var(--text); }
div[data-testid="stFileUploader"] label { color: var(--text) !important; font-size: 15px !important; }
.stSelectbox label, .stMultiSelect label, .stDateInput label,
.stSlider label, .stCheckbox label { color: var(--muted) !important; font-size: 13px !important; }
.stSelectbox > div > div, .stMultiSelect > div > div {
    background: var(--card2) !important;
    border-color: var(--border2) !important;
    color: var(--text) !important;
    border-radius: 8px !important;
    font-size: 14px !important;
}
.stDownloadButton button {
    background: linear-gradient(135deg, rgba(79,142,247,0.15) 0%, rgba(79,142,247,0.08) 100%) !important;
    border: 1px solid rgba(79,142,247,0.35) !important;
    color: var(--accent1) !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    padding: 0.6rem 1.2rem !important;
    transition: all .2s !important;
}
.stDownloadButton button:hover {
    background: rgba(79,142,247,0.25) !important;
    border-color: rgba(79,142,247,0.6) !important;
}
.streamlit-expanderHeader {
    font-size: 15px !important;
    font-weight: 600 !important;
    color: var(--text2) !important;
    background: var(--card) !important;
    border-radius: var(--radius-sm) !important;
    border: 1px solid var(--border) !important;
}
.stDataFrame { border-radius: var(--radius-sm) !important; overflow: hidden !important; }
.stSuccess { font-size: 14px !important; }
.stInfo    { font-size: 14px !important; }
.stTabs [data-baseweb="tab-list"] {
    background: var(--card) !important;
    border-radius: var(--radius-sm) !important;
    padding: 5px !important;
    gap: 4px !important;
    border: 1px solid var(--border) !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    border-radius: 8px !important;
    color: var(--muted) !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    padding: 7px 20px !important;
    transition: background .2s, color .2s !important;
}
.stTabs [data-baseweb="tab"]:hover {
    background: rgba(79,142,247,0.08) !important;
    color: var(--text2) !important;
}
.stTabs [aria-selected="true"] {
    background: rgba(79,142,247,0.18) !important;
    color: var(--accent1) !important;
    box-shadow: 0 0 0 1px rgba(79,142,247,0.25) !important;
}

.data-search-bar {
    background: var(--card2);
    border: 1px solid var(--border2);
    border-radius: 10px;
    padding: .5rem 1rem;
    color: var(--text);
    font-size: 14px;
    width: 100%;
    margin-bottom: .75rem;
    outline: none;
    transition: border-color .2s;
    font-family: 'Inter', sans-serif;
}
.data-search-bar:focus { border-color: rgba(79,142,247,0.5); }

.col-stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 8px;
    margin-bottom: 1rem;
}
.col-stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: .6rem .9rem;
}
.col-stat-name {
    font-size: .65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--muted);
    margin-bottom: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.col-stat-val {
    font-size: .88rem;
    font-weight: 600;
    color: var(--text2);
    font-family: 'DM Mono', monospace;
}

.pagination-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: .75rem;
    font-size: .82rem;
    color: var(--muted);
}
.pagination-btns { display: flex; gap: 6px; }
.pag-btn {
    background: var(--card2);
    border: 1px solid var(--border2);
    border-radius: 8px;
    color: var(--text2);
    font-size: .8rem;
    font-weight: 600;
    padding: 4px 12px;
    cursor: pointer;
    transition: background .15s, border-color .15s;
}
.pag-btn:hover { background: rgba(79,142,247,0.15); border-color: rgba(79,142,247,0.35); }
.pag-btn.active { background: rgba(79,142,247,0.2); border-color: #4f8ef7; color: #4f8ef7; }

/* ── Additional AI / Smart insight styles ── */
.ai-chat-wrap {
    display: flex;
    flex-direction: column;
    gap: 14px;
    max-height: 540px;
    overflow-y: auto;
    padding: 1.2rem 1rem;
    background: rgba(13,15,20,0.6);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    scroll-behavior: smooth;
}
.chat-msg-user {
    align-self: flex-end;
    background: rgba(79,142,247,0.18);
    border: 1px solid rgba(79,142,247,0.3);
    border-radius: 14px 14px 4px 14px;
    padding: .75rem 1.1rem;
    max-width: 76%;
    font-size: .9rem;
    color: #e8edf5;
    line-height: 1.55;
}
.chat-msg-ai {
    align-self: flex-start;
    background: rgba(24,29,42,0.9);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 4px 14px 14px 14px;
    padding: .85rem 1.2rem;
    max-width: 88%;
    font-size: .9rem;
    color: #c4cdd8;
    line-height: 1.65;
    position: relative;
}
.chat-msg-ai::before {
    content: '◈';
    position: absolute;
    top: -10px; left: -4px;
    font-size: .8rem;
    color: #4f8ef7;
    background: #080a0f;
    padding: 0 4px;
    border-radius: 4px;
}
.chat-timestamp {
    font-size: .65rem;
    color: #556070;
    margin-top: 4px;
    text-align: right;
}
.suggested-btns {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: .75rem 0;
}
.suggested-btn {
    background: rgba(79,142,247,0.08);
    border: 1px solid rgba(79,142,247,0.2);
    border-radius: 99px;
    padding: 6px 14px;
    font-size: .78rem;
    font-weight: 600;
    color: var(--accent1);
    cursor: pointer;
    transition: background .2s, border-color .2s;
    font-family: 'Inter', sans-serif;
}
.suggested-btn:hover {
    background: rgba(79,142,247,0.18);
    border-color: rgba(79,142,247,0.45);
}
.api-config-box {
    background: rgba(19,22,31,0.85);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
}

.exec-sum-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 14px;
    margin-top: .75rem;
}
.exec-sum-card {
    background: linear-gradient(135deg,rgba(24,29,42,0.95) 0%,rgba(19,22,31,0.95) 100%);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 14px;
    padding: 1.2rem 1.4rem;
    position: relative;
    overflow: hidden;
}
.exec-sum-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--ec, #4f8ef7), transparent);
    border-radius: 14px 14px 0 0;
}
.exec-sum-label {
    font-size: .65rem;
    font-weight: 700;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: #556070;
    margin-bottom: .4rem;
}
.exec-sum-val {
    font-size: 1.05rem;
    font-weight: 700;
    color: #e8edf5;
    line-height: 1.4;
}
.exec-sum-sub {
    font-size: .75rem;
    color: #556070;
    margin-top: .3rem;
}

.smart-ins-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
    margin-top: .5rem;
}
.smart-ins-card {
    background: var(--card2);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 14px;
    padding: 1.2rem 1.4rem;
    display: flex;
    gap: 14px;
    align-items: flex-start;
    transition: transform .22s, border-color .22s, box-shadow .22s;
    position: relative;
    overflow: hidden;
}
.smart-ins-card:hover {
    transform: translateY(-2px);
    border-color: rgba(79,142,247,0.3);
    box-shadow: 0 8px 30px rgba(0,0,0,0.4);
}
.smart-ins-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: var(--sc, #4f8ef7);
    opacity: 0.6;
}
.smart-ins-icon { font-size: 2rem; flex-shrink: 0; line-height: 1; margin-top: 2px; }
.smart-ins-title { font-size: .7rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; color: #556070; margin-bottom: .3rem; }
.smart-ins-body  { font-size: .88rem; color: #c4cdd8; line-height: 1.55; }
.smart-ins-val   { font-family: 'DM Mono',monospace; font-size: .95rem; font-weight: 700; color: var(--sc,#4f8ef7); display: block; margin-top: 5px; }

/* ── SAAS / Plan styles ── */
.plan-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 12px;
    border-radius: 99px;
    font-size: .68rem;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
}
.plan-free { background: rgba(100,116,139,0.15); border: 1px solid rgba(100,116,139,0.3); color: #94a3b8; }
.plan-pro  { background: rgba(167,139,250,0.15); border: 1px solid rgba(167,139,250,0.4); color: #a78bfa; }

.db-card {
    background: linear-gradient(135deg, rgba(24,29,42,0.95) 0%, rgba(19,22,31,0.95) 100%);
    border: 1px solid rgba(255,255,255,0.085);
    border-radius: 16px;
    padding: 1.4rem 1.6rem;
    position: relative;
    overflow: hidden;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    transition: border-color .25s, transform .25s, box-shadow .25s;
    margin-bottom: 14px;
}
.db-card:hover {
    border-color: rgba(79,142,247,0.35);
    transform: translateY(-2px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.5), 0 0 30px rgba(79,142,247,0.1);
}
.db-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #4f8ef7, #a78bfa, transparent);
}
.db-card-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: #e8edf5;
    margin-bottom: .3rem;
    letter-spacing: -.01em;
}
.db-card-sub {
    font-size: .8rem;
    color: #556070;
    margin-bottom: .85rem;
}
.db-card-meta {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: .85rem;
}
.db-meta-chip {
    font-size: .68rem;
    font-weight: 600;
    padding: 2px 9px;
    border-radius: 99px;
    background: rgba(79,142,247,0.08);
    border: 1px solid rgba(79,142,247,0.15);
    color: #7fb3f7;
    letter-spacing: .02em;
}
.db-card-actions {
    display: flex;
    gap: 7px;
    flex-wrap: wrap;
    margin-top: .5rem;
    border-top: 1px solid rgba(255,255,255,0.05);
    padding-top: .75rem;
}
.db-action-btn {
    font-size: .73rem;
    font-weight: 600;
    padding: 4px 13px;
    border-radius: 8px;
    cursor: pointer;
    border: 1px solid rgba(79,142,247,0.25);
    background: rgba(79,142,247,0.08);
    color: #4f8ef7;
    transition: background .18s, border-color .18s;
    white-space: nowrap;
}
.db-action-btn:hover { background: rgba(79,142,247,0.18); border-color: rgba(79,142,247,0.5); }
.db-action-danger { border-color: rgba(248,113,113,0.25); background: rgba(248,113,113,0.06); color: #f87171; }
.db-action-danger:hover { background: rgba(248,113,113,0.15); border-color: rgba(248,113,113,0.5); }
.db-action-green { border-color: rgba(52,211,153,0.25); background: rgba(52,211,153,0.06); color: #34d399; }
.db-action-green:hover { background: rgba(52,211,153,0.15); }

.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: .68rem;
    font-weight: 700;
    padding: 3px 10px;
    border-radius: 99px;
    letter-spacing: .04em;
}
.status-active { background: rgba(52,211,153,0.12); border: 1px solid rgba(52,211,153,0.3); color: #34d399; }
.status-soon   { background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.3); color: #f59e0b; }
.status-expired{ background: rgba(248,113,113,0.12); border: 1px solid rgba(248,113,113,0.3); color: #f87171; }

.share-panel {
    background: rgba(13,15,20,0.7);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
    margin-top: .75rem;
}
.share-id-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: .55rem 1rem;
    font-family: 'DM Mono', monospace;
    font-size: .82rem;
    color: #7fb3f7;
    margin-bottom: .75rem;
}
.share-meta-row {
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
    font-size: .78rem;
    color: #556070;
    margin-top: .5rem;
}
.share-meta-row span { color: #c4cdd8; font-weight: 600; }

.page-nav {
    display: flex;
    gap: 6px;
    margin-bottom: 1.5rem;
}
.page-nav-pill {
    padding: 6px 16px;
    border-radius: 10px;
    font-size: .8rem;
    font-weight: 600;
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.03);
    color: #556070;
    cursor: pointer;
    transition: background .18s, color .18s, border-color .18s;
}
.page-nav-pill.active {
    background: rgba(79,142,247,0.15);
    border-color: rgba(79,142,247,0.35);
    color: #4f8ef7;
}

.upgrade-banner {
    background: linear-gradient(135deg, rgba(167,139,250,0.12) 0%, rgba(79,142,247,0.08) 100%);
    border: 1px solid rgba(167,139,250,0.25);
    border-radius: 14px;
    padding: 1.1rem 1.4rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 1.5rem;
}
.upgrade-banner-text { font-size: .88rem; color: #c4cdd8; }
.upgrade-banner-text b { color: #a78bfa; }

.hist-card {
    background: rgba(19,22,31,0.9);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
    padding: 1.1rem 1.4rem;
    margin-bottom: 10px;
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr 1fr 1fr auto;
    align-items: center;
    gap: 12px;
    transition: border-color .2s, box-shadow .2s;
}
.hist-card:hover {
    border-color: rgba(79,142,247,0.25);
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}
.hist-card-name { font-size: .9rem; font-weight: 700; color: #e8edf5; }
.hist-card-sub  { font-size: .72rem; color: #556070; margin-top: 2px; }
.hist-col-label { font-size: .65rem; font-weight: 700; text-transform: uppercase; letter-spacing: .09em; color: #556070; }
.hist-col-val   { font-size: .85rem; font-weight: 600; color: #c4cdd8; font-family: 'DM Mono', monospace; }

.countdown-card {
    background: linear-gradient(135deg, rgba(24,29,42,0.95) 0%, rgba(19,22,31,0.95) 100%);
    border: 1px solid rgba(245,158,11,0.2);
    border-radius: 12px;
    padding: .9rem 1.2rem;
    display: flex;
    align-items: center;
    gap: 12px;
}
.countdown-days {
    font-size: 2rem;
    font-weight: 800;
    font-family: 'DM Mono', monospace;
    color: #f59e0b;
    line-height: 1;
}

/* ── Extra overrides ── */
body.mode-compact * { font-size: calc(1em * 0.88) !important; }
body.mode-compact .kpi-value { font-size: 1.7rem !important; }
body.mode-compact .kpi-grid  { gap: 10px !important; }
body.mode-large   .kpi-value { font-size: 2.5rem !important; }
body.mode-large   .dash-title { font-size: 2.7rem !important; }

.health-bar-bg {
    background: rgba(255,255,255,0.06);
    border-radius: 99px;
    height: 8px;
    width: 100%;
    margin-top: 8px;
    overflow: hidden;
}
.health-bar-fill {
    height: 8px;
    border-radius: 99px;
    transition: width .8s cubic-bezier(.4,0,.2,1);
}
.score-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 2.8rem;
    font-weight: 800;
    font-family: 'DM Mono', monospace;
    line-height: 1;
}
.stat-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 7px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    font-size: .875rem;
}
.stat-row:last-child { border-bottom: none; }
.stat-label { color: #556070; }
.stat-value { color: #e8edf5; font-weight: 600; }

.tmpl-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    margin: .5rem 0;
}
.tmpl-pill {
    padding: 8px 12px;
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.065);
    background: #13161f;
    font-size: .8rem;
    font-weight: 600;
    cursor: pointer;
    text-align: center;
    color: #e8edf5;
}
.tmpl-pill.active {
    border-color: #4f8ef7;
    background: rgba(79,142,247,0.12);
    color: #4f8ef7;
}
.dl-row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: .5rem;
}
.kpi-delta-pos { color: #34d399; font-size: .78rem; font-weight: 700; margin-top: 3px; }
.kpi-delta-neg { color: #f87171; font-size: .78rem; font-weight: 700; margin-top: 3px; }
.sidebar-section {
    font-size: .62rem;
    font-weight: 800;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: #556070;
    margin: 1.2rem 0 .5rem;
}
.glass-card {
    background: rgba(19,22,31,0.85) !important;
    backdrop-filter: blur(20px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
}
.outlier-chip {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 99px;
    font-size: .75rem;
    font-weight: 600;
    margin: 2px;
}
.outlier-high { background: rgba(248,113,113,0.12); color: #f87171; border: 1px solid rgba(248,113,113,0.25); }
.outlier-ok   { background: rgba(52,211,153,0.12);  color: #34d399; border: 1px solid rgba(52,211,153,0.25);  }
[data-testid="stPlotlyChart"] {
    background: rgba(13,15,20,0.6);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px !important;
    padding: 4px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    overflow: hidden;
}
.streamlit-expanderContent {
    background: rgba(13,15,20,0.5) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-top: none !important;
    border-radius: 0 0 12px 12px !important;
}
</style>
""", unsafe_allow_html=True)


SECTION_ICONS = {
    "Key Metrics": "⚡", "KPIs": "⚡",
    "Visualizations": "📊", "Auto-selected": "📊",
    "Dataset Health": "🩺", "Quality Score": "🩺",
    "Missing Values Analysis": "🔍", "Quality": "🔍",
    "Duplicate Detection": "🔁", "Integrity": "🔁",
    "Outlier Detection": "📐", "Statistics": "📐",
    "Correlation Matrix": "🔗",
    "Automated Insights": "💡", "AI-style": "💡",
    "⬇ Download": "⬇", "Export": "⬇",
    "📌 Dashboard Metadata": "📌", "Info": "📌",
    "Executive Summary": "🧭", "Business Insights": "📈",
    "Risk Detection": "⚠️", "Opportunities": "💎",
    "Recommendations": "💡", "Trend Analysis": "📊",
    "AI Analyst": "🤖",
}


def section_header(title: str, badge: str = ""):
    icon = SECTION_ICONS.get(title, "")
    badge_html = f'<span class="section-pill">{badge}</span>' if badge else ""
    icon_html = f'<span class="section-head-icon">{icon}</span>' if icon else ""
    st.markdown(f"""
    <div class="section-head">
        {icon_html}
        <h2>{title}</h2>
        {badge_html}
    </div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# TRANSLATIONS
# ─────────────────────────────────────────────
TRANSLATIONS = {
    "en": {
        "app_title": "Dynamic Dashboard",
        "app_sub": "Universal Data Explorer",
        "upload_label": "Upload Dataset",
        "upload_title": "Drop your file here",
        "upload_sub": "Supports CSV, XLS, XLSX — auto-detects schema & builds charts",
        "settings": "⚙ Settings",
        "language": "Language / اللغة",
        "theme": "Theme",
        "template": "Dashboard Template",
        "filters": "⚙ Filters",
        "date_range": "Date Range",
        "showing": "Showing",
        "of": "of",
        "rows": "rows",
        "key_metrics": "Key Metrics",
        "kpis": "KPIs",
        "visualizations": "Visualizations",
        "auto": "Auto-selected",
        "insights": "Automated Insights",
        "ai": "AI-style",
        "data_preview": "📋 Data Preview",
        "schema": "🔬 Detected Schema",
        "date_cols": "Date columns",
        "num_cols": "Numeric columns",
        "cat_cols": "Categorical columns",
        "health": "Dataset Health",
        "health_badge": "Quality Score",
        "missing": "Missing Values Analysis",
        "duplicates": "Duplicate Detection",
        "outliers": "Outlier Detection",
        "correlation": "Correlation Matrix",
        "download": "⬇ Download",
        "dl_csv": "Download CSV",
        "dl_excel": "Download Excel",
        "dl_pdf": "Download Report (PDF)",
        "metadata": "📌 Dashboard Metadata",
        "total_records": "Total Records",
        "total": "Total",
        "avg": "avg",
        "max": "max",
        "unique": "Unique",
        "distinct": "distinct values",
        "date_range_kpi": "Date Range",
        "rows_label": "rows in dataset",
        "no_plottable": "No plottable columns found. Check your dataset.",
        "analyzing": "Analyzing dataset…",
        "auto_dashboard": "Automatically generated interactive dashboard",
        "numeric": "numeric",
        "categorical": "categorical",
    },
    "ar": {
        "app_title": "لوحة التحكم الديناميكية",
        "app_sub": "مستكشف البيانات الشامل",
        "upload_label": "رفع مجموعة البيانات",
        "upload_title": "أسقط ملفك هنا",
        "upload_sub": "يدعم CSV، XLS، XLSX — يكتشف المخطط تلقائياً ويبني الرسوم البيانية",
        "settings": "⚙ الإعدادات",
        "language": "اللغة / Language",
        "theme": "المظهر",
        "template": "قالب اللوحة",
        "filters": "⚙ الفلاتر",
        "date_range": "نطاق التاريخ",
        "showing": "عرض",
        "of": "من",
        "rows": "صف",
        "key_metrics": "المقاييس الرئيسية",
        "kpis": "مؤشرات الأداء",
        "visualizations": "التصورات البيانية",
        "auto": "مختار تلقائياً",
        "insights": "رؤى آلية",
        "ai": "ذكاء اصطناعي",
        "data_preview": "📋 معاينة البيانات",
        "schema": "🔬 المخطط المكتشف",
        "date_cols": "أعمدة التاريخ",
        "num_cols": "الأعمدة الرقمية",
        "cat_cols": "الأعمدة الفئوية",
        "health": "صحة مجموعة البيانات",
        "health_badge": "درجة الجودة",
        "missing": "تحليل القيم المفقودة",
        "duplicates": "اكتشاف التكرارات",
        "outliers": "اكتشاف القيم الشاذة",
        "correlation": "مصفوفة الارتباط",
        "download": "⬇ تحميل",
        "dl_csv": "تحميل CSV",
        "dl_excel": "تحميل Excel",
        "dl_pdf": "تحميل التقرير (PDF)",
        "metadata": "📌 بيانات اللوحة",
        "total_records": "إجمالي السجلات",
        "total": "الإجمالي",
        "avg": "متوسط",
        "max": "أقصى",
        "unique": "فريد",
        "distinct": "قيم متميزة",
        "date_range_kpi": "نطاق التاريخ",
        "rows_label": "صف في مجموعة البيانات",
        "no_plottable": "لا توجد أعمدة قابلة للرسم. تحقق من بياناتك.",
        "analyzing": "جارٍ تحليل البيانات…",
        "auto_dashboard": "لوحة تحكم تفاعلية مُنشأة تلقائياً",
        "numeric": "رقمي",
        "categorical": "فئوي",
    }
}


def t(key: str) -> str:
    lang = st.session_state.get("lang", "en")
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key, key)

# ─────────────────────────────────────────────
# THEME & EXTRA CSS
# ─────────────────────────────────────────────
RTL_CSS = """
<style>
html, body, .stApp, .stMarkdown, .stSidebar { direction: rtl; text-align: right; }
.kpi-grid, .insight-grid, .meta-row { direction: rtl; }
</style>
"""
def inject_theme():
    lang = st.session_state.get("lang", "en")
    if lang == "ar":
        st.markdown(RTL_CSS, unsafe_allow_html=True)

EXTRA_CSS = """
<style>
body.mode-compact * { font-size: calc(1em * 0.88) !important; }
body.mode-compact .kpi-value { font-size: 1.7rem !important; }
body.mode-compact .kpi-grid  { gap: 10px !important; }
body.mode-large   .kpi-value { font-size: 2.5rem !important; }
body.mode-large   .dash-title { font-size: 2.7rem !important; }
.health-bar-bg { background: rgba(255,255,255,0.06); border-radius: 99px; height: 8px; width: 100%; margin-top: 8px; overflow: hidden; }
.health-bar-fill { height: 8px; border-radius: 99px; transition: width .8s cubic-bezier(.4,0,.2,1); }
.score-badge { display: inline-flex; align-items: center; gap: 6px; font-size: 2.8rem; font-weight: 800; font-family: 'DM Mono', monospace; line-height: 1; }
.stat-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: .875rem; }
.stat-row:last-child { border-bottom: none; }
.stat-label { color: #556070; }
.stat-value { color: #e8edf5; font-weight: 600; }
.tmpl-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: .5rem 0; }
.tmpl-pill { padding: 8px 12px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.065); background: #13161f; font-size: .8rem; font-weight: 600; cursor: pointer; text-align: center; color: #e8edf5; }
.tmpl-pill.active { border-color: #4f8ef7; background: rgba(79,142,247,0.12); color: #4f8ef7; }
.dl-row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: .5rem; }
.kpi-delta-pos { color: #34d399; font-size: .78rem; font-weight: 700; margin-top: 3px; }
.kpi-delta-neg { color: #f87171; font-size: .78rem; font-weight: 700; margin-top: 3px; }
.sidebar-section { font-size: .62rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; color: #556070; margin: 1.2rem 0 .5rem; }
.glass-card { background: rgba(19,22,31,0.85) !important; backdrop-filter: blur(20px) saturate(180%) !important; -webkit-backdrop-filter: blur(20px) saturate(180%) !important; border: 1px solid rgba(255,255,255,0.09) !important; }
.outlier-chip { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: .75rem; font-weight: 600; margin: 2px; }
.outlier-high { background: rgba(248,113,113,0.12); color: #f87171; border: 1px solid rgba(248,113,113,0.25); }
.outlier-ok   { background: rgba(52,211,153,0.12);  color: #34d399; border: 1px solid rgba(52,211,153,0.25);  }
[data-testid="stPlotlyChart"] { background: rgba(13,15,20,0.6); border: 1px solid rgba(255,255,255,0.06); border-radius: 16px !important; padding: 4px; box-shadow: 0 4px 24px rgba(0,0,0,0.4); overflow: hidden; }
.streamlit-expanderContent { background: rgba(13,15,20,0.5) !important; border: 1px solid rgba(255,255,255,0.06) !important; border-top: none !important; border-radius: 0 0 12px 12px !important; }
</style>
"""

# ─────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────
def init_session_state():
    defaults = {
        "lang": "en",
        "theme": "Dark",
        "template": "Auto",
        "last_file_name": None,
        "display_mode": "normal",
        "data_preview_page": 0,
        "dashboards": {},
        "active_dashboard_id": None,
        "plan": "free",
        "session_id": None,
        "current_page": "dashboard",
        "ai_chat_history": [],
        "ai_provider": "groq",  # we use Groq by default
        "openai_api_key": "",
        "gemini_api_key": "",
        # SECURITY: never hardcode a key here. Read from the environment;
        # if unset, the field is empty and AI features show a clear
        # "add your API key" prompt instead of silently using a baked-in
        # credential. Users may also paste a personal key into the
        # settings panel, which overwrites this session value only
        # (never written back to the environment or disk).
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "ai_charts": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if st.session_state.session_id is None:
        st.session_state.session_id = str(uuid.uuid4())[:8].upper()

# ─────────────────────────────────────────────
