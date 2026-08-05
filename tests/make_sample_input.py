"""Sinh bo input mau de test TRUOC khi de bai cong bo input that.

Chay:
    python tests/make_sample_input.py

Sinh ra:
    tests/sample_input/EC_001.json ... EC_012.json   (2 case cho moi nhanh rule)
    tests/expected_labels.json                       (nhan ky vong de tu cham)

LUU Y QUAN TRONG: expected_labels.json duoc tinh boi mot BAN THAM CHIEU DOC LAP
o file nay, khong phai ground truth cua ban to chuc. No dung de smoke-test format
va bat loi tich hop, KHONG dung de tranh cai ve nhan dung/sai. Neu src/ va file
nay bat dong, phai mo CSV kiem tay.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_DIR = ROOT / "tests" / "sample_input"

TOLERANCE = 0.10

# order_id thuc te lay tu CSV, moi nhanh 2 case.
CANDIDATES = [
    "1b9ecfe83cdc259250e1a8aca174f0ad",  # canceled + da thanh toan
    "714fb133a6730ab81fa1d3c1b2007291",
    "8e24261a7e58791d10cb1bf9da94df5c",  # unavailable + da thanh toan, KHONG co item row
    "c272bcd21c287498b4883c7512019702",
    "203096f03d82e0dffbc41ebc2e2bcfb7",  # giao tre, seller ban giao qua han
    "6ea2f835b4556291ffdc53fa0b3b95e8",
    "fbf9ac61453ac646ce8ad9783d7d0af6",  # giao tre, seller ban giao dung han
    "8563039e855156e48fccee4d611a3196",
    "e481f51cbdc54678b7cc49136f2d6af7",  # 3 payment row, khop tong
    "e69bfb5eb88e0ed6a785585b27e16dbf",
    "53cdb2fc8bc7dce0b6741e2150273451",  # giao dung han, payment khop
    "47770eb9100c2d0c44946d9cf07ec65d",
]

MESSAGES = {
    "late": "Đơn hàng của tôi có dấu hiệu giao trễ. Hãy kiểm tra nguyên nhân và quyền lợi phù hợp.",
    "canceled": "Đơn của tôi bị hủy nhưng tôi đã thanh toán. Tôi muốn được hoàn tiền.",
    "payment": "Tôi thấy nhiều giao dịch trừ tiền cho cùng một đơn. Hãy kiểm tra giúp tôi.",
}


def reference_label(facts: dict) -> tuple[str, str, float]:
    """Ban tham chieu doc lap cua rule engine. Tra (primary_issue, root_cause, refund)."""
    status = facts["order_status"]
    pay_total = facts["payment_total"]
    freight = facts["freight_total"]
    expected = round(facts["item_total"] + freight, 2)
    reconciled = abs(pay_total - expected) <= TOLERANCE
    is_split = facts["n_payments"] >= 2

    dc, est, car = facts["delivered"], facts["estimated"], facts["carrier"]
    is_late = bool(dc and est and dc > est)
    # "any item": seller tre neu carrier nhan hang sau shipping_limit cua BAT KY item nao
    handoff_late = bool(
        car and facts["limits"] and any(car > lim for lim in facts["limits"])
    )

    if status == "canceled" and pay_total > 0:
        return "canceled_order_paid", "ORDER_CANCELED_AFTER_PAYMENT", pay_total
    if status == "unavailable" and pay_total > 0:
        return "unavailable_order_paid", "ORDER_UNAVAILABLE_AFTER_PAYMENT", pay_total
    if is_late and handoff_late:
        return "late_delivery_seller", "SELLER_HANDOFF_AFTER_LIMIT", freight
    if is_late:
        return "late_delivery_logistics", "CARRIER_DELIVERED_AFTER_ESTIMATE", freight
    if is_split and reconciled:
        return "valid_split_payment", "MULTIPLE_PAYMENTS_RECONCILED", 0.0
    return "unsupported_late_claim", "DELIVERY_WITHIN_ESTIMATE", 0.0


def main() -> None:
    orders = pd.read_csv(DATA / "olist_orders_dataset.csv").set_index("order_id")
    items = pd.read_csv(DATA / "olist_order_items_dataset.csv")
    pays = pd.read_csv(DATA / "olist_order_payments_dataset.csv")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("EC_*.json"):
        stale.unlink()

    expected: dict[str, dict] = {}

    for idx, order_id in enumerate(CANDIDATES, start=1):
        case_id = f"EC_{idx:03d}"
        row = orders.loc[order_id]
        it = items[items.order_id == order_id]
        pm = pays[pays.order_id == order_id]

        def _s(v):
            return None if pd.isna(v) else str(v)

        facts = {
            "order_status": str(row["order_status"]),
            "delivered": _s(row["order_delivered_customer_date"]),
            "estimated": _s(row["order_estimated_delivery_date"]),
            "carrier": _s(row["order_delivered_carrier_date"]),
            "limits": [str(x) for x in it["shipping_limit_date"].tolist()],
            "item_total": round(float(it["price"].sum()), 2),
            "freight_total": round(float(it["freight_value"].sum()), 2),
            "payment_total": round(float(pm["payment_value"].sum()), 2),
            "n_payments": int(len(pm)),
        }

        issue, cause, refund = reference_label(facts)
        msg_key = (
            "canceled" if issue in ("canceled_order_paid", "unavailable_order_paid")
            else "payment" if issue == "valid_split_payment"
            else "late"
        )

        payload = {
            "case_id": case_id,
            "opened_at": "2018-10-18T00:00:00-03:00",
            "customer_request": {
                "language": "vi",
                "message": MESSAGES[msg_key],
                "claimed_order_id": order_id,
            },
            "policy_version": "EC_POLICY_V1",
        }
        (OUT_DIR / f"{case_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        expected[case_id] = {
            "order_id": order_id,
            "primary_issue": issue,
            "root_cause_code": cause,
            "case_status": "action_required" if refund > 0 else "no_action",
            "item_total_brl": facts["item_total"],
            "freight_total_brl": facts["freight_total"],
            "payment_total_brl": facts["payment_total"],
            "recommended_refund_brl": round(refund, 2),
        }
        print(f"{case_id}  {issue:<26} refund={refund:>8.2f}  {order_id}")

    (ROOT / "tests" / "expected_labels.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nDa ghi {len(expected)} case vao {OUT_DIR}")
    print(f"Nhan ky vong: {ROOT / 'tests' / 'expected_labels.json'}")


if __name__ == "__main__":
    main()
