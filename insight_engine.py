"""
insight_engine.py
─────────────────────────────────────────────
Rule-based business intelligence over the dataframe. Every number quoted
in every insight is computed directly from df statistics — nothing here
is a generic templated sentence with no data behind it. This is the
"hybrid system" rule-engine half described in the spec: it works
completely standalone (no AI required), and ai_engine.py is only ever
used afterward to *rewrite the wording* of these facts, never to
invent the facts themselves.

Sections produced (matches the spec's "AI Insight Page" redesign):
  • executive_summary   – headline cards (best/worst category, totals, health)
  • business_insights   – general analytical observations
  • risk_detection       – data-quality / concentration / volatility risks
  • opportunities        – under-served segments, growth pockets
  • outliers              – statistical outliers, with concrete row counts
  • recommendations       – actionable next steps tied to the above
  • trend_analysis        – month-over-month / period direction, with numbers
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from utils import fmt_number


# ─────────────────────────────────────────────
# HEALTH SCORE (dataset quality)
# ─────────────────────────────────────────────
def compute_health(df: pd.DataFrame) -> dict[str, Any]:
    total_cells = df.shape[0] * df.shape[1]
    missing_cells = int(df.isna().sum().sum())
    missing_pct = missing_cells / (total_cells + 1e-9)
    dup_rows = int(df.duplicated().sum())
    dup_pct = dup_rows / (len(df) + 1e-9)

    completeness = max(0, 40 * (1 - missing_pct * 2))
    uniqueness = max(0, 30 * (1 - dup_pct * 3))
    numeric_cols = df.select_dtypes(include="number").columns
    cat_cols = df.select_dtypes(include=["object", "category"]).columns
    diversity = min(15, 5 * (int(len(numeric_cols) > 0) + int(len(cat_cols) > 0) + int(len(df.columns) >= 4)))
    row_score = min(15, 15 * min(len(df) / 500, 1)) if len(df) else 0

    score = int(max(0, min(100, completeness + uniqueness + diversity + row_score)))
    color = "#34d399" if score >= 75 else "#f59e0b" if score >= 50 else "#f87171"
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "F"

    return {
        "score": score, "grade": grade, "color": color,
        "missing_pct": round(missing_pct * 100, 2),
        "missing_cells": missing_cells,
        "dup_rows": dup_rows,
        "dup_pct": round(dup_pct * 100, 2),
        "total_cells": total_cells,
    }


# ─────────────────────────────────────────────
# OUTLIER DETECTION
# ─────────────────────────────────────────────
def detect_outliers(df: pd.DataFrame, numeric_cols: list[str], max_cols: int = 10) -> list[dict[str, Any]]:
    results = []
    for col in numeric_cols[:max_cols]:
        s = df[col].dropna()
        if s.empty or len(s) < 5:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        n_iqr = int(((s < lower) | (s > upper)).sum())
        z = (s - s.mean()) / (s.std() + 1e-9)
        n_z = int((z.abs() > 3).sum())
        results.append({
            "column": col, "iqr_outliers": n_iqr, "zscore_outliers": n_z,
            "min": round(float(s.min()), 2), "max": round(float(s.max()), 2),
            "mean": round(float(s.mean()), 2), "std": round(float(s.std()), 2),
            "pct_of_rows": round(n_iqr / len(s) * 100, 2),
        })
    return results


# ─────────────────────────────────────────────
# EXECUTIVE SUMMARY
# ─────────────────────────────────────────────
def build_executive_summary(df: pd.DataFrame, profile, health: dict[str, Any]) -> list[dict[str, str]]:
    schema = profile.schema
    primary = profile.primary_measure
    cards: list[dict[str, str]] = []

    cards.append({
        "color": "#4f8ef7", "label": "📁 Dataset Overview",
        "value": f"{len(df):,} rows × {len(df.columns)} cols",
        "sub": f"Health {health['score']}/100 · Grade {health['grade']}",
    })

    if primary and schema["categorical"]:
        cat_col = schema["categorical"][0]
        try:
            grp = df.groupby(cat_col, observed=True)[primary].sum()
            best, worst = grp.idxmax(), grp.idxmin()
            cards.append({
                "color": "#34d399", "label": "🏆 Best Category",
                "value": str(best), "sub": f"{cat_col} · {fmt_number(grp[best])}",
            })
            cards.append({
                "color": "#f87171", "label": "📉 Worst Category",
                "value": str(worst), "sub": f"{cat_col} · {fmt_number(grp[worst])}",
            })
        except Exception:
            pass

    if primary:
        try:
            cards.append({
                "color": "#f59e0b", "label": "⚡ Highest Value",
                "value": fmt_number(df[primary].max()), "sub": f"Max {primary}",
            })
        except Exception:
            pass

    if schema["date"]:
        dcol = schema["date"][0]
        mn, mx = df[dcol].min(), df[dcol].max()
        if pd.notna(mn) and pd.notna(mx):
            cards.append({
                "color": "#a78bfa", "label": "📅 Date Coverage",
                "value": f"{mn:%b %Y} → {mx:%b %Y}", "sub": f"{len(schema['date'])} date column(s)",
            })

    cards.append({
        "color": "#38bdf8", "label": "📊 Key Observation",
        "value": f"{len(schema['numeric'])} numeric / {len(schema['categorical'])} categorical cols",
        "sub": f"Missing: {health['missing_pct']}% · Dupes: {health['dup_pct']}%",
    })

    return cards


# ─────────────────────────────────────────────
# BUSINESS INSIGHTS (general analytical observations)
# ─────────────────────────────────────────────
def build_business_insights(df: pd.DataFrame, profile) -> list[dict[str, Any]]:
    schema = profile.schema
    primary = profile.primary_measure
    insights: list[dict[str, Any]] = []

    if primary and schema["categorical"]:
        cat_col = schema["categorical"][0]
        try:
            grp = df.groupby(cat_col, observed=True)[primary].sum().sort_values(ascending=False)
            total = grp.sum()
            top_share = grp.iloc[0] / total * 100 if total else 0
            insights.append({
                "icon": "🏆", "title": "Best Category",
                "body": f"<b>{grp.index[0]}</b> leads in <b>{primary}</b>, contributing <b>{top_share:.1f}%</b> of the total.",
                "highlight": fmt_number(grp.iloc[0]),
            })
            insights.append({
                "icon": "📉", "title": "Lowest Performance",
                "body": f"<b>{grp.index[-1]}</b> has the lowest total <b>{primary}</b>.",
                "highlight": fmt_number(grp.iloc[-1]),
            })
            if len(grp) >= 3:
                top3_share = grp.head(3).sum() / total * 100 if total else 0
                insights.append({
                    "icon": "📦", "title": "Concentration",
                    "body": f"The top 3 {cat_col} values account for <b>{top3_share:.1f}%</b> of total {primary}.",
                    "highlight": None,
                })
        except Exception:
            pass

    if primary and schema["categorical"]:
        cat_col = schema["categorical"][0]
        try:
            top_row = df.loc[df[primary].idxmax()]
            insights.append({
                "icon": "⭐", "title": "Top Record",
                "body": f"Highest <b>{primary}</b> belongs to <b>{str(top_row[cat_col])[:40]}</b>.",
                "highlight": fmt_number(top_row[primary]),
            })
        except Exception:
            pass

    if len(schema["numeric"]) >= 2 and primary in schema["numeric"]:
        try:
            corr = df[schema["numeric"]].corr()[primary].drop(primary)
            corr = corr.dropna()
            if not corr.empty:
                best = corr.abs().idxmax()
                insights.append({
                    "icon": "🔗", "title": "Strongest Relationship",
                    "body": f"<b>{primary}</b> is most correlated with <b>{best}</b> (r = {corr[best]:.3f}).",
                    "highlight": None,
                })
        except Exception:
            pass

    return insights


# ─────────────────────────────────────────────
# TREND ANALYSIS
# ─────────────────────────────────────────────
def build_trend_analysis(df: pd.DataFrame, profile) -> list[dict[str, Any]]:
    schema = profile.schema
    primary = profile.primary_measure
    trends: list[dict[str, Any]] = []

    if not (primary and schema["date"]):
        return trends

    dcol = schema["date"][0]
    try:
        tmp = df[[dcol, primary]].dropna()
        tmp[dcol] = pd.to_datetime(tmp[dcol])
        monthly = tmp.set_index(dcol).resample("ME")[primary].sum()
        monthly = monthly[monthly.index.notna()]
        if len(monthly) >= 2:
            recent, previous = monthly.iloc[-1], monthly.iloc[-2]
            pct = (recent - previous) / (abs(previous) + 1e-9) * 100
            direction = "grew" if pct >= 0 else "fell"
            trends.append({
                "icon": "📈" if pct >= 0 else "📉", "title": "Recent Trend",
                "body": f"{primary} {direction} <b>{abs(pct):.1f}%</b> in {monthly.index[-1]:%b %Y} vs the prior month.",
                "highlight": fmt_number(recent),
            })
        if len(monthly) >= 3:
            best_month = monthly.idxmax()
            worst_month = monthly.idxmin()
            trends.append({
                "icon": "🗓️", "title": "Best Month",
                "body": f"<b>{best_month:%B %Y}</b> recorded the highest {primary}.",
                "highlight": fmt_number(monthly.max()),
            })
            trends.append({
                "icon": "🗓️", "title": "Weakest Month",
                "body": f"<b>{worst_month:%B %Y}</b> recorded the lowest {primary}.",
                "highlight": fmt_number(monthly.min()),
            })
        if len(monthly) >= 4:
            # simple linear-trend direction over the whole series
            x = np.arange(len(monthly))
            slope = np.polyfit(x, monthly.values, 1)[0]
            direction = "upward" if slope > 0 else "downward"
            article = "an" if direction == "upward" else "a"
            trends.append({
                "icon": "📊", "title": "Overall Trajectory",
                "body": f"Across the full period, {primary} shows {article} <b>{direction}</b> trend.",
                "highlight": None,
            })
    except Exception:
        pass

    return trends


# ─────────────────────────────────────────────
# RISK DETECTION
# ─────────────────────────────────────────────
def build_risk_detection(df: pd.DataFrame, profile, health: dict[str, Any], outliers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    schema = profile.schema
    primary = profile.primary_measure

    if health["missing_pct"] > 5:
        risks.append({
            "icon": "❗", "title": "Data Quality Risk",
            "body": f"Dataset has <b>{health['missing_pct']}%</b> missing values overall. This can bias aggregates and KPI accuracy.",
            "highlight": None,
        })
    if health["dup_pct"] > 1:
        risks.append({
            "icon": "🔁", "title": "Duplicate Records",
            "body": f"<b>{health['dup_rows']:,}</b> duplicate rows detected ({health['dup_pct']}% of data). Verify these aren't double-counted in totals.",
            "highlight": None,
        })

    for out in outliers:
        flagged = False
        if out["pct_of_rows"] > 3:
            risks.append({
                "icon": "⚠️", "title": f"Volatility in {out['column']}",
                "body": f"<b>{out['iqr_outliers']}</b> outlier values in <b>{out['column']}</b> ({out['pct_of_rows']}% of rows). Investigate before relying on averages.",
                "highlight": None,
            })
            flagged = True
        # severity check independent of count: a single extreme value can
        # distort sums/means even if it's a tiny fraction of rows.
        if not flagged and out["mean"] not in (0, None):
            try:
                ratio = abs(out["max"]) / (abs(out["mean"]) + 1e-9)
                if ratio > 10 and out["iqr_outliers"] > 0:
                    risks.append({
                        "icon": "⚠️", "title": f"Extreme Value in {out['column']}",
                        "body": f"<b>{out['column']}</b> has a maximum value ({fmt_number(out['max'])}) over <b>{ratio:.0f}x</b> the mean — a small number of extreme records may be skewing totals.",
                        "highlight": None,
                    })
            except Exception:
                pass

    if primary and schema["categorical"]:
        cat_col = schema["categorical"][0]
        try:
            grp = df.groupby(cat_col, observed=True)[primary].sum()
            total = grp.sum()
            if total and grp.max() / total > 0.5:
                risks.append({
                    "icon": "🎯", "title": "Concentration Risk",
                    "body": f"<b>{grp.idxmax()}</b> accounts for over <b>{grp.max()/total*100:.0f}%</b> of total {primary} — performance is highly dependent on a single {cat_col}.",
                    "highlight": None,
                })
        except Exception:
            pass

    if not risks:
        risks.append({
            "icon": "✅", "title": "No Major Risks Detected",
            "body": "No significant data quality or concentration risks found in this dataset.",
            "highlight": None,
        })

    return risks


# ─────────────────────────────────────────────
# OPPORTUNITIES
# ─────────────────────────────────────────────
def build_opportunities(df: pd.DataFrame, profile) -> list[dict[str, Any]]:
    opportunities: list[dict[str, Any]] = []
    schema = profile.schema
    primary = profile.primary_measure

    if primary and schema["categorical"]:
        cat_col = schema["categorical"][0]
        try:
            grp = df.groupby(cat_col, observed=True)[primary].agg(["sum", "count"])
            grp = grp[grp["count"] >= 3]
            if not grp.empty:
                grp["avg"] = grp["sum"] / grp["count"]
                # under-served: low total volume but reasonably high average — growth headroom
                median_count = grp["count"].median()
                low_volume_high_avg = grp[(grp["count"] < median_count) & (grp["avg"] > grp["avg"].median())]
                if not low_volume_high_avg.empty:
                    best = low_volume_high_avg.sort_values("avg", ascending=False).index[0]
                    opportunities.append({
                        "icon": "💎", "title": "Under-served Segment",
                        "body": f"<b>{best}</b> has a high average {primary} per record but low volume — there may be room to grow share here.",
                        "highlight": fmt_number(low_volume_high_avg.loc[best, "avg"]),
                    })
        except Exception:
            pass

    if schema["date"] and primary:
        dcol = schema["date"][0]
        try:
            tmp = df[[dcol, primary]].dropna()
            tmp[dcol] = pd.to_datetime(tmp[dcol])
            by_month_name = tmp.groupby(tmp[dcol].dt.month_name())[primary].mean()
            if len(by_month_name) >= 4:
                weakest = by_month_name.idxmin()
                opportunities.append({
                    "icon": "📅", "title": "Seasonal Opportunity",
                    "body": f"<b>{weakest}</b> shows the lowest average {primary} historically — a potential target for promotions.",
                    "highlight": None,
                })
        except Exception:
            pass

    if not opportunities:
        opportunities.append({
            "icon": "🔍", "title": "No Clear Opportunities Surfaced",
            "body": "Add more categorical or time-based columns for the engine to identify growth segments.",
            "highlight": None,
        })

    return opportunities


# ─────────────────────────────────────────────
# RECOMMENDATIONS (actionable, tied to the above)
# ─────────────────────────────────────────────
def build_recommendations(
    df: pd.DataFrame, profile, health: dict[str, Any],
    risks: list[dict[str, Any]], opportunities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    schema = profile.schema
    primary = profile.primary_measure

    if health["missing_pct"] > 5:
        recs.append({
            "icon": "🧹", "title": "Clean Missing Data",
            "body": f"Impute or remove records with missing values ({health['missing_pct']}% of cells) before deeper analysis.",
            "highlight": None,
        })
    if health["dup_rows"] > 0:
        recs.append({
            "icon": "🗑️", "title": "Deduplicate Records",
            "body": f"Review and remove the <b>{health['dup_rows']:,}</b> duplicate rows to avoid inflated totals.",
            "highlight": None,
        })
    if primary and schema["categorical"]:
        recs.append({
            "icon": "🎯", "title": "Focus on Top Performers",
            "body": f"Double down on the best-performing {schema['categorical'][0]} segments identified above to maximize {primary}.",
            "highlight": None,
        })
    if any("Concentration Risk" in r["title"] for r in risks):
        recs.append({
            "icon": "🛡️", "title": "Diversify Dependency",
            "body": "Performance is concentrated in a single segment — consider strategies to diversify revenue sources.",
            "highlight": None,
        })
    if not recs:
        recs.append({
            "icon": "💡", "title": "Keep Monitoring",
            "body": "The dataset looks healthy. Continue tracking key metrics over time to catch emerging trends early.",
            "highlight": None,
        })
    return recs[:6]


# ─────────────────────────────────────────────
# UNIFIED BUILDER — everything the AI Insight Page needs in one call
# ─────────────────────────────────────────────
def build_full_insight_report(df: pd.DataFrame, profile) -> dict[str, Any]:
    """Returns the complete set of sections for the redesigned AI Insight
    page: executive_summary, business_insights, risk_detection,
    opportunities, outliers, recommendations, trend_analysis.

    Pure rule-based — works with zero AI involvement. ai_engine.py may
    call this and then *rewrite wording only* on top of it.
    """
    health = compute_health(df)
    outliers = detect_outliers(df, profile.schema["numeric"])
    exec_summary = build_executive_summary(df, profile, health)
    business_insights = build_business_insights(df, profile)
    trend_analysis = build_trend_analysis(df, profile)
    risks = build_risk_detection(df, profile, health, outliers)
    opportunities = build_opportunities(df, profile)
    recommendations = build_recommendations(df, profile, health, risks, opportunities)

    return {
        "health": health,
        "executive_summary": exec_summary,
        "business_insights": business_insights,
        "risk_detection": risks,
        "opportunities": opportunities,
        "outliers": outliers,
        "recommendations": recommendations,
        "trend_analysis": trend_analysis,
    }
