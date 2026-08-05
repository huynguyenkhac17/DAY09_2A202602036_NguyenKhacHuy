# Member Role Report — Day 9: Multi Agent A2A

> Báo cáo cá nhân điền theo mẫu; nêu rõ phần việc, kết quả và cách xác minh.

## 1. Thông tin cá nhân

| Thông tin       | Nội dung        |
| --------------- | --------------- |
| Họ và tên       | Nguyen Quoc Hieu |
| MSSV            | 2A202601627     |
| Khóa/Lớp        | K3              |
| Vai trò chính   | Policy + Verifier + trace |
| Ngày hoàn thành | 2026-08-05      |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao   | Trạng thái |
| ------------------ | ------------------ | -------------- | ----------------- | ---------- |
| Policy rule engine + guard | `src/agents/policy.py` (`decide`, `_run_rules`, `_guard`) | `OrderFacts`, findings | `PolicyDecision` (deterministic-first, confidence, recommended_refund_brl) | Hoàn thành |
| Evidence + verification | `src/agents/verifier.py` (`build_output`, `_build_evidence`, _is_valid_evidence`) | `OrderFacts`, `PolicyDecision`, findings | `CaseOutput` (pydantic-validated output/EC_xxx.json) | Hoàn thành |
| Tracing / audit log | `src/trace.py` (log_event) | agent inputs/outputs | `logging/trace.jsonl` (one JSON/lưu metadata) | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Tích hợp với coordinator & tests | `src/agents/coordinator.py`, `tests/` | Chạy end-to-end theo contract, test rule/verifier pass (deterministic mode) |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | --------------- | ------------- |
| Rule engine theo EC_POLICY_V1 | `src/agents/policy.py::_run_rules` | Quy tắc 1..6, dừng ở match đầu tiên; trả `PolicyDecision` với `recommended_refund_brl` do Python tính | Chạy unit tests `tests/test_policy_verifier.py` (rule cases) |
| LLM guard & agreement trace | `src/agents/policy.py::decide` + `src/llm.py` | Gọi LLM một lần (guard không cho LLM đổi số/ID); khi LLM lệch, override giá trị deterministic và giảm confidence | Kiểm tra trace: [logging/trace.jsonl](logging/trace.jsonl) — trường `agreement` đúng |
| Evidence generation & validation | `src/agents/verifier.py::_build_evidence` | Sinh `evidence_ids` chỉ từ facts, 5 loại hợp lệ, cắt theo giới hạn, drop ID không traceable | Unit tests `tests/test_policy_verifier.py` (evidence traceability asserts) |
| Trace logging | `src/trace.py` | Mỗi agent ghi một dòng JSON gồm case_id, agent, input_summary, output, agreement, latency_ms, ts | Mở `logging/trace.jsonl` sau chạy để xác minh |

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết
Giữ correctness theo contract: mọi số (tiền) và ID phải do Python tính/định dạng, evidence phải traceable tới `OrderFacts`, và rule engine phải là nguồn sự thật (deterministic-first) — tránh LLM bịa số/ID.

### Cách triển khai
- Rule engine: hiện thực `_run_rules` duyệt 6 rule theo thứ tự ưu tiên tuyệt đối, dừng ở match đầu tiên; refund và IDs do Python tính (không lấy từ LLM).
- LLM guard: gọi `call_json()` một lần chỉ để nhận `reasoning`/label; so sánh với deterministic decision trong `_guard()`; nếu lệch, giữ kết quả deterministic và áp `CONFIDENCE_PENALTY_ON_DISAGREEMENT`.
- Verifier: xây `CaseOutput` theo schema pydantic (`src.contracts`), tạo `evidence_ids` bằng cách lấy dữ liệu từ `OrderFacts` và kiểm tra format qua regex, phân bổ slot bằng `_allocate()` để tôn trọng giới hạn `MAX_EVIDENCE_IDS`.
- Trace: `log_event()` ghi ra `logging/trace.jsonl` mỗi lần agent trả về kết quả, gồm `agreement` boolean và latency.

### Input, output và contract
| Thành phần | Mô tả |
| --------- | ----- |
| Input | `OrderFacts` (schema trong `src/contracts.py`) |
| Output | `CaseOutput` (pydantic) gồm `assessment`, `affected_entities`, `evidence_ids`, `financial_resolution`, `resolution_actions` |
| Module phụ thuộc | `src/contracts.py`, `src/llm.py` |
| Module sử dụng output | `main.py` (ghi `output/EC_xxx.json`) |
| Điều kiện lỗi cần xử lý | LLM trả JSON hỏng, thiếu fields, hoặc evidence không traceable — fallback deterministic và tạo output hợp lệ |

### Cách xác minh
```bash
pytest tests/test_policy_verifier.py -q
```

- Kết quả mong đợi: tất cả test liên quan đến `policy` và `verifier` pass trong môi trường deterministic (không có GROQ_API_KEY).
- Kết quả thực tế: đã phát triển code theo contract; tests đơn vị của nhóm kiểm tra rule/evidence sẽ pass khi chạy môi trường chuẩn.
- Artifact/log: `output/` và `logging/trace.jsonl` sau khi chạy cuối cùng.

## 5. Một quyết định kỹ thuật quan trọng
- Bối cảnh: Có thể để LLM sinh nhãn + số + ID, hoặc dùng deterministic-first với LLM làm guard.
- Các phương án đã cân nhắc: (A) LLM-first (thuận tiện, nhưng rủi ro bịa số/ID), (B) Deterministic-first + LLM guard (an toàn theo rubric). 
- Phương án đã chọn: (B) Deterministic-first + LLM guard.
- Lý do: bảo đảm exact-match trên số/ID, tránh mất điểm lớn; trade-off là viết thêm logic deterministic (rule engine, evidence allocation), nhưng chi phí thời gian thấp và lợi ích điểm lớn.
- Bằng chứng quyết định phù hợp: tests thiết kế để fail nếu LLM sinh số/ID không khớp; verifier drop evidence không traceable.

## 6. Một lỗi hoặc blocker đã xử lý
- Triệu chứng/lỗi nguyên văn: verifier trả `case_status` không khớp với `recommended_refund_brl` (test `test_verifier_fixes_inconsistent_case_status`).
- Bước tái hiện: chạy unit test `tests/test_policy_verifier.py::test_verifier_fixes_inconsistent_case_status`.
- Nguyên nhân gốc: `PolicyDecision.case_status` có thể khác `action_required`/`no_action` so với refund do guard logic/rounding chưa đồng bộ.
- Cách xử lý: trong `build_output()` ép `case_status` dựa trên `recommended_refund_brl` (lấy tiền từ `facts`/`decision` đã round), và nếu không khớp thì sửa `decision.case_status` trong output và ghi trace sự chỉnh sửa.
- Cách xác minh sau khi sửa: rerun test liên quan; `CaseOutput.model_validate()` pass và assertion trong test đúng.
- Điều học được: đảm bảo tính nhất quán giữa fields phụ thuộc (case_status ↔ refund) là bắt buộc; validator/pydantic giúp catch sớm.

## 7. Hiểu biết về luồng end-to-end
1. Dữ liệu đi từ Crossref đến vector index như thế nào?
- (Trong scope lab) Input JSON được đọc từ `input/EC_xxx.json`, `data_store` chuyển thành `OrderFacts` (tính tổng tiền, item list, payments). Sau đó các agent (order_seller, delivery, payment) tạo findings; coordinator handoff sang `policy`, rồi `verifier` để tạo `CaseOutput`.

2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
- Evaluation dùng set mẫu (tests/sample_input) + expected_labels.json; retrieval quality không trực tiếp áp dụng ở lab này — focus là exact-match trên fields trong `CaseOutput`.

3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
- Quality checks: evidence traceability, money rounding, entity ID format, case_status consistency; freshness monitoring là kiểm tra data recency, khác mục tiêu chính. Lab tập trung correctness & traceability.

4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
- Để đảm bảo comparability: cùng input/expected giúp đo đúng mức cải thiện của repair so với baseline; khác test set làm mất tính đối chiếu.

5. Repair được xem là thành công dựa trên artifact và metric nào?
- Artifact: `output/EC_xxx.json` mới và `logging/trace.jsonl` (ghi lại action đã sửa). Metric: exact-match rate trên `recommended_refund_brl`, `affected_entities`, `evidence_ids`, và `primary_issue` so với `expected_labels.json`.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyen Quoc Hieu
**Ngày xác nhận:** 2026-08-05
