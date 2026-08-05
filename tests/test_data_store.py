"""Test data layer — doi chieu voi gia tri doc tay tu CSV.

Chay: python -m pytest tests/test_data_store.py -q  (tu thu muc goc repo)
"""

from __future__ import annotations

import math
import time

import pytest

from src import data_store

# order_id that, gia tri lay tay tu data/*.csv
ORDER_UNAVAILABLE = "8e24261a7e58791d10cb1bf9da94df5c"
ORDER_DELIVERED = "e481f51cbdc54678b7cc49136f2d6af7"
ORDER_CANCELED = "1b9ecfe83cdc259250e1a8aca174f0ad"
ORDER_FAKE = "khong_ton_tai_123"


@pytest.fixture(scope="module", autouse=True)
def _warm() -> None:
    """Load CSV mot lan cho ca module test."""
    data_store.warmup()


def test_warmup_idempotent() -> None:
    """Goi warmup nhieu lan khong lam thay doi du lieu da nap."""
    before = data_store.order_count()
    data_store.warmup()
    data_store.warmup()
    assert data_store.order_count() == before
    assert before > 90000  # olist co ~99441 order


def test_order_unavailable_khong_co_item() -> None:
    """Order unavailable: khong co item row nhung van co payment."""
    facts = data_store.get_order_facts(ORDER_UNAVAILABLE)

    assert facts.exists is True
    assert facts.order_id == ORDER_UNAVAILABLE
    assert facts.order_status == "unavailable"
    assert facts.customer_id == "64a254d30eed42cd0e6c36dddb88adf0"

    # Khong co item row -> list rong, total 0.0 (khong phai None)
    assert facts.items == []
    assert facts.seller_ids == []
    assert facts.item_total_brl == 0.0
    assert facts.freight_total_brl == 0.0

    # Payment van co
    assert len(facts.payments) == 1
    assert facts.payments[0].payment_sequential == 1
    assert facts.payments[0].payment_type == "credit_card"
    assert facts.payments[0].payment_installments == 5
    assert facts.payment_total_brl == 84.0

    # Cac cot timestamp rong phai la None, khong duoc la nan
    assert facts.purchase_ts == "2017-11-16 15:09:28"
    assert facts.approved_at == "2017-11-16 15:26:57"
    assert facts.delivered_carrier_date is None
    assert facts.delivered_customer_date is None
    assert facts.estimated_delivery_date == "2017-12-05 00:00:00"


def test_order_delivered_split_payment() -> None:
    """Order delivered co 3 payment row, phai sort theo payment_sequential."""
    facts = data_store.get_order_facts(ORDER_DELIVERED)

    assert facts.exists is True
    assert facts.order_status == "delivered"
    assert facts.delivered_customer_date == "2017-10-10 21:25:13"
    assert facts.estimated_delivery_date == "2017-10-18 00:00:00"

    assert len(facts.items) == 1
    item = facts.items[0]
    assert item.order_item_id == 1
    assert isinstance(item.order_item_id, int)
    assert item.product_id == "87285b34884572647811a353c7ac498a"
    assert item.seller_id == "3504c0cb71d7fa48d967e0e4c94d59d9"
    assert item.shipping_limit_date == "2017-10-06 11:07:15"
    assert item.price == 29.99
    assert item.freight_value == 8.72

    # CSV luu theo thu tu 1, 3, 2 -> ta phai tra ve 1, 2, 3
    assert len(facts.payments) == 3
    assert [p.payment_sequential for p in facts.payments] == [1, 2, 3]
    assert [p.payment_value for p in facts.payments] == [18.12, 18.59, 2.00]
    assert [p.payment_type for p in facts.payments] == [
        "credit_card",
        "voucher",
        "voucher",
    ]

    assert facts.item_total_brl == 29.99
    assert facts.freight_total_brl == 8.72
    assert facts.payment_total_brl == 38.71
    assert facts.expected_total_brl == 38.71
    assert facts.seller_ids == ["3504c0cb71d7fa48d967e0e4c94d59d9"]


def test_order_canceled() -> None:
    """Order canceled: co item nhung khong co moc giao hang."""
    facts = data_store.get_order_facts(ORDER_CANCELED)

    assert facts.exists is True
    assert facts.order_status == "canceled"
    assert facts.item_total_brl == 25.0
    assert facts.freight_total_brl == 8.34
    assert facts.payment_total_brl == 33.34
    assert facts.seller_ids == ["9646c3513289980f17226a2fc4720dbd"]
    assert facts.delivered_carrier_date is None
    assert facts.delivered_customer_date is None
    assert facts.payments[0].payment_type == "boleto"


def test_order_khong_ton_tai() -> None:
    """order_id bia ra -> exists=False, moi total = 0.0."""
    facts = data_store.get_order_facts(ORDER_FAKE)

    assert facts.exists is False
    assert facts.order_id == ORDER_FAKE
    assert facts.order_status == ""
    assert facts.items == []
    assert facts.payments == []
    assert facts.seller_ids == []
    assert facts.item_total_brl == 0.0
    assert facts.freight_total_brl == 0.0
    assert facts.payment_total_brl == 0.0


def test_khong_co_nan_lot_ra() -> None:
    """Kiem tra khong con gia tri nan / chuoi 'nan' trong facts (hong JSON)."""
    for oid in (ORDER_UNAVAILABLE, ORDER_DELIVERED, ORDER_CANCELED):
        dumped = data_store.get_order_facts(oid).model_dump()
        for key, value in dumped.items():
            if isinstance(value, float):
                assert not math.isnan(value), f"{oid}.{key} la nan"
            if isinstance(value, str):
                assert value.lower() != "nan", f"{oid}.{key} la chuoi 'nan'"


def test_seller_ids_unique_giu_thu_tu() -> None:
    """seller_ids phai unique va giu thu tu xuat hien trong items."""
    # Tim mot order nhieu seller de test thu tu
    facts = data_store.get_order_facts(ORDER_DELIVERED)
    assert len(facts.seller_ids) == len(set(facts.seller_ids))

    # Kiem tra tren toan bo cac order co >= 2 item (lay 200 order dau cho nhanh)
    checked = 0
    for oid, rows in data_store._ITEMS.items():
        if len(rows) < 2:
            continue
        f = data_store.get_order_facts(oid)
        expected: list[str] = []
        for item in f.items:
            if item.seller_id not in expected:
                expected.append(item.seller_id)
        assert f.seller_ids == expected
        assert [i.order_item_id for i in f.items] == sorted(
            i.order_item_id for i in f.items
        )
        checked += 1
        if checked >= 200:
            break
    assert checked > 0


def test_seller_exists() -> None:
    """Helper doi chieu seller_id cho verifier."""
    facts = data_store.get_order_facts(ORDER_DELIVERED)
    assert data_store.seller_exists(facts.seller_ids[0]) is True
    assert data_store.seller_exists("seller_bia_ra") is False


def test_hieu_nang_50_lan_goi() -> None:
    """Sau warmup, 50 lan get_order_facts phai duoi 1 giay tong cong."""
    data_store.warmup()  # chac chan da nap xong truoc khi bam gio

    order_ids = list(data_store._ORDERS.keys())[:50]
    start = time.perf_counter()
    for oid in order_ids:
        data_store.get_order_facts(oid)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"50 lan goi mat {elapsed:.3f}s, qua cham"
