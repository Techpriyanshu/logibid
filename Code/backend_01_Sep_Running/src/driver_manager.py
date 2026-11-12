# src/driver_manager.py

from .driver_factory import create_driver
from .logging_service import get_logger

logger = get_logger("driver_manager")

_driver = None


def get_driver(depot_name=None):
    """
    Production mode:
    Single global driver instance.
    depot_name kept only for compatibility with old code.
    """
    global _driver

    if _driver is None:
        logger.info("🧠 Creating global Selenium driver instance")
        _driver = create_driver()
    else:
        logger.info("♻️ Reusing existing Selenium driver instance")

    return _driver


def close_driver():
    global _driver

    if _driver:
        try:
            logger.info("Closing global Selenium driver (all tabs will close)")
            _driver.quit()
            logger.info("Global Selenium driver closed successfully")
        except Exception as e:
            logger.warning("Global Selenium driver close failed: %s", e)
        _driver = None
