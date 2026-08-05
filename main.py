"""Entry point: doc input/EC_*.json -> ghi output/EC_*.json.

Chay:
    python main.py                 # chay het input/
    python main.py --limit 5       # chi 5 case dau (dev, tiet kiem quota)
    python main.py --case EC_001   # dung mot case

BAT BUOC: moi case deu phai co file output. Case loi van ghi output fallback hop le
schema — thieu file la hard gate 0 diem (README muc 8).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import traceback

from dotenv import load_dotenv

load_dotenv()

from src import config  # noqa: E402
from src.agents.coordinator import investigate  # noqa: E402
from src.contracts import (  # noqa: E402
    AffectedEntities,
    Assessment,
    CaseInput,
    CaseOutput,
    FinancialResolution,
    RankedCause,
    RootCauseAnalysis,
)
from src.trace import log_event, reset_trace  # noqa: E402


def fallback_output(case_id: str, order_id: str | None) -> CaseOutput:
    """Output an toan khi mot case no exception. Hop le schema, refund 0."""
    return CaseOutput(
        case_id=case_id,
        assessment=Assessment(
            primary_issue="unsupported_late_claim",
            case_status="no_action",
            confidence=0.3,
        ),
        affected_entities=AffectedEntities(order_ids=[order_id] if order_id else []),
        root_cause_analysis=RootCauseAnalysis(
            ranked_causes=[RankedCause(cause_code="DELIVERY_WITHIN_ESTIMATE", rank=1)],
            responsible_parties=[],
        ),
        evidence_ids=[f"order:{order_id}"] if order_id else [],
        financial_resolution=FinancialResolution(
            item_total_brl=0.0,
            freight_total_brl=0.0,
            payment_total_brl=0.0,
            recommended_refund_brl=0.0,
        ),
        resolution_actions=["reject_late_refund"],
    )


def run(
    limit: int | None = None,
    only_case: str | None = None,
    input_dir: str | None = None,
) -> int:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reset_trace()

    src_dir = pathlib.Path(input_dir) if input_dir else config.INPUT_DIR
    files = sorted(src_dir.glob("EC_*.json"))
    if only_case:
        files = [f for f in files if f.stem == only_case]
    if limit:
        files = files[:limit]

    if not files:
        print(f"[!] Khong tim thay file input nao trong {src_dir}")
        return 1

    print(f"[i] Model: {config.LLM_MODEL} ({config.LLM_PARAM_SIZE}) "
          f"| LLM {'BAT' if config.llm_enabled() else 'TAT (deterministic-only)'}")
    print(f"[i] Chay {len(files)} case...")

    started = time.perf_counter()
    failures = 0

    for path in files:
        case_id = path.stem
        order_id = None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            case = CaseInput.model_validate(raw)
            order_id = case.customer_request.claimed_order_id
            output = investigate(case)
        except Exception as exc:
            failures += 1
            log_event(case_id, "main", "case_error", error=traceback.format_exc())
            print(f"  [x] {case_id}: {type(exc).__name__}: {exc} -> dung fallback")
            output = fallback_output(case_id, order_id)

        dest = config.OUTPUT_DIR / f"{case_id}.json"
        dest.write_text(
            json.dumps(output.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  [v] {case_id} -> {output.assessment.primary_issue} "
              f"({output.financial_resolution.recommended_refund_brl} BRL)")

    elapsed = time.perf_counter() - started
    written = len(list(config.OUTPUT_DIR.glob("EC_*.json")))
    print(f"\n[i] Xong trong {elapsed:.1f}s | {written} file trong output/ | "
          f"{failures} case dung fallback")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-agent dispute resolution")
    parser.add_argument("--limit", type=int, default=None, help="chi chay N case dau")
    parser.add_argument("--case", type=str, default=None, help="chay dung 1 case, vd EC_001")
    parser.add_argument("--input-dir", type=str, default=None,
                        help="thu muc input khac, vd tests/sample_input")
    args = parser.parse_args()
    return run(limit=args.limit, only_case=args.case, input_dir=args.input_dir)


if __name__ == "__main__":
    sys.exit(main())
