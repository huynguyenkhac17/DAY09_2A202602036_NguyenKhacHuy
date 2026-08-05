"""Contract dong bang giua cac module. KHONG sua sau moc T+15.

Moi module chi giao tiep qua cac model o day. Xem docs/TEAM_PLAN.md muc 2.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ==============================================================================
# Hang so nghiep vu (EC_POLICY_V1)
# ==============================================================================

POLICY_VERSION = "EC_POLICY_V1"
CURRENCY = "BRL"

#: Sai so cho phep khi doi soat payment voi item + freight (README muc 4).
RECONCILE_TOLERANCE_BRL = 0.10

#: Gioi han so luong khi ghi output (README muc 6).
MAX_ENTITY_IDS = 5
MAX_EVIDENCE_IDS = 10
MAX_ROOT_CAUSES = 3
MAX_RESPONSIBLE_PARTIES = 3
MAX_ACTIONS = 5

PrimaryIssue = Literal[
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
]

CaseStatus = Literal["action_required", "no_action"]

RootCauseCode = Literal[
    "SELLER_HANDOFF_AFTER_LIMIT",
    "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "ORDER_CANCELED_AFTER_PAYMENT",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "MULTIPLE_PAYMENTS_RECONCILED",
    "DELIVERY_WITHIN_ESTIMATE",
]

ResolutionAction = Literal[
    "issue_full_refund",
    "refund_freight",
    "explain_valid_split_payment",
    "reject_late_refund",
]

PartyType = Literal["platform", "seller", "logistics_provider"]

PLATFORM_PARTY_ID = "OLIST_PLATFORM"
LOGISTICS_PARTY_ID = "LOGISTICS_PROVIDER"

#: confidence mac dinh theo nhanh rule (xem docs/TEAM_PLAN.md muc 2).
CONFIDENCE_BY_ISSUE: dict[str, float] = {
    "canceled_order_paid": 0.95,
    "unavailable_order_paid": 0.95,
    "late_delivery_seller": 0.92,
    "late_delivery_logistics": 0.92,
    "valid_split_payment": 0.90,
    "unsupported_late_claim": 0.88,
}

#: Moi lan LLM bat dong voi ket qua deterministic thi tru bang nay.
CONFIDENCE_PENALTY_ON_DISAGREEMENT = 0.05


# ==============================================================================
# Input
# ==============================================================================


class CustomerRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    language: str = "vi"
    message: str = ""
    claimed_order_id: str


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    opened_at: Optional[str] = None
    customer_request: CustomerRequest
    policy_version: str = POLICY_VERSION


# ==============================================================================
# Facts tu data layer (TV2 — src/data_store.py)
# ==============================================================================


class ItemRow(BaseModel):
    order_item_id: int
    product_id: str
    seller_id: str
    shipping_limit_date: Optional[str] = None
    price: float
    freight_value: float


class PaymentRow(BaseModel):
    payment_sequential: int
    payment_type: str
    payment_installments: int
    payment_value: float


class OrderFacts(BaseModel):
    """Nguon su that duy nhat ve du lieu CSV. Moi con so o day do Python tinh."""

    order_id: str
    exists: bool = True
    order_status: str = ""
    customer_id: str = ""
    purchase_ts: Optional[str] = None
    approved_at: Optional[str] = None
    delivered_carrier_date: Optional[str] = None
    delivered_customer_date: Optional[str] = None
    estimated_delivery_date: Optional[str] = None

    items: list[ItemRow] = Field(default_factory=list)
    payments: list[PaymentRow] = Field(default_factory=list)
    seller_ids: list[str] = Field(default_factory=list)

    item_total_brl: float = 0.0
    freight_total_brl: float = 0.0
    payment_total_brl: float = 0.0

    @property
    def expected_total_brl(self) -> float:
        return round(self.item_total_brl + self.freight_total_brl, 2)


# ==============================================================================
# Finding cua tung agent
# ==============================================================================


class DeliveryFinding(BaseModel):
    """TV3 — src/agents/delivery.py"""

    is_late: bool = False
    delivered_customer_date: Optional[str] = None
    estimated_delivery_date: Optional[str] = None
    delivered_carrier_date: Optional[str] = None
    days_late: Optional[int] = None
    reasoning: str = ""


class ItemHandoff(BaseModel):
    order_item_id: int
    seller_id: str
    shipping_limit_date: Optional[str] = None
    handoff_after_limit: bool = False


class SellerFinding(BaseModel):
    """TV3 — src/agents/order_seller.py"""

    any_handoff_after_limit: bool = False
    late_seller_ids: list[str] = Field(default_factory=list)
    per_item: list[ItemHandoff] = Field(default_factory=list)
    reasoning: str = ""


class PaymentFinding(BaseModel):
    """TV4 — src/agents/payment.py"""

    payment_row_count: int = 0
    payment_total_brl: float = 0.0
    expected_total_brl: float = 0.0
    delta_brl: float = 0.0
    reconciled: bool = False
    is_split: bool = False
    reasoning: str = ""


class ResponsibleParty(BaseModel):
    party_type: PartyType
    party_id: str


class PolicyDecision(BaseModel):
    """TV5 — src/agents/policy.py"""

    primary_issue: PrimaryIssue
    case_status: CaseStatus
    root_cause_code: RootCauseCode
    responsible_parties: list[ResponsibleParty] = Field(default_factory=list)
    recommended_refund_brl: float = 0.0
    resolution_actions: list[ResolutionAction] = Field(default_factory=list)
    confidence: float = 0.5
    reasoning: str = ""


# ==============================================================================
# Output schema (README muc 6) — Verifier chiu trach nhiem dung dung cai nay
# ==============================================================================


class Assessment(BaseModel):
    primary_issue: PrimaryIssue
    case_status: CaseStatus
    confidence: float = Field(ge=0.0, le=1.0)


class AffectedEntities(BaseModel):
    # LUU Y: item_ids / payment_ids KHONG co prefix -> "<order_id>:<n>"
    order_ids: list[str] = Field(default_factory=list, max_length=MAX_ENTITY_IDS)
    item_ids: list[str] = Field(default_factory=list, max_length=MAX_ENTITY_IDS)
    seller_ids: list[str] = Field(default_factory=list, max_length=MAX_ENTITY_IDS)
    payment_ids: list[str] = Field(default_factory=list, max_length=MAX_ENTITY_IDS)


class RankedCause(BaseModel):
    cause_code: RootCauseCode
    rank: int


class RootCauseAnalysis(BaseModel):
    ranked_causes: list[RankedCause] = Field(
        default_factory=list, max_length=MAX_ROOT_CAUSES
    )
    responsible_parties: list[ResponsibleParty] = Field(
        default_factory=list, max_length=MAX_RESPONSIBLE_PARTIES
    )


class FinancialResolution(BaseModel):
    currency: str = CURRENCY
    item_total_brl: float
    freight_total_brl: float
    payment_total_brl: float
    recommended_refund_brl: float


class CaseOutput(BaseModel):
    """Ghi thang ra output/EC_xxx.json."""

    case_id: str
    assessment: Assessment
    affected_entities: AffectedEntities
    root_cause_analysis: RootCauseAnalysis
    # evidence_ids CO prefix -> "order:", "item:", "payment:", "seller:", "policy:"
    evidence_ids: list[str] = Field(default_factory=list, max_length=MAX_EVIDENCE_IDS)
    financial_resolution: FinancialResolution
    resolution_actions: list[ResolutionAction] = Field(
        default_factory=list, max_length=MAX_ACTIONS
    )


def money(value: float) -> float:
    """Lam tron tien theo dung quy uoc de bai: 2 chu so, luon la float."""
    return round(float(value or 0.0), 2)
