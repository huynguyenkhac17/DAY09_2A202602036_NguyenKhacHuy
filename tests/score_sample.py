"""Tu cham output/ so voi nhan ky vong cua bo input mau.

Dung o buoc audit (TEAM_PLAN moc T+85). Chay:

    python main.py --input-dir tests/sample_input
    python tests/score_sample.py

LUU Y: expected_labels.json do tests/make_sample_input.py sinh ra bang mot ban
tham chieu doc lap, KHONG phai ground truth cua ban to chuc. Lech nhau nghia la
"co gi do can mo CSV kiem tay", khong phai "chac chan sai".
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
EXPECTED_PATH = ROOT / "tests" / "expected_labels.json"

EVIDENCE_PATTERNS = [
    re.compile(r"^order:[0-9a-f]{32}$"),
    re.compile(r"^item:[0-9a-f]{32}:\d+$"),
    re.compile(r"^payment:[0-9a-f]{32}:\d+$"),
    re.compile(r"^seller:[0-9a-f]{32}$"),
    re.compile(r"^policy:[A-Z_]+$"),
]

MAX_LIMITS = {
    "order_ids": 5, "item_ids": 5, "seller_ids": 5, "payment_ids": 5,
}


def check_schema(case_id: str, doc: dict) -> list[str]:
    """Kiem tra cac rang buoc cung cua de bai. Tra ve danh sach loi."""
    errs: list[str] = []

    ent = doc.get("affected_entities", {})
    for key, cap in MAX_LIMITS.items():
        if len(ent.get(key, [])) > cap:
            errs.append(f"{key} co {len(ent.get(key, []))} phan tu, vuot gioi han {cap}")

    ev = doc.get("evidence_ids", [])
    if len(ev) > 10:
        errs.append(f"evidence_ids co {len(ev)} phan tu, vuot gioi han 10")
    for e in ev:
        if not any(p.match(e) for p in EVIDENCE_PATTERNS):
            errs.append(f"evidence_id sai dinh dang: {e!r}")

    if len(doc.get("resolution_actions", [])) > 5:
        errs.append("resolution_actions vuot gioi han 5")
    rca = doc.get("root_cause_analysis", {})
    if len(rca.get("ranked_causes", [])) > 3:
        errs.append("ranked_causes vuot gioi han 3")
    if len(rca.get("responsible_parties", [])) > 3:
        errs.append("responsible_parties vuot gioi han 3")

    conf = doc.get("assessment", {}).get("confidence")
    if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
        errs.append(f"confidence khong hop le: {conf!r}")

    fin = doc.get("financial_resolution", {})
    refund = fin.get("recommended_refund_brl")
    status = doc.get("assessment", {}).get("case_status")
    if isinstance(refund, (int, float)):
        want = "action_required" if refund > 0 else "no_action"
        if status != want:
            errs.append(f"case_status={status!r} khong khop refund={refund} (can {want!r})")
    for key in ("item_total_brl", "freight_total_brl", "payment_total_brl",
                "recommended_refund_brl"):
        val = fin.get(key)
        if not isinstance(val, (int, float)):
            errs.append(f"{key} khong phai so: {val!r}")
        elif round(float(val), 2) != float(val):
            errs.append(f"{key}={val} chua lam tron 2 chu so")

    return errs


def main() -> int:
    if not EXPECTED_PATH.exists():
        print("[!] Chua co tests/expected_labels.json — chay tests/make_sample_input.py truoc")
        return 1

    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    match_fields = [
        "primary_issue", "case_status", "item_total_brl", "freight_total_brl",
        "payment_total_brl", "recommended_refund_brl",
    ]

    total = len(expected)
    exact = 0
    schema_bad = 0

    for case_id, want in sorted(expected.items()):
        path = OUTPUT_DIR / f"{case_id}.json"
        if not path.exists():
            print(f"[x] {case_id}: THIEU FILE OUTPUT")
            continue

        doc = json.loads(path.read_text(encoding="utf-8"))
        got = {
            "primary_issue": doc["assessment"]["primary_issue"],
            "case_status": doc["assessment"]["case_status"],
            "root_cause_code": (doc["root_cause_analysis"]["ranked_causes"] or [{}])[0]
                .get("cause_code"),
            **{k: doc["financial_resolution"][k] for k in
               ("item_total_brl", "freight_total_brl", "payment_total_brl",
                "recommended_refund_brl")},
        }

        diffs = [
            f"{f}: got={got[f]!r} want={want[f]!r}"
            for f in match_fields + ["root_cause_code"]
            if got.get(f) != want.get(f)
        ]
        errs = check_schema(case_id, doc)
        if errs:
            schema_bad += 1

        if not diffs and not errs:
            exact += 1
            print(f"[v] {case_id}  {got['primary_issue']}")
        else:
            print(f"[x] {case_id}  {got['primary_issue']}")
            for d in diffs:
                print(f"      lech  {d}")
            for e in errs:
                print(f"      schema {e}")

    print(f"\nKhop hoan toan: {exact}/{total} | Vi pham schema: {schema_bad}/{total}")
    return 0 if exact == total and schema_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
