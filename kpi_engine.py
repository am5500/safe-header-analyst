"""
kpi_engine.py
─────────────────────────────────────────────
Generates KPI cards whose *names* adapt to what the dataset actually
contains — Revenue / Profit / Orders / Customers / Average Order Value /
Growth %, but only when the corresponding semantic role was detected.
There is no hardcoded "always show Revenue" — if there's no revenue-like
column, there's no Revenue KPI; we generate the next most meaningful card
instead.

Trend % is computed from real month-over-month or period-over-period
deltas on the primary measure when a date column exists. No fabricated
or randomized trend numbers.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from utils import fmt_number, CHART_PALETTE


def _safe_sum(df: pd.DataFrame, col: str) -> float:
    try:
        return float(df[col].sum())
    except Exception:
        return 0.0


def _safe_mean(df: pd.DataFrame, col: str) -> float:
    try:
        return float(df[col].mean())
    except Exception:
        return 0.0


def _trend_for_measure(df: pd.DataFrame, date_col: str | None, measure: str | None) -> tuple[float | None, bool | None]:
    """Real period-over-period % change for `measure`, using the last two
    resampled months. Returns (None, None) if there isn't enough data —
    never a made-up number.
    """
    if not date_col or not measure:
        return None, None
    try:
        tmp = df[[date_col, measure]].dropna()
        tmp[date_col] = pd.to_datetime(tmp[date_col])
        monthly = tmp.set_index(date_col).resample("ME")[measure].sum()
        monthly = monthly[monthly.index.notna()]
        if len(monthly) < 2:
            return None, None
        prev, curr = monthly.iloc[-2], monthly.iloc[-1]
        if abs(prev) < 1e-9:
            return None, None
        pct = (curr - prev) / abs(prev) * 100
        return round(float(pct), 1), pct >= 0
    except Exception:
        return None, None


def build_kpis(df: pd.DataFrame, profile, max_kpis: int = 8) -> list[dict[str, Any]]:
    """Build the KPI card list, adapting names/values to detected
    semantic roles instead of hardcoding business terms.

    Each KPI dict: {"label", "value", "sub", "color", "trend_pct", "trend_up"}.
    `trend_pct`/`trend_up` are None when there isn't enough data for a
    real trend (never fabricated).
    """
    schema = profile.schema
    roles = profile.semantic_roles
    date_col = schema["date"][0] if schema["date"] else None
    primary = profile.primary_measure
    colors = CHART_PALETTE

    kpis: list[dict[str, Any]] = []
    used_cols: set[str] = set()

    def add(label: str, value: str, sub: str, source_col: str | None = None, trend: tuple | None = None):
        t_pct, t_up = trend if trend else (None, None)
        kpis.append({
            "label": label, "value": value, "sub": sub,
            "color": colors[len(kpis) % len(colors)],
            "trend_pct": t_pct, "trend_up": t_up,
        })
        if source_col:
            used_cols.add(source_col)

    # 1. Always-present baseline KPI: row count.
    add("Total Records", fmt_number(len(df)), "rows in dataset")

    # 2. Revenue / primary measure (whichever the dataset actually has).
    revenue_cols = roles.get("revenue", [])
    if revenue_cols:
        col = revenue_cols[0]
        total = _safe_sum(df, col)
        add(
            "Total Revenue", fmt_number(total), f"avg {fmt_number(_safe_mean(df, col))}",
            source_col=col, trend=_trend_for_measure(df, date_col, col),
        )
    elif primary and primary not in used_cols:
        col = primary
        total = _safe_sum(df, col)
        add(
            f"Total {col}", fmt_number(total), f"avg {fmt_number(_safe_mean(df, col))}",
            source_col=col, trend=_trend_for_measure(df, date_col, col),
        )

    # 3. Profit, if present and distinct from what we already showed.
    profit_cols = [c for c in roles.get("profit", []) if c not in used_cols]
    if profit_cols and len(kpis) < max_kpis:
        col = profit_cols[0]
        total = _safe_sum(df, col)
        add(
            "Total Profit", fmt_number(total), f"avg {fmt_number(_safe_mean(df, col))}",
            source_col=col, trend=_trend_for_measure(df, date_col, col),
        )

    # 4. Orders / transaction count, if an order-like or id-like role exists.
    order_cols = [c for c in roles.get("order", []) if c not in used_cols]
    if order_cols and len(kpis) < max_kpis:
        col = order_cols[0]
        count = int(df[col].nunique()) if col in schema["id"] or col in schema["categorical"] else len(df)
        add("Total Orders", fmt_number(count), "unique orders/transactions", source_col=col)
    elif schema["id"] and len(kpis) < max_kpis:
        col = schema["id"][0]
        add("Total Orders", fmt_number(int(df[col].nunique())), "unique records", source_col=col)

    # 5. Customers, if a customer-like role exists.
    customer_cols = [c for c in roles.get("customer", []) if c not in used_cols]
    if customer_cols and len(kpis) < max_kpis:
        col = customer_cols[0]
        add("Total Customers", fmt_number(int(df[col].nunique())), "unique customers", source_col=col)

    # 6. Average Order Value — only meaningful if we have both a revenue-like
    #    measure and a count of orders/rows to divide by.
    if revenue_cols and len(kpis) < max_kpis:
        rev_col = revenue_cols[0]
        denom = len(df)
        if order_cols:
            try:
                denom = max(int(df[order_cols[0]].nunique()), 1)
            except Exception:
                denom = len(df)
        aov = _safe_sum(df, rev_col) / max(denom, 1)
        add("Avg Order Value", fmt_number(aov), f"per {'order' if order_cols else 'record'}")

    # 7. Growth % — period-over-period change of the primary measure,
    #    surfaced explicitly as its own KPI (not just a trend arrow).
    if primary and date_col and len(kpis) < max_kpis:
        pct, up = _trend_for_measure(df, date_col, primary)
        if pct is not None:
            add(
                "Growth %", f"{'+' if up else ''}{pct:.1f}%",
                f"{primary} vs. previous period", trend=(pct, up),
            )

    # 8. Fill remaining slots with secondary numeric averages, then
    #    categorical cardinality, then date range — same fallback
    #    ladder as before, but only if we still have room.
    for col in schema["numeric"]:
        if len(kpis) >= max_kpis:
            break
        if col in used_cols or col == primary:
            continue
        add(f"Avg {col}", fmt_number(_safe_mean(df, col)), f"max {fmt_number(df[col].max())}", source_col=col)

    for col in schema["categorical"]:
        if len(kpis) >= max_kpis:
            break
        if col in used_cols:
            continue
        add(f"Unique {col}", fmt_number(int(df[col].nunique())), "distinct values", source_col=col)

    if date_col and len(kpis) < max_kpis:
        mn, mx = df[date_col].min(), df[date_col].max()
        if pd.notna(mn) and pd.notna(mx):
            add("Date Range", f"{(mx - mn).days} d", f"{mn:%b %Y} – {mx:%b %Y}")

    return kpis[:max_kpis]
