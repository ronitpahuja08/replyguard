"""Classification metrics M1-M4 (``testset/rubric.yaml``) over an eval run, checked against ``pass.yaml``, and
the live KPIs the Analyst reads from ``conversation.classified`` events (CM-047)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any

SAFETY = ("opt_out", "complaint", "bot_question")


def classification_metrics(
    cases: Iterable[Mapping[str, Any]], outputs: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """``cases``: the test cases; ``outputs``: case id -> agent output. Only cases with an expected label
    count."""
    rows = []
    for c in cases:
        want = (c.get("expect") or {}).get("label")
        if want is None:
            continue
        out = outputs.get(str(c.get("id"))) or {}
        got = out.get("label")
        labels = [x for x in [got, *(out.get("also") or [])] if x]
        rows.append((want, got, labels))
    n = len(rows)
    acc = sum(1 for w, g, _ in rows if w == g) / n if n else None
    safety = [(w, labels) for w, _, labels in rows if w in SAFETY]
    recall = sum(1 for w, labels in safety if w in labels) / len(safety) if safety else None
    pred_opt = [(w, g) for w, g, _ in rows if g == "opt_out"]
    opt_prec = (
        sum(1 for w, _ in pred_opt if w in ("opt_out", "complaint")) / len(pred_opt) if pred_opt else None
    )
    pred_auto = [(w, g) for w, g, _ in rows if g == "auto_reply"]
    auto_prec = sum(1 for w, _ in pred_auto if w == "auto_reply") / len(pred_auto) if pred_auto else None
    return {
        "labelled_cases": n,
        "M1_accuracy": acc,
        "M2_safety_recall": recall,
        "M3_opt_out_precision": opt_prec,
        "M4_auto_reply_precision": auto_prec,
    }


def metrics_pass(metrics: Mapping[str, Any], pass_rules: Mapping[str, Any]) -> list[str]:
    """Reasons the metrics miss ``pass.yaml`` ``classification`` thresholds (empty = they pass)."""
    th = pass_rules.get("classification") or {}
    pairs = (
        ("M1_accuracy", "accuracy_min"),
        ("M2_safety_recall", "safety_recall_min"),
        ("M3_opt_out_precision", "opt_out_precision_min"),
        ("M4_auto_reply_precision", "auto_reply_precision_min"),
    )
    out = []
    for m, t in pairs:
        if t in th and metrics.get(m) is not None and float(metrics[m]) < float(th[t]):
            out.append(f"{m} {metrics[m]:.3f} < {th[t]}")
    return out


def live_kpis(events: Iterable[Any]) -> dict[str, Any]:
    """From ``conversation.classified`` event payloads: label counts, handover rate by reason, median response
    time in working minutes (target < 15, a KPI, not a rule), share of auto-replies excluded from reply
    counts."""
    payloads = [getattr(e, "payload", e) or {} for e in events]
    replies = [p for p in payloads if p.get("counts_as_reply", True)]
    minutes = [
        float(p["response_working_minutes"]) for p in replies if p.get("response_working_minutes") is not None
    ]
    reasons: dict[str, int] = {}
    labels: dict[str, int] = {}
    for p in payloads:
        labels[str(p.get("label"))] = labels.get(str(p.get("label")), 0) + 1
        for r in p.get("handover_reasons") or []:
            reasons[r] = reasons.get(r, 0) + 1
    return {
        "messages": len(payloads),
        "replies": len(replies),
        "auto_replies_excluded": len(payloads) - len(replies),
        "labels": labels,
        "handover_reasons": reasons,
        "median_response_working_minutes": median(minutes) if minutes else None,
    }
