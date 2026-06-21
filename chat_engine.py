"""
chat_engine.py
─────────────────────────────────────────────
Conversational analyst. Answers questions like "Which region performs
best?" using real dataframe context (DatasetProfile + targeted on-demand
stats), not free-form hallucination. Falls back to a rule-based answer
generator if AI is unavailable, so chat never goes fully dead.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

import ai_engine as ai
from insight_engine import build_full_insight_report


# ─────────────────────────────────────────────
# SUGGESTED QUESTIONS
# ─────────────────────────────────────────────
def suggested_questions(profile) -> list[str]:
    schema = profile.schema
    primary = profile.primary_measure
    qs: list[str] = []
    if primary and schema["categorical"]:
        cat = schema["categorical"][0]
        qs.append(f"Which {cat} performs best by {primary}?")
        qs.append(f"What are the top {cat} segments?")
    if primary and schema["date"]:
        qs.append(f"How is {primary} trending over time?")
        qs.append(f"Why might {primary} be decreasing?")
    if primary:
        qs.append(f"What's driving {primary}?")
        qs.append("Are there any outliers I should know about?")
    if not qs:
        qs = ["Summarize this dataset for me.", "What stands out in this data?"]
    return qs[:6]


# ─────────────────────────────────────────────
# RULE-BASED FALLBACK ANSWER (no AI required)
# ─────────────────────────────────────────────
def _rule_based_answer(question: str, df: pd.DataFrame, profile) -> str:
    schema = profile.schema
    primary = profile.primary_measure
    q = question.lower()

    if primary and schema["categorical"] and any(w in q for w in ["best", "top", "highest", "leading"]):
        cat = schema["categorical"][0]
        try:
            grp = df.groupby(cat, observed=True)[primary].sum().sort_values(ascending=False)
            return f"Based on {primary}, **{grp.index[0]}** leads with {grp.iloc[0]:,.0f}, followed by {grp.index[1] if len(grp) > 1 else 'N/A'}."
        except Exception:
            pass

    if primary and schema["categorical"] and any(w in q for w in ["worst", "lowest", "weak"]):
        cat = schema["categorical"][0]
        try:
            grp = df.groupby(cat, observed=True)[primary].sum().sort_values(ascending=True)
            return f"**{grp.index[0]}** has the lowest {primary} at {grp.iloc[0]:,.0f}."
        except Exception:
            pass

    if primary and schema["date"] and any(w in q for w in ["trend", "decreas", "increas", "growth"]):
        try:
            tmp = df[[schema["date"][0], primary]].dropna()
            tmp[schema["date"][0]] = pd.to_datetime(tmp[schema["date"][0]])
            monthly = tmp.set_index(schema["date"][0]).resample("ME")[primary].sum()
            if len(monthly) >= 2:
                pct = (monthly.iloc[-1] - monthly.iloc[-2]) / (abs(monthly.iloc[-2]) + 1e-9) * 100
                direction = "increased" if pct >= 0 else "decreased"
                return f"{primary} {direction} by {abs(pct):.1f}% in the most recent period compared to the one before."
        except Exception:
            pass

    if "outlier" in q or "anomal" in q:
        report = build_full_insight_report(df, profile)
        if report["outliers"]:
            o = report["outliers"][0]
            return f"**{o['column']}** has {o['iqr_outliers']} outlier values ({o['pct_of_rows']}% of rows), ranging up to {o['max']:,.0f}."
        return "No significant outliers were detected in the numeric columns."

    if "summar" in q or "overview" in q:
        return (
            f"This dataset has **{len(df):,} rows** and **{len(df.columns)} columns**. "
            f"It includes {len(schema['numeric'])} numeric, {len(schema['categorical'])} categorical, "
            f"and {len(schema['date'])} date column(s)."
            + (f" The primary measure appears to be **{primary}**." if primary else "")
        )

    return (
        "I can answer questions about top/bottom performers, trends, growth, and outliers "
        "based on this dataset. Try asking something like \"Which "
        f"{schema['categorical'][0] if schema['categorical'] else 'category'} performs best?\""
    )


# ─────────────────────────────────────────────
# AI-POWERED ANSWER (falls back to rule-based on any failure)
# ─────────────────────────────────────────────
def answer_question(
    question: str,
    df: pd.DataFrame,
    profile,
    chat_history: list[dict[str, str]] | None = None,
    api_key: str | None = None,
) -> str:
    """Answer a natural-language question about the dataset.

    Always grounded in real computed context (DatasetProfile.to_ai_context
    + a pre-computed insight report) — never the raw dataframe is sent to
    the model. Falls back to _rule_based_answer if AI is unavailable or
    fails for any reason, so chat is never fully broken.
    """
    if not ai.is_available(api_key):
        return _rule_based_answer(question, df, profile)

    try:
        context = profile.to_ai_context()
        report = build_full_insight_report(df, profile)
        # keep the payload small: only the parts of the report useful for Q&A
        compact_report = {
            "health": report["health"],
            "top_business_insights": report["business_insights"][:4],
            "risks": report["risk_detection"][:3],
            "trend_analysis": report["trend_analysis"][:3],
            "outliers": report["outliers"][:3],
        }

        history_msgs = []
        for turn in (chat_history or [])[-6:]:
            role = "user" if turn.get("role") == "user" else "assistant"
            history_msgs.append({"role": role, "content": str(turn.get("content", ""))[:500]})

        system_prompt = (
            "You are a data analyst answering questions about a specific dataset. "
            "Use ONLY the facts in the provided context — never invent numbers that "
            "aren't there. If the context doesn't contain enough information to answer "
            "precisely, say so plainly instead of guessing. Be concise (2-4 sentences). "
            f"\n\nDataset context:\n{json.dumps(context, default=str)[:2000]}"
            f"\n\nPrecomputed analysis:\n{json.dumps(compact_report, default=str)[:2000]}"
        )

        messages = [{"role": "system", "content": system_prompt}, *history_msgs, {"role": "user", "content": question}]
        return ai.call_groq(messages, api_key=api_key, max_tokens=400).strip()
    except Exception:
        return _rule_based_answer(question, df, profile)
