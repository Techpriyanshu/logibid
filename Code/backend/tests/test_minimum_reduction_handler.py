from decimal import Decimal

import pytest

from src.minimum_reduction_handler import (
    BidCalculationError,
    BidRow,
    ConfigError,
    MinimumReductionConfig,
    MinimumReductionHandler,
    PopupParseError,
    RowMatchError,
    calculate_new_bid,
    format_bid,
    is_minimum_reduction_message,
    parse_amount,
    parse_minimum_reduction_message,
    select_unique_row,
)

MSG = "Reduce your bid by minimum Rs. 4.000 from L1 bid amount for COF order 5578118593 Line no 000101"
D = Decimal


def cfg(**kw):
    base = {"auto_handle_minimum_reduction": True}
    base.update(kw)
    return MinimumReductionConfig.from_mapping(base)


class FakeUi:
    def __init__(self, rows, fail_direct=False, close_ok=True, ignore_set=False):
        self.rows = rows
        self.values = {r.row_index: "" for r in rows}
        self.fail_direct = fail_direct
        self.close_ok = close_ok
        self.ignore_set = ignore_set
        self.closed = 0
        self.popup_open = True

    def list_rows(self):
        return self.rows

    def set_bid(self, row, value):
        if self.fail_direct and self.popup_open:
            raise RuntimeError("click intercepted")
        if not self.ignore_set:
            self.values[row.row_index] = value

    def read_bid(self, row):
        return self.values[row.row_index]

    def close_popup(self):
        self.closed += 1
        self.popup_open = False

    def wait_popup_closed(self):
        return self.close_ok


def rows():
    return [
        BidRow(0, "5578118593 000101 TANDA", "281.00"),
        BidRow(1, "5578118593 000102 TANDA", "300"),
        BidRow(2, "5578000000 000101 OTHER", "150"),
    ]


PLANNED = [{"row_index": 0, "bid_price": 275}, {"row_index": 2, "bid_price": 140}]


# ---- parsing ----
def test_parse_message():
    m = parse_minimum_reduction_message(MSG)
    assert (m.min_reduction, m.order, m.line) == (D("4.000"), "5578118593", "000101")
    assert is_minimum_reduction_message(MSG)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Reduce your bid by minimum Rs.4 from L1 for order 123456 line 10", D("4")),
        ("  reduce   your bid by  minimum  \u20b9 2.50 from L1 ", D("2.50")),
        ("Reduce your bid by minimum INR 1,000.50 from L1", D("1000.50")),
        ("Reduce your bid by minimum Rs. 4,5 from L1", D("4.5")),
    ],
)
def test_parse_message_variants(text, expected):
    assert parse_minimum_reduction_message(text).min_reduction == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("4.000", D("4.000")), ("1,234.50", D("1234.50")), ("1.234,50", D("1234.50")),
     ("1,23,456", D("123456")), ("Rs. 281", D("281")), ("\u20b9 200.00", D("200.00")), (" 7 ", D("7"))],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "abc", True])
def test_parse_amount_invalid(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


@pytest.mark.parametrize("text", [None, "", "   ", "Bid saved successfully", "Reduce your bid by minimum from L1"])
def test_malformed_messages(text):
    with pytest.raises(PopupParseError):
        parse_minimum_reduction_message(text)


def test_zero_minimum_rejected():
    with pytest.raises(PopupParseError):
        parse_minimum_reduction_message("Reduce your bid by minimum Rs. 0.000 from L1")


# ---- calculation ----
def test_examples():
    assert calculate_new_bid(D("200"), D("4"), cfg(configured_reduction_amount=4)) == D("196")
    assert calculate_new_bid(D("281"), D("4"), cfg()) == D("277")


@pytest.mark.parametrize("configured", [2, 3, "2.5"])
def test_configured_smaller_than_sap_minimum_never_used(configured):
    assert calculate_new_bid(D("200"), D("4"), cfg(configured_reduction_amount=configured)) == D("196")


def test_configured_greater_than_minimum():
    assert calculate_new_bid(D("200"), D("4"), cfg(configured_reduction_amount=6)) == D("194")


def test_safety_margin():
    assert calculate_new_bid(D("200"), D("4"), cfg(safety_margin="1")) == D("195")
    assert calculate_new_bid(D("200"), D("4"), cfg(configured_reduction_amount=5, safety_margin="0.5")) == D("194.5")


def test_decimal_exactness():
    assert calculate_new_bid(D("0.3"), D("0.1"), cfg()) == D("0.2")


@pytest.mark.parametrize("l1", [None, D("0"), D("-5"), D("4"), D("3")])
def test_invalid_or_nonpositive_bid(l1):
    with pytest.raises(BidCalculationError):
        calculate_new_bid(l1, D("4"), cfg())


def test_format_bid():
    assert format_bid(D("196.000")) == "196"
    assert format_bid(D("194.50")) == "194.5"


# ---- config ----
def test_config_defaults_safe():
    c = MinimumReductionConfig.from_mapping(None)
    assert not c.auto_handle_minimum_reduction
    assert c.require_confirmation_for_exact_bid_conflicts
    assert c.max_bid_retry_attempts == 2


@pytest.mark.parametrize(
    "bad",
    [{"configured_reduction_amount": "x"}, {"safety_margin": -1}, {"max_bid_retry_attempts": 99},
     {"max_bid_retry_attempts": "2"}, {"auto_handle_minimum_reduction": "yes"},
     {"configured_reduction_amount": True}],
)
def test_config_invalid(bad):
    with pytest.raises(ConfigError):
        MinimumReductionConfig.from_mapping(bad)


# ---- row matching ----
def test_unique_row():
    m = parse_minimum_reduction_message(MSG)
    assert select_unique_row(rows(), m).row_index == 0


def test_duplicate_rows_ambiguous():
    rs = rows() + [BidRow(3, "5578118593 000101 DUP", "281")]
    with pytest.raises(RowMatchError, match="Ambiguous"):
        select_unique_row(rs, parse_minimum_reduction_message(MSG))


def test_order_only_with_multiple_lines_ambiguous():
    m = parse_minimum_reduction_message("Reduce your bid by minimum Rs. 4 from L1 for order 5578118593")
    with pytest.raises(RowMatchError):
        select_unique_row(rows(), m)


def test_no_match_and_no_identifiers():
    with pytest.raises(RowMatchError):
        select_unique_row(rows(), parse_minimum_reduction_message(MSG.replace("5578118593", "9999999999")))
    with pytest.raises(RowMatchError):
        select_unique_row(rows(), parse_minimum_reduction_message("Reduce your bid by minimum Rs. 4 from L1"))


def test_line_matches_unpadded_and_not_substring():
    m = parse_minimum_reduction_message(MSG.replace("000101", "101"))
    assert select_unique_row(rows(), m).row_index == 0
    m2 = parse_minimum_reduction_message(MSG.replace("000101", "10"))
    with pytest.raises(RowMatchError):
        select_unique_row(rows(), m2)


# ---- handler ----
def test_handler_fills_matching_row_only_and_retries():
    ui = FakeUi(rows())
    r = MinimumReductionHandler(cfg(), ui).handle(MSG, PLANNED)
    assert r.action == "retry" and r.new_bid == D("277") and r.row_index == 0
    assert ui.values == {0: "277", 1: "", 2: ""}
    assert ui.closed == 1


def test_handler_closes_popup_first_when_fill_blocked():
    ui = FakeUi(rows(), fail_direct=True)
    r = MinimumReductionHandler(cfg(), ui).handle(MSG, PLANNED)
    assert r.action == "retry" and ui.values[0] == "277"


def test_handler_disabled():
    r = MinimumReductionHandler(MinimumReductionConfig(), FakeUi(rows())).handle(MSG, PLANNED)
    assert r.action == "stop"


def test_handler_verification_failure_stops():
    ui = FakeUi(rows(), ignore_set=True)
    assert MinimumReductionHandler(cfg(), ui).handle(MSG, PLANNED).action == "stop"


def test_handler_popup_not_closing_stops():
    ui = FakeUi(rows(), close_ok=False)
    assert MinimumReductionHandler(cfg(), ui).handle(MSG, PLANNED).action == "stop"


def test_handler_missing_l1_stops():
    rs = [BidRow(0, "5578118593 000101", None)]
    assert MinimumReductionHandler(cfg(), FakeUi(rs)).handle(MSG, PLANNED).action == "stop"


def test_handler_negative_bid_stops():
    rs = [BidRow(0, "5578118593 000101", "3")]
    r = MinimumReductionHandler(cfg(), FakeUi(rs)).handle(MSG, PLANNED)
    assert r.action == "stop" and "not positive" in r.reason


def test_handler_ambiguous_rows_stop():
    rs = rows() + [BidRow(3, "5578118593 000101", "281")]
    r = MinimumReductionHandler(cfg(), FakeUi(rs)).handle(MSG, PLANNED + [{"row_index": 3}])
    assert r.action == "stop" and "Ambiguous" in r.reason


def test_handler_unplanned_row_stops():
    r = MinimumReductionHandler(cfg(), FakeUi(rows())).handle(MSG, [{"row_index": 2}])
    assert r.action == "stop"


def test_exact_bid_conflict_stops_and_leaves_field():
    ui = FakeUi(rows())
    planned = [{"row_index": 0, "bid_price": 276, "exact_bid": True}]
    r = MinimumReductionHandler(cfg(), ui).handle(MSG, planned)
    assert r.action == "stop" and "Exact-bid" in r.reason
    assert ui.values[0] == "" and ui.closed == 0


def test_exact_bid_allowed_when_confirmation_disabled():
    planned = [{"row_index": 0, "exact_bid_amount": 276}]
    c = cfg(require_confirmation_for_exact_bid_conflicts=False)
    assert MinimumReductionHandler(c, FakeUi(rows())).handle(MSG, planned).action == "retry"


def test_retry_limit_and_repeated_popup():
    ui = FakeUi(rows())
    h = MinimumReductionHandler(cfg(max_bid_retry_attempts=2), ui)
    assert h.handle(MSG, PLANNED).action == "retry"
    # SAP re-shows the popup but the row still reports the same L1 -> repeated, no loop
    r = h.handle(MSG, PLANNED)
    assert r.action == "stop" and "Repeated" in r.reason
    assert h.attempts == 1


def test_retry_limit_zero_never_retries():
    r = MinimumReductionHandler(cfg(max_bid_retry_attempts=0), FakeUi(rows())).handle(MSG, PLANNED)
    assert r.action == "stop" and "Retry limit" in r.reason


def test_retry_limit_across_different_rows():
    ui = FakeUi(rows())
    h = MinimumReductionHandler(cfg(max_bid_retry_attempts=1), ui)
    assert h.handle(MSG, PLANNED).action == "retry"
    other = MSG.replace("5578118593", "5578000000")
    assert h.handle(other, PLANNED).action == "stop"
