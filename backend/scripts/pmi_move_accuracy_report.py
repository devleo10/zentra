"""Run a local analysis and audit PMI/MOVE against external references.

Usage (from backend/):
    python scripts/pmi_move_accuracy_report.py --timeframe current --fresh
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from run_analysis import run_analysis
from data_fetchers import fred_data, yahoo_data, trusted_market_apis

PMI_MATCH_ABS = 0.30
PMI_WARN_ABS = 1.00
MOVE_MATCH_REL_PCT = 2.0
MOVE_WARN_REL_PCT = 5.0


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _delta(local_value: Optional[float], external_value: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if local_value is None or external_value is None:
        return None, None
    abs_delta = abs(local_value - external_value)
    rel_delta_pct = abs_delta / abs(external_value) * 100.0 if external_value != 0 else None
    return abs_delta, rel_delta_pct


def _status_for_metric(metric: str, abs_delta: Optional[float], rel_delta_pct: Optional[float]) -> Tuple[str, str]:
    if abs_delta is None:
        return "no_reference", "Missing local or external value"

    if metric == "PMI":
        if abs_delta <= PMI_MATCH_ABS:
            return "match", f"|delta| <= {PMI_MATCH_ABS:.2f}"
        if abs_delta <= PMI_WARN_ABS:
            return "warning", f"|delta| <= {PMI_WARN_ABS:.2f}"
        return "mismatch", f"|delta| > {PMI_WARN_ABS:.2f}"

    if rel_delta_pct is None:
        return "warning", "External comparator is zero; relative delta unavailable"
    if rel_delta_pct <= MOVE_MATCH_REL_PCT:
        return "match", f"rel delta <= {MOVE_MATCH_REL_PCT:.1f}%"
    if rel_delta_pct <= MOVE_WARN_REL_PCT:
        return "warning", f"rel delta <= {MOVE_WARN_REL_PCT:.1f}%"
    return "mismatch", f"rel delta > {MOVE_WARN_REL_PCT:.1f}%"


def _get_pmi_references(timeframe: str) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []

    try:
        calendar = trusted_market_apis.get_tradingeconomics_us_pmi_calendar_event()
        if isinstance(calendar, dict):
            refs.append(
                {
                    "name": "TradingEconomics Calendar",
                    "source": calendar.get("source") or "TradingEconomics:calendar:US:Manufacturing PMI",
                    "url": "https://api.tradingeconomics.com/calendar/country/united%20states",
                    "value": _safe_float(calendar.get("actual_value")),
                    "date": str(calendar.get("date") or "")[:10] or None,
                }
            )
    except Exception:
        pass

    try:
        te = trusted_market_apis.get_tradingeconomics_us_manufacturing_pmi()
        if isinstance(te, dict):
            refs.append(
                {
                    "name": "TradingEconomics Indicator",
                    "source": te.get("source") or "TradingEconomics:US:Manufacturing PMI",
                    "url": "https://api.tradingeconomics.com/historical/country/united%20states/indicator/manufacturing%20pmi",
                    "value": _safe_float(te.get("pmi_value")),
                    "date": str(te.get("date") or "")[:10] or None,
                }
            )
    except Exception:
        pass

    try:
        te_web = fred_data._get_pmi_from_tradingeconomics_page(timeframe)
        if isinstance(te_web, dict):
            refs.append(
                {
                    "name": "TradingEconomics Web",
                    "source": te_web.get("source") or "TradingEconomics:web",
                    "url": fred_data.TRADINGECONOMICS_US_PMI_PAGE,
                    "value": _safe_float(te_web.get("pmi_value")),
                    "date": str(te_web.get("latest_date") or "")[:10] or None,
                }
            )
    except Exception:
        pass

    try:
        ism = fred_data._get_pmi_from_ism_scrape(timeframe)
        if isinstance(ism, dict):
            refs.append(
                {
                    "name": "ISM Release Page",
                    "source": ism.get("source") or "ISM:html",
                    "url": fred_data.ISM_PMI_URL,
                    "value": _safe_float(ism.get("pmi_value")),
                    "date": str(ism.get("latest_date") or "")[:10] or None,
                }
            )
    except Exception:
        pass

    try:
        inv = fred_data._get_pmi_from_investing_page(timeframe)
        if isinstance(inv, dict):
            refs.append(
                {
                    "name": "Investing Calendar",
                    "source": inv.get("source") or "Investing:ISM_PMI_event_173",
                    "url": fred_data.INVESTING_US_ISM_PMI_PAGE,
                    "value": _safe_float(inv.get("pmi_value")),
                    "date": str(inv.get("latest_date") or "")[:10] or None,
                }
            )
    except Exception:
        pass

    try:
        tv = fred_data._get_pmi_from_tradingview(timeframe)
        if isinstance(tv, dict):
            refs.append(
                {
                    "name": "TradingView Economics",
                    "source": tv.get("source") or "TradingView:ECONOMICS:USPMI",
                    "url": "https://scanner.tradingview.com/america/scan",
                    "value": _safe_float(tv.get("pmi_value")),
                    "date": str(tv.get("latest_date") or "")[:10] or None,
                }
            )
    except Exception:
        pass

    return refs


def _get_move_references(timeframe: str) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []

    try:
        yahoo_move = yahoo_data._yahoo_pct_change_series("^MOVE", timeframe)
        if isinstance(yahoo_move, dict) and "error" not in yahoo_move:
            refs.append(
                {
                    "name": "Yahoo Finance ^MOVE",
                    "source": yahoo_move.get("source") or "^MOVE",
                    "url": "https://query1.finance.yahoo.com/v8/finance/chart/%5EMOVE",
                    "value": _safe_float(yahoo_move.get("current_price")),
                    "date": str(yahoo_move.get("date") or "")[:10] or None,
                }
            )
    except Exception:
        pass

    try:
        tv_value = yahoo_data._tradingview_scan_latest_close("INDEX:MOVE")
        if tv_value is not None:
            refs.append(
                {
                    "name": "TradingView INDEX:MOVE",
                    "source": "TradingView:INDEX:MOVE",
                    "url": "https://scanner.tradingview.com/america/scan",
                    "value": _safe_float(tv_value),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                }
            )
    except Exception:
        pass

    try:
        fmp = trusted_market_apis.get_fmp_quote("^MOVE")
        if isinstance(fmp, dict):
            refs.append(
                {
                    "name": "FMP ^MOVE",
                    "source": fmp.get("source") or "FMP:^MOVE",
                    "url": "https://financialmodelingprep.com/api/v3/quote/%5EMOVE",
                    "value": _safe_float(fmp.get("price")),
                    "date": str(fmp.get("date") or "")[:10] or None,
                }
            )
    except Exception:
        pass

    return refs


def _pick_primary_reference(metric: str, refs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if metric == "PMI":
        priority = [
            "TradingEconomics Calendar",
            "ISM Release Page",
            "TradingEconomics Indicator",
            "TradingEconomics Web",
            "Investing Calendar",
            "TradingView Economics",
        ]
    else:
        priority = [
            "Yahoo Finance ^MOVE",
            "TradingView INDEX:MOVE",
            "FMP ^MOVE",
        ]

    by_name = {str(row.get("name")): row for row in refs}
    for name in priority:
        row = by_name.get(name)
        if row and row.get("value") is not None:
            return row

    for row in refs:
        if row.get("value") is not None:
            return row
    return None


def _format_float(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _escape_md(value: Any) -> str:
    text = str(value) if value is not None else "n/a"
    return text.replace("|", "\\|")


def _build_report_markdown(
    *,
    timeframe: str,
    run_started_at: str,
    run_finished_at: str,
    snapshot: Dict[str, Any],
    comparisons: List[Dict[str, Any]],
) -> str:
    final_score = snapshot.get("final_score")
    bias = snapshot.get("bias")
    confidence = snapshot.get("confidence_pct")

    mismatch_count = sum(1 for row in comparisons if row["status"] == "mismatch")
    warning_count = sum(1 for row in comparisons if row["status"] == "warning")
    match_count = sum(1 for row in comparisons if row["status"] == "match")

    lines: List[str] = []
    lines.append("# PMI and MOVE Accuracy Summary Report")
    lines.append("")
    lines.append(f"- generated_at_utc: {run_finished_at}")
    lines.append(f"- timeframe: {timeframe}")
    lines.append(f"- local_command: python run_analysis.py {timeframe}")
    lines.append(f"- run_started_at_utc: {run_started_at}")
    lines.append(f"- run_finished_at_utc: {run_finished_at}")
    lines.append("")
    lines.append("## Local Run Summary")
    lines.append("")
    lines.append(f"- final_score: {final_score}")
    lines.append(f"- bias: {bias}")
    lines.append(f"- confidence_pct: {confidence}")
    lines.append(f"- pmi_local: {_format_float(_safe_float(snapshot.get('pmi_value')), 1)}")
    lines.append(f"- pmi_source: {snapshot.get('pmi_source') or 'n/a'}")
    lines.append(f"- move_local: {_format_float(_safe_float(snapshot.get('move_index_value')), 2)}")
    lines.append(f"- move_source: {snapshot.get('move_index_source') or 'n/a'}")
    lines.append("")
    lines.append("## Cross-Check Results")
    lines.append("")
    lines.append("| Metric | Local Value | External Value | External Source | External Date | Delta Abs | Delta Rel % | Status | Notes | URL |")
    lines.append("|---|---:|---:|---|---|---:|---:|---|---|---|")

    for row in comparisons:
        lines.append(
            "| "
            + f"{row['metric']} | "
            + f"{_format_float(row['local_value'], 2)} | "
            + f"{_format_float(row['external_value'], 2)} | "
            + f"{_escape_md(row['external_source'])} | "
            + f"{_escape_md(row['external_date'])} | "
            + f"{_format_float(row['delta_abs'], 2)} | "
            + f"{_format_float(row['delta_rel_pct'], 2)} | "
            + f"{_escape_md(row['status'])} | "
            + f"{_escape_md(row['notes'])} | "
            + f"{_escape_md(row['url'])} |"
        )

    lines.append("")
    lines.append("## Accuracy Summary")
    lines.append("")
    lines.append(f"- matches: {match_count}")
    lines.append(f"- warnings: {warning_count}")
    lines.append(f"- mismatches: {mismatch_count}")
    lines.append("")

    if mismatch_count == 0 and warning_count == 0:
        lines.append("- overall_status: aligned")
    elif mismatch_count == 0:
        lines.append("- overall_status: aligned_with_warnings")
    else:
        lines.append("- overall_status: mismatches_detected")

    lines.append(
        f"- tolerances: PMI |delta|<= {PMI_MATCH_ABS:.2f} match, <= {PMI_WARN_ABS:.2f} warning; "
        f"MOVE rel<= {MOVE_MATCH_REL_PCT:.1f}% match, <= {MOVE_WARN_REL_PCT:.1f}% warning"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a PMI/MOVE external accuracy report")
    parser.add_argument("--timeframe", default="current", choices=["current", "week", "month"])
    parser.add_argument("--fresh", action="store_true", help="Clear cache and force fresh fetch")
    parser.add_argument(
        "--output-dir",
        default=str(BACKEND_ROOT / "logs"),
        help="Directory where report files will be written",
    )
    args = parser.parse_args()

    run_started_at = _iso_now()
    snapshot = run_analysis(args.timeframe, fresh=args.fresh)
    run_finished_at = _iso_now()

    pmi_local = _safe_float(snapshot.get("pmi_value"))
    move_local = _safe_float(snapshot.get("move_index_value"))

    pmi_refs = _get_pmi_references(args.timeframe)
    move_refs = _get_move_references(args.timeframe)

    comparisons: List[Dict[str, Any]] = []

    pmi_primary = _pick_primary_reference("PMI", pmi_refs)
    if pmi_primary:
        pmi_abs, pmi_rel = _delta(pmi_local, _safe_float(pmi_primary.get("value")))
        pmi_status, pmi_notes = _status_for_metric("PMI", pmi_abs, pmi_rel)
        comparisons.append(
            {
                "metric": "PMI",
                "local_value": pmi_local,
                "external_value": _safe_float(pmi_primary.get("value")),
                "external_source": pmi_primary.get("source"),
                "external_date": pmi_primary.get("date"),
                "delta_abs": pmi_abs,
                "delta_rel_pct": pmi_rel,
                "status": pmi_status,
                "notes": pmi_notes,
                "url": pmi_primary.get("url"),
            }
        )
    else:
        comparisons.append(
            {
                "metric": "PMI",
                "local_value": pmi_local,
                "external_value": None,
                "external_source": None,
                "external_date": None,
                "delta_abs": None,
                "delta_rel_pct": None,
                "status": "no_reference",
                "notes": "No external PMI source returned data",
                "url": None,
            }
        )

    move_primary = _pick_primary_reference("MOVE", move_refs)
    if move_primary:
        move_abs, move_rel = _delta(move_local, _safe_float(move_primary.get("value")))
        move_status, move_notes = _status_for_metric("MOVE", move_abs, move_rel)
        comparisons.append(
            {
                "metric": "MOVE",
                "local_value": move_local,
                "external_value": _safe_float(move_primary.get("value")),
                "external_source": move_primary.get("source"),
                "external_date": move_primary.get("date"),
                "delta_abs": move_abs,
                "delta_rel_pct": move_rel,
                "status": move_status,
                "notes": move_notes,
                "url": move_primary.get("url"),
            }
        )
    else:
        comparisons.append(
            {
                "metric": "MOVE",
                "local_value": move_local,
                "external_value": None,
                "external_source": None,
                "external_date": None,
                "delta_abs": None,
                "delta_rel_pct": None,
                "status": "no_reference",
                "notes": "No external MOVE source returned data",
                "url": None,
            }
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"pmi_move_accuracy_{args.timeframe}_{ts}"

    report_md = _build_report_markdown(
        timeframe=args.timeframe,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        snapshot=snapshot,
        comparisons=comparisons,
    )

    md_path = output_dir / f"{base_name}.md"
    json_path = output_dir / f"{base_name}.json"

    payload = {
        "generated_at_utc": run_finished_at,
        "timeframe": args.timeframe,
        "fresh": bool(args.fresh),
        "snapshot": snapshot,
        "comparisons": comparisons,
        "references": {
            "pmi": pmi_refs,
            "move": move_refs,
        },
    }

    md_path.write_text(report_md, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Report markdown: {md_path}")
    print(f"Report json: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
