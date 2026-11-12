from __future__ import annotations

import importlib
import os
import random
import re
import shutil
import ssl
import subprocess
import tempfile
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium_stealth import stealth
from webdriver_manager.chrome import ChromeDriverManager

from . import execution_logging as elog
from .logging_service import get_logger
from .config_loader import get_app_config


logger = get_logger("driver_factory")

CHROME_FALLBACK_WIN = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_FALLBACK_LINUX = "/usr/bin/google-chrome"

CHROME_UA_LINUX = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _chromedriver_filename() -> str:
    return "chromedriver.exe" if os.name == "nt" else "chromedriver"


def _detect_chrome_major_version(binary_path: str) -> int | None:
    try:
        out = subprocess.check_output(
            [binary_path, "--version"],
            timeout=5,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        match = re.search(r"(\d+)\.\d+\.\d+", out)
        return int(match.group(1)) if match else None
    except Exception:
        if os.name == "nt":
            try:
                ps_cmd = (
                    "powershell.exe -NoLogo -NoProfile -NonInteractive "
                    "-ExecutionPolicy Bypass "
                    f"-Command \"(Get-Item '{binary_path}').VersionInfo.ProductVersion\""
                )
                out = subprocess.check_output(
                    ps_cmd,
                    timeout=15,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    shell=True,
                )
                match = re.search(r"(\d+)\.\d+\.\d+", out)
                return int(match.group(1)) if match else None
            except Exception:
                return None
        return None


def _is_retryable_bootstrap_error(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            ssl.SSLError,
            OSError,
            PermissionError,
            FileExistsError,
            TimeoutError,
            ConnectionError,
            BlockingIOError,
        ),
    ):
        return True
    msg = (str(exc) or "").lower()
    needles = (
        "decryption_failed",
        "bad_record_mac",
        "ssl",
        "file exists",
        "being used by another",
        "cannot access",
        "winerror 32",
        "rename",
        "chromedriver",
        "connection reset",
        "connection aborted",
        "tempfailure",
        "timed out",
        "session not created",
        "cannot connect to chrome",
        "cannot reuse the chromeoptions",
        "supports chrome version",
    )
    return any(n in msg for n in needles)


def _cached_chromedriver_path(major: int | None = None) -> str | None:
    """Newest webdriver-manager cached chromedriver, preferring the given Chrome major."""
    cache_root = Path.home() / ".wdm" / "drivers" / "chromedriver"
    candidates = []
    for exe in cache_root.glob(f"*/*/*/**/{_chromedriver_filename()}"):
        match = re.search(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", str(exe.relative_to(cache_root)))
        if match:
            candidates.append((tuple(int(p) for p in match.groups()), exe))
    if major is not None:
        candidates = [c for c in candidates if c[0][0] == major]
    if not candidates:
        return None
    return str(max(candidates, key=lambda c: c[0])[1])


def _root_dir() -> Path:
    root = Path(tempfile.gettempdir()) / "ebidding_driver_isolated"
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_driver(headless_override: bool | None = None):
    """Create Chrome driver with optional headless override from API request."""
    logger.info("Starting Chrome driver (pid=%s)", os.getpid())
    elog.log_event(
        phase="BROWSER",
        component="driver",
        action="BOOTSTRAP_START",
        status="ok",
        message="Starting Chrome driver bootstrap",
    )

    config = get_app_config()
    browser_config = config.get("browser", {})

    chrome_binary = browser_config.get("binary_path", "/usr/bin/google-chrome")
    logger.info(f"Chrome binary from config: {chrome_binary}")
    
    if not os.path.isfile(chrome_binary) and not Path(chrome_binary).is_file():
        logger.warning(f"Configured Chrome path not found: {chrome_binary}")
        fallback = CHROME_FALLBACK_WIN if os.name == "nt" else CHROME_FALLBACK_LINUX
        logger.info(f"Checking fallback Chrome path: {fallback}")
        if os.path.isfile(fallback) or Path(fallback).is_file():
            logger.warning(
                "Configured Chrome path not found (%s), using fallback: %s",
                chrome_binary,
                fallback,
            )
            chrome_binary = fallback
        else:
            logger.error(
                "Configured Chrome path not found: %s (no fallback available)",
                chrome_binary,
            )
            raise RuntimeError(f"Chrome not found at {chrome_binary} or {fallback}")
    
    # Verify Chrome binary exists
    if not os.path.isfile(chrome_binary):
        logger.error(f"Chrome binary does not exist: {chrome_binary}")
        raise FileNotFoundError(f"Chrome binary not found: {chrome_binary}")
    
    logger.info(f"Using Chrome binary: {chrome_binary}")
    logger.info(f"Chrome binary path exists: {Path(chrome_binary).exists()}")
    logger.info(f"Chrome binary is file: {Path(chrome_binary).is_file()}")

    headless = bool(browser_config.get("headless", False))
    window_size = browser_config.get("window_size", "1920,1080")
    proxy = browser_config.get("proxy")

    # Override headless mode from API request
    if headless_override is not None:
        original_headless = headless
        headless = headless_override
        logger.info(f"Headless mode override: {original_headless} -> {headless} (from API request)")

    logger.info("Chrome binary: %s", chrome_binary)
    logger.info("Chrome Headless Mode: %s", headless)

    version_main_env = os.getenv("CHROME_VERSION_MAIN", "").strip()
    env_main = int(version_main_env) if version_main_env.isdigit() else None
    detected_main = _detect_chrome_major_version(chrome_binary)
    # Prefer detected major from the actual Chrome binary
    if detected_main is not None:
        version_main = detected_main
        src = "auto-detect"
    elif env_main is not None:
        version_main = env_main
        src = "env CHROME_VERSION_MAIN"
    else:
        version_main = None
        src = ""
    if version_main is not None:
        logger.info("Using Chrome major version: %s (%s)", version_main, src)
    else:
        logger.warning(
            "Could not detect Chrome major version. Set CHROME_VERSION_MAIN to avoid driver mismatch."
        )

    max_attempts = max(1, int(browser_config.get("chromedriver_create_retries", 6)))
    base_delay = float(browser_config.get("chromedriver_retry_base_delay_seconds", 2.0))

    def _fresh_options() -> Options:
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-sync")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-first-run")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-infobars")
        options.add_argument("--lang=en-US,en")
        options.add_argument(f"--user-agent={CHROME_UA_LINUX}")
        options.add_argument(f"--window-size={window_size}")
        if headless:
            options.add_argument("--headless=new")
        if proxy:
            logger.info("Using proxy: %s", proxy)
            options.add_argument(f"--proxy-server={proxy}")
        options.binary_location = chrome_binary
        return options

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            work_dir = Path(
                tempfile.mkdtemp(
                    prefix=f"selenium_{os.getpid()}_",
                    dir=_root_dir(),
                )
            )
            logger.info(
                "Bootstrap attempt %d/%d work_dir=%s",
                attempt,
                max_attempts,
                work_dir,
            )

            # Install chromedriver using webdriver-manager
            logger.info("Installing chromedriver using webdriver-manager...")
            try:
                driver_executable_path = ChromeDriverManager().install()
            except OSError as install_exc:
                # A running chromedriver locks the cached exe, so a refresh can't overwrite it.
                driver_executable_path = _cached_chromedriver_path(version_main)
                if not driver_executable_path:
                    raise
                logger.warning(
                    "Chromedriver refresh failed (%s); using cached driver %s",
                    install_exc,
                    driver_executable_path,
                )
            logger.info(f"Chromedriver installed at: {driver_executable_path}")
            
            # Verify chromedriver exists
            if not Path(driver_executable_path).exists():
                logger.error(f"Chromedriver not found at: {driver_executable_path}")
                raise FileNotFoundError(f"Chromedriver not found at {driver_executable_path}")
            
            logger.info(f"Chromedriver file exists: {Path(driver_executable_path).exists()}")
            logger.info(f"Chromedriver is file: {Path(driver_executable_path).is_file()}")
            
            # Get chromedriver version
            try:
                import subprocess
                logger.info(f"Getting chromedriver version...")
                result = subprocess.run([driver_executable_path, "--version"], 
                                      capture_output=True, text=True, timeout=5)
                logger.info(f"Chromedriver version: {result.stdout.strip()}")
            except subprocess.TimeoutExpired:
                logger.error("Chromedriver version check timed out")
                raise
            except Exception as e:
                logger.warning(f"Could not get chromedriver version: {e}")

            # Create service
            service = Service(driver_executable_path)
            logger.info(f"Service created with driver path: {service.path}")

            # Create driver with options
            options = _fresh_options()
            logger.info(f"Creating Chrome driver with service path: {service.path}")
            logger.info(f"Options binary location: {options.binary_location}")
            logger.info(f"Starting webdriver.Chrome()...")
            driver = webdriver.Chrome(service=service, options=options)
            chromedriver_pid = getattr(getattr(service, "process", None), "pid", None)
            logger.info("Chrome driver created successfully (chromedriver_pid=%s, worker_pid=%s)", chromedriver_pid, os.getpid())

            # Apply selenium-stealth to hide automation
            stealth(
                driver=driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
            )

            # Additional anti-detection
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
                        delete navigator.__proto__.webdriver;
                        window.chrome = {runtime: {}};
                        Object.defineProperty(window, 'canvas', {get: () => undefined});
                    """
                },
            )

            logger.info("Chrome driver started successfully")
            elog.log_event(
                phase="BROWSER",
                component="driver",
                action="BOOTSTRAP_OK",
                status="ok",
                message="Chrome driver started successfully",
                retry=f"{attempt}/{max_attempts}",
            )
            return driver
        except Exception as e:
            last_exc = e
            logger.warning(
                "Chrome driver bootstrap failed (attempt %d/%d): %s",
                attempt,
                max_attempts,
                e,
            )
            elog.log_error(
                phase="BROWSER",
                component="driver",
                action="BOOTSTRAP_FAIL",
                message=f"Chrome driver bootstrap failed attempt={attempt}",
                exc=e,
                retry=f"{attempt}/{max_attempts}",
                recovery="retry" if attempt < max_attempts else "raise",
            )
            if attempt >= max_attempts or not _is_retryable_bootstrap_error(e):
                logger.exception("Failed to create Chrome driver (giving up)")
                raise RuntimeError(f"Chrome driver failed: {e}") from e
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.25, 1.25)
            logger.info("Retrying driver bootstrap in %.2fs", delay)
            time.sleep(delay)

    raise RuntimeError(f"Chrome driver failed: {last_exc}") from last_exc
