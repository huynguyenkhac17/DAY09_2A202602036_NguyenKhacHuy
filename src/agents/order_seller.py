"""Order & Seller Agent — chu so huu: TV3.

Nhiem vu: kiem tra tung item cua order xem seller co ban giao hang cho don vi van
chuyen sau `shipping_limit_date` hay khong, va gom `seller_id` cua cac item vi pham.

Quy uoc README muc 4: seller bi coi la ban giao muon neu
`order_delivered_carrier_date > shipping_limit_date` cua item thuoc seller do
-> `any_handoff_after_limit` dung semantics "co it nhat mot item vi pham".

Kien truc theo docs/TEAM_PLAN.md muc 1: Python tinh boolean, LLM chi suy luan va
viet `reasoning`, guard doi chieu hai ben roi ghi trace.
"""

from __future__ import annotations

from typing import Any, Optional

from src.contracts import ItemHandoff, OrderFacts, SellerFinding
from src.llm import call_json
from src.trace import log_event

AGENT_NAME = "order_seller"

#: So item toi da dua vao prompt de tranh lam prompt phinh to.
_MAX_ITEMS_IN_PROMPT = 10

_SYSTEM_PROMPT = """Ban la Order & Seller Agent cua he thong xu ly khieu nai thuong mai dien tu Olist.
Nhiem vu: kiem tra seller co ban giao hang cho don vi van chuyen dung han hay khong.
Quy tac: mot item bi coi la BAN GIAO MUON khi order_delivered_carrier_date > shipping_limit_date cua item do.
Order bi coi la co ban giao muon neu CO IT NHAT MOT item vi pham.
Neu thieu order_delivered_carrier_date hoac shipping_limit_date thi KHONG coi la vi pham.
Ban KHONG duoc bia them moc thoi gian, KHONG duoc tu tinh lai so tien va KHONG duoc bia seller_id.
Tra ve DUY NHAT mot JSON object dang:
{"any_handoff_after_limit": true | false, "reasoning": "mot cau ngan giai thich"}"""


def analyze(case_id: str, facts: OrderFacts) -> SellerFinding:
    """Phan tich moc ban giao cua tung item va tra ve SellerFinding.

    Gia tri boolean tra ve LUON la gia tri deterministic; LLM chi dong gop
    truong `reasoning`.
    """
    delivered_carrier = facts.delivered_carrier_date

    # --- 1) Deterministic: nguon su that -------------------------------------
    per_item: list[ItemHandoff] = []
    late_seller_ids: list[str] = []

    for item in facts.items:
        limit = item.shipping_limit_date
        after_limit: bool = bool(
            delivered_carrier and limit and delivered_carrier > limit
        )
        per_item.append(
            ItemHandoff(
                order_item_id=item.order_item_id,
                seller_id=item.seller_id,
                shipping_limit_date=limit,
                handoff_after_limit=after_limit,
            )
        )
        # unique nhung giu thu tu xuat hien
        if after_limit and item.seller_id and item.seller_id not in late_seller_ids:
            late_seller_ids.append(item.seller_id)

    any_after_limit: bool = any(row.handoff_after_limit for row in per_item)

    log_event(
        case_id,
        AGENT_NAME,
        "deterministic",
        payload={
            "delivered_carrier_date": delivered_carrier,
            "n_items": len(per_item),
            "any_handoff_after_limit": any_after_limit,
            "late_seller_ids": late_seller_ids,
        },
    )

    # --- 2) LLM that: suy luan tren dung cac moc thoi gian da trich ra --------
    llm_out: dict[str, Any] | None = call_json(
        case_id=case_id,
        agent=AGENT_NAME,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=(
            f"Trang thai don: {facts.order_status or 'khong ro'}\n"
            f"Ngay ban giao cho don vi van chuyen (order_delivered_carrier_date): "
            f"{delivered_carrier}\n"
            f"So item trong don: {len(facts.items)}\n"
            f"Han ban giao cua tung item:\n{_items_block(per_item)}\n"
            "Hay ket luan don nay co item nao bi ban giao muon hay khong."
        ),
    )

    # --- 3) Guard: deterministic luon thang ----------------------------------
    reasoning = _guard(
        case_id, llm_out, any_after_limit, late_seller_ids, per_item, delivered_carrier
    )

    return SellerFinding(
        any_handoff_after_limit=any_after_limit,
        late_seller_ids=late_seller_ids,
        per_item=per_item,
        reasoning=reasoning,
    )


def _guard(
    case_id: str,
    llm_out: dict[str, Any] | None,
    any_after_limit: bool,
    late_seller_ids: list[str],
    per_item: list[ItemHandoff],
    delivered_carrier: Optional[str],
) -> str:
    """Doi chieu ket luan LLM voi deterministic, tra ve `reasoning` cuoi cung."""
    fallback = _fallback_reasoning(
        any_after_limit, late_seller_ids, per_item, delivered_carrier
    )

    if llm_out is None:
        # Khong co API key / LLM loi -> chay deterministic-only, khong tinh la bat dong.
        log_event(
            case_id,
            AGENT_NAME,
            "llm_unavailable",
            payload={"any_handoff_after_limit": any_after_limit},
        )
        return fallback

    llm_any = _as_bool(llm_out.get("any_handoff_after_limit"))
    llm_reasoning = str(llm_out.get("reasoning") or "").strip()

    if llm_any == any_after_limit:
        log_event(
            case_id,
            AGENT_NAME,
            "guard",
            payload={"any_handoff_after_limit": any_after_limit},
            agreement=True,
        )
        return llm_reasoning or fallback

    log_event(
        case_id,
        AGENT_NAME,
        "guard",
        payload={
            "llm_any_handoff_after_limit": llm_any,
            "deterministic_any_handoff_after_limit": any_after_limit,
        },
        agreement=False,
    )
    return fallback


def _fallback_reasoning(
    any_after_limit: bool,
    late_seller_ids: list[str],
    per_item: list[ItemHandoff],
    delivered_carrier: Optional[str],
) -> str:
    """Reasoning tu sinh bang Python khi khong dung duoc reasoning cua LLM."""
    if not per_item:
        return "Order khong co item row nen khong danh gia duoc moc ban giao cua seller."
    if any_after_limit:
        n_late = sum(1 for row in per_item if row.handoff_after_limit)
        return (
            f"Hang duoc ban giao cho don vi van chuyen luc {delivered_carrier}, "
            f"muon hon shipping_limit_date cua {n_late}/{len(per_item)} item; "
            f"seller vi pham: {', '.join(late_seller_ids) or 'khong xac dinh'}."
        )
    if not delivered_carrier:
        return (
            "Khong co order_delivered_carrier_date nen khong ket luan seller ban giao muon."
        )
    return (
        f"Hang duoc ban giao cho don vi van chuyen luc {delivered_carrier}, "
        f"khong muon hon shipping_limit_date cua bat ky item nao trong {len(per_item)} item."
    )


def _items_block(per_item: list[ItemHandoff]) -> str:
    """Dung khoi text mo ta han ban giao cua tung item cho prompt."""
    if not per_item:
        return "(order khong co item row)"
    lines = [
        f"- item {row.order_item_id} | seller {row.seller_id} | "
        f"shipping_limit_date {row.shipping_limit_date}"
        for row in per_item[:_MAX_ITEMS_IN_PROMPT]
    ]
    if len(per_item) > _MAX_ITEMS_IN_PROMPT:
        lines.append(f"- ... con {len(per_item) - _MAX_ITEMS_IN_PROMPT} item nua")
    return "\n".join(lines)


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
