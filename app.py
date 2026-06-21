"""
app.py
─────────────────────────────────────────────
Main Streamlit entrypoint. Thin orchestration layer: upload → profile →
rule-based charts/KPIs/insights (always works) → optional AI enhancement
(renames/reranks only) → render. Visual design (CSS, layout, language)
is preserved from the original app via theme.py / render_engine.py.

Run with:  streamlit run app.py
Requires (optional, for AI features):  export GROQ_API_KEY=sk-...
"""

from __future__ import annotations

import datetime
import hashlib
import io
import warnings

import pandas as pd
import streamlit as st

import ai_engine as ai
import chart_engine as ce
import chat_engine as chate
import dataset_profiler as dp
import insight_engine as ie
import kpi_engine as ke
import render_engine as re_ui
from theme import (
    inject_global_css, inject_theme, init_session_state, section_header, t, EXTRA_CSS,
)

warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="Dynamic Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

KPI_ICONS = ["📦", "💰", "📈", "📉", "🏷️", "🎯", "📅", "🔢"]
TEMPLATES = ["Auto", "Sales", "Finance", "HR", "Marketing"]


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────
@st.cache_data(show_spinner=False, max_entries=4)
def load_data(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    """Parse an uploaded CSV/XLSX into a dataframe. Cached on the exact
    file bytes + name, so re-running the script (filters, tab switches)
    never re-parses the file from scratch — important once files get
    into the hundreds of thousands of rows.
    """
    if file_name.lower().endswith(".csv"):
        last_err: Exception | None = None
        for enc in ["utf-8", "latin1", "cp1252"]:
            try:
                return pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        raise ValueError(f"Could not parse CSV with any known encoding: {last_err}")
    return pd.read_excel(io.BytesIO(file_bytes))


@st.cache_data(show_spinner=False, max_entries=4)
def profile_data(df: pd.DataFrame, template: str):
    """Schema detection + profiling, cached per (dataframe content, template).
    This is the expensive-ish step (column-type scanning, role detection)
    we don't want re-running on every filter/widget interaction.
    """
    schema = dp.detect_schema(df.copy())
    df = dp.coerce_dates(df, schema["date"])
    profile = dp.build_profile(df, schema)
    if template != "Auto":
        primary = dp.pick_primary_with_template(df, schema["numeric"], template)
        profile.primary_measure = primary
    return df, profile


def get_active_api_key() -> str | None:
    """Session-pasted key (if any) takes priority over the server-wide
    environment variable, so a user can bring their own key without
    needing access to the host environment.
    """
    return st.session_state.get("groq_api_key") or ai.get_api_key()


# ─────────────────────────────────────────────
# PERFORMANCE: row-count aware sampling notice
# ─────────────────────────────────────────────
def maybe_warn_large_file(df: pd.DataFrame) -> None:
    n = len(df)
    if n >= 1_000_000:
        st.warning(
            f"This file has {n:,} rows. Aggregations are computed on the full "
            f"dataset (fast — groupby/sum scale well), but scatter/point charts "
            f"are automatically sampled to 2,000 points for responsiveness."
        )
    elif n >= 500_000:
        st.info(f"Large file detected ({n:,} rows) — charts may take a moment to render.")


# ─────────────────────────────────────────────
# SETTINGS PANEL (AI key entry)
# ─────────────────────────────────────────────
def render_settings_panel() -> None:
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"<div class='sidebar-section'>Settings</div>", unsafe_allow_html=True)
    with st.sidebar.expander("🤖 AI Settings", expanded=False):
        key_input = st.text_input(
            "Groq API Key", value=st.session_state.get("groq_api_key", ""),
            type="password", help="Get a free key at console.groq.com. Stored only in this session.",
        )
        st.session_state.groq_api_key = key_input
        if ai.is_available(key_input):
            st.success("AI features enabled.")
        else:
            st.caption("Without a key, the dashboard still works fully — charts, KPIs, and insights use the built-in rule engine. AI only adds nicer titles and a smarter chat.")

    template = st.sidebar.selectbox("Dashboard Template", TEMPLATES, index=TEMPLATES.index(st.session_state.get("template", "Auto")))
    st.session_state.template = template
    return None


# ─────────────────────────────────────────────
# KPI CARDS (real per-KPI trends, no fabricated offsets)
# ─────────────────────────────────────────────
def render_kpi_cards(kpis: list[dict]) -> None:
    section_header(t("key_metrics"), t("kpis"))
    kpi_html = '<div class="kpi-grid">'
    for i, kpi in enumerate(kpis):
        icon = KPI_ICONS[i % len(KPI_ICONS)]
        if kpi.get("trend_pct") is not None:
            arrow = "↑" if kpi["trend_up"] else "↓"
            trend_cls = "kpi-trend-up" if kpi["trend_up"] else "kpi-trend-down"
            trend_display = f"{arrow} {abs(kpi['trend_pct']):.1f}%"
        else:
            trend_display = "—"
            trend_cls = "kpi-trend-neu"
        kpi_html += f"""
        <div class='kpi-card' style='--accent-color:{kpi["color"]}'>
            <div class='kpi-top-row'>
                <span class='kpi-icon'>{icon}</span>
                <span class='kpi-trend {trend_cls}'>{trend_display}</span>
            </div>
            <div class='kpi-label'>{kpi["label"]}</div>
            <div class='kpi-value'>{kpi["value"]}</div>
            <div class='kpi-sub'>{kpi["sub"]}</div>
        </div>"""
    kpi_html += "</div>"
    st.markdown(kpi_html, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# CHARTS (config-driven, hybrid rule+AI)
# ─────────────────────────────────────────────
def render_charts(df: pd.DataFrame, profile, api_key: str | None) -> dict:
    section_header(t("visualizations"), t("auto"))

    cache_key = f"charts_{hash(tuple(df.columns))}_{len(df)}"
    rule_configs = ce.build_rule_based_charts(df, profile)

    if ai.is_available(api_key):
        if st.session_state.get("ai_charts_cache_key") != cache_key:
            with st.spinner("🤖 AI is refining chart titles and priority..."):
                enhanced = ai.enhance_chart_configs(rule_configs, profile.to_ai_context(), api_key=api_key)
                st.session_state.ai_charts = enhanced
                st.session_state.ai_charts_cache_key = cache_key
        configs = st.session_state.get("ai_charts") or rule_configs
    else:
        configs = rule_configs

    rendered_figures: dict = {}
    if not configs:
        st.info(t("no_plottable"))
        return rendered_figures

    for cfg in configs:
        fig = ce.render_chart(df, cfg)
        if fig is None:
            st.markdown(f"""
            <div class='glass-card' style='padding:1rem;border-color:rgba(245,158,11,0.3)'>
                ⚠️ Could not render chart "<b>{cfg.get('title','Untitled')}</b>" — required columns may be missing or incompatible.
            </div>""", unsafe_allow_html=True)
            continue
        with st.container():
            st.plotly_chart(fig, width="stretch")
            if cfg.get("description"):
                st.caption(f"💡 {cfg['description']}")
        rendered_figures[cfg.get("title", f"chart_{len(rendered_figures)}")] = fig

    return rendered_figures


# ─────────────────────────────────────────────
# AI INSIGHT PAGE (Executive Summary / Business Insights / Risk /
# Opportunities / Outliers / Recommendations / Trend Analysis)
# ─────────────────────────────────────────────
def render_insight_cards(title: str, icon_badge: str, items: list[dict]) -> None:
    section_header(title, icon_badge)
    if not items:
        st.info("Nothing notable found for this section.")
        return
    cols = st.columns(2)
    for i, item in enumerate(items):
        with cols[i % 2]:
            highlight_html = f"<div style='font-size:1.4rem;font-weight:800;color:#4f8ef7;margin-top:.4rem'>{item['highlight']}</div>" if item.get("highlight") else ""
            st.markdown(f"""
            <div class='glass-card' style='padding:1rem;margin-bottom:.75rem'>
                <div style='font-size:1.3rem'>{item.get('icon','💡')}</div>
                <div style='font-weight:700;color:#e8edf5;margin-top:.3rem'>{item.get('title','')}</div>
                <div style='font-size:.85rem;color:#a8b3c2;margin-top:.3rem;line-height:1.5'>{item.get('body','')}</div>
                {highlight_html}
            </div>""", unsafe_allow_html=True)


def render_executive_summary_cards(cards: list[dict]) -> None:
    section_header("Executive Summary", "🧭")
    cols = st.columns(min(len(cards), 3) or 1)
    for i, card in enumerate(cards):
        with cols[i % len(cols)]:
            st.markdown(f"""
            <div class='glass-card' style='padding:1rem;text-align:center;margin-bottom:.75rem;border-top:3px solid {card['color']}'>
                <div style='font-size:.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em'>{card['label']}</div>
                <div style='font-size:1.3rem;font-weight:800;color:#e8edf5;margin-top:.4rem'>{card['value']}</div>
                <div style='font-size:.78rem;color:#a8b3c2;margin-top:.2rem'>{card['sub']}</div>
            </div>""", unsafe_allow_html=True)


def render_ai_insight_page(df: pd.DataFrame, profile, api_key: str | None) -> None:
    report = ie.build_full_insight_report(df, profile)

    if ai.is_available(api_key):
        cache_key = f"insights_{hash(tuple(df.columns))}_{len(df)}"
        if st.session_state.get("insight_rewrite_cache_key") != cache_key:
            with st.spinner("🤖 Polishing insight wording..."):
                report["business_insights"] = ai.rewrite_insight_list(report["business_insights"], api_key=api_key)
                report["risk_detection"] = ai.rewrite_insight_list(report["risk_detection"], api_key=api_key, max_items=3)
                report["opportunities"] = ai.rewrite_insight_list(report["opportunities"], api_key=api_key, max_items=3)
                report["trend_analysis"] = ai.rewrite_insight_list(report["trend_analysis"], api_key=api_key, max_items=3)
                st.session_state.insight_report_cache = report
                st.session_state.insight_rewrite_cache_key = cache_key
        report = st.session_state.get("insight_report_cache", report)

    render_executive_summary_cards(report["executive_summary"])
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)
    render_insight_cards("Business Insights", "📈", report["business_insights"])
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)
    render_insight_cards("Risk Detection", "⚠️", report["risk_detection"])
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)
    render_insight_cards("Opportunities", "💎", report["opportunities"])
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)
    render_insight_cards("Trend Analysis", "📊", report["trend_analysis"])
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)
    render_insight_cards(
        "Recommendations", "💡",
        [{"icon": r["icon"], "title": r["title"], "body": r["body"]} for r in report["recommendations"]],
    )


# ─────────────────────────────────────────────
# AI CHAT TAB
# ─────────────────────────────────────────────
def render_chat_tab(df: pd.DataFrame, profile, api_key: str | None) -> None:
    section_header("AI Analyst", "🤖")

    if not ai.is_available(api_key):
        st.info("Add a Groq API key in the sidebar settings for AI-powered answers. Basic rule-based answers still work below.")

    suggestions = chate.suggested_questions(profile)
    st.markdown("**Suggested questions:**")
    cols = st.columns(min(len(suggestions), 3) or 1)
    for i, q in enumerate(suggestions):
        with cols[i % len(cols)]:
            if st.button(q, key=f"sugg_{i}", width="stretch"):
                st.session_state.ai_chat_history.append({"role": "user", "content": q})

    for turn in st.session_state.ai_chat_history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])

    user_input = st.chat_input("Ask a question about your data...")
    if user_input:
        st.session_state.ai_chat_history.append({"role": "user", "content": user_input})

    # Answer any unanswered trailing user message (covers both chat_input
    # and the suggested-question buttons above).
    history = st.session_state.ai_chat_history
    if history and history[-1]["role"] == "user":
        with st.chat_message("user"):
            st.markdown(history[-1]["content"])
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                answer = chate.answer_question(
                    history[-1]["content"], df, profile, chat_history=history[:-1], api_key=api_key,
                )
            st.markdown(answer)
        history.append({"role": "assistant", "content": answer})
        st.rerun()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main() -> None:
    init_session_state()
    inject_global_css()
    inject_theme()
    st.markdown(EXTRA_CSS, unsafe_allow_html=True)

    template = st.session_state.get("template", "Auto")

    with st.sidebar:
        st.markdown(f"""
        <div style='margin-bottom:.75rem;padding:.75rem 0 .5rem'>
            <div style='font-size:1.5rem;font-weight:800;color:#e8edf5;letter-spacing:-.02em;line-height:1.1'>
                <span style='background:linear-gradient(120deg,#4f8ef7,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent'>◈</span>
                &nbsp;{t("app_title")}
            </div>
            <div style='font-size:.72rem;color:#556070;margin-top:4px;letter-spacing:.04em;text-transform:uppercase;font-weight:600'>{t("app_sub")}</div>
        </div>
        <div style='height:1px;background:rgba(255,255,255,0.06);margin:.25rem 0 1rem'></div>
        """, unsafe_allow_html=True)
        uploaded = st.file_uploader(t("upload_label"), type=["csv", "xlsx", "xls"], label_visibility="collapsed")

    if uploaded is None:
        st.markdown(f"""
        <div style='padding:2.5rem 0 1rem'>
            <div class='dash-title'>{t("app_title")}</div>
            <div class='dash-sub'>{t("upload_sub")}</div>
        </div>
        <div class='upload-wrapper'>
            <div class='upload-icon'>📂</div>
            <div class='upload-title'>{t("upload_title")}</div>
            <div class='upload-sub'>{t("upload_sub")}</div>
        </div>
        """, unsafe_allow_html=True)
        with st.sidebar:
            render_settings_panel()
        return

    # reset cached AI/chat state when a new file is uploaded
    if st.session_state.get("last_file_name") != uploaded.name:
        st.session_state.last_file_name = uploaded.name
        st.session_state.ai_charts = None
        st.session_state.ai_charts_cache_key = None
        st.session_state.insight_rewrite_cache_key = None
        st.session_state.ai_chat_history = []

    with st.spinner(t("analyzing")):
        try:
            df_raw = load_data(uploaded.getvalue(), uploaded.name)
        except Exception as exc:
            st.error(f"Could not load file: {exc}")
            return
        if df_raw.empty:
            st.warning("The uploaded file has no rows.")
            return
        df_raw, profile = profile_data(df_raw, template)

    maybe_warn_large_file(df_raw)

    with st.sidebar:
        render_settings_panel()
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"<div class='sidebar-section'>{t('filters')}</div>", unsafe_allow_html=True)
        df = re_ui.render_sidebar_filters(df_raw, profile.schema)

    api_key = get_active_api_key()
    health = ie.compute_health(df)
    file_label = uploaded.name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    dash_id = "DB-" + hashlib.md5(uploaded.name.encode()).hexdigest()[:8].upper()
    health_color = "#34d399" if health["score"] >= 75 else "#f59e0b" if health["score"] >= 50 else "#f87171"

    st.markdown(f"""
    <div class='sticky-header'>
        <div class='dash-title'>{file_label}</div>
        <div class='dash-sub'>{t("auto_dashboard")} &nbsp;·&nbsp; <span style='color:#4f8ef7;font-weight:600'>{template}</span></div>
        <div class='header-badges-row'>
            <span class='hbadge'>🆔 {dash_id}</span>
            <span class='hbadge-green'>📅 Created {now_str}</span>
            <span class='hbadge'>📦 {len(df):,} rows</span>
            <span class='hbadge'>⚙️ {len(df.columns)} cols</span>
            <span class='hbadge-amber'>🗂️ {profile.dataset_type}</span>
            <span class='hbadge' style='color:{health_color};border-color:{health_color}55;background:{health_color}14'>🩺 Health {health["score"]}/100 ({health["grade"]})</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tab_dashboard, tab_insights, tab_chat, tab_quality = st.tabs(
        ["📊 Dashboard", "🧭 AI Insights", "🤖 AI Analyst", "🩺 Data Quality"]
    )

    with tab_dashboard:
        kpis = ke.build_kpis(df, profile)
        render_kpi_cards(kpis)
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        figures = render_charts(df, profile, api_key)
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        re_ui.render_download_section(df, health, file_label, figures=figures)
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        re_ui.render_metadata(df, profile, health, uploaded.name, template)

    with tab_insights:
        render_ai_insight_page(df, profile, api_key)

    with tab_chat:
        render_chat_tab(df, profile, api_key)

    with tab_quality:
        re_ui.render_health_section(df, health)
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        re_ui.render_missing_analysis(df)
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        re_ui.render_duplicate_detection(df)
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        outliers = ie.detect_outliers(df, profile.schema["numeric"])
        re_ui.render_outlier_detection(df, profile.schema, outliers)
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        re_ui.render_correlation(df, profile.schema)


if __name__ == "__main__":
    main()
