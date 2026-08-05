"""Test rule engine (policy) va bo dung output (verifier) — TV5.

Moi fixture duoc dung BANG TAY tu src.contracts, KHONG dung src/data_store.py hay
cac agent khac (nhung module do dang duoc viet song song).

Khong co GROQ_API_KEY -> call_json() tra None -> hai module chay deterministic-only,
toan bo test o day phai pass o trang thai do.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents import policy, verifier  # noqa: E402
from src.contracts import (  # noqa: E402
    CONFIDENCE_BY_ISSUE,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE_IDS,
    CaseOutput,
    DeliveryFinding,
    ItemHandoff,
    ItemRow,
    OrderFacts,
    PaymentFinding,
    PaymentRow,
    SellerFinding,
)

from src import config  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _isolate_trace(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Test khong duoc ghi de len logging/trace.jsonl cua lan chay that."""
    tmp_dir = tmp_path_factory.mktemp("trace")
    config.LOG_DIR = tmp_dir
    config.TRACE_PATH = tmp_dir / "trace.jsonl"


ORDER_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
SELLER_A = "seller_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SELLER_B = "seller_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

_EVIDENCE_REGEXES = (
    re.compile(r"^order:[0-9a-zA-Z_]+$"),
    re.compile(r"^item:[0-9a-zA-Z_]+:\d+$"),
    re.compile(r"^payment:[0-9a-zA-Z_]+:\d+$"),
    re.compile(r"^seller:[0-9a-zA-Z_]+$"),
    re.compile(r"^policy:[A-Z_]+$"),
)


# ==============================================================================
# Helper dung fixture bang tay
# ==============================================================================


def make_facts(
    *,
    order_status: str = "delivered",
    n_items: int = 1,
    seller_ids: Optional[list[str]] = None,
    payments: Optional[list[tuple[int, float]]] = None,
    price: float = 100.0,
    freight: float = 15.0,
    delivered_customer_date: Optional[str] = "2018-01-10 00:00:00",
    estimated_delivery_date: Optional[str] = "2018-01-20 00:00:00",
    delivered_carrier_date: Optional[str] = "2018-01-03 00:00:00",
) -> OrderFacts:
    """Dung OrderFacts bang tay; moi tong tien tinh san giong data layer."""
    sellers = seller_ids or [SELLER_A]
    items: list[ItemRow] = [
        ItemRow(
            order_item_id=i + 1,
            product_id=f"product_{i + 1}",
            seller_id=sellers[i % len(sellers)],
            shipping_limit_date="2018-01-05 00:00:00",
            price=price,
            freight_value=freight,
        )
        for i in range(n_items)
    ]
    pay_rows: list[PaymentRow] = [
        PaymentRow(
            payment_sequential=seq,
            payment_type="credit_card",
            payment_installments=1,
            payment_value=value,
        )
        for seq, value in (
            payments
            if payments is not None
            else [(1, round(n_items * (price + freight), 2))]
        )
    ]
    unique_sellers: list[str] = []
    for it in items:
        if it.seller_id not in unique_sellers:
            unique_sellers.append(it.seller_id)

    return OrderFacts(
        order_id=ORDER_ID,
        exists=True,
        order_status=order_status,
        customer_id="customer_0001",
        purchase_ts="2018-01-01 00:00:00",
        approved_at="2018-01-01 01:00:00",
        delivered_carrier_date=delivered_carrier_date,
        delivered_customer_date=delivered_customer_date,
        estimated_delivery_date=estimated_delivery_date,
        items=items,
        payments=pay_rows,
        seller_ids=unique_sellers,
        item_total_brl=round(sum(it.price for it in items), 2),
        freight_total_brl=round(sum(it.freight_value for it in items), 2),
        payment_total_brl=round(sum(p.payment_value for p in pay_rows), 2),
    )


def make_delivery(is_late: bool = False) -> DeliveryFinding:
    return DeliveryFinding(
        is_late=is_late,
        delivered_customer_date="2018-01-25 00:00:00" if is_late else "2018-01-10 00:00:00",
        estimated_delivery_date="2018-01-20 00:00:00",
        delivered_carrier_date="2018-01-03 00:00:00",
        days_late=5 if is_late else None,
        reasoning="fixture",
    )


def make_seller(
    late: bool = False, late_ids: Optional[list[str]] = None
) -> SellerFinding:
    ids = late_ids if late_ids is not None else ([SELLER_A] if late else [])
    return SellerFinding(
        any_handoff_after_limit=late,
        late_seller_ids=ids,
        per_item=[
            ItemHandoff(
                order_item_id=1,
                seller_id=ids[0] if ids else SELLER_A,
                shipping_limit_date="2018-01-05 00:00:00",
                handoff_after_limit=late,
            )
        ],
        reasoning="fixture",
    )


def make_payment(
    *, rows: int = 1, reconciled: bool = True, total: float = 115.0, expected: float = 115.0
) -> PaymentFinding:
    return PaymentFinding(
        payment_row_count=rows,
        payment_total_brl=total,
        expected_total_brl=expected,
        delta_brl=round(abs(total - expected), 2),
        reconciled=reconciled,
        is_split=rows >= 2,
        reasoning="fixture",
    )


def run(
    facts: OrderFacts,
    delivery: DeliveryFinding,
    seller: SellerFinding,
    payment: PaymentFinding,
    case_id: str = "EC_TEST",
) -> tuple[Any, CaseOutput]:
    """Chay policy.decide + verifier.build_output nhu coordinator van goi."""
    decision = policy.decide(case_id, facts, delivery, seller, payment)
    output = verifier.build_output(
        case_id, facts, decision, delivery, seller, payment
    )
    return decision, output


# ==============================================================================
# 1) Du 6 nhanh rule
# ==============================================================================


def test_rule1_canceled_order_paid() -> None:
    facts = make_facts(order_status="canceled", delivered_customer_date=None)
    decision, out = run(facts, make_delivery(False), make_seller(False), make_payment())

    assert decision.primary_issue == "canceled_order_paid"
    assert decision.root_cause_code == "ORDER_CANCELED_AFTER_PAYMENT"
    assert decision.recommended_refund_brl == facts.payment_total_brl == 115.0
    assert decision.case_status == "action_required"
    assert decision.resolution_actions == ["issue_full_refund"]
    assert decision.confidence == CONFIDENCE_BY_ISSUE["canceled_order_paid"]

    assert out.assessment.primary_issue == "canceled_order_paid"
    assert out.assessment.case_status == "action_required"
    assert out.financial_resolution.recommended_refund_brl == 115.0
    assert out.root_cause_analysis.responsible_parties[0].party_type == "platform"
    assert out.root_cause_analysis.responsible_parties[0].party_id == "OLIST_PLATFORM"
    assert out.resolution_actions == ["issue_full_refund"]


def test_rule2_unavailable_order_paid() -> None:
    facts = make_facts(order_status="unavailable", delivered_customer_date=None)
    decision, out = run(facts, make_delivery(False), make_seller(False), make_payment())

    assert decision.primary_issue == "unavailable_order_paid"
    assert decision.root_cause_code == "ORDER_UNAVAILABLE_AFTER_PAYMENT"
    assert decision.recommended_refund_brl == 115.0
    assert decision.case_status == "action_required"
    assert out.resolution_actions == ["issue_full_refund"]
    assert out.root_cause_analysis.responsible_parties[0].party_id == "OLIST_PLATFORM"


def test_rule3_late_delivery_seller() -> None:
    facts = make_facts()
    decision, out = run(
        facts, make_delivery(True), make_seller(True), make_payment()
    )

    assert decision.primary_issue == "late_delivery_seller"
    assert decision.root_cause_code == "SELLER_HANDOFF_AFTER_LIMIT"
    assert decision.recommended_refund_brl == facts.freight_total_brl == 15.0
    assert decision.case_status == "action_required"
    assert decision.resolution_actions == ["refund_freight"]
    assert out.root_cause_analysis.responsible_parties[0].party_type == "seller"
    assert out.root_cause_analysis.responsible_parties[0].party_id == SELLER_A
    assert out.root_cause_analysis.ranked_causes[0].cause_code == "SELLER_HANDOFF_AFTER_LIMIT"
    assert out.root_cause_analysis.ranked_causes[0].rank == 1


def test_rule3_picks_first_violating_seller() -> None:
    """Nhieu seller vi pham -> lay ID dau tien trong late_seller_ids."""
    facts = make_facts(n_items=2, seller_ids=[SELLER_A, SELLER_B])
    decision, out = run(
        facts,
        make_delivery(True),
        make_seller(True, late_ids=[SELLER_B, SELLER_A]),
        make_payment(total=facts.payment_total_brl, expected=facts.expected_total_brl),
    )
    assert decision.responsible_parties[0].party_id == SELLER_B
    assert f"seller:{SELLER_B}" in out.evidence_ids


def test_rule4_late_delivery_logistics() -> None:
    facts = make_facts()
    decision, out = run(
        facts, make_delivery(True), make_seller(False), make_payment()
    )

    assert decision.primary_issue == "late_delivery_logistics"
    assert decision.root_cause_code == "CARRIER_DELIVERED_AFTER_ESTIMATE"
    assert decision.recommended_refund_brl == 15.0
    assert decision.case_status == "action_required"
    assert decision.resolution_actions == ["refund_freight"]
    assert out.root_cause_analysis.responsible_parties[0].party_type == "logistics_provider"
    assert out.root_cause_analysis.responsible_parties[0].party_id == "LOGISTICS_PROVIDER"


def test_rule5_valid_split_payment() -> None:
    facts = make_facts(payments=[(1, 60.0), (2, 55.0)])
    decision, out = run(
        facts,
        make_delivery(False),
        make_seller(False),
        make_payment(rows=2, reconciled=True, total=115.0, expected=115.0),
    )

    assert decision.primary_issue == "valid_split_payment"
    assert decision.root_cause_code == "MULTIPLE_PAYMENTS_RECONCILED"
    assert decision.recommended_refund_brl == 0.0
    assert decision.case_status == "no_action"
    assert decision.resolution_actions == ["explain_valid_split_payment"]
    assert decision.responsible_parties == []
    assert out.root_cause_analysis.responsible_parties == []
    assert out.financial_resolution.recommended_refund_brl == 0.0
    assert isinstance(out.financial_resolution.recommended_refund_brl, float)


def test_rule6_unsupported_late_claim() -> None:
    facts = make_facts()
    decision, out = run(
        facts, make_delivery(False), make_seller(False), make_payment()
    )

    assert decision.primary_issue == "unsupported_late_claim"
    assert decision.root_cause_code == "DELIVERY_WITHIN_ESTIMATE"
    assert decision.recommended_refund_brl == 0.0
    assert decision.case_status == "no_action"
    assert decision.resolution_actions == ["reject_late_refund"]
    assert out.root_cause_analysis.responsible_parties == []


def test_rule6_is_default_even_when_not_reconciled() -> None:
    """Khong khop dieu kien nao khac -> van roi ve nhanh mac dinh, khong crash."""
    facts = make_facts(payments=[(1, 999.0)])
    decision, _ = run(
        facts,
        make_delivery(False),
        make_seller(False),
        make_payment(rows=1, reconciled=False, total=999.0, expected=115.0),
    )
    assert decision.primary_issue == "unsupported_late_claim"
    assert decision.case_status == "no_action"


# ==============================================================================
# 2) + 3) Uu tien rule
# ==============================================================================


def test_priority_canceled_beats_late() -> None:
    """Don canceled DONG THOI giao tre -> phai ra canceled_order_paid."""
    facts = make_facts(order_status="canceled")
    decision, out = run(
        facts, make_delivery(True), make_seller(True), make_payment()
    )
    assert decision.primary_issue == "canceled_order_paid"
    assert decision.recommended_refund_brl == facts.payment_total_brl
    assert out.assessment.primary_issue == "canceled_order_paid"


def test_priority_unavailable_beats_late() -> None:
    facts = make_facts(order_status="unavailable")
    decision, _ = run(facts, make_delivery(True), make_seller(True), make_payment())
    assert decision.primary_issue == "unavailable_order_paid"


def test_priority_late_beats_valid_split_payment() -> None:
    """Giao tre DONG THOI co 2 payment row khop -> phai ra nhanh late (rule 3/4)."""
    facts = make_facts(payments=[(1, 60.0), (2, 55.0)])
    split = make_payment(rows=2, reconciled=True, total=115.0, expected=115.0)

    seller_case, _ = run(facts, make_delivery(True), make_seller(True), split)
    assert seller_case.primary_issue == "late_delivery_seller"

    logistics_case, _ = run(facts, make_delivery(True), make_seller(False), split)
    assert logistics_case.primary_issue == "late_delivery_logistics"


def test_canceled_but_zero_payment_falls_through() -> None:
    """canceled nhung payment = 0 -> rule 1 khong khop, roi xuong nhanh sau."""
    facts = make_facts(order_status="canceled", payments=[(1, 0.0)])
    decision, out = run(
        facts,
        make_delivery(False),
        make_seller(False),
        make_payment(rows=1, reconciled=False, total=0.0, expected=115.0),
    )
    assert decision.primary_issue == "unsupported_late_claim"
    assert out.assessment.case_status == "no_action"


# ==============================================================================
# 4) Cat gioi han
# ==============================================================================


def test_truncation_8_items() -> None:
    facts = make_facts(n_items=8, payments=[(i + 1, 14.375) for i in range(8)])
    _, out = run(
        facts,
        make_delivery(True),
        make_seller(True),
        make_payment(rows=8, reconciled=False, total=115.0, expected=920.0),
    )

    assert len(out.affected_entities.item_ids) == MAX_ENTITY_IDS == 5
    assert out.affected_entities.item_ids == [f"{ORDER_ID}:{i}" for i in range(1, 6)]
    assert len(out.affected_entities.payment_ids) == 5
    assert len(out.affected_entities.order_ids) == 1
    assert len(out.affected_entities.seller_ids) <= MAX_ENTITY_IDS

    assert len(out.evidence_ids) <= MAX_EVIDENCE_IDS == 10
    assert f"order:{ORDER_ID}" in out.evidence_ids
    assert "policy:SELLER_HANDOFF_AFTER_LIMIT" in out.evidence_ids
    assert len(set(out.evidence_ids)) == len(out.evidence_ids)


def test_evidence_covers_all_five_kinds_when_room_allows() -> None:
    facts = make_facts(n_items=2, payments=[(1, 60.0), (2, 55.0)])
    _, out = run(
        facts,
        make_delivery(True),
        make_seller(True),
        make_payment(rows=2, reconciled=False, total=115.0, expected=230.0),
    )
    kinds = {ev.split(":", 1)[0] for ev in out.evidence_ids}
    assert kinds == {"order", "item", "payment", "seller", "policy"}


# ==============================================================================
# 5) Order khong co item row
# ==============================================================================


def test_order_without_item_rows() -> None:
    facts = make_facts(n_items=0, payments=[(1, 50.0)])
    assert facts.items == []

    _, out = run(
        facts,
        make_delivery(False),
        make_seller(False),
        make_payment(rows=1, reconciled=False, total=50.0, expected=0.0),
    )

    assert out.affected_entities.item_ids == []
    assert out.affected_entities.seller_ids == []
    assert out.affected_entities.order_ids == [ORDER_ID]
    assert out.affected_entities.payment_ids == [f"{ORDER_ID}:1"]
    assert out.financial_resolution.item_total_brl == 0.0
    assert out.financial_resolution.freight_total_brl == 0.0
    assert isinstance(out.financial_resolution.item_total_brl, float)
    assert isinstance(out.financial_resolution.freight_total_brl, float)
    assert not any(ev.startswith("item:") for ev in out.evidence_ids)
    assert not any(ev.startswith("seller:") for ev in out.evidence_ids)


def test_late_order_without_items_gets_zero_refund_and_no_action() -> None:
    """Giao tre nhung khong co item row -> freight = 0 -> phai la no_action."""
    facts = make_facts(n_items=0, payments=[(1, 50.0)])
    _, out = run(
        facts,
        make_delivery(True),
        make_seller(False),
        make_payment(rows=1, reconciled=False, total=50.0, expected=0.0),
    )
    assert out.assessment.primary_issue == "late_delivery_logistics"
    assert out.financial_resolution.recommended_refund_brl == 0.0
    assert out.assessment.case_status == "no_action"


def test_handoff_late_but_no_seller_id_downgrades_to_logistics() -> None:
    """any_handoff_after_limit=True nhung facts khong co seller nao -> khong bia ID."""
    facts = make_facts(n_items=0, payments=[(1, 50.0)])
    decision, out = run(
        facts,
        make_delivery(True),
        make_seller(True, late_ids=[]),
        make_payment(rows=1, reconciled=False, total=50.0, expected=0.0),
    )
    assert decision.primary_issue == "late_delivery_logistics"
    assert decision.responsible_parties[0].party_id == "LOGISTICS_PROVIDER"
    assert out.evidence_ids  # van co order: va policy:


def test_empty_late_seller_ids_recovered_from_facts() -> None:
    """late_seller_ids rong nhung facts co seller -> van ra rule 3 voi ID that."""
    facts = make_facts(n_items=1)
    decision, out = run(
        facts,
        make_delivery(True),
        make_seller(True, late_ids=[]),
        make_payment(),
    )
    assert decision.primary_issue == "late_delivery_seller"
    assert decision.responsible_parties[0].party_id == SELLER_A
    assert f"seller:{SELLER_A}" in out.evidence_ids


def test_unknown_late_seller_id_is_dropped() -> None:
    """LLM/agent khac tra ID khong co trong facts -> khong duoc dung lam evidence."""
    facts = make_facts(n_items=1)
    fake = "seller_ffffffffffffffffffffffffffffff"
    decision, out = run(
        facts,
        make_delivery(True),
        make_seller(True, late_ids=[fake]),
        make_payment(),
    )
    assert decision.responsible_parties[0].party_id == SELLER_A
    assert f"seller:{fake}" not in out.evidence_ids


# ==============================================================================
# 6) Evidence hop le va truy nguoc duoc ve facts
# ==============================================================================


def _assert_evidence_traceable(out: CaseOutput, facts: OrderFacts) -> None:
    valid_items = {str(it.order_item_id) for it in facts.items}
    valid_payments = {str(p.payment_sequential) for p in facts.payments}
    valid_sellers = set(facts.seller_ids)

    assert len(out.evidence_ids) <= MAX_EVIDENCE_IDS
    for ev in out.evidence_ids:
        assert any(rx.match(ev) for rx in _EVIDENCE_REGEXES), f"sai format: {ev}"
        kind, rest = ev.split(":", 1)
        if kind == "order":
            assert rest == facts.order_id
        elif kind == "item":
            oid, raw = rest.rsplit(":", 1)
            assert oid == facts.order_id and raw in valid_items
        elif kind == "payment":
            oid, raw = rest.rsplit(":", 1)
            assert oid == facts.order_id and raw in valid_payments
        elif kind == "seller":
            assert rest in valid_sellers
        elif kind == "policy":
            assert rest == out.root_cause_analysis.ranked_causes[0].cause_code

    assert f"order:{facts.order_id}" in out.evidence_ids
    assert any(ev.startswith("policy:") for ev in out.evidence_ids)


SCENARIOS: list[tuple[str, dict[str, Any]]] = [
    (
        "canceled_order_paid",
        {
            "facts": dict(order_status="canceled", delivered_customer_date=None),
            "late": False,
            "seller_late": False,
            "pay": dict(rows=1, reconciled=True, total=115.0, expected=115.0),
        },
    ),
    (
        "unavailable_order_paid",
        {
            "facts": dict(order_status="unavailable", delivered_customer_date=None),
            "late": False,
            "seller_late": False,
            "pay": dict(rows=1, reconciled=True, total=115.0, expected=115.0),
        },
    ),
    (
        "late_delivery_seller",
        {
            "facts": dict(n_items=2, seller_ids=[SELLER_A, SELLER_B]),
            "late": True,
            "seller_late": True,
            "pay": dict(rows=1, reconciled=True, total=230.0, expected=230.0),
        },
    ),
    (
        "late_delivery_logistics",
        {
            "facts": dict(n_items=3),
            "late": True,
            "seller_late": False,
            "pay": dict(rows=1, reconciled=True, total=345.0, expected=345.0),
        },
    ),
    (
        "valid_split_payment",
        {
            "facts": dict(payments=[(1, 60.0), (2, 55.0)]),
            "late": False,
            "seller_late": False,
            "pay": dict(rows=2, reconciled=True, total=115.0, expected=115.0),
        },
    ),
    (
        "unsupported_late_claim",
        {
            "facts": dict(),
            "late": False,
            "seller_late": False,
            "pay": dict(rows=1, reconciled=True, total=115.0, expected=115.0),
        },
    ),
]


@pytest.mark.parametrize("issue,cfg", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_evidence_and_status_consistency_all_branches(
    issue: str, cfg: dict[str, Any]
) -> None:
    facts = make_facts(**cfg["facts"])
    decision, out = run(
        facts,
        make_delivery(cfg["late"]),
        make_seller(cfg["seller_late"]),
        make_payment(**cfg["pay"]),
    )

    assert decision.primary_issue == issue
    assert out.assessment.primary_issue == issue

    # 7) case_status luon nhat quan voi refund tren ca 6 nhanh.
    refund = out.financial_resolution.recommended_refund_brl
    expected_status = "action_required" if refund > 0 else "no_action"
    assert out.assessment.case_status == expected_status

    # 6) evidence hop le va truy nguoc duoc ve facts.
    _assert_evidence_traceable(out, facts)

    # Rang buoc chung ve schema va gioi han.
    assert 0.0 <= out.assessment.confidence <= 1.0
    assert len(out.affected_entities.order_ids) <= MAX_ENTITY_IDS
    assert len(out.affected_entities.item_ids) <= MAX_ENTITY_IDS
    assert len(out.affected_entities.seller_ids) <= MAX_ENTITY_IDS
    assert len(out.affected_entities.payment_ids) <= MAX_ENTITY_IDS
    assert len(out.root_cause_analysis.ranked_causes) <= 3
    assert len(out.root_cause_analysis.responsible_parties) <= 3
    assert len(out.resolution_actions) <= 5
    assert out.financial_resolution.currency == "BRL"

    # Khong prefix trong affected_entities.
    for iid in out.affected_entities.item_ids:
        assert iid.startswith(f"{ORDER_ID}:") and not iid.startswith("item:")
    for pid in out.affected_entities.payment_ids:
        assert pid.startswith(f"{ORDER_ID}:") and not pid.startswith("payment:")

    # Output cuoi phai validate lai duoc, khong raise.
    CaseOutput.model_validate(out.model_dump())


# ==============================================================================
# Kiem tra tu sua cua verifier
# ==============================================================================


def test_verifier_fixes_inconsistent_case_status() -> None:
    """PolicyDecision bi hong (refund 0 nhung action_required) -> verifier sua lai."""
    facts = make_facts()
    decision = policy.decide(
        "EC_TEST", facts, make_delivery(False), make_seller(False), make_payment()
    )
    broken = decision.model_copy(
        update={"case_status": "action_required", "recommended_refund_brl": 0.0}
    )
    out = verifier.build_output(
        "EC_TEST", facts, broken, make_delivery(False), make_seller(False), make_payment()
    )
    assert out.assessment.case_status == "no_action"


def test_verifier_clamps_confidence() -> None:
    facts = make_facts()
    decision = policy.decide(
        "EC_TEST", facts, make_delivery(False), make_seller(False), make_payment()
    )
    for bad, expected in ((5.0, 1.0), (-3.0, 0.0)):
        out = verifier.build_output(
            "EC_TEST",
            facts,
            decision.model_copy(update={"confidence": bad}),
            make_delivery(False),
            make_seller(False),
            make_payment(),
        )
        assert out.assessment.confidence == expected


def test_money_rounding_two_decimals() -> None:
    facts = make_facts(price=33.333, freight=5.555, payments=[(1, 38.888)])
    _, out = run(
        facts,
        make_delivery(True),
        make_seller(False),
        make_payment(rows=1, reconciled=True, total=38.89, expected=38.89),
    )
    fin = out.financial_resolution
    for value in (
        fin.item_total_brl,
        fin.freight_total_brl,
        fin.payment_total_brl,
        fin.recommended_refund_brl,
    ):
        assert isinstance(value, float)
        assert round(value, 2) == value
    assert fin.recommended_refund_brl == facts.freight_total_brl
