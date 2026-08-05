"""Payment Agent — chu so huu: TV4 (Nam).

Doi soat tong tien thanh toan voi tong item + freight cua don hang.

Nguyen tac (docs/TEAM_PLAN.md muc 1):
  - MOI con so va MOI boolean trong PaymentFinding do Python tinh (deterministic).
  - LLM chi duoc dong gop truong `reasoning`; neu LLM ket luan lech voi
    deterministic thi guard override va tu sinh reasoning bang Python.
  - Khong co API key -> call_json() tra None -> chay deterministic-only,
    pipeline van hoat dong binh thuong.

Cam bay da xu ly (README muc 2 + docs/TEAM_PLAN.md muc 3):
  - `payment_value` la tien cua TUNG PAYMENT ROW, KHONG phai tien tung ky tra gop.
    Tuyet doi KHONG nhan voi `payment_installments`.
  - Don khong co item row (vi du status `unavailable`) -> expected_total_brl = 0.0
    trong khi payment_total_brl > 0 -> reconciled = False. Day la ket qua DUNG,
    khong duoc "chinh" cho khop.
  - So sanh tien luon lam tren gia tri da qua money() (round 2 chu so), khong so
    sanh float tho.
"""

from __future__ import annotations

from typing import Any

from src.contracts import RECONCILE_TOLERANCE_BRL, OrderFacts, PaymentFinding, money
from src.llm import call_json
from src.trace import log_event

_SYSTEM_PROMPT = """Ban la Payment Reconciliation Agent cua he thong xu ly khieu nai thuong mai dien tu Olist.
Nhiem vu: doc cac con so da duoc he thong tinh san va ket luan xem tong thanh toan co khop
voi tong tien hang cong tien van chuyen hay khong, va don co bi chia nhieu lan thanh toan hay khong.

Quy tac bat buoc:
- KHONG tu cong lai, KHONG tu tinh lai bat ky con so nao. Cac so da duoc cung cap la chinh xac.
- reconciled = true khi delta_brl <= 0.10 BRL (bao gom ca dung bang 0.10), nguoc lai la false.
- is_split = true khi so payment row >= 2, nguoc lai la false.
- Tien cua moi payment row la so tien THUC TE cua row do, KHONG phai tien moi ky tra gop.
  Tuyet doi khong nhan voi so ky tra gop (installments).

Tra ve DUY NHAT mot JSON object dang:
{"reconciled": true hoac false,
 "is_split": true hoac false,
 "reasoning": "mot den hai cau giai thich ngan gon"}"""


def analyze(case_id: str, facts: OrderFacts) -> PaymentFinding:
    """Doi soat payment cho mot don hang va tra ve PaymentFinding.

    Toan bo truong so/boolean deu la gia tri deterministic; LLM chi anh huong
    toi `reasoning`.
    """
    # ---------------------------------------------------------------- #
    # 1) Deterministic — nguon su that, LLM khong duoc phep ghi de.
    # ---------------------------------------------------------------- #
    payment_row_count: int = len(facts.payments)

    # Lay thang tu data layer de khong lech voi con so ghi ra output cuoi cung.
    payment_total_brl: float = money(facts.payment_total_brl)
    expected_total_brl: float = money(facts.item_total_brl + facts.freight_total_brl)

    # money() truoc khi so sanh de tranh sai so dau phay dong (vi du 0.09999999).
    delta_brl: float = money(abs(payment_total_brl - expected_total_brl))

    # Bien 0.10 tinh la KHOP (inclusive) — README muc 4 ghi "trong sai so 0.10 BRL".
    reconciled: bool = delta_brl <= RECONCILE_TOLERANCE_BRL
    is_split: bool = payment_row_count >= 2

    log_event(
        case_id,
        "payment",
        "deterministic",
        payload={
            "payment_row_count": payment_row_count,
            "payment_total_brl": payment_total_brl,
            "expected_total_brl": expected_total_brl,
            "delta_brl": delta_brl,
            "reconciled": reconciled,
            "is_split": is_split,
        },
    )

    # ---------------------------------------------------------------- #
    # 2) LLM call that — dua san so da tinh, chi hoi ket luan + giai thich.
    # ---------------------------------------------------------------- #
    llm_out: dict[str, Any] | None = call_json(
        case_id=case_id,
        agent="payment",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(
            facts=facts,
            payment_row_count=payment_row_count,
            payment_total_brl=payment_total_brl,
            expected_total_brl=expected_total_brl,
            delta_brl=delta_brl,
        ),
    )

    # ---------------------------------------------------------------- #
    # 3) Guard — doi chieu ket luan LLM voi deterministic.
    # ---------------------------------------------------------------- #
    fallback_reasoning = _deterministic_reasoning(
        payment_row_count=payment_row_count,
        payment_total_brl=payment_total_brl,
        expected_total_brl=expected_total_brl,
        delta_brl=delta_brl,
        reconciled=reconciled,
        is_split=is_split,
        has_items=bool(facts.items),
    )

    if llm_out is None:
        # Khong co API key hoac LLM loi -> chay deterministic-only.
        reasoning = fallback_reasoning
        log_event(
            case_id,
            "payment",
            "llm_unavailable",
            payload={"reasoning": reasoning},
            agreement=None,
        )
    else:
        llm_reconciled = _as_bool(llm_out.get("reconciled"))
        llm_is_split = _as_bool(llm_out.get("is_split"))
        agreement = (llm_reconciled == reconciled) and (llm_is_split == is_split)

        if agreement:
            llm_reasoning = str(llm_out.get("reasoning") or "").strip()
            reasoning = llm_reasoning or fallback_reasoning
        else:
            # Lech -> giu deterministic, bo reasoning cua LLM.
            reasoning = fallback_reasoning

        log_event(
            case_id,
            "payment",
            "guard",
            payload={
                "llm_reconciled": llm_reconciled,
                "llm_is_split": llm_is_split,
                "det_reconciled": reconciled,
                "det_is_split": is_split,
            },
            agreement=agreement,
        )

    return PaymentFinding(
        payment_row_count=payment_row_count,
        payment_total_brl=payment_total_brl,
        expected_total_brl=expected_total_brl,
        delta_brl=delta_brl,
        reconciled=reconciled,
        is_split=is_split,
        reasoning=reasoning,
    )


# ====================================================================== #
# Helper noi bo
# ====================================================================== #


def _build_user_prompt(
    *,
    facts: OrderFacts,
    payment_row_count: int,
    payment_total_brl: float,
    expected_total_brl: float,
    delta_brl: float,
) -> str:
    """Dung prompt chua san moi con so da tinh — LLM khong phai cong gi ca."""
    if facts.payments:
        rows = "\n".join(
            f"  - row #{p.payment_sequential}: type={p.payment_type}, "
            f"installments={p.payment_installments}, value={money(p.payment_value)} BRL"
            for p in facts.payments
        )
    else:
        rows = "  (khong co payment row nao)"

    return (
        f"Trang thai don hang: {facts.order_status or 'khong xac dinh'}\n"
        f"So item row: {len(facts.items)}\n"
        f"Danh sach payment row ({payment_row_count} row):\n{rows}\n"
        f"\nCac tong da duoc he thong tinh san:\n"
        f"  item_total_brl    = {money(facts.item_total_brl):.2f}\n"
        f"  freight_total_brl = {money(facts.freight_total_brl):.2f}\n"
        f"  expected_total_brl (item + freight) = {expected_total_brl:.2f}\n"
        f"  payment_total_brl = {payment_total_brl:.2f}\n"
        f"  delta_brl = |payment_total - expected_total| = {delta_brl:.2f}\n"
        f"  nguong sai so cho phep = {RECONCILE_TOLERANCE_BRL:.2f} BRL\n"
        "\nHay ket luan reconciled va is_split theo dung quy tac da neu."
    )


def _deterministic_reasoning(
    *,
    payment_row_count: int,
    payment_total_brl: float,
    expected_total_brl: float,
    delta_brl: float,
    reconciled: bool,
    is_split: bool,
    has_items: bool,
) -> str:
    """Sinh reasoning bang Python khi khong dung duoc reasoning cua LLM."""
    split_part = (
        f"Don co {payment_row_count} payment row nen la thanh toan chia nho (split)."
        if is_split
        else f"Don co {payment_row_count} payment row nen khong phai thanh toan chia nho."
    )

    if not has_items:
        note = (
            " Don khong co item row nao nen expected_total_brl = 0.00; "
            "chenh lech nay phan anh dung du lieu, khong phai loi tinh toan."
        )
    else:
        note = ""

    verdict = (
        f"khop trong nguong sai so {RECONCILE_TOLERANCE_BRL:.2f} BRL"
        if reconciled
        else f"vuot nguong sai so {RECONCILE_TOLERANCE_BRL:.2f} BRL"
    )

    return (
        f"Tong thanh toan {payment_total_brl:.2f} BRL so voi tong item + freight "
        f"{expected_total_brl:.2f} BRL, chenh lech {delta_brl:.2f} BRL -> {verdict}. "
        f"{split_part}{note}"
    )


def _as_bool(value: Any) -> bool:
    """Ep gia tri LLM tra ve thanh bool (model doi khi tra chuoi 'true'/'false')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "co", "dung"}
    return bool(value)
