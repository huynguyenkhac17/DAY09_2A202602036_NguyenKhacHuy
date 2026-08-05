"""Test cho Payment Agent (TV4).

OrderFacts duoc dung BANG TAY, khong phu thuoc src/data_store.py (dang duoc viet
song song). Khong co GROQ_API_KEY -> call_json() tra None -> agent chay
deterministic-only; toan bo test phai pass o trang thai do.

Chay: python -m pytest tests/test_payment.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.payment import analyze  # noqa: E402
from src.contracts import (  # noqa: E402
    RECONCILE_TOLERANCE_BRL,
    ItemRow,
    OrderFacts,
    PaymentRow,
    money,
)


# ====================================================================== #
# Helper dung facts bang tay
# ====================================================================== #


def _item(order_item_id: int, price: float, freight: float) -> ItemRow:
    return ItemRow(
        order_item_id=order_item_id,
        product_id=f"prod_{order_item_id}",
        seller_id=f"seller_{order_item_id}",
        shipping_limit_date="2018-01-10 00:00:00",
        price=price,
        freight_value=freight,
    )


def _payment(seq: int, value: float, installments: int = 1) -> PaymentRow:
    return PaymentRow(
        payment_sequential=seq,
        payment_type="credit_card",
        payment_installments=installments,
        payment_value=value,
    )


def _facts(
    items: list[ItemRow],
    payments: list[PaymentRow],
    order_status: str = "delivered",
) -> OrderFacts:
    """Dung OrderFacts giong cach data layer se lam: tong da round 2 chu so."""
    return OrderFacts(
        order_id="a" * 32,
        exists=True,
        order_status=order_status,
        customer_id="c" * 32,
        items=items,
        payments=payments,
        seller_ids=[it.seller_id for it in items],
        item_total_brl=money(sum(it.price for it in items)),
        freight_total_brl=money(sum(it.freight_value for it in items)),
        payment_total_brl=money(sum(p.payment_value for p in payments)),
    )


# ====================================================================== #
# 1) Mot payment row, khop chinh xac
# ====================================================================== #


def test_single_payment_exact_match() -> None:
    facts = _facts(
        items=[_item(1, 29.99, 8.72)],
        payments=[_payment(1, 38.71)],
    )
    finding = analyze("EC_TEST_01", facts)

    assert finding.payment_row_count == 1
    assert finding.payment_total_brl == 38.71
    assert finding.expected_total_brl == 38.71
    assert finding.delta_brl == 0.0
    assert finding.reconciled is True
    assert finding.is_split is False
    assert finding.reasoning  # luon co giai thich, ke ca khi khong co LLM


# ====================================================================== #
# 2) Ba payment row cong lai dung tong -> split va reconciled
# ====================================================================== #


def test_three_payment_rows_reconciled_split() -> None:
    facts = _facts(
        items=[_item(1, 100.00, 15.00), _item(2, 50.00, 10.00)],
        payments=[_payment(1, 100.00), _payment(2, 50.00), _payment(3, 25.00)],
    )
    finding = analyze("EC_TEST_02", facts)

    assert finding.payment_row_count == 3
    assert finding.expected_total_brl == 175.00
    assert finding.payment_total_brl == 175.00
    assert finding.delta_brl == 0.0
    assert finding.reconciled is True
    assert finding.is_split is True


# ====================================================================== #
# 3) Lech dung 0.10 -> bien tren VAN tinh la khop (inclusive)
# ====================================================================== #


def test_delta_exactly_at_tolerance_is_reconciled() -> None:
    facts = _facts(
        items=[_item(1, 29.99, 8.72)],
        payments=[_payment(1, 38.81)],  # 38.81 - 38.71 = 0.10
    )
    finding = analyze("EC_TEST_03", facts)

    assert finding.delta_brl == 0.10
    assert finding.delta_brl == RECONCILE_TOLERANCE_BRL
    assert finding.reconciled is True


def test_delta_exactly_at_tolerance_negative_direction() -> None:
    """Lech 0.10 theo chieu thieu tien cung phai la reconciled (dung abs)."""
    facts = _facts(
        items=[_item(1, 29.99, 8.72)],
        payments=[_payment(1, 38.61)],  # 38.71 - 38.61 = 0.10
    )
    finding = analyze("EC_TEST_03b", facts)

    assert finding.delta_brl == 0.10
    assert finding.reconciled is True


# ====================================================================== #
# 4) Lech 0.11 -> khong khop
# ====================================================================== #


def test_delta_just_over_tolerance_is_not_reconciled() -> None:
    facts = _facts(
        items=[_item(1, 29.99, 8.72)],
        payments=[_payment(1, 38.82)],  # 38.82 - 38.71 = 0.11
    )
    finding = analyze("EC_TEST_04", facts)

    assert finding.delta_brl == 0.11
    assert finding.reconciled is False
    assert finding.is_split is False


# ====================================================================== #
# 5) Khong co item row (vi du order unavailable) nhung da thanh toan
# ====================================================================== #


def test_no_item_rows_but_paid() -> None:
    facts = _facts(
        items=[],
        payments=[_payment(1, 84.00)],
        order_status="unavailable",
    )
    finding = analyze("EC_TEST_05", facts)

    assert finding.expected_total_brl == 0.0
    assert finding.payment_total_brl == 84.00
    assert finding.delta_brl == 84.00
    assert finding.reconciled is False
    assert finding.is_split is False
    assert finding.payment_row_count == 1


# ====================================================================== #
# 6) Khong co payment row nao -> khong crash
# ====================================================================== #


def test_no_payment_rows() -> None:
    facts = _facts(
        items=[_item(1, 29.99, 8.72)],
        payments=[],
    )
    finding = analyze("EC_TEST_06", facts)

    assert finding.payment_row_count == 0
    assert finding.payment_total_brl == 0.0
    assert finding.expected_total_brl == 38.71
    assert finding.delta_brl == 38.71
    assert finding.reconciled is False
    assert finding.is_split is False


def test_no_item_and_no_payment_rows() -> None:
    """Don rong hoan toan: 0 vs 0 -> delta 0 -> reconciled True, khong crash."""
    facts = _facts(items=[], payments=[])
    finding = analyze("EC_TEST_06b", facts)

    assert finding.payment_row_count == 0
    assert finding.delta_brl == 0.0
    assert finding.reconciled is True
    assert finding.is_split is False


# ====================================================================== #
# 7) payment_installments KHONG duoc anh huong toi bat ky con so nao
# ====================================================================== #


@pytest.mark.parametrize("installments", [1, 2, 6, 10, 24])
def test_installments_do_not_affect_any_number(installments: int) -> None:
    facts = _facts(
        items=[_item(1, 29.99, 8.72)],
        payments=[_payment(1, 38.71, installments=installments)],
    )
    finding = analyze("EC_TEST_07", facts)

    # Neu ai do nhan voi installments thi payment_total se phong len ngay.
    assert finding.payment_total_brl == 38.71
    assert finding.expected_total_brl == 38.71
    assert finding.delta_brl == 0.0
    assert finding.reconciled is True
    assert finding.is_split is False


def test_installments_do_not_affect_split_result() -> None:
    """2 row tra gop 10 ky: van la split, tong van la tong cua 2 row."""
    facts = _facts(
        items=[_item(1, 100.00, 20.00)],
        payments=[
            _payment(1, 60.00, installments=10),
            _payment(2, 60.00, installments=10),
        ],
    )
    finding = analyze("EC_TEST_07b", facts)

    assert finding.payment_row_count == 2
    assert finding.payment_total_brl == 120.00
    assert finding.expected_total_brl == 120.00
    assert finding.delta_brl == 0.0
    assert finding.reconciled is True
    assert finding.is_split is True


# ====================================================================== #
# Kiem tra phu: sai so dau phay dong va hang so tolerance
# ====================================================================== #


def test_tolerance_constant_is_from_contracts() -> None:
    assert RECONCILE_TOLERANCE_BRL == 0.10


def test_float_noise_is_rounded_before_compare() -> None:
    """Tong nhieu so le sinh nhieu duoi ~1e-13 khong duoc lam lech ket luan."""
    facts = _facts(
        items=[_item(i, 10.10, 1.05) for i in range(1, 8)],
        payments=[_payment(i, 11.15) for i in range(1, 8)],
    )
    finding = analyze("EC_TEST_08", facts)

    assert finding.delta_brl == 0.0
    assert finding.reconciled is True
    assert finding.is_split is True
