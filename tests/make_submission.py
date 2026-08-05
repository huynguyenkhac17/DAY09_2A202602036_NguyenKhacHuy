"""Kiem tra output/ va dong goi file zip nop bai.

Chay:
    python tests/make_submission.py

Kiem tra truoc khi zip (fail thi KHONG tao zip):
  1. Dung 50 file EC_001.json .. EC_050.json, khong thua khong thieu
  2. Moi file parse duoc va pass schema CaseOutput
  3. Moi evidence_id khop 1 trong 5 dinh dang hop le
  4. case_status nhat quan voi recommended_refund_brl
  5. Moi truong tien da lam tron 2 chu so
  6. Khong co file la trong output/

Zip chi chua cac file JSON o goc (README muc 8: khong source, khong .env).
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.contracts import CaseOutput  # noqa: E402

OUTPUT_DIR = ROOT / "output"
ZIP_PATH = ROOT / "output.zip"

EXPECTED = [f"EC_{i:03d}" for i in range(1, 51)]

EVIDENCE_RE = [
    re.compile(r"^order:[0-9a-f]{32}$"),
    re.compile(r"^item:[0-9a-f]{32}:\d+$"),
    re.compile(r"^payment:[0-9a-f]{32}:\d+$"),
    re.compile(r"^seller:[0-9a-f]{32}$"),
    re.compile(r"^policy:[A-Z_]+$"),
]


def check() -> tuple[list[pathlib.Path], list[str]]:
    errors: list[str] = []
    files: list[pathlib.Path] = []

    present = {p.stem for p in OUTPUT_DIR.glob("EC_*.json")}
    missing = [c for c in EXPECTED if c not in present]
    extra = sorted(present - set(EXPECTED))
    if missing:
        errors.append(f"THIEU {len(missing)} file: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    if extra:
        errors.append(f"THUA file la: {extra}")

    stray = [p.name for p in OUTPUT_DIR.iterdir()
             if p.is_file() and not re.fullmatch(r"EC_\d{3}\.json", p.name)]
    if stray:
        errors.append(f"File la trong output/ (phai xoa truoc khi zip): {stray}")

    for case_id in EXPECTED:
        path = OUTPUT_DIR / f"{case_id}.json"
        if not path.exists():
            continue
        files.append(path)

        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{case_id}: JSON hong - {exc}")
            continue

        try:
            CaseOutput.model_validate(doc)
        except Exception as exc:
            errors.append(f"{case_id}: sai schema - {str(exc)[:200]}")
            continue

        if doc["case_id"] != case_id:
            errors.append(f"{case_id}: case_id ben trong la {doc['case_id']!r}")

        for ev in doc["evidence_ids"]:
            if not any(r.match(ev) for r in EVIDENCE_RE):
                errors.append(f"{case_id}: evidence_id sai dinh dang {ev!r}")

        fin = doc["financial_resolution"]
        refund = fin["recommended_refund_brl"]
        want = "action_required" if refund > 0 else "no_action"
        if doc["assessment"]["case_status"] != want:
            errors.append(
                f"{case_id}: case_status={doc['assessment']['case_status']!r} "
                f"nhung refund={refund} (can {want!r})"
            )

        for key in ("item_total_brl", "freight_total_brl", "payment_total_brl",
                    "recommended_refund_brl"):
            val = fin[key]
            if round(float(val), 2) != float(val):
                errors.append(f"{case_id}: {key}={val} chua lam tron 2 chu so")

    return files, errors


def main() -> int:
    if not OUTPUT_DIR.exists():
        print("[!] Khong co thu muc output/")
        return 1

    files, errors = check()

    if errors:
        print(f"[x] {len(errors)} loi - KHONG tao zip:\n")
        for e in errors[:30]:
            print(f"    {e}")
        if len(errors) > 30:
            print(f"    ... va {len(errors) - 30} loi nua")
        return 1

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(files):
            zf.write(path, arcname=path.name)

    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = zf.namelist()
    size_kb = ZIP_PATH.stat().st_size / 1024

    print(f"[v] {len(files)} file hop le, khong loi")
    print(f"[v] Da tao {ZIP_PATH.name} ({size_kb:.1f} KB, {len(names)} entry)")
    print(f"[v] Entry dau/cuoi: {names[0]} .. {names[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
