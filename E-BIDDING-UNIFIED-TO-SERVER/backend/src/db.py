"""
Database helper: initializes SQLAlchemy engine for MySQL (default).
SQLite is ONLY used if DATABASE_URL explicitly starts with 'sqlite://'.
If DATABASE_URL is not set, MySQL is required and an error is raised.
"""
from __future__ import annotations

import os
import json
import sys
import threading
from pathlib import Path
from typing import Optional

from .logging_service import get_logger

logger = get_logger("src.db")

# ---------------------------------------------------------------------------
# Load environment variables from .env files
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    try:
        from .config_loader import ENV_FILE, CREDENTIALS_FILE, BASE_DIR
    except Exception:
        BASE_DIR = Path(__file__).resolve().parent.parent
        ENV_FILE = BASE_DIR / ".env"
        CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.env"
        PARENT_ENV_FILE = BASE_DIR.parent / ".env"
        if PARENT_ENV_FILE.exists():
            ENV_FILE = PARENT_ENV_FILE
    try:
        if CREDENTIALS_FILE and Path(CREDENTIALS_FILE).exists():
            load_dotenv(CREDENTIALS_FILE, override=True)
            logger.info("Loaded credentials file: %s", CREDENTIALS_FILE)
        if ENV_FILE and Path(ENV_FILE).exists():
            load_dotenv(ENV_FILE, override=True)
            logger.info("Loaded env file: %s", ENV_FILE)
    except Exception as e:
        logger.warning("dotenv loading failed: %s", e)
except Exception:
    BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# SQLAlchemy imports
# ---------------------------------------------------------------------------
try:
    from sqlalchemy import (
        create_engine,
        MetaData,
        Table,
        Column,
        String,
        Float,
        Integer,
        Text,
    )
    from sqlalchemy.event import listen
    from sqlalchemy.exc import SQLAlchemyError
except ImportError:
    create_engine = None  # type: ignore

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
ENGINE = None
METADATA = None
JOBS_TABLE = None
ARTIFACTS_TABLE = None
LIVE_BIDS_TABLE = None
FLEET_DAILY_TABLE = None
FLEET_REQUESTS_TABLE = None
NOTIFICATIONS_TABLE = None
BID_OUTCOMES_TABLE = None
SUCCESSFUL_BIDS_TABLE = None

DATABASE_URL = os.getenv("DATABASE_URL")

# Thread lock to prevent concurrent initialization
_INIT_LOCK = threading.Lock()
_INITIALIZED = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mask_db_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        if "://" not in url:
            return url
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            auth_part, tail = rest.split("@", 1)
            if ":" in auth_part:
                user, _ = auth_part.split(":", 1)
                return f"{scheme}://{user}:***@{tail}"
        return f"{scheme}://***@{rest}"
    except Exception:
        return "***redacted***"


def _log_sql_query(conn, cursor, statement, parameters, context, executemany):
    """Log SQL queries for debugging."""
    try:
        logger.debug("DB QUERY: %s | params=%s", statement, parameters)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# init_db - SINGLE ENTRY POINT for DB initialization
# ---------------------------------------------------------------------------
def init_db() -> Optional[str]:
    """Initialize the DB engine and create all tables.

    Rules:
    - MySQL is DEFAULT. If DATABASE_URL is set and not sqlite://, use MySQL.
    - SQLite ONLY if DATABASE_URL explicitly starts with 'sqlite://'.
    - If DATABASE_URL is not set, return error (MySQL is required).
    - Called once at startup. Subsequent calls are no-ops.

    Returns: error string on failure, None on success.
    """
    global ENGINE, METADATA, _INITIALIZED
    global JOBS_TABLE, ARTIFACTS_TABLE, LIVE_BIDS_TABLE
    global FLEET_DAILY_TABLE, FLEET_REQUESTS_TABLE, NOTIFICATIONS_TABLE
    global BID_OUTCOMES_TABLE, SUCCESSFUL_BIDS_TABLE

    # Fast path: already initialized
    if _INITIALIZED and ENGINE is not None:
        return None

    with _INIT_LOCK:
        # Double-check after acquiring lock
        if _INITIALIZED and ENGINE is not None:
            return None

        logger.info(
            "[db.py:%d] init_db called. DATABASE_URL=%s, ENGINE=%s, _INITIALIZED=%s",
            sys._getframe().f_lineno, _mask_db_url(DATABASE_URL),
            "SET" if ENGINE else "None", _INITIALIZED
        )

        # Validate DATABASE_URL
        if not DATABASE_URL:
            msg = "DATABASE_URL is not configured. MySQL is REQUIRED. Set DATABASE_URL in .env"
            logger.error("[db.py] %s", msg)
            return msg

        if create_engine is None:
            msg = "sqlalchemy is not installed but DATABASE_URL is configured"
            logger.error("[db.py] %s", msg)
            return msg

        # Determine mode
        is_sqlite = DATABASE_URL.startswith("sqlite://")
        if is_sqlite:
            logger.info("[db.py] SQLite mode (explicitly configured via DATABASE_URL)")
        else:
            logger.info("[db.py] MySQL mode (default)")

        try:
            ENGINE = create_engine(DATABASE_URL, pool_pre_ping=True)
            listen(ENGINE, "before_cursor_execute", _log_sql_query)
            METADATA = MetaData()

            # ----- JOBS TABLE -----
            JOBS_TABLE = Table(
                "jobs", METADATA,
                Column("job_id", String(64), primary_key=True),
                Column("truck_id", String(128), nullable=True),
                Column("depots", Text, nullable=True),
                Column("status", String(32), nullable=False, default="queued"),
                Column("created_at", Float, nullable=False),
                Column("started_at", Float, nullable=True),
                Column("completed_at", Float, nullable=True),
                Column("desired_bids_count", Integer, nullable=True),
                Column("results", Text, nullable=True),
                Column("errors", Text, nullable=True),
                Column("summary", Text, nullable=True),
                Column("desired_bids", Text, nullable=True),
                extend_existing=True,
            )

            # ----- JOB ARTIFACTS TABLE -----
            ARTIFACTS_TABLE = Table(
                "job_artifacts", METADATA,
                Column("id", String(64), primary_key=True),
                Column("job_id", String(64), nullable=False),
                Column("depot", String(128), nullable=True),
                Column("perf_csv_path", Text, nullable=True),
                Column("recording_path", Text, nullable=True),
                extend_existing=True,
            )

            # ----- LIVE BIDS TABLE -----
            LIVE_BIDS_TABLE = Table(
                "live_bids", METADATA,
                Column("id", String(64), primary_key=True),
                Column("job_id", String(64), nullable=False, index=True),
                Column("depot", String(128), nullable=False),
                Column("destination", String(128), nullable=True),
                Column("quantity", Float, nullable=False),
                Column("organization_name", String(256), nullable=True),
                Column("current_rank", Integer, nullable=True),
                Column("status", String(32), nullable=False, default="monitoring"),
                Column("won_timestamp", String(32), nullable=True),
                Column("user_control", String(32), nullable=False, default="active"),
                Column("updated_at", String(32), nullable=False),
                extend_existing=True,
            )

            # ----- FLEET DAILY TABLE -----
            FLEET_DAILY_TABLE = Table(
                "fleet_daily_entries", METADATA,
                Column("id", String(16), primary_key=True),
                Column("business_date", String(32), nullable=False, index=True),
                Column("truck_id", String(64), nullable=True),
                Column("truck_number", String(128), nullable=False),
                Column("driver_name", String(256), nullable=False, default=""),
                Column("tonnage", String(32), nullable=False),
                Column("previous_depot", String(128), nullable=True),
                Column("current_depot", String(128), nullable=False),
                Column("destination", String(128), nullable=True),
                Column("status", String(32), nullable=False),
                Column("remarks", Text, nullable=True),
                Column("available_since", String(32), nullable=True),
                Column("updated_at", String(32), nullable=False),
                extend_existing=True,
            )

            # ----- FLEET REQUESTS TABLE -----
            FLEET_REQUESTS_TABLE = Table(
                "fleet_control_requests", METADATA,
                Column("id", String(16), primary_key=True),
                Column("leg_id", String(64), nullable=False),
                Column("job_id", String(64), nullable=True),
                Column("truck_number", String(128), nullable=True),
                Column("request_type", String(32), nullable=False),
                Column("status", String(32), nullable=False, default="Pending"),
                Column("depot_name", String(128), nullable=True),
                Column("destination", String(128), nullable=True),
                Column("tonnage", Float, nullable=True),
                Column("plant_name", String(256), nullable=True),
                Column("requested_by", String(256), nullable=False),
                Column("requested_at", String(32), nullable=False),
                Column("resolved_by", String(256), nullable=True),
                Column("resolved_at", String(32), nullable=True),
                Column("remarks", Text, nullable=True),
                extend_existing=True,
            )

            # ----- NOTIFICATIONS TABLE -----
            NOTIFICATIONS_TABLE = Table(
                "notifications", METADATA,
                Column("id", String(16), primary_key=True),
                Column("event_type", String(64), nullable=False),
                Column("title", String(256), nullable=False),
                Column("message", Text, nullable=False),
                Column("type", String(32), nullable=False, default="info"),
                Column("job_id", String(64), nullable=True, index=True),
                Column("leg_id", String(64), nullable=True),
                Column("depot", String(128), nullable=True),
                Column("destination", String(128), nullable=True),
                Column("quantity", Float, nullable=True),
                Column("truck_number", String(128), nullable=True),
                Column("rank", Integer, nullable=True),
                Column("read_at", String(32), nullable=True),
                Column("created_at", String(32), nullable=False),
                Column("source_key", String(256), nullable=True, unique=True),
                extend_existing=True,
            )

            # ----- BID OUTCOMES TABLE -----
            BID_OUTCOMES_TABLE = Table(
                "bid_outcomes", METADATA,
                Column("outcome_id", String(16), primary_key=True),
                Column("leg_id", String(64), nullable=False, unique=True),
                Column("job_id", String(64), nullable=False, index=True),
                Column("depot", String(128), nullable=False),
                Column("destination", String(128), nullable=True),
                Column("quantity", Float, nullable=False),
                Column("organization_name", String(256), nullable=True),
                Column("bid_amount", Integer, nullable=True),
                Column("rank", Integer, nullable=True),
                Column("outcome_status", String(32), nullable=False),
                Column("started_at", String(32), nullable=True),
                Column("completed_at", String(32), nullable=True),
                Column("duration_ms", Integer, nullable=True),
                Column("created_at", String(32), nullable=False),
                extend_existing=True,
            )

            # ----- SUCCESSFUL BIDS TABLE -----
            SUCCESSFUL_BIDS_TABLE = Table(
                "successful_bids", METADATA,
                Column("id", Integer, primary_key=True, autoincrement=True),
                Column("depot", String(128), nullable=False, index=True),
                Column("destination", String(128), nullable=True),
                Column("quantity", Float, nullable=False),
                Column("bid_amount", Integer, nullable=False),
                Column("won_timestamp", String(32), nullable=False),
                Column("rank", Integer, nullable=False, default=1),
                extend_existing=True,
            )

            # Create all tables
            METADATA.create_all(ENGINE)
            _INITIALIZED = True
            logger.info("[db.py] DB initialized successfully. URL=%s", _mask_db_url(DATABASE_URL))
            return None

        except Exception as e:
            logger.exception("[db.py] DB init FAILED for %s", _mask_db_url(DATABASE_URL))
            ENGINE = None
            METADATA = None
            return str(e)


# ---------------------------------------------------------------------------
# Accessor functions
# ---------------------------------------------------------------------------
def get_engine():
    """Get the DB engine. Calls init_db() if not yet initialized."""
    if ENGINE is None:
        init_db()
    return ENGINE


def get_tables():
    if JOBS_TABLE is None:
        init_db()
    return METADATA, JOBS_TABLE, ARTIFACTS_TABLE


def get_live_bids_table():
    if LIVE_BIDS_TABLE is None:
        init_db()
    return LIVE_BIDS_TABLE


def get_fleet_daily_table():
    if FLEET_DAILY_TABLE is None:
        init_db()
    return FLEET_DAILY_TABLE


def get_fleet_requests_table():
    if FLEET_REQUESTS_TABLE is None:
        init_db()
    return FLEET_REQUESTS_TABLE


def get_notifications_table():
    if NOTIFICATIONS_TABLE is None:
        init_db()
    return NOTIFICATIONS_TABLE


def get_bid_outcomes_table():
    if BID_OUTCOMES_TABLE is None:
        init_db()
    return BID_OUTCOMES_TABLE


def get_successful_bids_table():
    if SUCCESSFUL_BIDS_TABLE is None:
        init_db()
    return SUCCESSFUL_BIDS_TABLE


def safe_json_dumps(obj):
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return json.dumps({"error": "serialization_failed"})
