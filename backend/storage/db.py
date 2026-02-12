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
    """Create table if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            -- Timestamp of this analysis run
            timestamp TEXT NOT NULL,
            
            -- Raw numeric inputs
            cpi_mom_change REAL,
            pce_mom_change REAL,
            oil_change REAL,
            dxy_value REAL,
            dxy_change_7d REAL,
            vix REAL,
            ten_year_yield REAL,
            yield_curve_spread REAL,
            fed_balance_sheet_trend TEXT,
            sp500_change REAL,
            gold_change REAL,
            btc_price REAL,
            
            -- Per-section scores (JSON dict)
            section_scores TEXT NOT NULL,
            
            -- Section reasoning (JSON dict)
            section_reasoning TEXT,
            
            -- Weighted numeric score before headline adjustment
            weighted_numeric_score INTEGER NOT NULL,
            score_breakdown TEXT,
            
            -- Headline data
            headlines_fetched INTEGER DEFAULT 0,
            headlines_classified TEXT,
            headline_adjustment INTEGER DEFAULT 0,
            headline_reasoning TEXT,
            
            -- Final output
            final_score INTEGER NOT NULL,
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
            pivot_keyword_count INTEGER
        )
    """)
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
                timestamp,
                cpi_mom_change, pce_mom_change, oil_change,
                dxy_value, dxy_change_7d,
                vix, ten_year_yield, yield_curve_spread, fed_balance_sheet_trend,
                sp500_change, gold_change, btc_price,
                section_scores, section_reasoning,
                weighted_numeric_score, score_breakdown,
                headlines_fetched, headlines_classified, headline_adjustment, headline_reasoning,
                final_score, bias, action, confidence_pct, confidence_label,
                data_freshness_info,
                config_hash, prompt_version, llm_model,
                dovish_keyword_count, hawkish_keyword_count, pivot_keyword_count
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            snapshot.get("timestamp", datetime.now().isoformat()),
            snapshot.get("cpi_mom_change"),
            snapshot.get("pce_mom_change"),
            snapshot.get("oil_change"),
            snapshot.get("dxy_value"),
            snapshot.get("dxy_change_7d"),
            snapshot.get("vix"),
            snapshot.get("ten_year_yield"),
            snapshot.get("yield_curve_spread"),
            snapshot.get("fed_balance_sheet_trend"),
            snapshot.get("sp500_change"),
            snapshot.get("gold_change"),
            snapshot.get("btc_price"),
            json.dumps(snapshot.get("section_scores", {})),
            json.dumps(snapshot.get("section_reasoning", {})),
            snapshot.get("weighted_numeric_score", 50),
            json.dumps(snapshot.get("score_breakdown", {})),
            snapshot.get("headlines_fetched", 0),
            json.dumps(snapshot.get("headlines_classified", [])),
            snapshot.get("headline_adjustment", 0),
            snapshot.get("headline_reasoning", ""),
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
        ))
        conn.commit()
        row_id = cursor.lastrowid
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
        return [dict(row) for row in rows]
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
        return dict(row) if row else None
    finally:
        conn.close()
