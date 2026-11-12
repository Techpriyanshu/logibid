# src/config_loader.py

import os
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml
from dotenv import load_dotenv
from .depot_normalization import normalize_depot_name
from .logging_service import get_logger

logger = get_logger(__name__)

# -------------------------------------------------
# Paths
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.env"
APP_CONFIG_FILE = BASE_DIR / "config" / "application.yaml"

# Also check parent directory for .env (project root)
PARENT_DIR = BASE_DIR.parent
PARENT_ENV_FILE = PARENT_DIR / ".env"
if PARENT_ENV_FILE.exists():
    ENV_FILE = PARENT_ENV_FILE


def normalize_excluded_spi_by_tonnage_config(config: dict) -> None:
    """
    Build ``excluded_spi_by_tonnage`` from application.yaml.

    Keys: integer tonnage (18, 25, 30, …). Values: SPI strings (exact match at plan time;
    case-sensitive, no trimming of SPI value characters).
    """
    raw = config.get("excluded_spi_by_tonnage")
    by_tonnage: Dict[int, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                ton_key = int(float(str(k).strip()))
            except (TypeError, ValueError):
                continue
            if v is None:
                continue
            spi = str(v)
            if not spi:
                continue
            by_tonnage[ton_key] = spi
    config["excluded_spi_by_tonnage"] = by_tonnage


def normalize_company_name(value: Any) -> str:
    """
    Exact-match key for company exclusion: strip, collapse whitespace, casefold.
    No fuzzy / contains / regex.
    """
    s = str(value or "").strip()
    s = " ".join(s.split())
    return s.casefold()


def normalize_excluded_companies_by_depot_config(config: dict) -> None:
    """
    Build ``excluded_companies_by_depot`` from application.yaml.

    Keys: normalized depot names (UPPER). Values: sets of normalized company names.
    """
    raw = config.get("excluded_companies_by_depot")
    by_depot: Dict[str, Set[str]] = {}
    if isinstance(raw, dict):
        for depot_key, companies in raw.items():
            depot = normalize_depot_name(str(depot_key) if depot_key is not None else "")
            if not depot:
                continue
            names: Set[str] = set()
            if isinstance(companies, (list, tuple, set)):
                iterable = companies
            elif companies is None:
                iterable = []
            else:
                iterable = [companies]
            for c in iterable:
                n = normalize_company_name(c)
                if n:
                    names.add(n)
            if names:
                by_depot.setdefault(depot, set()).update(names)
    config["excluded_companies_by_depot"] = by_depot


# -------------------------------------------------
# Load Environment Files (.env last so local/server overrides credentials.env)
# -------------------------------------------------
if CREDENTIALS_FILE.exists():
    load_dotenv(CREDENTIALS_FILE, override=True)
    logger.info(f"Loaded credentials file: {CREDENTIALS_FILE}")
else:
    logger.warning(f"credentials.env not found: {CREDENTIALS_FILE}")

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)
    logger.info(f"Loaded env file: {ENV_FILE}")
else:
    logger.warning(f".env file not found: {ENV_FILE}")

# -------------------------------------------------
# Load YAML Application Config (with env overrides for VPS)
# -------------------------------------------------
def get_app_config() -> dict:
    if not APP_CONFIG_FILE.exists():
        raise RuntimeError(f"❌ application.yaml not found: {APP_CONFIG_FILE}")

    with open(APP_CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f)

    # Env overrides: .env (loaded last) wins so local Windows vs server Linux can differ.
    # The authoritative default for headless comes from application.yaml (browser.headless).
    browser_config = config.get("browser", {}) or {}

    headless_env = os.getenv("HEADLESS", "").strip().lower()
    if headless_env in ("true", "1", "yes"):
        browser_config["headless"] = True
    elif headless_env in ("false", "0", "no"):
        browser_config["headless"] = False

    chrome_binary_env = os.getenv("CHROME_BINARY")
    if chrome_binary_env:
        browser_config["binary_path"] = chrome_binary_env

    proxy_env = os.getenv("BROWSER_PROXY")
    if proxy_env:
        browser_config["proxy"] = proxy_env.strip()

    config["browser"] = browser_config

    mode = os.getenv("AUTOMATION_EXECUTION_MODE", "").strip().lower()
    if mode in ("legacy", "multiprocess"):
        auto = config.setdefault("automation", {})
        if isinstance(auto, dict):
            auto["execution_mode"] = mode

    # Operator window rotation defaults (Phase 1 — UI only; env applied in get_window_rotation_settings)
    wr = config.setdefault("window_rotation", {})
    if not isinstance(wr, dict):
        wr = {}
        config["window_rotation"] = wr
    wr.setdefault("enabled", False)
    wr.setdefault("interval_seconds", 5)
    wr.setdefault("freeze_on_execution", True)

    sio = config.setdefault("start_in_observer", {})
    if not isinstance(sio, dict):
        sio = {}
        config["start_in_observer"] = sio
    sio.setdefault("enabled", True)
    sio.setdefault("sample_interval_seconds", 5)
    sio.setdefault("poll_interval_seconds", 0.5)
    sio.setdefault("freeze_unchanged_samples", 2)

    normalize_excluded_spi_by_tonnage_config(config)
    normalize_excluded_companies_by_depot_config(config)
    sap_cfg = config.get("sap")
    if isinstance(sap_cfg, dict):
        yaml_depots = sap_cfg.get("depots")
        if isinstance(yaml_depots, list):
            sap_cfg["depots"] = [
                normalize_depot_name(d) for d in yaml_depots if str(d).strip()
            ]
            sap_cfg["depots"] = [d for d in sap_cfg["depots"] if d]
    tonnage_rules = len(config.get("excluded_spi_by_tonnage") or {})
    company_depots = len(config.get("excluded_companies_by_depot") or {})
    logger.info(
        "✅ application.yaml loaded | excluded_spi_by_tonnage: %d tonnage keys | "
        "excluded_companies_by_depot: %d depots",
        tonnage_rules,
        company_depots,
    )
    return config


# -------------------------------------------------
# Load Credentials Separately
# -------------------------------------------------
def get_credentials() -> dict:
    creds = {
        "username": os.getenv("E2S_USERNAME"),
        "password": os.getenv("E2S_PASSWORD"),
    }

    if not creds["username"] or not creds["password"]:
        raise RuntimeError("❌ Missing credentials in config/credentials.env")

    return creds
