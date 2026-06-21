"""
utils.py
─────────────────────────────────────────────
Shared, dependency-light helpers used across every engine module:
  • number formatting
  • the shared Plotly dark theme / palette
  • a safe-execution wrapper so a single bad chart/insight never
    crashes the dashboard
  • light sampling helpers for large dataframes

No Streamlit imports live here on purpose — keeping this module
free of `st` means every other engine (profiler, kpi, insight, ai,
chat) can be unit-tested without a running Streamlit session.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

import pandas as pd

logger = logging.getLogger("dashboard_saas")

T = TypeVar("T")

# ─────────────────────────────────────────────
# COLOR PALETTE / PLOTLY THEME
# ─────────────────────────────────────────────
CHART_PALETTE: list[str] = [
    "#4f8ef7", "#a78bfa", "#34d399", "#f59e0b", "#f87171",
    "#38bdf8", "#fb923c", "#e879f9", "#a3e635", "#2dd4bf",
]

PLOTLY_LAYOUT: dict[str, Any] = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter", color="#94a3b8", size=13),
    margin=dict(l=20, r=20, t=52, b=30),
    legend=dict(
        bgcolor="rgba(13,15,20,0.7)",
        bordercolor="rgba(255,255,255,0.08)",
        borderwidth=1,
        font=dict(size=12, color="#c4cdd8"),
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
    xaxis=dict(
        gridcolor="rgba(255,255,255,0.04)",
        zerolinecolor="rgba(255,255,255,0.06)",
        tickfont=dict(size=12),
        title_font=dict(size=13),
    ),
    yaxis=dict(
        gridcolor="rgba(255,255,255,0.04)",
        zerolinecolor="rgba(255,255,255,0.06)",
        tickfont=dict(size=12),
        title_font=dict(size=13),
    ),
    colorway=CHART_PALETTE,
    hoverlabel=dict(
        bgcolor="#181d2a",
        bordercolor="rgba(255,255,255,0.12)",
        font=dict(family="Inter", size=13, color="#e8edf5"),
    ),
)


def apply_template(fig, title: str = ""):
    """Apply the shared dark Plotly theme to any figure.

    Uses the modern `title=dict(text=..., font=dict(...))` form.
    Never use the deprecated `titlefont` kwarg anywhere else in the
    codebase — Plotly >= 5.x raises/ignores it inconsistently across
    versions, so we standardize on the dict form everywhere.
    """
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title=dict(
            text=title,
            font=dict(color="#e8edf5", size=17, family="Inter"),
            x=0,
            xref="paper",
            pad=dict(l=4),
        ),
        height=400,
    )
    return fig


# ─────────────────────────────────────────────
# NUMBER FORMATTING
# ─────────────────────────────────────────────
def fmt_number(n: Any, is_percent: bool = False) -> str:
    """Human-friendly number formatting (1.2M, 3.4K, etc.)."""
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return "—"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if is_percent:
        return f"{n:.1f}%"
    if abs(n) >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}K"
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.2f}"


# ─────────────────────────────────────────────
# SAFE EXECUTION
# ─────────────────────────────────────────────
def safe_call(
    func: Callable[..., T],
    *args: Any,
    default: T | None = None,
    on_error: Callable[[Exception], None] | None = None,
    label: str | None = None,
    **kwargs: Any,
) -> T | None:
    """Run `func`, swallowing any exception and returning `default` instead.

    This is the single choke point used by chart_engine / insight_engine /
    kpi_engine to guarantee one broken chart or one broken stat never takes
    down the rest of the dashboard. `on_error` lets callers (e.g. Streamlit
    UI code) surface a warning without each call site re-implementing
    try/except.
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - intentionally broad, this is a safety net
        logger.warning("safe_call failed for %s: %s", label or getattr(func, "__name__", func), exc)
        if on_error is not None:
            try:
                on_error(exc)
            except Exception:  # noqa: BLE001
                pass
        return default


# ─────────────────────────────────────────────
# SAMPLING / PERFORMANCE HELPERS
# ─────────────────────────────────────────────
def sample_for_plot(df: pd.DataFrame, max_rows: int = 5000, random_state: int = 42) -> pd.DataFrame:
    """Down-sample a dataframe for scatter/point-heavy charts.

    Aggregated charts (bar/line/pie) operate on groupby sums, which are
    cheap even at millions of rows, so they don't need this. This helper
    is specifically for charts that plot raw rows (scatter, violin points).
    """
    if len(df) <= max_rows:
        return df
    return df.sample(n=max_rows, random_state=random_state)


def memory_mb(df: pd.DataFrame) -> float:
    """Approximate memory footprint of a dataframe, in MB."""
    return round(df.memory_usage(deep=True).sum() / (1024 * 1024), 2)


def downcast_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """In-place-ish numeric downcast to shrink memory for large files.

    Safe for dashboard purposes: we only need values for aggregation and
    plotting, not bit-exact dtype preservation. Strings/categoricals are
    left untouched (categorical conversion is handled by the profiler
    where it has the column-cardinality context to decide).
    """
    for col in df.select_dtypes(include=["int64", "int32"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="float")
    return df
