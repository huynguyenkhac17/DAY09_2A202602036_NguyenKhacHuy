"""Policy Agent — chu so huu: TV5.

Ap dung EC_POLICY_V1 (README muc 4, docs/TEAM_PLAN.md muc 2).

Kien truc (docs/TEAM_PLAN.md muc 1):
  - Rule engine deterministic chay TRUOC, theo dung thu tu uu tien tuyet doi,
    dung lai o match dau tien. Day la nguon su that cua nhan, refund va action.
  - LLM duoc goi that MOT lan: nhan toan van bang rule + cac finding da tinh san,
    tra ve {"primary_issue", "reasoning"}.
  - Guard: LLM lech nhan -> DUNG rule engine, tru CONFIDENCE_PENALTY_ON_DISAGREEMENT
    va ghi trace agreement=False. Khop -> giu reasoning cua LLM, agreement=True.

Nguyen tac vang: LLM KHONG BAO GIO quyet dinh con so tien hay ID.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.contracts import (
    CONFIDENCE_BY_ISSUE,
    CONFIDENCE_PENALTY_ON_DISAGREEMENT,
    LOGISTICS_PARTY_ID,
    PLATFORM_PARTY_ID,
    DeliveryFinding,
    OrderFacts,
    PaymentFinding,
    PolicyDecision,
    ResponsibleParty,
    SellerFinding,
    money,
)
from src.llm import call_json
from src.trace import log_event

AGENT_NAME = "policy"

#: Toan van bang rule, dua thang vao system prompt de LLM suy luan tren dung luat.
RULE_TABLE_TEXT = """BANG RULE EC_POLICY_V1 — ap dung theo THU TU UU TIEN TUYET DOI, dung lai o dieu kien dau tien khop:

1. order_status == "canceled" VA payment_total_brl > 0
   -> primary_issue = canceled_order_paid | ben chiu trach nhiem: platform/OLIST_PLATFORM
      | refund = tong payment | action = issue_full_refund
      | root_cause = ORDER_CANCELED_AFTER_PAYMENT | case_status = action_required

2. order_status == "unavailable" VA payment_total_brl > 0
   -> primary_issue = unavailable_order_paid | ben chiu trach nhiem: platform/OLIST_PLATFORM
      | refund = tong payment | action = issue_full_refund
      | root_cause = ORDER_UNAVAILABLE_AFTER_PAYMENT | case_status = action_required

3. is_late == true VA any_handoff_after_limit == true
   -> primary_issue = late_delivery_seller | ben chiu trach nhiem: seller/<seller_id vi pham>
      | refund = tong freight | action = refund_freight
      | root_cause = SELLER_HANDOFF_AFTER_LIMIT | case_status = action_required

4. is_late == true VA any_handoff_after_limit == false
   -> primary_issue = late_delivery_logistics | ben chiu trach nhiem: logistics_provider/LOGISTICS_PROVIDER
      | refund = tong freight | action = refund_freight
      | root_cause = CARRIER_DELIVERED_AFTER_ESTIMATE | case_status = action_required

5. is_split == true VA reconciled == true
   -> primary_issue = valid_split_payment | KHONG co ben chiu trach nhiem
      | refund = 0 | action = explain_valid_split_payment
      | root_cause = MULTIPLE_PAYMENTS_RECONCILED | case_status = no_action

6. Con lai (mac dinh)
   -> primary_issue = unsupported_late_claim | KHONG co ben chiu trach nhiem
      | refund = 0 | action = reject_late_refund
      | root_cause = DELIVERY_WITHIN_ESTIMATE | case_status = no_action"""

_SYSTEM_PROMPT = f"""Ban la Policy Agent cua he thong xu ly khieu nai thuong mai dien tu Olist.
Nhiem vu: doc cac ket luan dieu tra da duoc he thong tinh san va chon DUNG MOT primary_issue theo bang rule duoi day.

{RULE_TABLE_TEXT}

RANG BUOC BAT BUOC:
- Chi duoc chon mot trong sau nhan: canceled_order_paid, unavailable_order_paid, late_delivery_seller,
  late_delivery_logistics, valid_split_payment, unsupported_late_claim.
- Phai duyet rule tu 1 den 6 va dung lai o rule dau tien khop. Rule so nho hon LUON thang rule so lon hon.
- Ban KHONG duoc tinh lai bat ky so tien nao, KHONG duoc bia ID va KHONG duoc tao nhan moi.
Tra ve DUY NHAT mot JSON object dang:
{{"primary_issue": "<mot trong sau nhan>", "reasoning": "mot cau ngan giai thich rule nao khop"}}"""

_VALID_ISSUES = frozenset(CONFIDENCE_BY_ISSUE)


def decide(
    case_id: str,
    facts: OrderFacts,
    delivery: DeliveryFinding,
    seller: SellerFinding,
    payment: PaymentFinding,
) -> PolicyDecision:
    """Ap rule engine + LLM guard, tra ve PolicyDecision cuoi cung.

    Moi con so trong ket qua deu do Python tinh tu `facts`; LLM chi dong gop
    truong `reasoning` khi no dong y voi rule engine.
    """
    # --- 1) Rule engine deterministic: nguon su that -------------------------
    decision = _run_rules(case_id, facts, delivery, seller, payment)

    log_event(
        case_id,
        AGENT_NAME,
        "deterministic",
        payload={
            "primary_issue": decision.primary_issue,
            "root_cause_code": decision.root_cause_code,
            "recommended_refund_brl": decision.recommended_refund_brl,
            "case_status": decision.case_status,
            "inputs": {
                "order_status": facts.order_status,
                "payment_total_brl": facts.payment_total_brl,
                "freight_total_brl": facts.freight_total_brl,
                "is_late": delivery.is_late,
                "any_handoff_after_limit": seller.any_handoff_after_limit,
                "is_split": payment.is_split,
                "reconciled": payment.reconciled,
            },
        },
    )

    # --- 2) LLM that: 1 lan goi, chi de suy luan ra nhan ----------------------
    llm_out: Optional[dict[str, Any]] = call_json(
        case_id=case_id,
        agent=AGENT_NAME,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(facts, delivery, seller, payment),
    )

    # --- 3) Guard: rule engine luon thang ------------------------------------
    return _guard(case_id, decision, llm_out)


# ==============================================================================
# Rule engine
# ==============================================================================


def _run_rules(
    case_id: str,
    facts: OrderFacts,
    delivery: DeliveryFinding,
    seller: SellerFinding,
    payment: PaymentFinding,
) -> PolicyDecision:
    """Duyet 6 rule theo thu tu uu tien tuyet doi, dung o match dau tien."""
    status: str = (facts.order_status or "").strip().lower()
    payment_total: float = money(facts.payment_total_brl)
    freight_total: float = money(facts.freight_total_brl)

    # Rule 1 — don bi huy nhung da thu tien.
    if status == "canceled" and payment_total > 0:
        return _make_decision(
            primary_issue="canceled_order_paid",
            root_cause_code="ORDER_CANCELED_AFTER_PAYMENT",
            refund=payment_total,
            action="issue_full_refund",
            parties=[ResponsibleParty(party_type="platform", party_id=PLATFORM_PARTY_ID)],
            reasoning=(
                f"Don o trang thai canceled nhung tong payment {payment_total} BRL > 0 "
                "nen platform phai hoan toan bo so tien da thu."
            ),
        )

    # Rule 2 — don unavailable nhung da thu tien.
    if status == "unavailable" and payment_total > 0:
        return _make_decision(
            primary_issue="unavailable_order_paid",
            root_cause_code="ORDER_UNAVAILABLE_AFTER_PAYMENT",
            refund=payment_total,
            action="issue_full_refund",
            parties=[ResponsibleParty(party_type="platform", party_id=PLATFORM_PARTY_ID)],
            reasoning=(
                f"Don o trang thai unavailable nhung tong payment {payment_total} BRL > 0 "
                "nen platform phai hoan toan bo so tien da thu."
            ),
        )

    # Rule 3 — giao tre va co seller ban giao qua han.
    if delivery.is_late and seller.any_handoff_after_limit:
        seller_id: Optional[str] = _pick_late_seller(case_id, facts, seller)
        if seller_id is not None:
            return _make_decision(
                primary_issue="late_delivery_seller",
                root_cause_code="SELLER_HANDOFF_AFTER_LIMIT",
                refund=freight_total,
                action="refund_freight",
                parties=[ResponsibleParty(party_type="seller", party_id=seller_id)],
                reasoning=(
                    f"Don giao sau han du kien va seller {seller_id} ban giao cho don vi "
                    "van chuyen sau shipping_limit_date nen seller chiu trach nhiem freight."
                ),
            )
        # Khong truy duoc seller_id nao tu facts -> khong duoc bia ID,
        # ha xuong rule 4 (logistics) de output van hop le.
        log_event(
            case_id,
            AGENT_NAME,
            "rule3_downgraded",
            payload={
                "reason": "any_handoff_after_limit=True nhung khong co seller_id nao trong facts",
                "late_seller_ids": seller.late_seller_ids,
                "facts_seller_ids": facts.seller_ids,
            },
        )

    # Rule 4 — giao tre nhung seller ban giao dung han.
    if delivery.is_late:
        return _make_decision(
            primary_issue="late_delivery_logistics",
            root_cause_code="CARRIER_DELIVERED_AFTER_ESTIMATE",
            refund=freight_total,
            action="refund_freight",
            parties=[
                ResponsibleParty(
                    party_type="logistics_provider", party_id=LOGISTICS_PARTY_ID
                )
            ],
            reasoning=(
                f"Don duoc giao luc {delivery.delivered_customer_date} sau han du kien "
                f"{delivery.estimated_delivery_date} trong khi khong seller nao ban giao "
                "qua han nen trach nhiem thuoc don vi van chuyen."
            ),
        )

    # Rule 5 — nhieu payment row nhung doi soat khop.
    if payment.is_split and payment.reconciled:
        return _make_decision(
            primary_issue="valid_split_payment",
            root_cause_code="MULTIPLE_PAYMENTS_RECONCILED",
            refund=0.0,
            action="explain_valid_split_payment",
            parties=[],
            reasoning=(
                f"Don co {payment.payment_row_count} payment row va tong payment khop "
                f"tong item + freight (lech {payment.delta_brl} BRL) nen khong phat sinh hoan tien."
            ),
        )

    # Rule 6 — mac dinh.
    return _make_decision(
        primary_issue="unsupported_late_claim",
        root_cause_code="DELIVERY_WITHIN_ESTIMATE",
        refund=0.0,
        action="reject_late_refund",
        parties=[],
        reasoning=(
            "Du lieu khong cho thay don giao tre hay sai lech thanh toan nen "
            "khieu nai khong co can cu de hoan tien."
        ),
    )


def _make_decision(
    *,
    primary_issue: str,
    root_cause_code: str,
    refund: float,
    action: str,
    parties: list[ResponsibleParty],
    reasoning: str,
) -> PolicyDecision:
    """Dung PolicyDecision, ep case_status luon nhat quan voi refund."""
    refund_value: float = money(refund)
    return PolicyDecision(
        primary_issue=primary_issue,  # type: ignore[arg-type]
        case_status="action_required" if refund_value > 0 else "no_action",
        root_cause_code=root_cause_code,  # type: ignore[arg-type]
        responsible_parties=parties,
        recommended_refund_brl=refund_value,
        resolution_actions=[action],  # type: ignore[list-item]
        confidence=_clamp(CONFIDENCE_BY_ISSUE.get(primary_issue, 0.5)),
        reasoning=reasoning,
    )


def _pick_late_seller(
    case_id: str, facts: OrderFacts, seller: SellerFinding
) -> Optional[str]:
    """Chon seller_id vi pham dau tien, chi lay ID CO THAT trong facts.

    Thu tu uu tien:
      1) seller.late_seller_ids (giu thu tu) — chi nhan ID co trong facts
      2) per_item co handoff_after_limit=True — cuu khi late_seller_ids rong
      3) facts.seller_ids[0] — don 1 seller thi khong the nham
    Tra None khi facts khong co seller nao (khong duoc bia ID).
    """
    known: set[str] = set(facts.seller_ids) | {it.seller_id for it in facts.items}

    for sid in seller.late_seller_ids:
        if sid and sid in known:
            return sid

    if seller.late_seller_ids:
        # Co ID nhung khong khop facts -> ID la, khong duoc dung.
        log_event(
            case_id,
            AGENT_NAME,
            "seller_id_dropped",
            payload={"late_seller_ids": seller.late_seller_ids, "known": sorted(known)},
        )

    for row in seller.per_item:
        if row.handoff_after_limit and row.seller_id and row.seller_id in known:
            return row.seller_id

    if facts.seller_ids:
        return facts.seller_ids[0]
    if facts.items:
        return facts.items[0].seller_id
    return None


# ==============================================================================
# LLM + guard
# ==============================================================================


def _build_user_prompt(
    facts: OrderFacts,
    delivery: DeliveryFinding,
    seller: SellerFinding,
    payment: PaymentFinding,
) -> str:
    """Dong goi cac finding da tinh san thanh prompt cho LLM.

    Chi dua FACT da tinh, khong dua ket luan cua rule engine vao de tranh moi y.
    """
    findings: dict[str, Any] = {
        "order_status": facts.order_status,
        "payment_total_brl": money(facts.payment_total_brl),
        "item_total_brl": money(facts.item_total_brl),
        "freight_total_brl": money(facts.freight_total_brl),
        "delivery": {
            "is_late": delivery.is_late,
            "delivered_customer_date": delivery.delivered_customer_date,
            "estimated_delivery_date": delivery.estimated_delivery_date,
            "delivered_carrier_date": delivery.delivered_carrier_date,
            "days_late": delivery.days_late,
        },
        "seller": {
            "any_handoff_after_limit": seller.any_handoff_after_limit,
            "n_late_sellers": len(seller.late_seller_ids),
        },
        "payment": {
            "payment_row_count": payment.payment_row_count,
            "is_split": payment.is_split,
            "reconciled": payment.reconciled,
            "delta_brl": money(payment.delta_brl),
        },
    }
    return (
        "Ket qua dieu tra da duoc he thong tinh san (JSON):\n"
        + json.dumps(findings, ensure_ascii=False, indent=2)
        + "\n\nHay duyet bang rule tu 1 den 6 va chon primary_issue dau tien khop."
    )


def _guard(
    case_id: str,
    decision: PolicyDecision,
    llm_out: Optional[dict[str, Any]],
) -> PolicyDecision:
    """Doi chieu nhan cua LLM voi rule engine. Rule engine LUON thang."""
    if llm_out is None:
        # Khong co API key / LLM loi -> deterministic-only, khong tinh la bat dong.
        log_event(
            case_id,
            AGENT_NAME,
            "llm_unavailable",
            payload={"primary_issue": decision.primary_issue},
        )
        return decision

    llm_issue: str = str(llm_out.get("primary_issue") or "").strip()
    llm_reasoning: str = str(llm_out.get("reasoning") or "").strip()

    if llm_issue in _VALID_ISSUES and llm_issue == decision.primary_issue:
        log_event(
            case_id,
            AGENT_NAME,
            "guard",
            payload={"primary_issue": decision.primary_issue},
            agreement=True,
        )
        # Nhan van la cua rule engine; chi muon lai loi giai thich cua LLM.
        return decision.model_copy(
            update={"reasoning": llm_reasoning or decision.reasoning}
        )

    penalized: float = _clamp(decision.confidence - CONFIDENCE_PENALTY_ON_DISAGREEMENT)
    log_event(
        case_id,
        AGENT_NAME,
        "guard",
        payload={
            "llm_primary_issue": llm_issue or None,
            "deterministic_primary_issue": decision.primary_issue,
            "confidence_before": decision.confidence,
            "confidence_after": penalized,
        },
        agreement=False,
    )
    return decision.model_copy(update={"confidence": penalized})


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Ep confidence ve [0, 1] va lam tron cho gon."""
    return round(min(max(float(value), low), high), 4)
