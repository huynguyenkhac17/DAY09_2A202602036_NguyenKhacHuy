"""Data layer — nguon su that duy nhat doc tu CSV (TV2).

Nguyen tac:
- Load 4 file CSV DUNG MOT LAN vao cache module-level, index san theo order_id.
- KHONG bao gio dung df[df.order_id == x] trong get_order_facts: 50 case x nhieu
  lan goi se quet full DataFrame 100k+ dong moi lan, qua cham.
- NaN cua pandas -> None, khong de "nan" lot vao JSON output.
- Moi con so tien di qua money() (contracts) de luon la float lam tron 2 chu so.

Moi agent chi doc du lieu qua module nay, khong agent nao tu mo CSV.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from src import config
from src.contracts import ItemRow, OrderFacts, PaymentRow, money

# ==============================================================================
# Ten file CSV can dung (4 file, khong load thua cho nhe bo nho)
# ==============================================================================

ORDERS_CSV = "olist_orders_dataset.csv"
ITEMS_CSV = "olist_order_items_dataset.csv"
PAYMENTS_CSV = "olist_order_payments_dataset.csv"
SELLERS_CSV = "olist_sellers_dataset.csv"

# ==============================================================================
# Cache module-level — lazy, chi load 1 lan
# ==============================================================================

#: order_id -> dict thong tin order (1 dong orders)
_ORDERS: dict[str, dict[str, Any]] = {}
#: order_id -> list dong order_items (chua sort)
_ITEMS: dict[str, list[dict[str, Any]]] = {}
#: order_id -> list dong order_payments (chua sort)
_PAYMENTS: dict[str, list[dict[str, Any]]] = {}
#: tap seller_id hop le, dung de verifier kiem tra evidence "seller:<id>"
_SELLER_IDS: set[str] = set()

_LOADED: bool = False


# ==============================================================================
# Helper ep kieu — chiu duoc NaN / chuoi rong
# ==============================================================================


def _clean_str(value: Any) -> Optional[str]:
    """NaN / None / chuoi rong -> None. Con lai -> str da strip."""
    if value is None:
        return None
    # pd.isna tra ve array neu value la list, o day luon la scalar nen an toan
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _req_str(value: Any) -> str:
    """Nhu _clean_str nhung khong bao gio tra None (dung cho truong bat buoc)."""
    return _clean_str(value) or ""


def _to_int(value: Any, default: int = 0) -> int:
    """Ep ve int, hong thi tra default. Chiu duoc chuoi kieu '3' hoac '3.0'."""
    text = _clean_str(value)
    if text is None:
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    """Ep ve float, hong thi tra default."""
    text = _clean_str(value)
    if text is None:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _read_csv(filename: str) -> pd.DataFrame:
    """Doc CSV voi dtype=str cho MOI cot.

    Doc thang ra str de:
    - order_id / product_id / seller_id khong bi pandas doan kieu roi mat ky tu.
    - o rong tro thanh NaN, ta tu ep ve None o buoc sau.
    """
    path = config.DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Thieu file du lieu: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=True)


# ==============================================================================
# API chinh
# ==============================================================================


def warmup() -> None:
    """Load 4 CSV vao cache. Idempotent — goi nhieu lan chi load 1 lan."""
    global _LOADED
    if _LOADED:
        return

    orders_df = _read_csv(ORDERS_CSV)
    items_df = _read_csv(ITEMS_CSV)
    payments_df = _read_csv(PAYMENTS_CSV)
    sellers_df = _read_csv(SELLERS_CSV)

    # --- orders: 1 order_id <-> 1 dong -------------------------------------
    orders: dict[str, dict[str, Any]] = {}
    for row in orders_df.to_dict("records"):
        order_id = _clean_str(row.get("order_id"))
        if order_id is None:
            continue
        orders[order_id] = {
            "order_status": _req_str(row.get("order_status")),
            "customer_id": _req_str(row.get("customer_id")),
            "purchase_ts": _clean_str(row.get("order_purchase_timestamp")),
            # 3 cot duoi day rat hay rong (order canceled / unavailable)
            "approved_at": _clean_str(row.get("order_approved_at")),
            "delivered_carrier_date": _clean_str(
                row.get("order_delivered_carrier_date")
            ),
            "delivered_customer_date": _clean_str(
                row.get("order_delivered_customer_date")
            ),
            "estimated_delivery_date": _clean_str(
                row.get("order_estimated_delivery_date")
            ),
        }

    # --- order_items: gom san thanh dict[order_id, list[row]] ---------------
    items: dict[str, list[dict[str, Any]]] = {}
    for row in items_df.to_dict("records"):
        order_id = _clean_str(row.get("order_id"))
        if order_id is None:
            continue
        items.setdefault(order_id, []).append(
            {
                "order_item_id": _to_int(row.get("order_item_id")),
                "product_id": _req_str(row.get("product_id")),
                "seller_id": _req_str(row.get("seller_id")),
                "shipping_limit_date": _clean_str(row.get("shipping_limit_date")),
                "price": _to_float(row.get("price")),
                "freight_value": _to_float(row.get("freight_value")),
            }
        )

    # --- order_payments: gom san thanh dict[order_id, list[row]] ------------
    payments: dict[str, list[dict[str, Any]]] = {}
    for row in payments_df.to_dict("records"):
        order_id = _clean_str(row.get("order_id"))
        if order_id is None:
            continue
        payments.setdefault(order_id, []).append(
            {
                "payment_sequential": _to_int(row.get("payment_sequential")),
                "payment_type": _req_str(row.get("payment_type")),
                "payment_installments": _to_int(row.get("payment_installments")),
                "payment_value": _to_float(row.get("payment_value")),
            }
        )

    # --- sort mot lan luc warmup, get_order_facts khong phai sort lai ------
    for rows in items.values():
        rows.sort(key=lambda r: r["order_item_id"])
    for rows in payments.values():
        rows.sort(key=lambda r: r["payment_sequential"])

    # --- sellers: chi can tap id de doi chieu ------------------------------
    seller_ids = {
        sid
        for sid in (_clean_str(v) for v in sellers_df.get("seller_id", pd.Series(dtype=str)))
        if sid is not None
    }

    _ORDERS.clear()
    _ORDERS.update(orders)
    _ITEMS.clear()
    _ITEMS.update(items)
    _PAYMENTS.clear()
    _PAYMENTS.update(payments)
    _SELLER_IDS.clear()
    _SELLER_IDS.update(seller_ids)
    _LOADED = True


def get_order_facts(order_id: str) -> OrderFacts:
    """Tra ve OrderFacts day du cho mot order_id.

    Neu order_id khong co trong CSV -> OrderFacts(order_id=..., exists=False)
    voi moi total = 0.0 (khong phai None, xem README muc 6).
    """
    warmup()

    oid = (order_id or "").strip()
    order = _ORDERS.get(oid)
    if order is None:
        return OrderFacts(order_id=oid, exists=False)

    # Da sort san tu warmup: items theo order_item_id, payments theo sequential.
    item_rows = _ITEMS.get(oid, [])
    payment_rows = _PAYMENTS.get(oid, [])

    items = [ItemRow(**row) for row in item_rows]
    payments = [PaymentRow(**row) for row in payment_rows]

    # seller_ids: unique nhung GIU NGUYEN thu tu xuat hien trong items.
    seen: set[str] = set()
    seller_ids: list[str] = []
    for row in item_rows:
        sid = row["seller_id"]
        if sid and sid not in seen:
            seen.add(sid)
            seller_ids.append(sid)

    # Cong het roi moi round MOT LAN (README muc 4).
    # Order khong co item row (vd status unavailable) -> sum([]) = 0.0, khong crash.
    item_total = money(sum(row["price"] for row in item_rows))
    freight_total = money(sum(row["freight_value"] for row in item_rows))
    payment_total = money(sum(row["payment_value"] for row in payment_rows))

    return OrderFacts(
        order_id=oid,
        exists=True,
        order_status=order["order_status"],
        customer_id=order["customer_id"],
        purchase_ts=order["purchase_ts"],
        approved_at=order["approved_at"],
        delivered_carrier_date=order["delivered_carrier_date"],
        delivered_customer_date=order["delivered_customer_date"],
        estimated_delivery_date=order["estimated_delivery_date"],
        items=items,
        payments=payments,
        seller_ids=seller_ids,
        item_total_brl=item_total,
        freight_total_brl=freight_total,
        payment_total_brl=payment_total,
    )


# ==============================================================================
# Tien ich phu — khong bat buoc nhung tien cho verifier
# ==============================================================================


def seller_exists(seller_id: str) -> bool:
    """True neu seller_id co that trong olist_sellers_dataset.csv.

    Dung de verifier drop evidence "seller:<id>" bia ra (false positive).
    """
    warmup()
    return (seller_id or "").strip() in _SELLER_IDS


def order_count() -> int:
    """So order da nap — tien cho smoke test / log khoi dong."""
    warmup()
    return len(_ORDERS)


def reset_cache() -> None:
    """Xoa cache de test co the ep load lai. Khong dung trong pipeline chinh."""
    global _LOADED
    _ORDERS.clear()
    _ITEMS.clear()
    _PAYMENTS.clear()
    _SELLER_IDS.clear()
    _LOADED = False
