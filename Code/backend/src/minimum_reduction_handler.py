"""
Automatic handler for the SAP validation popup:

    "Reduce your bid by minimum Rs. 4.000 from L1 bid amount for COF order 5578118593 Line no 000101"

Pure logic (parsing, Decimal math, row matching, retry guard) is separate from the Selenium
adapter so it can be unit-tested without a browser. Nothing here touches login, session,
proxy or access-block handling, and SAP's server-side validation is never bypassed: the
handler only lowers a bid to a value SAP itself asked for, and the normal Save flow re-submits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from .logging_service import get_logger

logger = get_logger(__name__)

HARD_MAX_RETRIES = 5


class MinimumReductionError(Exception):
    """Base class; message is a user-facing diagnostic."""


class ConfigError(MinimumReductionError):
    pass


class PopupParseError(MinimumReductionError):
    pass


class RowMatchError(MinimumReductionError):
    pass


class BidCalculationError(MinimumReductionError):
    pass


# --------------------------------------------------------------------------
# Amount / message parsing
# --------------------------------------------------------------------------
_AMOUNT_TOKEN = r"[0-9][0-9.,\s]*[0-9]|[0-9]"
_MESSAGE_RE = re.compile(
    r"reduce\s+(?:your\s+)?bid\s+by\s+(?:a\s+)?(?:minimum|min\.?)\s*(?:of\s+)?"
    r"(?:(?:rs\.?|inr|rupees?|\u20b9)\s*)?(?P<amount>" + _AMOUNT_TOKEN + r")",
    re.IGNORECASE,
)
_ORDER_RE = re.compile(r"(?:cof\s+)?order\s*(?:no\.?|number|#)?\s*[:\-]?\s*(?P<order>\d{4,})", re.IGNORECASE)
_LINE_RE = re.compile(r"line\s*(?:no\.?|number|item|#)?\s*[:\-]?\s*(?P<line>\d+)", re.IGNORECASE)


def parse_amount(raw: Any) -> Decimal:
    """
    Parse a currency string into Decimal. Handles "Rs. 4.000", "\u20b94", "1,234.50",
    "1,23,456", "1.234,50", "4,5" and surrounding whitespace.
    A lone separator followed by exactly three digits is a thousands separator only for
    commas ("1,234"); a lone dot is always decimal ("4.000" == 4).
    """
    if isinstance(raw, Decimal):
        return raw
    if raw is None or isinstance(raw, bool):
        raise ValueError("amount missing")
    s = re.sub(r"(?i)rs\.?|inr|rupees?|\u20b9", "", str(raw))
    s = re.sub(r"\s+", "", s).strip(".,")
    if not s or not re.fullmatch(r"[0-9.,]+", s):
        raise ValueError(f"not a currency amount: {raw!r}")
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        dec_sep = "." if last_dot > last_comma else ","
    elif last_comma >= 0:
        digits_after = len(s) - last_comma - 1
        dec_sep = "," if (s.count(",") == 1 and digits_after != 3) else None
    elif last_dot >= 0:
        dec_sep = "." if s.count(".") == 1 else None
    else:
        dec_sep = None
    if dec_sep:
        head, _, tail = s.rpartition(dec_sep)
        head = head.replace(".", "").replace(",", "")
        s = f"{head or '0'}.{tail}"
    else:
        s = s.replace(".", "").replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"not a currency amount: {raw!r}") from exc


@dataclass(frozen=True)
class ReductionMessage:
    raw: str
    min_reduction: Decimal
    order: Optional[str]
    line: Optional[str]


def is_minimum_reduction_message(text: Optional[str]) -> bool:
    return bool(text) and _MESSAGE_RE.search(" ".join(str(text).split())) is not None


def parse_minimum_reduction_message(text: Optional[str]) -> ReductionMessage:
    if not text or not str(text).strip():
        raise PopupParseError("SAP popup message is empty")
    norm = " ".join(str(text).split())
    m = _MESSAGE_RE.search(norm)
    if not m:
        raise PopupParseError(f"Popup is not a minimum-reduction message: {norm[:200]!r}")
    try:
        minimum = parse_amount(m.group("amount"))
    except ValueError as exc:
        raise PopupParseError(f"Cannot parse minimum reduction in: {norm[:200]!r}") from exc
    if minimum <= 0:
        raise PopupParseError(f"Minimum reduction must be positive, got {minimum}")
    rest = norm[m.end():]
    om = _ORDER_RE.search(rest)
    lm = _LINE_RE.search(rest)
    return ReductionMessage(
        raw=norm,
        min_reduction=minimum,
        order=om.group("order") if om else None,
        line=lm.group("line") if lm else None,
    )


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def _decimal_setting(name: str, value: Any, default: Decimal) -> Decimal:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ConfigError(f"bid_reduction.{name} must be a number, got boolean")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ConfigError(f"bid_reduction.{name} must be a number, got {value!r}") from exc
    if not d.is_finite() or d < 0:
        raise ConfigError(f"bid_reduction.{name} must be >= 0, got {value!r}")
    return d


def _bool_setting(name: str, value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ConfigError(f"bid_reduction.{name} must be true or false, got {value!r}")


@dataclass(frozen=True)
class MinimumReductionConfig:
    auto_handle_minimum_reduction: bool = False
    configured_reduction_amount: Decimal = Decimal("0")
    safety_margin: Decimal = Decimal("0")
    max_bid_retry_attempts: int = 2
    require_confirmation_for_exact_bid_conflicts: bool = True

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "MinimumReductionConfig":
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise ConfigError("bid_reduction must be a mapping")
        retries_raw = raw.get("max_bid_retry_attempts", cls.max_bid_retry_attempts)
        if isinstance(retries_raw, bool) or not isinstance(retries_raw, int):
            raise ConfigError(f"bid_reduction.max_bid_retry_attempts must be an integer, got {retries_raw!r}")
        if not 0 <= retries_raw <= HARD_MAX_RETRIES:
            raise ConfigError(
                f"bid_reduction.max_bid_retry_attempts must be between 0 and {HARD_MAX_RETRIES}, got {retries_raw}"
            )
        return cls(
            auto_handle_minimum_reduction=_bool_setting(
                "auto_handle_minimum_reduction", raw.get("auto_handle_minimum_reduction"), False
            ),
            configured_reduction_amount=_decimal_setting(
                "configured_reduction_amount", raw.get("configured_reduction_amount"), Decimal("0")
            ),
            safety_margin=_decimal_setting("safety_margin", raw.get("safety_margin"), Decimal("0")),
            max_bid_retry_attempts=retries_raw,
            require_confirmation_for_exact_bid_conflicts=_bool_setting(
                "require_confirmation_for_exact_bid_conflicts",
                raw.get("require_confirmation_for_exact_bid_conflicts"),
                True,
            ),
        )


# --------------------------------------------------------------------------
# Calculation
# --------------------------------------------------------------------------
def effective_reduction(sap_minimum: Decimal, cfg: MinimumReductionConfig) -> Decimal:
    """max(SAP minimum, configured) + safety margin. A smaller configured value never wins."""
    return max(sap_minimum, cfg.configured_reduction_amount) + cfg.safety_margin


def calculate_new_bid(l1_bid: Optional[Decimal], sap_minimum: Decimal, cfg: MinimumReductionConfig) -> Decimal:
    if l1_bid is None:
        raise BidCalculationError("L1 bid amount is missing")
    if l1_bid <= 0:
        raise BidCalculationError(f"L1 bid amount is not positive: {l1_bid}")
    reduction = effective_reduction(sap_minimum, cfg)
    new_bid = l1_bid - reduction
    if new_bid <= 0:
        raise BidCalculationError(
            f"Calculated bid {new_bid} is not positive (L1={l1_bid}, reduction={reduction})"
        )
    if new_bid > l1_bid - sap_minimum:
        raise BidCalculationError("Calculated bid does not satisfy SAP's minimum reduction")
    return new_bid


def format_bid(amount: Decimal) -> str:
    """Plain decimal text without exponent or trailing zeros ("196", "196.5")."""
    if amount == amount.to_integral_value():
        return str(int(amount))
    return format(amount.normalize(), "f")


# --------------------------------------------------------------------------
# Row matching
# --------------------------------------------------------------------------
@dataclass
class BidRow:
    row_index: int
    text: str
    l1_text: Optional[str] = None
    handle: Any = None  # Selenium row element or test double


def _digit_tokens(text: str) -> List[str]:
    return re.findall(r"\d+", text or "")


def match_rows(rows: Sequence[BidRow], order: Optional[str], line: Optional[str]) -> List[BidRow]:
    """Rows whose text contains the order number and the line number as whole numeric tokens."""
    def _line_ok(tokens: List[str]) -> bool:
        stripped = line.lstrip("0")
        return any(
            t == line or (t.lstrip("0") == stripped and (t.startswith("0") or line.startswith("0")))
            for t in tokens
        )

    matched: List[BidRow] = []
    for r in rows:
        tokens = _digit_tokens(r.text)
        if order and order not in tokens:
            continue
        if line and not _line_ok(tokens):
            continue
        matched.append(r)
    return matched


def select_unique_row(rows: Sequence[BidRow], msg: ReductionMessage) -> BidRow:
    if not msg.order and not msg.line:
        raise RowMatchError("SAP message has neither order nor line number; cannot identify the bid row")
    found = match_rows(rows, msg.order, msg.line)
    if not found:
        raise RowMatchError(f"No table row matches order={msg.order} line={msg.line}")
    if len(found) > 1:
        raise RowMatchError(
            f"Ambiguous: {len(found)} rows match order={msg.order} line={msg.line} "
            f"(row indexes {[r.row_index for r in found]})"
        )
    return found[0]


# --------------------------------------------------------------------------
# UI abstraction + handler
# --------------------------------------------------------------------------
class BidUi(Protocol):
    def list_rows(self) -> List[BidRow]: ...
    def set_bid(self, row: BidRow, value: str) -> None: ...
    def read_bid(self, row: BidRow) -> str: ...
    def close_popup(self) -> None: ...
    def wait_popup_closed(self) -> bool: ...


@dataclass
class HandlerResult:
    action: str  # "retry" (re-run Save flow) or "stop"
    reason: str = ""
    order: Optional[str] = None
    line: Optional[str] = None
    new_bid: Optional[Decimal] = None
    row_index: Optional[int] = None


@dataclass
class MinimumReductionHandler:
    cfg: MinimumReductionConfig
    ui: BidUi
    log_prefix: str = ""
    attempts: int = 0
    _applied: Dict[Any, Decimal] = field(default_factory=dict)

    def _stop(self, reason: str, **kw: Any) -> HandlerResult:
        logger.error("%s [MIN_REDUCTION][STOP] %s", self.log_prefix, reason)
        return HandlerResult(action="stop", reason=reason, **kw)

    def handle(self, message: str, planned: Sequence[Mapping[str, Any]]) -> HandlerResult:
        p = self.log_prefix
        if not self.cfg.auto_handle_minimum_reduction:
            return self._stop("auto_handle_minimum_reduction is disabled")
        logger.info("%s [MIN_REDUCTION] SAP validation message: %s", p, " ".join(str(message).split())[:300])
        if self.attempts >= self.cfg.max_bid_retry_attempts:
            return self._stop(
                f"Retry limit reached ({self.attempts}/{self.cfg.max_bid_retry_attempts}); SAP keeps rejecting the bid"
            )
        try:
            msg = parse_minimum_reduction_message(message)
            row = select_unique_row(self.ui.list_rows(), msg)
        except MinimumReductionError as exc:
            return self._stop(str(exc))
        key = (msg.order, msg.line, row.row_index)
        ctx = dict(order=msg.order, line=msg.line, row_index=row.row_index)

        planned_row = next((x for x in planned if x.get("row_index") == row.row_index), None)
        if planned_row is None:
            return self._stop(f"Matched row {row.row_index} is not part of the planned bids", **ctx)
        if planned_row.get("exact_bid") or planned_row.get("exact_bid_amount") is not None:
            if self.cfg.require_confirmation_for_exact_bid_conflicts:
                return self._stop(
                    f"Exact-bid rule conflicts with SAP minimum reduction {msg.min_reduction} on row "
                    f"{row.row_index}; user review required",
                    **ctx,
                )

        try:
            l1 = parse_amount(row.l1_text)
        except ValueError:
            return self._stop(f"L1 bid amount missing/unreadable on row {row.row_index}: {row.l1_text!r}", **ctx)
        try:
            new_bid = calculate_new_bid(l1, msg.min_reduction, self.cfg)
        except BidCalculationError as exc:
            return self._stop(str(exc), **ctx)
        if key in self._applied and self._applied[key] <= new_bid:
            return self._stop(f"Repeated popup for row {row.row_index} after bid {self._applied[key]}", **ctx)

        self.attempts += 1
        logger.info(
            "%s [MIN_REDUCTION] order=%s line=%s row=%s L1=%s sap_min=%s configured=%s margin=%s "
            "effective=%s new_bid=%s attempt=%d/%d",
            p, msg.order, msg.line, row.row_index, l1, msg.min_reduction,
            self.cfg.configured_reduction_amount, self.cfg.safety_margin,
            effective_reduction(msg.min_reduction, self.cfg), new_bid,
            self.attempts, self.cfg.max_bid_retry_attempts,
        )
        text = format_bid(new_bid)
        popup_closed = False
        try:
            try:
                self.ui.set_bid(row, text)
            except Exception as exc:  # blocklayer may intercept input; close popup first
                logger.warning("%s [MIN_REDUCTION] Direct fill failed (%s); closing popup first", p, exc)
                self.ui.close_popup()
                popup_closed = True
                if not self.ui.wait_popup_closed():
                    return self._stop("Popup did not close", **ctx)
                self.ui.set_bid(row, text)
            if not self._verify(row, new_bid):
                return self._stop(f"Bid field on row {row.row_index} does not contain {text}", **ctx)
            if not popup_closed:
                self.ui.close_popup()
                if not self.ui.wait_popup_closed():
                    return self._stop("Popup did not close", **ctx)
            if not self._verify(row, new_bid):
                return self._stop(f"Bid field on row {row.row_index} changed after popup closed", **ctx)
        except Exception as exc:
            return self._stop(f"UI interaction failed: {type(exc).__name__}: {exc}", **ctx)
        self._applied[key] = new_bid
        logger.info("%s [MIN_REDUCTION] Bid updated to %s; retrying save (attempt %d)", p, text, self.attempts)
        return HandlerResult(action="retry", new_bid=new_bid, **ctx)

    def _verify(self, row: BidRow, expected: Decimal) -> bool:
        try:
            return parse_amount(self.ui.read_bid(row)) == expected
        except ValueError:
            return False


# --------------------------------------------------------------------------
# Selenium adapter
# --------------------------------------------------------------------------
class SeleniumBidUi:
    """Selenium implementation of BidUi for the SAP UI5 e-bidding table."""

    POPUP_XPATH = "//div[contains(@class,'sapMDialog') and not(contains(@style,'display: none'))]"
    ROW_XPATH = "//tr[.//input[contains(@id,'idBidAmount')]]"

    def __init__(self, driver: Any, l1_cell_index: int, timeout: float = 8.0) -> None:
        self.driver = driver
        self.l1_cell_index = int(l1_cell_index)
        self.timeout = timeout

    def wait_popup_message(self, timeout: float = 0.0) -> Optional[str]:
        """Single instant read of a visible dialog's text (JS, so no implicit-wait delay); no polling."""
        script = (
            "var d=document.querySelectorAll('.sapMDialog');"
            "for(var i=0;i<d.length;i++){var e=d[i];"
            "if(e.offsetParent!==null||e.getClientRects().length){"
            "var t=(e.innerText||'').trim();if(t)return t;}}return null;"
        )
        try:
            text = self.driver.execute_script(script)
        except Exception:
            return None
        return str(text).strip() or None if text else None

    def list_rows(self) -> List[BidRow]:
        from selenium.webdriver.common.by import By

        rows: List[BidRow] = []
        for tr in self.driver.find_elements(By.XPATH, self.ROW_XPATH):
            inp = tr.find_element(By.XPATH, ".//input[contains(@id,'idBidAmount')]")
            m = re.search(r"-(\d+)-inner$", inp.get_attribute("id") or "")
            if not m:
                continue
            cells = tr.find_elements(By.TAG_NAME, "td")
            l1 = None
            if 0 <= self.l1_cell_index < len(cells):
                l1 = (cells[self.l1_cell_index].get_attribute("textContent") or "").strip() or None
            rows.append(BidRow(int(m.group(1)), tr.get_attribute("textContent") or "", l1, inp))
        return rows

    def set_bid(self, row: BidRow, value: str) -> None:
        row.handle.clear()
        row.handle.send_keys(value)

    def read_bid(self, row: BidRow) -> str:
        return row.handle.get_attribute("value") or ""

    def close_popup(self) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        WebDriverWait(self.driver, self.timeout).until(
            EC.element_to_be_clickable(
                (By.XPATH, self.POPUP_XPATH + "//bdi[normalize-space()='OK']/ancestor::button")
            )
        ).click()

    def wait_popup_closed(self) -> bool:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            WebDriverWait(self.driver, self.timeout).until(
                lambda d: not any(e.is_displayed() for e in d.find_elements(By.XPATH, self.POPUP_XPATH))
            )
            return True
        except Exception:
            return False
