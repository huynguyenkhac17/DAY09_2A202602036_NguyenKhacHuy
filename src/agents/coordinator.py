"""Coordinator Agent — chu so huu: LEAD.

Nhan case, truy xuat facts, dieu phoi 3 agent dieu tra, handoff cho Policy roi
Verifier. Buoc lap ke hoach la mot LLM call that (co ghi trace); ket qua ke hoach
KHONG duoc phep bo qua agent nao — deterministic van chay du 3 agent de bao dam
khong mat bang chung.
"""

from __future__ import annotations

from src import data_store
from src.agents import delivery, order_seller, payment, policy, verifier
from src.contracts import CaseInput, CaseOutput
from src.llm import call_json
from src.trace import log_event

_PLANNER_SYSTEM = """Ban la Coordinator Agent cua he thong xu ly khieu nai thuong mai dien tu Olist.
Nhiem vu: doc khieu nai cua khach va tom tat trang thai don hang, roi lap ke hoach dieu tra.
Ban KHONG duoc tinh toan so tien va KHONG duoc bia ID.
Tra ve DUY NHAT mot JSON object dang:
{"focus": "delivery" | "payment" | "order_status",
 "agents_to_run": ["order_seller", "delivery", "payment"],
 "rationale": "mot cau ngan"}"""


def investigate(case: CaseInput) -> CaseOutput:
    """Chay full pipeline cho mot case va tra ve output da duoc verify."""
    case_id = case.case_id
    order_id = case.customer_request.claimed_order_id

    log_event(case_id, "coordinator", "case_received", payload={"order_id": order_id})

    # 1) Truy xuat facts — nguon su that duy nhat cho moi con so va ID.
    facts = data_store.get_order_facts(order_id)
    log_event(
        case_id,
        "coordinator",
        "facts_loaded",
        payload={
            "exists": facts.exists,
            "order_status": facts.order_status,
            "n_items": len(facts.items),
            "n_payments": len(facts.payments),
            "item_total_brl": facts.item_total_brl,
            "freight_total_brl": facts.freight_total_brl,
            "payment_total_brl": facts.payment_total_brl,
        },
    )

    # 2) LLM lap ke hoach dieu tra (co the None neu khong co API key).
    plan = call_json(
        case_id=case_id,
        agent="coordinator",
        system_prompt=_PLANNER_SYSTEM,
        user_prompt=(
            f"Khieu nai cua khach: {case.customer_request.message}\n"
            f"Trang thai don: {facts.order_status or 'khong tim thay'}\n"
            f"So item: {len(facts.items)} | So payment row: {len(facts.payments)}\n"
            f"Da giao cho khach luc: {facts.delivered_customer_date}\n"
            f"Han giao du kien: {facts.estimated_delivery_date}\n"
            "Hay lap ke hoach dieu tra."
        ),
    )
    log_event(case_id, "coordinator", "plan", payload=plan or {"fallback": "run_all"})

    # 3) Handoff — luon chay du 3 agent bat ke ke hoach cua LLM.
    seller_finding = order_seller.analyze(case_id, facts)
    delivery_finding = delivery.analyze(case_id, facts)
    payment_finding = payment.analyze(case_id, facts)

    log_event(
        case_id,
        "coordinator",
        "handoff_to_policy",
        payload={
            "is_late": delivery_finding.is_late,
            "any_handoff_after_limit": seller_finding.any_handoff_after_limit,
            "reconciled": payment_finding.reconciled,
            "is_split": payment_finding.is_split,
        },
    )

    # 4) Policy quyet dinh, Verifier kiem chung va dung output cuoi.
    decision = policy.decide(
        case_id, facts, delivery_finding, seller_finding, payment_finding
    )
    output = verifier.build_output(
        case_id, facts, decision, delivery_finding, seller_finding, payment_finding
    )

    log_event(
        case_id,
        "coordinator",
        "case_done",
        payload={
            "primary_issue": output.assessment.primary_issue,
            "refund": output.financial_resolution.recommended_refund_brl,
        },
    )
    return output
