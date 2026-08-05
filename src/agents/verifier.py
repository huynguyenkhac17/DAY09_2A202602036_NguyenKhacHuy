"""Verifier Agent — chu so huu: TV5.

Dung output cuoi cung theo dung README muc 5 + muc 6 va cac BAY DIEM o
docs/TEAM_PLAN.md muc 3:

  - affected_entities KHONG co prefix: "<order_id>:<n>".
  - evidence_ids CO prefix, chi 5 dang hop le, va phai dung duoc tu OrderFacts.
    ID khong truy nguoc duoc ve facts bi DROP (chong false positive).
  - Cat theo gioi han MAX_* va giu phan quan trong nhat khi phai cat.
  - Moi truong tien lay THANG tu facts, di qua money() (2 chu so, luon la float).
  - case_status <=> recommended_refund_brl > 0, lech thi tu sua va ghi trace.

Toan bo buoc nay la deterministic: LLM khong tham gia vao viec sinh ID hay so tien.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from src.contracts import (
    CURRENCY,
    MAX_ACTIONS,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE_IDS,
    MAX_RESPONSIBLE_PARTIES,
    MAX_ROOT_CAUSES,
    CaseOutput,
    DeliveryFinding,
    ItemRow,
    OrderFacts,
    PaymentFinding,
    PolicyDecision,
    SellerFinding,
    money,
)
from src.trace import log_event

AGENT_NAME = "verifier"

#: Ngan sach mem cho tung nhom evidence o giua (sau "order:" va truoc "policy:").
#: Con slot thua se duoc chia tiep theo dung thu tu uu tien item -> payment -> seller.
_SOFT_CAP_ITEM = 3
_SOFT_CAP_PAYMENT = 3
_SOFT_CAP_SELLER = 2

#: 5 dang evidence hop le (README muc 5). Dung de chan ID sai format.
_EVIDENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^order:[^:]+$"),
    re.compile(r"^item:[^:]+:\d+$"),
    re.compile(r"^payment:[^:]+:\d+$"),
    re.compile(r"^seller:[^:]+$"),
    re.compile(r"^policy:[A-Z_]+$"),
)


def build_output(
    case_id: str,
    facts: OrderFacts,
    decision: PolicyDecision,
    delivery: DeliveryFinding,
    seller: SellerFinding,
    payment: PaymentFinding,
) -> CaseOutput:
    """Kiem chung PolicyDecision + OrderFacts roi dung CaseOutput hop le schema."""
    # --- 1) Kiem tra nhat quan case_status <-> refund -------------------------
    refund: float = money(decision.recommended_refund_brl)
    case_status: str = "action_required" if refund > 0 else "no_action"
    if case_status != decision.case_status:
        log_event(
            case_id,
            AGENT_NAME,
            "fixed_case_status",
            payload={
                "from": decision.case_status,
                "to": case_status,
                "recommended_refund_brl": refund,
            },
        )

    # --- 2) Confidence luon nam trong [0, 1] ---------------------------------
    confidence: float = _clamp(decision.confidence)
    if abs(confidence - float(decision.confidence)) > 1e-9:
        log_event(
            case_id,
            AGENT_NAME,
            "fixed_confidence",
            payload={"from": decision.confidence, "to": confidence},
        )

    # --- 3) Affected entities (KHONG prefix) ---------------------------------
    entities: dict[str, list[str]] = _build_entities(facts)

    # --- 4) Evidence IDs (CO prefix, chi dung tu facts) ----------------------
    evidence_ids: list[str] = _build_evidence(case_id, facts, decision, seller)

    # --- 5) Root cause + responsible parties ---------------------------------
    ranked_causes: list[dict[str, Any]] = [
        {"cause_code": decision.root_cause_code, "rank": 1}
    ][:MAX_ROOT_CAUSES]
    responsible_parties: list[dict[str, str]] = [
        {"party_type": p.party_type, "party_id": p.party_id}
        for p in decision.responsible_parties
    ][:MAX_RESPONSIBLE_PARTIES]

    # --- 6) Tien: lay THANG tu facts, khong tinh lai --------------------------
    financial: dict[str, Any] = {
        "currency": CURRENCY,
        "item_total_brl": money(facts.item_total_brl),
        "freight_total_brl": money(facts.freight_total_brl),
        "payment_total_brl": money(facts.payment_total_brl),
        "recommended_refund_brl": refund,
    }

    actions: list[str] = _dedupe(decision.resolution_actions)[:MAX_ACTIONS]

    payload: dict[str, Any] = {
        "case_id": case_id,
        "assessment": {
            "primary_issue": decision.primary_issue,
            "case_status": case_status,
            "confidence": confidence,
        },
        "affected_entities": entities,
        "root_cause_analysis": {
            "ranked_causes": ranked_causes,
            "responsible_parties": responsible_parties,
        },
        "evidence_ids": evidence_ids,
        "financial_resolution": financial,
        "resolution_actions": actions,
    }

    output: CaseOutput = CaseOutput.model_validate(payload)

    log_event(
        case_id,
        AGENT_NAME,
        "verified",
        payload={
            "primary_issue": output.assessment.primary_issue,
            "case_status": output.assessment.case_status,
            "confidence": output.assessment.confidence,
            "n_evidence": len(output.evidence_ids),
            "n_item_ids": len(output.affected_entities.item_ids),
            "n_seller_ids": len(output.affected_entities.seller_ids),
            "n_payment_ids": len(output.affected_entities.payment_ids),
            "recommended_refund_brl": output.financial_resolution.recommended_refund_brl,
            "is_late": delivery.is_late,
            "reconciled": payment.reconciled,
        },
    )
    return output


# ==============================================================================
# Affected entities — KHONG prefix
# ==============================================================================


def _build_entities(facts: OrderFacts) -> dict[str, list[str]]:
    """Dung 4 entity set tu facts, cat con toi da MAX_ENTITY_IDS, giu thu tu dau.

    Order khong co item row -> item_ids va seller_ids rong (README muc 6).
    """
    order_id: str = facts.order_id
    order_ids: list[str] = [order_id] if order_id else []

    item_ids: list[str] = [
        f"{order_id}:{it.order_item_id}" for it in facts.items if order_id
    ]
    seller_ids: list[str] = _seller_ids_from_facts(facts) if facts.items else []
    payment_ids: list[str] = [
        f"{order_id}:{p.payment_sequential}" for p in facts.payments if order_id
    ]

    return {
        "order_ids": _dedupe(order_ids)[:MAX_ENTITY_IDS],
        "item_ids": _dedupe(item_ids)[:MAX_ENTITY_IDS],
        "seller_ids": _dedupe(seller_ids)[:MAX_ENTITY_IDS],
        "payment_ids": _dedupe(payment_ids)[:MAX_ENTITY_IDS],
    }


def _seller_ids_from_facts(facts: OrderFacts) -> list[str]:
    """seller_ids theo facts; neu data layer bo trong thi suy tu item rows.

    Khong co item row -> khong co seller nao (README muc 6).
    """
    if not facts.items:
        return []
    if facts.seller_ids:
        return _dedupe(s for s in facts.seller_ids if s)
    return _dedupe(it.seller_id for it in facts.items if it.seller_id)


# ==============================================================================
# Evidence IDs — CO prefix, chi dung tu facts
# ==============================================================================


def _build_evidence(
    case_id: str,
    facts: OrderFacts,
    decision: PolicyDecision,
    seller: SellerFinding,
) -> list[str]:
    """Sinh evidence theo uu tien: order -> item lien quan -> payment -> seller -> policy.

    Luon giu bang duoc "order:" va "policy:" (2 slot dat truoc), 8 slot con lai
    chia cho item/payment/seller theo ngan sach mem roi do phan du theo dung
    thu tu uu tien.
    """
    order_id: str = facts.order_id
    order_ev: list[str] = [f"order:{order_id}"] if order_id else []
    policy_ev: list[str] = [f"policy:{decision.root_cause_code}"]

    late_sellers: list[str] = _relevant_seller_ids(facts, decision, seller)
    late_set: set[str] = set(late_sellers)

    item_ev: list[str] = [
        f"item:{order_id}:{it.order_item_id}"
        for it in _order_items_by_relevance(facts, late_set)
        if order_id
    ]
    payment_ev: list[str] = [
        f"payment:{order_id}:{p.payment_sequential}" for p in facts.payments if order_id
    ]
    seller_ev: list[str] = [f"seller:{sid}" for sid in late_sellers]

    budget: int = MAX_EVIDENCE_IDS - len(order_ev) - len(policy_ev)
    middle: list[str] = _allocate(
        groups=[
            (item_ev, _SOFT_CAP_ITEM),
            (payment_ev, _SOFT_CAP_PAYMENT),
            (seller_ev, _SOFT_CAP_SELLER),
        ],
        budget=max(budget, 0),
    )

    candidates: list[str] = _dedupe(order_ev + middle + policy_ev)
    valid: list[str] = [ev for ev in candidates if _is_valid_evidence(ev, facts, decision)]

    dropped: list[str] = [ev for ev in candidates if ev not in set(valid)]
    if dropped:
        log_event(
            case_id, AGENT_NAME, "evidence_dropped", payload={"dropped": dropped}
        )

    return valid[:MAX_EVIDENCE_IDS]


def _allocate(groups: list[tuple[list[str], int]], budget: int) -> list[str]:
    """Chia `budget` slot cho cac nhom theo ngan sach mem, roi do phan du."""
    taken: list[list[str]] = []
    used: int = 0
    for values, cap in groups:
        room: int = max(min(cap, budget - used), 0)
        taken.append(values[:room])
        used += len(taken[-1])

    # Do phan du theo dung thu tu uu tien cua groups.
    for idx, (values, _cap) in enumerate(groups):
        if used >= budget:
            break
        extra: list[str] = values[len(taken[idx]) : len(taken[idx]) + (budget - used)]
        taken[idx].extend(extra)
        used += len(extra)

    result: list[str] = []
    for chunk in taken:
        result.extend(chunk)
    return result


def _order_items_by_relevance(facts: OrderFacts, late_set: set[str]) -> list[ItemRow]:
    """Item cua seller vi pham len truoc (stable), phan con lai giu nguyen thu tu."""
    if not late_set:
        return list(facts.items)
    first: list[ItemRow] = [it for it in facts.items if it.seller_id in late_set]
    rest: list[ItemRow] = [it for it in facts.items if it.seller_id not in late_set]
    return first + rest


def _relevant_seller_ids(
    facts: OrderFacts, decision: PolicyDecision, seller: SellerFinding
) -> list[str]:
    """Seller dang duoc quy trach nhiem len truoc, chi giu ID CO THAT trong facts."""
    known: set[str] = set(_seller_ids_from_facts(facts))
    ordered: list[str] = []

    for party in decision.responsible_parties:
        if party.party_type == "seller":
            ordered.append(party.party_id)
    ordered.extend(seller.late_seller_ids)
    ordered.extend(_seller_ids_from_facts(facts))

    return _dedupe([sid for sid in ordered if sid and sid in known])


def _is_valid_evidence(
    evidence_id: str, facts: OrderFacts, decision: PolicyDecision
) -> bool:
    """True khi ID dung 1 trong 5 format VA truy nguoc duoc ve du lieu that.

    Day la chot chan false positive: moi ID khong dung duoc tu `facts`
    (hoac tu root_cause_code cua decision) deu bi loai.
    """
    if not isinstance(evidence_id, str) or not evidence_id:
        return False
    if not any(pattern.match(evidence_id) for pattern in _EVIDENCE_PATTERNS):
        return False

    kind, _, rest = evidence_id.partition(":")

    if kind == "order":
        return bool(facts.order_id) and rest == facts.order_id

    if kind == "item":
        order_id, _, raw = rest.rpartition(":")
        if order_id != facts.order_id:
            return False
        return any(str(it.order_item_id) == raw for it in facts.items)

    if kind == "payment":
        order_id, _, raw = rest.rpartition(":")
        if order_id != facts.order_id:
            return False
        return any(str(p.payment_sequential) == raw for p in facts.payments)

    if kind == "seller":
        return rest in set(_seller_ids_from_facts(facts))

    if kind == "policy":
        return rest == decision.root_cause_code

    return False


# ==============================================================================
# Tien ich
# ==============================================================================


def _dedupe(values: Iterable[str]) -> list[str]:
    """Bo trung lap nhung giu nguyen thu tu xuat hien dau tien."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _clamp(value: Optional[float], low: float = 0.0, high: float = 1.0) -> float:
    """Ep confidence ve [0, 1]; gia tri hong -> 0.0."""
    try:
        number = float(value if value is not None else 0.0)
    except (TypeError, ValueError):
        return 0.0
    return round(min(max(number, low), high), 4)
