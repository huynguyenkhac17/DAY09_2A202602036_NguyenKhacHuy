"""Test cho Delivery Agent va Order & Seller Agent (TV3).

OrderFacts duoc dung BANG TAY o day, khong phu thuoc src/data_store.py.
Khong co GROQ_API_KEY -> call_json() tra None -> ca hai agent chay duong
deterministic-only; test phai pass o dung trang thai do.
"""

from __future__ import annotations

import pytest

from src import config
from src.agents import delivery, order_seller
from src.contracts import ItemRow, OrderFacts


@pytest.fixture(autouse=True)
def _isolate_trace(tmp_path, monkeypatch):
    """Ghi trace vao tmp de khong lam ban logging/trace.jsonl cua luot chay that."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "TRACE_PATH", tmp_path / "trace.jsonl")


def _item(
    order_item_id: int,
    seller_id: str,
    shipping_limit_date: str | None,
    price: float = 100.0,
    freight_value: float = 15.0,
) -> ItemRow:
    return ItemRow(
        order_item_id=order_item_id,
        product_id=f"prod_{order_item_id}",
        seller_id=seller_id,
        shipping_limit_date=shipping_limit_date,
        price=price,
        freight_value=freight_value,
    )


def _facts(
    *,
    order_status: str = "delivered",
    delivered_carrier_date: str | None = None,
    delivered_customer_date: str | None = None,
    estimated_delivery_date: str | None = None,
    items: list[ItemRow] | None = None,
) -> OrderFacts:
    items = items or []
    return OrderFacts(
        order_id="order_test_0001",
        exists=True,
        order_status=order_status,
        customer_id="cust_0001",
        purchase_ts="2018-01-01 10:00:00",
        approved_at="2018-01-01 10:30:00",
        delivered_carrier_date=delivered_carrier_date,
        delivered_customer_date=delivered_customer_date,
        estimated_delivery_date=estimated_delivery_date,
        items=items,
        payments=[],
        seller_ids=[it.seller_id for it in items],
        item_total_brl=round(sum(it.price for it in items), 2),
        freight_total_brl=round(sum(it.freight_value for it in items), 2),
        payment_total_brl=0.0,
    )


# ==============================================================================
# 1) Giao tre + carrier nhan hang sau shipping_limit -> loi seller
# ==============================================================================


def test_late_delivery_with_seller_handoff_after_limit():
    facts = _facts(
        delivered_carrier_date="2018-01-10 08:00:00",
        delivered_customer_date="2018-01-20 12:00:00",
        estimated_delivery_date="2018-01-15 00:00:00",
        items=[_item(1, "seller_A", "2018-01-05 23:59:00")],
    )

    dfind = delivery.analyze("EC_T01", facts)
    assert dfind.is_late is True
    assert dfind.days_late == 5
    assert dfind.delivered_customer_date == "2018-01-20 12:00:00"
    assert dfind.estimated_delivery_date == "2018-01-15 00:00:00"
    assert dfind.delivered_carrier_date == "2018-01-10 08:00:00"
    assert dfind.reasoning

    sfind = order_seller.analyze("EC_T01", facts)
    assert sfind.any_handoff_after_limit is True
    assert sfind.late_seller_ids == ["seller_A"]
    assert len(sfind.per_item) == 1
    assert sfind.per_item[0].handoff_after_limit is True
    assert sfind.per_item[0].order_item_id == 1
    assert sfind.reasoning


# ==============================================================================
# 2) Giao tre nhung seller ban giao dung han -> loi logistics
# ==============================================================================


def test_late_delivery_with_handoff_within_limit():
    facts = _facts(
        delivered_carrier_date="2018-01-04 08:00:00",
        delivered_customer_date="2018-01-20 12:00:00",
        estimated_delivery_date="2018-01-15 00:00:00",
        items=[_item(1, "seller_A", "2018-01-05 23:59:00")],
    )

    dfind = delivery.analyze("EC_T02", facts)
    assert dfind.is_late is True
    assert dfind.days_late == 5

    sfind = order_seller.analyze("EC_T02", facts)
    assert sfind.any_handoff_after_limit is False
    assert sfind.late_seller_ids == []
    assert sfind.per_item[0].handoff_after_limit is False


# ==============================================================================
# 3) Giao dung han
# ==============================================================================


def test_delivery_within_estimate():
    facts = _facts(
        delivered_carrier_date="2018-01-04 08:00:00",
        delivered_customer_date="2018-01-12 12:00:00",
        estimated_delivery_date="2018-01-15 00:00:00",
        items=[_item(1, "seller_A", "2018-01-05 23:59:00")],
    )

    dfind = delivery.analyze("EC_T03", facts)
    assert dfind.is_late is False
    assert dfind.days_late is None


def test_delivery_exactly_on_estimate_is_not_late():
    """Bang dung moc estimated -> khong tinh la tre (so sanh chat '>')."""
    facts = _facts(
        delivered_customer_date="2018-01-15 00:00:00",
        estimated_delivery_date="2018-01-15 00:00:00",
    )
    assert delivery.analyze("EC_T03b", facts).is_late is False


# ==============================================================================
# 4) Order canceled: delivered_customer_date = None
# ==============================================================================


def test_canceled_order_without_delivery_date():
    facts = _facts(
        order_status="canceled",
        delivered_carrier_date=None,
        delivered_customer_date=None,
        estimated_delivery_date="2018-01-15 00:00:00",
        items=[_item(1, "seller_A", "2018-01-05 23:59:00")],
    )

    dfind = delivery.analyze("EC_T04", facts)
    assert dfind.is_late is False
    assert dfind.days_late is None
    assert dfind.delivered_customer_date is None

    # carrier date = None -> khong the ket luan seller ban giao muon
    sfind = order_seller.analyze("EC_T04", facts)
    assert sfind.any_handoff_after_limit is False
    assert sfind.late_seller_ids == []
    assert len(sfind.per_item) == 1
    assert sfind.per_item[0].handoff_after_limit is False


def test_missing_estimated_date_is_not_late():
    facts = _facts(
        delivered_customer_date="2018-01-20 12:00:00",
        estimated_delivery_date=None,
    )
    dfind = delivery.analyze("EC_T04b", facts)
    assert dfind.is_late is False
    assert dfind.days_late is None


# ==============================================================================
# 5) Order khong co item row
# ==============================================================================


def test_order_without_items():
    facts = _facts(
        delivered_carrier_date="2018-01-10 08:00:00",
        delivered_customer_date="2018-01-20 12:00:00",
        estimated_delivery_date="2018-01-15 00:00:00",
        items=[],
    )

    sfind = order_seller.analyze("EC_T05", facts)
    assert sfind.per_item == []
    assert sfind.late_seller_ids == []
    assert sfind.any_handoff_after_limit is False
    assert sfind.reasoning

    # Delivery van ket luan duoc vi khong phu thuoc item
    assert delivery.analyze("EC_T05", facts).is_late is True


def test_item_without_shipping_limit_is_not_violation():
    facts = _facts(
        delivered_carrier_date="2018-01-10 08:00:00",
        delivered_customer_date="2018-01-20 12:00:00",
        estimated_delivery_date="2018-01-15 00:00:00",
        items=[_item(1, "seller_A", None)],
    )
    sfind = order_seller.analyze("EC_T05b", facts)
    assert sfind.any_handoff_after_limit is False
    assert sfind.per_item[0].handoff_after_limit is False


# ==============================================================================
# 6) Multi-item: chi item 2 qua han
# ==============================================================================


def test_multi_item_only_second_seller_late():
    facts = _facts(
        delivered_carrier_date="2018-01-10 08:00:00",
        delivered_customer_date="2018-01-20 12:00:00",
        estimated_delivery_date="2018-01-15 00:00:00",
        items=[
            _item(1, "seller_A", "2018-01-12 23:59:00"),  # dung han
            _item(2, "seller_B", "2018-01-05 23:59:00"),  # qua han
        ],
    )

    sfind = order_seller.analyze("EC_T06", facts)
    assert sfind.any_handoff_after_limit is True
    assert sfind.late_seller_ids == ["seller_B"]
    assert [row.handoff_after_limit for row in sfind.per_item] == [False, True]
    assert [row.order_item_id for row in sfind.per_item] == [1, 2]


def test_multi_item_same_seller_late_ids_are_unique():
    """Hai item cung mot seller cung vi pham -> late_seller_ids chi liet ke 1 lan."""
    facts = _facts(
        delivered_carrier_date="2018-01-10 08:00:00",
        delivered_customer_date="2018-01-20 12:00:00",
        estimated_delivery_date="2018-01-15 00:00:00",
        items=[
            _item(1, "seller_A", "2018-01-05 23:59:00"),
            _item(2, "seller_A", "2018-01-06 23:59:00"),
            _item(3, "seller_B", "2018-01-20 23:59:00"),
        ],
    )

    sfind = order_seller.analyze("EC_T07", facts)
    assert sfind.any_handoff_after_limit is True
    assert sfind.late_seller_ids == ["seller_A"]
    assert len(sfind.per_item) == 3
