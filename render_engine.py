"""
render_engine.py
─────────────────────────────────────────────
Streamlit rendering helpers for the data-quality / exploration sections
of the dashboard (sidebar filters, health score, missing-values,
duplicates, outliers, correlation, metadata, export). Visual design is
ported from the original app (same CSS classes from theme.py, same
glass-card layout) — only the data plumbing underneath was rewritten to
use dataset_profiler / insight_engine instead of ad-hoc recomputation.

Kept separate from app.py so app.py stays a thin orchestration layer.
"""

from __future__ import annotations

import datetime
import hashlib
import io
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from theme import section_header, t
from utils import apply_template, CHART_PALETTE


# ─────────────────────────────────────────────
# SIDEBAR FILTERS
# ─────────────────────────────────────────────
def render_sidebar_filters(df: pd.DataFrame, schema: dict[str, list[str]]) -> pd.DataFrame:
    st.sidebar.markdown("## ⚙ Filters")
    filtered = df.copy()

    if schema["date"]:
        dcol = schema["date"][0]
        dates = pd.to_datetime(filtered[dcol].dropna())
        if not dates.empty:
            mn, mx = dates.min().date(), dates.max().date()
            sel = st.sidebar.date_input(
                "Date Range", value=(mn, mx), min_value=mn, max_value=mx, key="date_range"
            )
            if isinstance(sel, (list, tuple)) and len(sel) == 2:
                start, end = pd.Timestamp(sel[0]), pd.Timestamp(sel[1])
                mask = (pd.to_datetime(filtered[dcol]) >= start) & (pd.to_datetime(filtered[dcol]) <= end)
                filtered = filtered[mask]

    shown = 0
    for col in schema["categorical"]:
        if shown >= 5:
            break
        vals = sorted(df[col].dropna().unique().tolist())
        if 1 < len(vals) <= 100:
            sel = st.sidebar.multiselect(col, vals, default=[], key=f"filter_{col}")
            if sel:
                filtered = filtered[filtered[col].isin(sel)]
            shown += 1

    if schema["numeric"]:
        num_col = schema["numeric"][0]
        col_data = df[num_col].dropna()
        if not col_data.empty:
            mn, mx = float(col_data.min()), float(col_data.max())
            if mn < mx:
                sel = st.sidebar.slider(f"{num_col} Range", mn, mx, (mn, mx), key=f"slider_{num_col}")
                filtered = filtered[(filtered[num_col] >= sel[0]) & (filtered[num_col] <= sel[1])]

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"<div style='color:#64748b;font-size:.8rem;'>Showing "
        f"<b style='color:#e2e8f0'>{len(filtered):,}</b> of {len(df):,} rows</div>",
        unsafe_allow_html=True,
    )
    return filtered


# ─────────────────────────────────────────────
# HEALTH SECTION
# ─────────────────────────────────────────────
def render_health_section(df: pd.DataFrame, health: dict[str, Any]) -> None:
    section_header(t("health"), t("health_badge"))
    c1, c2, c3 = st.columns([1, 2, 2])
    with c1:
        color = health["color"]
        st.markdown(f"""
        <div class='glass-card' style='text-align:center;padding:1.5rem 1rem'>
            <div class='score-badge' style='color:{color}'>{health["score"]}</div>
            <div style='font-size:2rem;font-weight:800;color:{color};line-height:1'>{health["grade"]}</div>
            <div style='font-size:.75rem;color:var(--muted);margin-top:.4rem'>Health Score</div>
            <div class='health-bar-bg' style='margin-top:.75rem'>
                <div class='health-bar-fill' style='width:{health["score"]}%;background:{color}'></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class='glass-card'>
            <div style='font-size:.8rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.75rem'>Completeness</div>
            <div class='stat-row'><span class='stat-label'>Total Cells</span><span class='stat-value'>{health["total_cells"]:,}</span></div>
            <div class='stat-row'><span class='stat-label'>Missing Cells</span><span class='stat-value'>{health["missing_cells"]:,}</span></div>
            <div class='stat-row'><span class='stat-label'>Missing %</span><span class='stat-value' style='color:{"#f87171" if health["missing_pct"]>10 else "#34d399"}'>{health["missing_pct"]}%</span></div>
            <div class='stat-row'><span class='stat-label'>Rows</span><span class='stat-value'>{len(df):,}</span></div>
            <div class='stat-row'><span class='stat-label'>Columns</span><span class='stat-value'>{len(df.columns)}</span></div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class='glass-card'>
            <div style='font-size:.8rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.75rem'>Uniqueness & Size</div>
            <div class='stat-row'><span class='stat-label'>Duplicate Rows</span><span class='stat-value' style='color:{"#f87171" if health["dup_rows"]>0 else "#34d399"}'>{health["dup_rows"]:,}</span></div>
            <div class='stat-row'><span class='stat-label'>Duplicate %</span><span class='stat-value'>{health["dup_pct"]}%</span></div>
            <div class='stat-row'><span class='stat-label'>Unique Rows</span><span class='stat-value'>{len(df) - health["dup_rows"]:,}</span></div>
            <div class='stat-row'><span class='stat-label'>Memory (KB)</span><span class='stat-value'>{df.memory_usage(deep=True).sum() // 1024:,}</span></div>
            <div class='stat-row'><span class='stat-label'>Numeric Cols</span><span class='stat-value'>{len(df.select_dtypes(include="number").columns)}</span></div>
        </div>
        """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MISSING VALUES
# ─────────────────────────────────────────────
def render_missing_analysis(df: pd.DataFrame) -> None:
    section_header(t("missing"), "Quality")
    miss = df.isna().sum()
    miss = miss[miss > 0].sort_values(ascending=False)
    if miss.empty:
        st.success("✅ No missing values found in this dataset.")
        return
    miss_df = pd.DataFrame({
        "Column": miss.index, "Missing": miss.values,
        "Pct (%)": (miss.values / len(df) * 100).round(2),
    })
    c1, c2 = st.columns([2, 3])
    with c1:
        st.dataframe(miss_df, width="stretch", height=260)
    with c2:
        fig = px.bar(
            miss_df.sort_values("Missing", ascending=True),
            x="Missing", y="Column", orientation="h", color="Pct (%)",
            color_continuous_scale=["#34d399", "#f59e0b", "#f87171"], text="Pct (%)",
        )
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(coloraxis_showscale=False, yaxis_title="", xaxis_title="Missing Count")
        st.plotly_chart(apply_template(fig, "🔍 Missing Values per Column"), width="stretch")


# ─────────────────────────────────────────────
# DUPLICATE DETECTION
# ─────────────────────────────────────────────
def render_duplicate_detection(df: pd.DataFrame) -> None:
    section_header(t("duplicates"), "Integrity")
    dup_mask = df.duplicated(keep=False)
    n_dups = df.duplicated().sum()
    col1, col2 = st.columns([1, 3])
    with col1:
        color = "#f87171" if n_dups > 0 else "#34d399"
        st.markdown(f"""
        <div class='glass-card' style='text-align:center;padding:1.2rem'>
            <div style='font-size:2rem;font-weight:800;color:{color}'>{n_dups:,}</div>
            <div style='font-size:.8rem;color:var(--muted)'>Duplicate Rows</div>
            <div style='font-size:.75rem;color:{color};margin-top:.3rem'>{n_dups/max(len(df),1)*100:.2f}% of total</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        if n_dups > 0:
            with st.expander(f"Show {min(n_dups, 50)} duplicate rows", expanded=False):
                st.dataframe(df[dup_mask].head(50), width="stretch", height=220)
        else:
            st.success("✅ No duplicate rows detected.")
    uniq = pd.DataFrame({
        "Column": df.columns,
        "Unique Values": [df[c].nunique() for c in df.columns],
        "Uniqueness %": [(df[c].nunique() / max(len(df), 1) * 100) for c in df.columns],
    }).sort_values("Uniqueness %", ascending=False)
    fig = px.bar(
        uniq, x="Column", y="Uniqueness %", color="Uniqueness %",
        color_continuous_scale=["#f87171", "#f59e0b", "#34d399"], text="Uniqueness %",
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside", marker_line_width=0)
    fig.update_layout(coloraxis_showscale=False, xaxis_tickangle=-35)
    st.plotly_chart(apply_template(fig, "🔁 Column Uniqueness (%)"), width="stretch")


# ─────────────────────────────────────────────
# OUTLIER DETECTION
# ─────────────────────────────────────────────
def render_outlier_detection(df: pd.DataFrame, schema: dict[str, list[str]], outliers: list[dict[str, Any]]) -> None:
    section_header(t("outliers"), "Statistics")
    if not outliers:
        st.info("No numeric columns available for outlier analysis.")
        return
    out_df = pd.DataFrame([{
        "Column": o["column"], "IQR Outliers": o["iqr_outliers"], "Z-Score Outliers": o["zscore_outliers"],
        "Min": o["min"], "Max": o["max"], "Mean": o["mean"], "Std": o["std"],
    } for o in outliers])
    c1, c2 = st.columns([3, 2])
    with c1:
        st.dataframe(out_df, width="stretch", height=280)
    with c2:
        fig = px.bar(
            out_df, x="Column", y="IQR Outliers", color="IQR Outliers",
            color_continuous_scale=["#34d399", "#f59e0b", "#f87171"], text="IQR Outliers",
        )
        fig.update_traces(texttemplate="%{text}", textposition="outside", marker_line_width=0)
        fig.update_layout(coloraxis_showscale=False, xaxis_tickangle=-35)
        st.plotly_chart(apply_template(fig, "📐 Outliers per Column (IQR)"), width="stretch")
    top_out_cols = out_df.sort_values("IQR Outliers", ascending=False)["Column"].tolist()[:2]
    if top_out_cols:
        cols = st.columns(len(top_out_cols))
        for i, col in enumerate(top_out_cols):
            with cols[i]:
                fig = px.box(df, y=col, color_discrete_sequence=[CHART_PALETTE[i % len(CHART_PALETTE)]])
                fig.update_layout(yaxis_title=col)
                st.plotly_chart(apply_template(fig, f"{col} Box Plot"), width="stretch")


# ─────────────────────────────────────────────
# CORRELATION
# ─────────────────────────────────────────────
def render_correlation(df: pd.DataFrame, schema: dict[str, list[str]]) -> None:
    section_header(t("correlation"), "Statistics")
    num_cols = schema["numeric"]
    if len(num_cols) < 2:
        st.info("Need at least 2 numeric columns for correlation analysis.")
        return
    corr = df[num_cols].corr()
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.imshow(
            corr, color_continuous_scale=["#f87171", "rgba(20,24,36,0.9)", "#4f8ef7"],
            zmin=-1, zmax=1, aspect="auto", text_auto=".2f",
        )
        fig.update_traces(
            textfont_size=11, hovertemplate="<b>%{x}</b> × <b>%{y}</b><br>r = <b>%{z:.3f}</b><extra></extra>",
        )
        fig.update_layout(coloraxis_colorbar=dict(title="r", tickvals=[-1, 0, 1]))
        st.plotly_chart(apply_template(fig, "🔗 Correlation Heatmap"), width="stretch")
    with c2:
        corr_pairs = (
            corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool)).stack().reset_index()
        )
        corr_pairs.columns = ["Col A", "Col B", "r"]
        corr_pairs["abs_r"] = corr_pairs["r"].abs()
        corr_pairs = corr_pairs.sort_values("abs_r", ascending=False).head(10)
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:.8rem;font-weight:600;color:var(--muted);"
            "text-transform:uppercase;letter-spacing:.07em;margin-bottom:.75rem'>Top Correlations</div>",
            unsafe_allow_html=True,
        )
        for _, row in corr_pairs.iterrows():
            color = "#4f8ef7" if row["r"] > 0 else "#f87171"
            st.markdown(f"""
            <div class='stat-row'>
                <span class='stat-label' style='font-size:.75rem'>{row["Col A"]} × {row["Col B"]}</span>
                <span class='stat-value' style='color:{color}'>{row["r"]:.3f}</span>
            </div>""", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# METADATA
# ─────────────────────────────────────────────
def render_metadata(df: pd.DataFrame, profile, health: dict[str, Any], file_label: str, template: str) -> None:
    section_header(t("metadata"), "Info")
    schema = profile.schema
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    dash_id = "DB-" + hashlib.md5(file_label.encode()).hexdigest()[:8].upper()
    items = [
        ("📁 File Name", file_label),
        ("🆔 Dashboard ID", dash_id),
        ("📅 Creation Date", now),
        ("🔄 Last Update", now),
        ("📊 Template", template),
        ("🗂️ Dataset Type", profile.dataset_type),
        ("📦 Total Rows", f"{len(df):,}"),
        ("⚙️ Columns", str(len(df.columns))),
        ("🔢 Numeric Cols", str(len(schema["numeric"]))),
        ("🏷️ Categorical Cols", str(len(schema["categorical"]))),
        ("📅 Date Cols", str(len(schema["date"]))),
        ("🩺 Health Score", f"{health['score']}/100 (Grade {health['grade']})"),
        ("❌ Missing Cells", f"{health['missing_cells']:,} ({health['missing_pct']}%)"),
        ("🔁 Duplicate Rows", f"{health['dup_rows']:,} ({health['dup_pct']}%)"),
        ("💾 Memory", f"{df.memory_usage(deep=True).sum() // 1024:,} KB"),
    ]
    grid_html = "<div class='meta-info-grid'>" + "".join(
        f"<div class='meta-info-item'><div class='meta-info-label'>{label}</div>"
        f"<div class='meta-info-value'>{val}</div></div>"
        for label, val in items
    ) + "</div>"
    st.markdown(grid_html, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# EXPORT (CSV / Excel / PDF-as-printable-HTML / PNG charts)
# ─────────────────────────────────────────────
def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _to_excel_bytes(df: pd.DataFrame, health: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
        summary = pd.DataFrame({
            "Metric": ["Rows", "Columns", "Missing Cells", "Duplicate Rows", "Health Score"],
            "Value": [len(df), len(df.columns), health["missing_cells"], health["dup_rows"], health["score"]],
        })
        summary.to_excel(writer, index=False, sheet_name="Summary")
    return buf.getvalue()


def _to_pdf_bytes(df: pd.DataFrame, health: dict[str, Any], label: str) -> bytes:
    """A print-ready HTML report. Opening it and using the browser's
    Ctrl+P / 'Save as PDF' produces a genuine PDF without adding a heavy
    PDF-rendering dependency to the app — same approach as the original.
    """
    rows_html = df.head(50).to_html(index=False, border=0, classes="pdf-table")
    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<style>
body {{ font-family: Arial, sans-serif; font-size: 12px; color: #1a202c; padding: 2rem; }}
h1 {{ color: #4f8ef7; }} h2 {{ color: #718096; font-size:14px; }}
.pdf-table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
.pdf-table th {{ background: #4f8ef7; color: white; padding: 6px 10px; text-align: left; }}
.pdf-table td {{ padding: 5px 10px; border-bottom: 1px solid #e2e8f0; }}
.stats {{ display: flex; gap: 2rem; margin: 1rem 0; flex-wrap: wrap; }}
.stat {{ padding: .5rem 1rem; background: #f0f4f8; border-radius: 8px; }}
</style></head><body>
<h1>{label} — Dashboard Report</h1>
<div class='stats'>
  <div class='stat'><b>Rows:</b> {len(df):,}</div>
  <div class='stat'><b>Columns:</b> {len(df.columns)}</div>
  <div class='stat'><b>Health Score:</b> {health["score"]}/100</div>
  <div class='stat'><b>Missing:</b> {health["missing_pct"]}%</div>
  <div class='stat'><b>Duplicates:</b> {health["dup_rows"]}</div>
</div>
<h2>Data Preview (first 50 rows)</h2>
{rows_html}
<p style='color:#718096;margin-top:2rem;font-size:11px'>Generated by Dynamic Dashboard</p>
</body></html>"""
    return html.encode("utf-8")


def render_download_section(
    df: pd.DataFrame, health: dict[str, Any], file_label: str, figures: dict[str, Any] | None = None,
) -> None:
    """CSV / Excel / printable-HTML(PDF) / per-chart PNG export.

    `figures` is an optional {title: go.Figure} map of the charts
    currently on screen — when provided, a PNG download is offered for
    each (requires the `kaleido` package; if it's missing, that's
    surfaced as a one-line note instead of crashing the export section).
    """
    section_header(t("download"), "Export")
    c1, c2, c3 = st.columns(3)
    safe_label = file_label.replace(" ", "_")
    with c1:
        st.download_button(
            label=f"⬇ {t('dl_csv')}", data=_to_csv_bytes(df),
            file_name=f"{safe_label}.csv", mime="text/csv", width="stretch",
        )
    with c2:
        st.download_button(
            label=f"⬇ {t('dl_excel')}", data=_to_excel_bytes(df, health),
            file_name=f"{safe_label}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    with c3:
        st.download_button(
            label=f"⬇ {t('dl_pdf')}", data=_to_pdf_bytes(df, health, file_label),
            file_name=f"{safe_label}_report.html", mime="text/html", width="stretch",
        )
    st.caption("PDF export is a print-ready HTML report — open it and use Ctrl+P → Save as PDF.")

    if figures:
        st.markdown("##### Export Individual Charts (PNG)")
        png_cols = st.columns(min(len(figures), 4) or 1)
        kaleido_missing = False
        for i, (title, fig) in enumerate(figures.items()):
            if kaleido_missing:
                break
            with png_cols[i % len(png_cols)]:
                try:
                    png_bytes = fig.to_image(format="png", scale=2)
                    st.download_button(
                        label=f"🖼️ {title[:24]}", data=png_bytes,
                        file_name=f"{title.replace(' ', '_')[:40]}.png", mime="image/png",
                        width="stretch", key=f"png_{i}_{title[:20]}",
                    )
                except Exception:
                    st.caption("PNG export needs the `kaleido` package (`pip install kaleido`).")
                    kaleido_missing = True
