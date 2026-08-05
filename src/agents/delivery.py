"""Delivery Agent — chu so huu: TV3.

Nhiem vu: so sanh moc giao thuc te voi han giao du kien de ket luan don co tre hay
khong. Kien truc theo docs/TEAM_PLAN.md muc 1:

  - Python tinh `is_late` / `days_late` (deterministic, day la nguon su that).
  - LLM duoc goi that 1 lan de suy luan va viet `reasoning`.
  - Guard doi chieu ket luan boolean cua LLM voi gia tri deterministic; lech thi
    override bang deterministic va ghi trace `agreement=false`.

So sanh chuoi ISO truc tiep la du (README muc 2: khong can doi mui gio).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from src.contracts import DeliveryFinding, OrderFacts
from src.llm import call_json
from src.trace import log_event

AGENT_NAME = "delivery"

_SYSTEM_PROMPT = """Ban la Delivery Agent cua he thong xu ly khieu nai thuong mai dien tu Olist.
Nhiem vu: so sanh thoi diem don duoc giao cho khach voi han giao du kien de ket luan don co giao tre hay khong.
Quy tac: don duoc coi la GIAO TRE khi order_delivered_customer_date > order_estimated_delivery_date.
Neu thieu mot trong hai moc thoi gian (don bi huy hoac chua tung giao) thi KHONG coi la giao tre.
Ban KHONG duoc bia them moc thoi gian, KHONG duoc tu tinh lai so tien va KHONG duoc bia ID.
Tra ve DUY NHAT mot JSON object dang:
{"is_late": true | false, "reasoning": "mot cau ngan giai thich"}"""


def analyze(case_id: str, facts: OrderFacts) -> DeliveryFinding:
    """Phan tich timeline giao hang cua mot order va tra ve DeliveryFinding.

    Gia tri boolean tra ve LUON la gia tri deterministic; LLM chi dong gop
    truong `reasoning`.
    """
    delivered_customer = facts.delivered_customer_date
    estimated = facts.estimated_delivery_date
    delivered_carrier = facts.delivered_carrier_date

    # --- 1) Deterministic: nguon su that -------------------------------------
    is_late: bool = bool(
        delivered_customer and estimated and delivered_customer > estimated
    )
    days_late: Optional[int] = _days_between(estimated, delivered_customer) if is_late else None

    log_event(
        case_id,
        AGENT_NAME,
        "deterministic",
        payload={
            "delivered_customer_date": delivered_customer,
            "estimated_delivery_date": estimated,
            "delivered_carrier_date": delivered_carrier,
            "is_late": is_late,
            "days_late": days_late,
        },
    )

    # --- 2) LLM that: suy luan tren dung cac moc thoi gian da trich ra --------
    llm_out: dict[str, Any] | None = call_json(
        case_id=case_id,
        agent=AGENT_NAME,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=(
            f"Trang thai don: {facts.order_status or 'khong ro'}\n"
            f"Ngay giao cho khach (order_delivered_customer_date): {delivered_customer}\n"
            f"Han giao du kien (order_estimated_delivery_date): {estimated}\n"
            f"Ngay ban giao cho don vi van chuyen (order_delivered_carrier_date): {delivered_carrier}\n"
            "Hay ket luan don nay co giao tre hay khong."
        ),
    )

    # --- 3) Guard: deterministic luon thang ----------------------------------
    reasoning = _guard(case_id, llm_out, is_late, days_late, delivered_customer, estimated)

    return DeliveryFinding(
        is_late=is_late,
        delivered_customer_date=delivered_customer,
        estimated_delivery_date=estimated,
        delivered_carrier_date=delivered_carrier,
        days_late=days_late,
        reasoning=reasoning,
    )


def _guard(
    case_id: str,
    llm_out: dict[str, Any] | None,
    is_late: bool,
    days_late: Optional[int],
    delivered_customer: Optional[str],
    estimated: Optional[str],
) -> str:
    """Doi chieu ket luan LLM voi deterministic, tra ve `reasoning` cuoi cung."""
    fallback = _fallback_reasoning(is_late, days_late, delivered_customer, estimated)

    if llm_out is None:
        # Khong co API key / LLM loi -> chay deterministic-only, khong tinh la bat dong.
        log_event(case_id, AGENT_NAME, "llm_unavailable", payload={"is_late": is_late})
        return fallback

    llm_is_late = _as_bool(llm_out.get("is_late"))
    llm_reasoning = str(llm_out.get("reasoning") or "").strip()

    if llm_is_late == is_late:
        log_event(
            case_id,
            AGENT_NAME,
            "guard",
            payload={"is_late": is_late},
            agreement=True,
        )
        return llm_reasoning or fallback

    log_event(
        case_id,
        AGENT_NAME,
        "guard",
        payload={"llm_is_late": llm_is_late, "deterministic_is_late": is_late},
        agreement=False,
    )
    return fallback


def _fallback_reasoning(
    is_late: bool,
    days_late: Optional[int],
    delivered_customer: Optional[str],
    estimated: Optional[str],
) -> str:
    """Reasoning tu sinh bang Python khi khong dung duoc reasoning cua LLM."""
    if is_late:
        suffix = f" (tre {days_late} ngay)" if days_late is not None else ""
        return (
            f"Don duoc giao luc {delivered_customer}, sau han du kien {estimated}"
            f"{suffix} nen bi coi la giao tre."
        )
    if not delivered_customer or not estimated:
        return (
            "Thieu moc giao cho khach hoac han giao du kien "
            f"(delivered_customer_date={delivered_customer}, "
            f"estimated_delivery_date={estimated}) nen khong ket luan giao tre."
        )
    return (
        f"Don duoc giao luc {delivered_customer}, khong muon hon han du kien "
        f"{estimated} nen khong bi coi la giao tre."
    )


def _as_bool(value: Any) -> Optional[bool]:
    """Ep gia tri LLM tra ve thanh bool. None khi khong hieu duoc -> tinh la bat dong."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
    return None


def _days_between(earlier: Optional[str], later: Optional[str]) -> Optional[int]:
    """So ngay chenh lech giua hai moc ISO, chi lay phan ngay. None neu khong parse duoc."""
    start = _parse_date(earlier)
    end = _parse_date(later)
    if start is None or end is None:
        return None
    return (end - start).days


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    """Parse phan ngay cua chuoi ISO ("YYYY-MM-DD..."). None neu du lieu hong."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10])
    except ValueError:
        return None
