"""
Local SQLite storage for macro analysis snapshots.

Every analysis run is persisted for auditability.
Schema is flat + JSON columns for flexibility.
"""
import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger("btc_macro.storage")

DB_PATH = Path(__file__).parent.parent / "storage" / "macro_snapshots.db"


def _get_connection() -> sqlite3.Connection:
    """Get SQLite connection, creating DB and table if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    """Create table if not exists, and migrate existing tables with new columns."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Timestamp of this analysis run
            timestamp TEXT NOT NULL,

            -- Timeframe used for this run ('current', 'week', 'month', 'year')
            timeframe TEXT,

            -- Raw numeric inputs
            cpi_mom_change REAL,
            cpi_yoy_rate REAL,
            cpi_core_mom_change REAL,
            cpi_core_yoy_rate REAL,
            cpi_mom_avg_3m REAL,
            cpi_mom_avg_3m_prior REAL,
            cpi_mom_avg_3m_trend TEXT,
            core_cpi_mom_avg_3m REAL,
            core_cpi_mom_avg_3m_prior REAL,
            core_cpi_mom_avg_3m_trend TEXT,
            cpi_source TEXT,
            pce_mom_change REAL,
            pce_mom_avg_3m REAL,
            pce_mom_avg_3m_prior REAL,
            pce_mom_avg_3m_trend TEXT,
            oil_change REAL,
            oil_price REAL,
            oil_observed_at TEXT,
            oil_fetched_at TEXT,
            fed_funds_rate REAL,
            fed_rate_trend TEXT,
            dxy_value REAL,
            dxy_change REAL,
            dxy_change_7d REAL,
            dxy_source TEXT,
            dxy_observed_at TEXT,
            dxy_fetched_at TEXT,
            vix REAL,
            vix_source TEXT,
            vix_observed_at TEXT,
            vix_fetched_at TEXT,
            ten_year_yield REAL,
            yield_curve_spread REAL,
            fed_balance_sheet_trend TEXT,
            sp500_change REAL,
            sp500_price REAL,
            sp500_source TEXT,
            sp500_observed_at TEXT,
            sp500_fetched_at TEXT,
            gold_price REAL,
            gold_change REAL,
            gold_source TEXT,
            gold_observed_at TEXT,
            gold_fetched_at TEXT,
            btc_price REAL,
            btc_observed_at TEXT,
            btc_fetched_at TEXT,

            -- Per-section scores (JSON dict)
            section_scores TEXT NOT NULL,

            -- Section reasoning (JSON dict)
            section_reasoning TEXT,

            -- Weighted numeric score before headline adjustment (REAL to preserve fractional scores)
            weighted_numeric_score REAL NOT NULL,
            score_breakdown TEXT,

            -- Headline data
            headlines_fetched INTEGER DEFAULT 0,
            headlines_classified TEXT,
            headline_adjustment INTEGER DEFAULT 0,
            headline_reasoning TEXT,

            -- Headline market report (text + JSON meta)
            headline_report TEXT,
            headline_report_meta TEXT,

            -- Final output
            final_score REAL NOT NULL,
            bias TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence_pct REAL,
            confidence_label TEXT,

            -- Data freshness report (JSON)
            data_freshness_info TEXT,

            -- Reproducibility metadata
            config_hash TEXT,
            prompt_version TEXT,
            llm_model TEXT,

            -- Fed keyword counts for auditability
            dovish_keyword_count INTEGER,
            hawkish_keyword_count INTEGER,
            pivot_keyword_count INTEGER,

            -- LLM cross-signal review
            cross_signal_adjustment INTEGER DEFAULT 0,
            cross_signal_reasoning TEXT,

            -- LLM narrative output
            narrative TEXT,
            key_risk TEXT,
            catalyst_to_watch TEXT,

            -- Full API payload for forward-compatible snapshot reads
            full_payload TEXT
        )
    """)

    # Index on timestamp for efficient range queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_macro_snapshots_timestamp
        ON macro_snapshots (timestamp)
    """)
    conn.commit()

    # Migrate existing databases: add new columns if they don't exist yet
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(macro_snapshots)").fetchall()}
    migrations = [
        ("cpi_yoy_rate",          "REAL"),
        ("cpi_core_mom_change",   "REAL"),
        ("cpi_core_yoy_rate",     "REAL"),
        ("cpi_mom_avg_3m",        "REAL"),
        ("cpi_mom_avg_3m_prior",  "REAL"),
        ("cpi_mom_avg_3m_trend",  "TEXT"),
        ("core_cpi_mom_avg_3m",       "REAL"),
        ("core_cpi_mom_avg_3m_prior", "REAL"),
        ("core_cpi_mom_avg_3m_trend", "TEXT"),
        ("cpi_source",            "TEXT"),
        ("pce_mom_avg_3m",        "REAL"),
        ("pce_mom_avg_3m_prior",  "REAL"),
        ("pce_mom_avg_3m_trend",  "TEXT"),
        ("oil_observed_at",       "TEXT"),
        ("oil_fetched_at",        "TEXT"),
        ("oil_price",             "REAL"),
        ("fed_funds_rate",        "REAL"),
        ("fed_rate_trend",        "TEXT"),
        ("dxy_change",            "REAL"),
        ("dxy_source",            "TEXT"),
        ("dxy_observed_at",       "TEXT"),
        ("dxy_fetched_at",        "TEXT"),
        ("vix_source",            "TEXT"),
        ("vix_observed_at",       "TEXT"),
        ("vix_fetched_at",        "TEXT"),
        ("sp500_price",           "REAL"),
        ("sp500_source",          "TEXT"),
        ("sp500_observed_at",     "TEXT"),
        ("sp500_fetched_at",      "TEXT"),
        ("gold_price",            "REAL"),
        ("gold_source",           "TEXT"),
        ("gold_observed_at",      "TEXT"),
        ("gold_fetched_at",       "TEXT"),
        ("btc_observed_at",       "TEXT"),
        ("btc_fetched_at",        "TEXT"),
        ("timeframe",             "TEXT"),
        ("headline_report",       "TEXT"),
        ("headline_report_meta",  "TEXT"),
        ("cross_signal_adjustment", "INTEGER DEFAULT 0"),
        ("cross_signal_reasoning",  "TEXT"),
        ("narrative",               "TEXT"),
        ("key_risk",                "TEXT"),
        ("catalyst_to_watch",       "TEXT"),
        ("full_payload",            "TEXT"),
        ("natgas_price",            "REAL"),
        ("natgas_change",           "REAL"),
        ("natgas_trend",            "TEXT"),
        ("financial_stress_index",  "REAL"),
        ("financial_stress_level",  "TEXT"),
        ("financial_stress_trend",  "TEXT"),
        ("hy_oas",                  "REAL"),
        ("hy_trend",                "TEXT"),
        ("btc_dominance",           "REAL"),
        ("stablecoin_dominance",    "REAL"),
        ("btc_ma200",               "REAL"),
        ("btc_realized_vol_30d",    "REAL"),
        ("btc_etf_volume",          "INTEGER"),
        ("btc_etf_flow_level",      "TEXT"),
        ("dxy_structure",           "TEXT"),
        ("geopolitics_risk_level",  "TEXT"),
        ("fed_tone",                "TEXT"),
        ("weighted_numeric_stale_downweight", "INTEGER"),
        ("coherence_adjustment",    "INTEGER DEFAULT 0"),
        ("coherence_reasoning",     "TEXT"),
        ("ten_year_breakeven",      "REAL"),
        ("real_yield_10y",          "REAL"),
        ("btc_change",              "REAL"),
        ("btc_change_24h",          "REAL"),
        ("btc_change_7d",           "REAL"),
    ]
    for col_name, col_type in migrations:
        if col_name not in existing_columns:
            conn.execute(f"ALTER TABLE macro_snapshots ADD COLUMN {col_name} {col_type}")
            logger.info("DB migration: added column %s %s to macro_snapshots", col_name, col_type)
    conn.commit()


def save_snapshot(snapshot: Dict[str, Any]) -> int:
    """
    Save an analysis snapshot to the database.
    
    Args:
        snapshot: Dict with all analysis results
    
    Returns:
        Row ID of the inserted record
    """
    conn = _get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO macro_snapshots (
                timestamp, timeframe,
                cpi_mom_change, cpi_yoy_rate, cpi_core_mom_change, cpi_core_yoy_rate,
                cpi_mom_avg_3m, cpi_mom_avg_3m_prior, cpi_mom_avg_3m_trend,
                core_cpi_mom_avg_3m, core_cpi_mom_avg_3m_prior, core_cpi_mom_avg_3m_trend,
                cpi_source,
                pce_mom_change, pce_mom_avg_3m, pce_mom_avg_3m_prior, pce_mom_avg_3m_trend,
                oil_change, oil_price, oil_observed_at, oil_fetched_at,
                fed_funds_rate, fed_rate_trend,
                dxy_value, dxy_change, dxy_change_7d, dxy_source, dxy_observed_at, dxy_fetched_at,
                vix, vix_source, vix_observed_at, vix_fetched_at,
                ten_year_yield, yield_curve_spread, fed_balance_sheet_trend,
                sp500_change, sp500_price, sp500_source, sp500_observed_at, sp500_fetched_at,
                gold_price, gold_change, gold_source, gold_observed_at, gold_fetched_at,
                btc_price, btc_observed_at, btc_fetched_at, btc_change, btc_change_24h, btc_change_7d,
                section_scores, section_reasoning,
                weighted_numeric_score, score_breakdown,
                weighted_numeric_stale_downweight, coherence_adjustment, coherence_reasoning,
                ten_year_breakeven, real_yield_10y,
                headlines_fetched, headlines_classified, headline_adjustment, headline_reasoning,
                headline_report, headline_report_meta,
                final_score, bias, action, confidence_pct, confidence_label,
                data_freshness_info,
                config_hash, prompt_version, llm_model,
                dovish_keyword_count, hawkish_keyword_count, pivot_keyword_count,
                cross_signal_adjustment, cross_signal_reasoning,
                narrative, key_risk, catalyst_to_watch,
                natgas_price, natgas_change, natgas_trend,
                financial_stress_index, financial_stress_level, financial_stress_trend,
                hy_oas, hy_trend,
                btc_dominance, stablecoin_dominance,
                btc_ma200, btc_realized_vol_30d,
                btc_etf_volume, btc_etf_flow_level,
                dxy_structure, geopolitics_risk_level, fed_tone
            ) VALUES (
                ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?, ?,
                ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?
            )
        """, (
            snapshot.get("timestamp", datetime.now().isoformat()),
            snapshot.get("timeframe"),
            snapshot.get("cpi_mom_change"),
            snapshot.get("cpi_yoy_rate"),
            snapshot.get("cpi_core_mom_change"),
            snapshot.get("cpi_core_yoy_rate"),
            snapshot.get("cpi_mom_avg_3m"),
            snapshot.get("cpi_mom_avg_3m_prior"),
            snapshot.get("cpi_mom_avg_3m_trend"),
            snapshot.get("core_cpi_mom_avg_3m"),
            snapshot.get("core_cpi_mom_avg_3m_prior"),
            snapshot.get("core_cpi_mom_avg_3m_trend"),
            snapshot.get("cpi_source"),
            snapshot.get("pce_mom_change"),
            snapshot.get("pce_mom_avg_3m"),
            snapshot.get("pce_mom_avg_3m_prior"),
            snapshot.get("pce_mom_avg_3m_trend"),
            snapshot.get("oil_change"),
            snapshot.get("oil_price"),
            snapshot.get("oil_observed_at"),
            snapshot.get("oil_fetched_at"),
            snapshot.get("fed_funds_rate"),
            snapshot.get("fed_rate_trend"),
            snapshot.get("dxy_value"),
            snapshot.get("dxy_change"),
            snapshot.get("dxy_change_7d"),
            snapshot.get("dxy_source"),
            snapshot.get("dxy_observed_at"),
            snapshot.get("dxy_fetched_at"),
            snapshot.get("vix"),
            snapshot.get("vix_source"),
            snapshot.get("vix_observed_at"),
            snapshot.get("vix_fetched_at"),
            snapshot.get("ten_year_yield"),
            snapshot.get("yield_curve_spread"),
            snapshot.get("fed_balance_sheet_trend"),
            snapshot.get("sp500_change"),
            snapshot.get("sp500_price"),
            snapshot.get("sp500_source"),
            snapshot.get("sp500_observed_at"),
            snapshot.get("sp500_fetched_at"),
            snapshot.get("gold_price"),
            snapshot.get("gold_change"),
            snapshot.get("gold_source"),
            snapshot.get("gold_observed_at"),
            snapshot.get("gold_fetched_at"),
            snapshot.get("btc_price"),
            snapshot.get("btc_observed_at"),
            snapshot.get("btc_fetched_at"),
            snapshot.get("btc_change"),
            snapshot.get("btc_change_24h"),
            snapshot.get("btc_change_7d"),
            json.dumps(snapshot.get("section_scores", {})),
            json.dumps(snapshot.get("section_reasoning", {})),
            snapshot.get("weighted_numeric_score", 50),
            json.dumps(snapshot.get("score_breakdown", {})),
            snapshot.get("weighted_numeric_stale_downweight"),
            snapshot.get("coherence_adjustment", 0),
            snapshot.get("coherence_reasoning", ""),
            snapshot.get("ten_year_breakeven"),
            snapshot.get("real_yield_10y"),
            snapshot.get("headlines_fetched", 0),
            json.dumps(snapshot.get("headlines_classified", [])),
            snapshot.get("headline_adjustment", 0),
            snapshot.get("headline_reasoning", ""),
            snapshot.get("headline_report", ""),
            json.dumps(snapshot.get("headline_report_meta", {})),
            snapshot.get("final_score", 50),
            snapshot.get("bias", "Neutral"),
            snapshot.get("action", "Small positions only"),
            snapshot.get("confidence_pct"),
            snapshot.get("confidence_label"),
            json.dumps(snapshot.get("data_freshness_info", {})),
            snapshot.get("config_hash"),
            snapshot.get("prompt_version"),
            snapshot.get("llm_model"),
            snapshot.get("dovish_keyword_count"),
            snapshot.get("hawkish_keyword_count"),
            snapshot.get("pivot_keyword_count"),
            snapshot.get("cross_signal_adjustment", 0),
            snapshot.get("cross_signal_reasoning", ""),
            snapshot.get("narrative", ""),
            snapshot.get("key_risk", ""),
            snapshot.get("catalyst_to_watch", ""),
            snapshot.get("natgas_price"),
            snapshot.get("natgas_change"),
            snapshot.get("natgas_trend"),
            snapshot.get("financial_stress_index"),
            snapshot.get("financial_stress_level"),
            snapshot.get("financial_stress_trend"),
            snapshot.get("hy_oas"),
            snapshot.get("hy_trend"),
            snapshot.get("btc_dominance"),
            snapshot.get("stablecoin_dominance"),
            snapshot.get("btc_ma200"),
            snapshot.get("btc_realized_vol_30d"),
            snapshot.get("btc_etf_volume"),
            snapshot.get("btc_etf_flow_level"),
            snapshot.get("dxy_structure"),
            snapshot.get("geopolitics_risk_level"),
            snapshot.get("fed_tone"),
        ))
        row_id = cursor.lastrowid
        conn.execute(
            "UPDATE macro_snapshots SET full_payload = ? WHERE id = ?",
            (json.dumps(snapshot), row_id),
        )
        conn.commit()
        logger.info(f"Snapshot saved: id={row_id}")
        return row_id
    finally:
        conn.close()


def get_latest_snapshots(limit: int = 10) -> List[Dict[str, Any]]:
    """Get the most recent N snapshots."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM macro_snapshots ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [_merge_full_payload(dict(row)) for row in rows]
    finally:
        conn.close()


def get_snapshot_by_id(snapshot_id: int) -> Optional[Dict[str, Any]]:
    """Get a specific snapshot by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM macro_snapshots WHERE id = ?",
            (snapshot_id,)
        ).fetchone()
        return _merge_full_payload(dict(row)) if row else None
    finally:
        conn.close()


def _merge_full_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the stored full payload JSON into a DB row for API reads."""
    payload_raw = row.get("full_payload")
    if isinstance(payload_raw, str) and payload_raw.strip():
        try:
            payload = json.loads(payload_raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Snapshot id=%s has unreadable full_payload", row.get("id"))
            return row
        if isinstance(payload, dict):
            merged = {**row, **payload}
            merged["id"] = row.get("id")
            return merged
    return row
