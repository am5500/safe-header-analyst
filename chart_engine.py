"""
chart_engine.py
─────────────────────────────────────────────
The config-driven chart engine. Every chart on the dashboard is described
by a small dict:

    {
        "type": "bar",
        "x": "Country",
        "y": "Sales",
        "color": None,
        "title": "Sales by Country",
        "description": "...",
    }

`render_chart(df, config)` turns one of these into a Plotly figure (or
None + a warning if it can't be rendered) — nothing crashes the caller.

`build_rule_based_charts(df, profile)` is the deterministic rule engine
that produces a sensible `charts_config` list from a DatasetProfile,
with NO AI involved:

    Date + Numeric        -> line chart
    Category + Numeric    -> bar chart
    2 Numeric              -> scatter plot
    Single Numeric         -> histogram
    Categorical alone      -> pie / frequency chart
    Top N categories        -> horizontal bar

ai_engine.py is allowed to take this list and rename / reorder / drop
entries, or hand back its own list in the same shape — chart_engine
doesn't care who produced the config, only that it's well-formed. If
the AI-produced config is malformed or empty, callers should fall back
to build_rule_based_charts() (see ai_engine.suggest_chart_configs).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from utils import CHART_PALETTE, apply_template, safe_call, sample_for_plot

# Supported chart types — keep in sync with the dispatch table in
# render_chart() below and with any "type" enum exposed to the AI prompt.
SUPPORTED_CHART_TYPES = [
    "line", "bar", "barh", "pie", "scatter", "histogram", "box", "heatmap",
    "treemap", "funnel", "violin", "cumulative", "rolling_avg", "pareto",
]


# ─────────────────────────────────────────────
# INDIVIDUAL CHART RENDERERS
# Each returns a go.Figure or raises — callers always go through
# render_chart() / safe_call(), never call these directly from UI code.
# ─────────────────────────────────────────────
def _chart_line(df: pd.DataFrame, x: str, y: str, color: str | None, title: str) -> go.Figure:
    tmp = df[[c for c in [x, y, color] if c]].dropna(subset=[x, y])
    tmp[x] = pd.to_datetime(tmp[x])
    if color and color in tmp.columns:
        grp = tmp.groupby([pd.Grouper(key=x, freq="ME"), color], observed=True)[y].sum().reset_index()
        fig = px.line(grp, x=x, y=y, color=color, color_discrete_sequence=CHART_PALETTE, markers=True)
    else:
        grp = tmp.set_index(x).resample("ME")[y].sum().reset_index()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=grp[x], y=grp[y], mode="lines+markers", name=y,
            line=dict(color=CHART_PALETTE[0], width=2.5),
            marker=dict(size=6, color=CHART_PALETTE[0]),
            fill="tozeroy", fillcolor="rgba(79,142,247,0.10)",
            hovertemplate="<b>%{x|%b %Y}</b><br>" + y + ": <b>%{y:,.0f}</b><extra></extra>",
        ))
    return apply_template(fig, title or f"{y} Over Time")


def _chart_bar(df: pd.DataFrame, x: str, y: str, color: str | None, title: str, top_n: int = 15) -> go.Figure:
    grp = df.groupby(x, observed=True)[y].sum().nlargest(top_n).reset_index()
    grp = grp.sort_values(y, ascending=True)
    fig = px.bar(
        grp, x=y, y=x, orientation="h", color=y,
        color_continuous_scale=["#1a3060", "#4f8ef7", "#a78bfa"], text=y,
    )
    fig.update_traces(
        texttemplate="%{text:,.0f}", textposition="outside",
        hovertemplate="<b>%{y}</b><br>" + y + ": <b>%{x:,.0f}</b><extra></extra>",
        marker_line_width=0,
    )
    fig.update_layout(coloraxis_showscale=False, yaxis_title="", xaxis_title=y)
    return apply_template(fig, title or f"Top {top_n} {x} by {y}")


def _chart_histogram(df: pd.DataFrame, y: str, title: str) -> go.Figure:
    series = df[y].dropna()
    fig = px.histogram(series, nbins=30, color_discrete_sequence=[CHART_PALETTE[2]])
    fig.update_traces(
        marker_line_width=0, marker_line_color="rgba(0,0,0,0)",
        hovertemplate="Range: <b>%{x}</b><br>Count: <b>%{y}</b><extra></extra>",
    )
    fig.update_layout(yaxis_title="Count", xaxis_title=y, showlegend=False)
    return apply_template(fig, title or f"Distribution of {y}")


def _chart_pie(df: pd.DataFrame, x: str, y: str | None, title: str) -> go.Figure:
    if y:
        grp = df.groupby(x, observed=True)[y].sum().reset_index()
        values_col, names_col = y, x
    else:
        grp = df[x].value_counts().reset_index()
        grp.columns = [x, "count"]
        values_col, names_col = "count", x
    grp = grp.nlargest(10, values_col)
    fig = px.pie(grp, values=values_col, names=names_col, color_discrete_sequence=CHART_PALETTE, hole=0.42)
    fig.update_traces(
        textinfo="percent+label", textposition="outside",
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} (%{percent})<extra></extra>",
    )
    return apply_template(fig, title or (f"{x} Share" + (f" by {y}" if y else "")))


def _chart_scatter(df: pd.DataFrame, x: str, y: str, color: str | None, title: str) -> go.Figure:
    plot_df = sample_for_plot(df, max_rows=2000)
    if color and color in plot_df.columns and plot_df[color].nunique() <= 12:
        fig = px.scatter(plot_df, x=x, y=y, color=color, color_discrete_sequence=CHART_PALETTE)
    else:
        fig = px.scatter(plot_df, x=x, y=y, color_discrete_sequence=[CHART_PALETTE[0]])
    fig.update_traces(marker=dict(size=5, opacity=0.6))
    return apply_template(fig, title or f"{x} vs {y}")


def _chart_box(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    top = df[x].value_counts().nlargest(8).index
    tmp = df[df[x].isin(top)]
    fig = px.box(tmp, x=x, y=y, color=x, color_discrete_sequence=CHART_PALETTE, notched=True)
    fig.update_layout(showlegend=False, xaxis_tickangle=-30)
    return apply_template(fig, title or f"{y} Distribution by {x}")


def _chart_violin(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    top = df[x].value_counts().nlargest(6).index
    tmp = df[df[x].isin(top)]
    fig = px.violin(tmp, x=x, y=y, box=True, points=False, color=x, color_discrete_sequence=CHART_PALETTE)
    fig.update_layout(showlegend=False, xaxis_tickangle=-30)
    return apply_template(fig, title or f"{y} Violin by {x}")


def _chart_treemap(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    grp = df.groupby(x, observed=True)[y].sum().reset_index()
    fig = px.treemap(
        grp, path=[x], values=y, color=y,
        color_continuous_scale=["#0f1e40", "#4f8ef7", "#a78bfa"],
    )
    fig.update_traces(texttemplate="<b>%{label}</b><br>%{value:,.0f}", textfont=dict(size=13))
    fig.update_layout(coloraxis_showscale=False)
    return apply_template(fig, title or f"{y} Treemap by {x}")


def _chart_funnel(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    grp = df.groupby(x, observed=True)[y].sum().nlargest(8).reset_index().sort_values(y, ascending=False)
    fig = go.Figure(go.Funnel(
        y=grp[x], x=grp[y],
        marker=dict(color=CHART_PALETTE[: len(grp)], line=dict(width=0)),
        textinfo="value+percent total",
    ))
    return apply_template(fig, title or f"{y} Funnel by {x}")


def _chart_heatmap(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    """Monthly heatmap: x must be a date column, y a numeric measure."""
    tmp = df[[x, y]].dropna()
    tmp[x] = pd.to_datetime(tmp[x])
    tmp["Year"] = tmp[x].dt.year
    tmp["Month"] = tmp[x].dt.month_name().str[:3]
    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    pivot = tmp.pivot_table(index="Year", columns="Month", values=y, aggfunc="sum")
    pivot = pivot.reindex(columns=[m for m in month_order if m in pivot.columns])
    fig = px.imshow(
        pivot, color_continuous_scale=["#0f1e40", "#4f8ef7", "#a78bfa"],
        aspect="auto", text_auto=".0f",
    )
    fig.update_layout(coloraxis_showscale=False)
    return apply_template(fig, title or f"{y} by Month/Year")


def _chart_cumulative(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    tmp = df[[x, y]].dropna()
    tmp[x] = pd.to_datetime(tmp[x])
    tmp = tmp.set_index(x).resample("ME")[y].sum().cumsum().reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=tmp[x], y=tmp[y], mode="lines+markers", name=f"Cumulative {y}",
        line=dict(color=CHART_PALETTE[2], width=2.5), marker=dict(size=5),
        fill="tozeroy", fillcolor="rgba(52,211,153,0.10)",
        hovertemplate="<b>%{x|%b %Y}</b><br>Cumulative: <b>%{y:,.0f}</b><extra></extra>",
    ))
    return apply_template(fig, title or f"Cumulative {y}")


def _chart_rolling_avg(df: pd.DataFrame, x: str, y: str, title: str, window: int = 3) -> go.Figure:
    tmp = df[[x, y]].dropna()
    tmp[x] = pd.to_datetime(tmp[x])
    tmp = tmp.set_index(x).resample("ME")[y].sum().reset_index()
    tmp["rolling"] = tmp[y].rolling(window, min_periods=1).mean()
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=tmp[x], y=tmp[y], name=y, marker_color="rgba(79,142,247,0.35)", marker_line_width=0,
    ))
    fig.add_trace(go.Scatter(
        x=tmp[x], y=tmp["rolling"], name=f"{window}m Avg", line=dict(color=CHART_PALETTE[1], width=2.5),
    ))
    return apply_template(fig, title or f"{y} + {window}m Rolling Average")


def _chart_pareto(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    grp = df.groupby(x, observed=True)[y].sum().sort_values(ascending=False).head(15).reset_index()
    grp["cumulative_pct"] = grp[y].cumsum() / grp[y].sum() * 100
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=grp[x], y=grp[y], name=y, marker_color=CHART_PALETTE[0], marker_line_width=0,
        text=grp[y], texttemplate="%{text:,.0f}", textposition="outside",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=grp[x], y=grp["cumulative_pct"], name="Cumulative %",
        line=dict(color=CHART_PALETTE[3], width=2.5), marker=dict(size=6),
    ), secondary_y=True)
    fig.update_layout(xaxis_tickangle=-30)
    fig.update_yaxes(title_text=y, secondary_y=False)
    # Modern Plotly form — never use the deprecated `titlefont` kwarg here.
    fig.update_yaxes(
        title_text="Cumulative %", secondary_y=True, ticksuffix="%", range=[0, 110], showgrid=False,
        title_font=dict(color=CHART_PALETTE[3], size=12), tickfont=dict(color=CHART_PALETTE[3]),
    )
    return apply_template(fig, title or f"Pareto: {y} by {x}")


def _chart_cat_frequency(df: pd.DataFrame, x: str, title: str) -> go.Figure:
    grp = df[x].value_counts().nlargest(15).reset_index()
    grp.columns = [x, "count"]
    fig = px.bar(
        grp, x=x, y="count", color="count",
        color_continuous_scale=["#1a1f40", "#a78bfa"], text="count",
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside", marker_line_width=0)
    fig.update_layout(coloraxis_showscale=False, xaxis_tickangle=-30, showlegend=False)
    return apply_template(fig, title or f"{x} Frequency")


# ─────────────────────────────────────────────
# CONFIG-DRIVEN DISPATCH
# ─────────────────────────────────────────────
def render_chart(df: pd.DataFrame, config: dict[str, Any]) -> go.Figure | None:
    """Render a single chart from a config dict. Returns None on any
    failure or unsupported/incomplete config — never raises. UI code
    should check for None and show a warning card instead of a chart,
    never let an exception propagate up into the page render.
    """
    chart_type = (config.get("type") or "").lower()
    x = config.get("x")
    y = config.get("y")
    color = config.get("color")
    title = config.get("title") or ""

    if x and x not in df.columns:
        return None
    if y and y not in df.columns:
        return None
    if color and color not in df.columns:
        color = None

    # "bar" with no y means "category frequency count", a distinct
    # rendering path from "bar of an aggregated measure".
    if chart_type == "bar" and not y and x:
        return safe_call(_chart_cat_frequency, df, x, title, label="cat_frequency")

    def _dispatch() -> go.Figure | None:
        if chart_type == "line" and x and y:
            return _chart_line(df, x, y, color, title)
        if chart_type in ("bar", "barh") and x and y:
            return _chart_bar(df, x, y, color, title)
        if chart_type == "pie" and x:
            return _chart_pie(df, x, y, title)
        if chart_type == "scatter" and x and y:
            return _chart_scatter(df, x, y, color, title)
        if chart_type == "histogram" and (y or x):
            return _chart_histogram(df, y or x, title)
        if chart_type == "box" and x and y:
            return _chart_box(df, x, y, title)
        if chart_type == "violin" and x and y:
            return _chart_violin(df, x, y, title)
        if chart_type == "treemap" and x and y:
            return _chart_treemap(df, x, y, title)
        if chart_type == "funnel" and x and y:
            return _chart_funnel(df, x, y, title)
        if chart_type == "heatmap" and x and y:
            return _chart_heatmap(df, x, y, title)
        if chart_type == "cumulative" and x and y:
            return _chart_cumulative(df, x, y, title)
        if chart_type == "rolling_avg" and x and y:
            return _chart_rolling_avg(df, x, y, title)
        if chart_type == "pareto" and x and y:
            return _chart_pareto(df, x, y, title)
        return None

    return safe_call(_dispatch, label=f"render_chart[{chart_type}]")


# ─────────────────────────────────────────────
# RULE ENGINE — produces charts_config with NO AI involved
# ─────────────────────────────────────────────
def build_rule_based_charts(df: pd.DataFrame, profile) -> list[dict[str, Any]]:
    """Deterministic chart selection straight from the rule table in the
    spec:

        Date + Numeric      -> Line chart
        Category + Numeric  -> Bar chart
        2 Numeric           -> Scatter plot
        Single Numeric      -> Histogram
        Categorical alone   -> Pie chart
        Top N categories    -> Horizontal bar (frequency)

    Returns a `charts_config` list. This is the guaranteed-working
    fallback used whenever the AI layer is unavailable, slow, or returns
    something malformed — the dashboard must never depend on AI to
    produce *some* charts.
    """
    schema = profile.schema
    date_cols = schema.get("date", [])
    num_cols = schema.get("numeric", [])
    cat_cols = schema.get("categorical", [])
    primary = profile.primary_measure or (num_cols[0] if num_cols else None)
    secondary_cat = cat_cols[1] if len(cat_cols) > 1 else None

    configs: list[dict[str, Any]] = []

    if date_cols and primary:
        configs.append({
            "type": "line", "x": date_cols[0], "y": primary, "color": None,
            "title": f"{primary} Over Time",
            "description": f"Monthly trend of {primary}.",
        })

    if cat_cols and primary:
        configs.append({
            "type": "bar", "x": cat_cols[0], "y": primary, "color": None,
            "title": f"Top {cat_cols[0]} by {primary}",
            "description": f"Highest-performing {cat_cols[0]} segments ranked by {primary}.",
        })

    if len(num_cols) >= 2:
        x_num = num_cols[0] if num_cols[0] != primary else num_cols[1]
        y_num = primary or num_cols[-1]
        if x_num != y_num:
            configs.append({
                "type": "scatter", "x": x_num, "y": y_num,
                "color": cat_cols[0] if cat_cols else None,
                "title": f"{x_num} vs {y_num}",
                "description": f"Relationship between {x_num} and {y_num}.",
            })

    if primary:
        configs.append({
            "type": "histogram", "x": None, "y": primary, "color": None,
            "title": f"Distribution of {primary}",
            "description": f"How {primary} values are spread across the dataset.",
        })

    if cat_cols:
        cat_for_pie = secondary_cat or cat_cols[0]
        if df[cat_for_pie].nunique() <= 12:
            configs.append({
                "type": "pie", "x": cat_for_pie, "y": primary, "color": None,
                "title": f"{cat_for_pie} Share" + (f" by {primary}" if primary else ""),
                "description": f"Proportional breakdown of {cat_for_pie}.",
            })
        configs.append({
            "type": "bar", "x": cat_for_pie, "y": None, "color": None,
            "title": f"{cat_for_pie} Frequency (Top N)",
            "description": f"Most frequent {cat_for_pie} values.",
        })

    if date_cols and primary:
        configs.append({
            "type": "rolling_avg", "x": date_cols[0], "y": primary, "color": None,
            "title": f"{primary} Trend + Rolling Average",
            "description": f"Smoothed trend line for {primary}.",
        })

    if cat_cols and primary and len(configs) < 8:
        configs.append({
            "type": "pareto", "x": cat_cols[0], "y": primary, "color": None,
            "title": f"Pareto: {primary} by {cat_cols[0]}",
            "description": f"Cumulative contribution of {cat_cols[0]} segments to total {primary}.",
        })

    if not configs:
        # absolute last resort fallback so the dashboard never shows nothing
        if num_cols:
            configs.append({"type": "histogram", "x": None, "y": num_cols[0], "title": f"Distribution of {num_cols[0]}"})
        elif cat_cols:
            configs.append({"type": "bar", "x": cat_cols[0], "y": None, "title": f"{cat_cols[0]} Frequency"})

    return configs


def validate_chart_configs(df: pd.DataFrame, configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out configs referencing columns that don't exist in `df`,
    or missing required fields for their type. Used to sanity-check
    AI-produced configs before they ever reach render_chart — keeps
    the AI layer's "must include x/y/title/type" contract enforced in
    one place rather than scattered across callers.
    """
    valid: list[dict[str, Any]] = []
    for cfg in configs:
        if not isinstance(cfg, dict):
            continue
        ctype = (cfg.get("type") or "").lower()
        if ctype not in SUPPORTED_CHART_TYPES:
            continue
        x, y = cfg.get("x"), cfg.get("y")
        if x and x not in df.columns:
            continue
        if y and y not in df.columns:
            continue
        if not x and not y:
            continue
        valid.append(cfg)
    return valid
