# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung          |
| --------------- | ----------------- |
| Họ và tên       | Lê Kim Nam        |
| MSSV            | 2A202601803             |
| Khóa/Lớp        | K3                |
| Vai trò chính   | Payment Agent     |
| Ngày hoàn thành | 2026-08-05        |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable             | File/hàm phụ trách                                                        | Input nhận vào                      | Output bàn giao                              | Trạng thái  |
| ------------------------------ | ------------------------------------------------------------------------- | ----------------------------------- | -------------------------------------------- | ----------- |
| Payment Agent — hàm phân tích  | `src/agents/payment.py` → `analyze()`                                     | `case_id: str`, `facts: OrderFacts` | `PaymentFinding` (reconciled, split, delta)  | Hoàn thành  |
| Deterministic guard            | `src/agents/payment.py` → `_as_bool()`, `_deterministic_reasoning()`      | Kết quả LLM & giá trị deterministic | `reasoning: str` (Python-generated fallback) | Hoàn thành  |
| System prompt & user prompt    | `src/agents/payment.py` → `_SYSTEM_PROMPT`, `_build_user_prompt()`        | `OrderFacts`, các số đã tính        | Prompt định dạng JSON chuẩn                  | Hoàn thành  |
| Test suite Payment Agent       | `tests/test_payment.py` (16 test case)                                    | `OrderFacts` dựng tay               | 16 PASSED, không phụ thuộc API key           | Hoàn thành  |

Tôi trực tiếp thực hiện toàn bộ `src/agents/payment.py` và `tests/test_payment.py`. Module này nhận `OrderFacts` từ data layer (TV2 — `src/agents/data_store.py`) và bàn giao `PaymentFinding` cho Policy Agent (TV5 — `src/agents/policy.py`).

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                                      | Thành viên/module được hỗ trợ             | Kết quả                                                                                          |
| ---------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Xác nhận contract `PaymentFinding`             | TV2 (data_store) và TV5 (policy agent)    | Trường, kiểu và quy ước `money()` được đóng băng trong `src/contracts.py`                       |
| Debug import path `src.agent` → `src.agents`  | TV toàn nhóm (test runner bị fail)        | Sửa import trong `tests/test_payment.py` thành `src.agents.payment`; toàn bộ 16 test pass       |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện                                              | File/hàm/artifact liên quan                       | Kết quả bàn giao                                  | Cách xác minh                                |
| ------------------------------------------------------------------ | ------------------------------------------------- | ------------------------------------------------- | -------------------------------------------- |
| Đối soát payment: tổng payment vs item + freight                   | `src/agents/payment.py::analyze()`                | `PaymentFinding.reconciled`, `delta_brl`          | `python -m pytest tests/test_payment.py -v`  |
| Phát hiện split payment (≥ 2 payment row)                          | `src/agents/payment.py::analyze()`                | `PaymentFinding.is_split`                         | `test_three_payment_rows_reconciled_split`   |
| Guard đảm bảo LLM không ghi đè kết quả deterministic              | `src/agents/payment.py` (bước guard, step 3)      | Log `agreement`, fallback `reasoning`             | `test_installments_do_not_affect_any_number` |
| Xử lý đơn không có item row (order `unavailable`)                  | `_deterministic_reasoning()` + test `EC_TEST_05`  | `expected_total_brl = 0.0`, `reconciled = False`  | `test_no_item_rows_but_paid`                 |
| Kiểm soát sai số dấu phẩy động bằng `money()` trước khi so sánh  | `src/contracts.py::money()`                       | `delta_brl = 0.0` dù tổng nhiều số lẻ            | `test_float_noise_is_rounded_before_compare` |

**Output cụ thể phần Payment Agent tạo ra:**

`PaymentFinding` là Pydantic model được bàn giao cho Policy Agent. Ví dụ điển hình từ test `EC_TEST_02`:

```python
PaymentFinding(
    payment_row_count=3,
    payment_total_brl=175.00,
    expected_total_brl=175.00,
    delta_brl=0.0,
    reconciled=True,
    is_split=True,
    reasoning="Tong thanh toan 175.00 BRL so voi tong item + freight 175.00 BRL, "
              "chenh lech 0.00 BRL -> khop trong nguong sai so 0.10 BRL. "
              "Don co 3 payment row nen la thanh toan chia nho (split)."
)
```

Kết quả này giúp Policy Agent phân loại đúng `valid_split_payment` hoặc xác định đơn có bất thường tài chính, và Policy Agent sử dụng trực tiếp `payment_total_brl` để điền vào `financial_resolution.payment_total_brl` của output cuối.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Payment Agent giải quyết hai câu hỏi cốt lõi trong pipeline:

1. **Đối soát (reconciliation):** Tổng số tiền khách đã thanh toán (`payment_total_brl`) có khớp với tổng giá trị hàng (`item_total_brl`) cộng vận chuyển (`freight_total_brl`) trong ngưỡng sai số 0.10 BRL không? Nếu không khớp, đây là tín hiệu bất thường tài chính cần Policy Agent xử lý.
2. **Split payment:** Đơn hàng có bị chia thành từ 2 payment row trở lên không? Điều này phân biệt `valid_split_payment` với thanh toán đơn thuần.

Nếu không có Payment Agent, Policy Agent phải tự tính toán tài chính — vi phạm nguyên tắc phân công và làm Policy Agent khó kiểm chứng.

### Cách triển khai

Toàn bộ triển khai theo kiến trúc **deterministic-first, LLM-for-reasoning** gồm 3 bước:

**Bước 1 — Deterministic (nguồn sự thật):**
- Tính `payment_total_brl = money(facts.payment_total_brl)` — lấy thẳng từ data layer, không cộng lại.
- Tính `expected_total_brl = money(facts.item_total_brl + facts.freight_total_brl)`.
- `delta_brl = money(abs(payment_total - expected_total))` — áp dụng `money()` trước khi so sánh để triệt sai số dấu phẩy động.
- `reconciled = delta_brl <= 0.10` (ngưỡng inclusive theo README mục 4: "trong sai số 0.10 BRL").
- `is_split = payment_row_count >= 2`.
- Ghi log deterministic event qua `log_event()`.

**Bước 2 — LLM call (chỉ dùng cho `reasoning`):**
- Gọi `call_json()` với `_SYSTEM_PROMPT` và `_build_user_prompt()`. Prompt đã nhúng sẵn các số đã tính → LLM không phải cộng, chỉ xác nhận và giải thích bằng ngôn ngữ tự nhiên.
- `call_json()` trả `None` khi không có API key → agent tự động chạy deterministic-only, pipeline không crash.

**Bước 3 — Guard (kiểm chứng chéo):**
- So sánh `llm_reconciled` và `llm_is_split` với kết quả deterministic.
- Nếu LLM **đồng ý**: dùng `reasoning` của LLM.
- Nếu LLM **lệch**: giữ deterministic, thay `reasoning` bằng kết quả Python-generated từ `_deterministic_reasoning()`, log `agreement=False`.
- Không bao giờ để LLM ghi đè bất kỳ trường số hoặc boolean nào.

Quyết định dùng `money()` tại cả data layer lẫn `payment.py` là chủ ý: đảm bảo không có trường hợp nào so sánh float thô dù data layer có lỗi làm tròn.

### Input, output và contract

| Thành phần              | Mô tả                                                                                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Input                   | `case_id: str` (để trace log), `facts: OrderFacts` — Pydantic model từ `src/contracts.py`, chứa `payments: list[PaymentRow]`, `item_total_brl`, `freight_total_brl`, `payment_total_brl` đã tính sẵn |
| Output                  | `PaymentFinding` — Pydantic model: `payment_row_count`, `payment_total_brl`, `expected_total_brl`, `delta_brl`, `reconciled: bool`, `is_split: bool`, `reasoning: str`         |
| Module phụ thuộc        | `src/contracts.py` (định nghĩa `OrderFacts`, `PaymentFinding`, `RECONCILE_TOLERANCE_BRL`, `money()`), `src/llm.py` (`call_json()`), `src/trace.py` (`log_event()`)             |
| Module sử dụng output   | `src/agents/policy.py` — đọc `reconciled`, `is_split`, `payment_total_brl` để phân loại `valid_split_payment` và tính refund                                                  |
| Điều kiện lỗi cần xử lý | Không có payment row → `payment_total_brl = 0.0`; không có item row (order `unavailable`) → `expected_total_brl = 0.0`, `reconciled = False` (đúng theo nghiệp vụ); LLM timeout / no API key → `call_json()` trả `None`, agent chạy bình thường |

### Cách xác minh

```bash
# Từ thư mục root của repo
python -m pytest tests/test_payment.py -v
```

- **Kết quả mong đợi:** 16 test PASSED, 0 failed, 0 error.
- **Kết quả thực tế:** `16 passed in 0.25s` (Python 3.11.9, pytest 9.1.1, không cần API key).
- **Artifact/log:** Không có secret. Log trace ghi vào `logging/` theo cấu hình `src/trace.py`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Payment Agent cần quyết định khi nào thì `reconciled = True`. Có hai cách hiểu ngưỡng 0.10 BRL trong README mục 4: (a) `delta < 0.10` (exclusive) hoặc (b) `delta <= 0.10` (inclusive).

- **Các phương án đã cân nhắc:**
  1. **`delta < 0.10` (exclusive):** Đơn có delta = 0.10 bị coi là không khớp → Policy Agent có thể phân loại sai `valid_split_payment` thành bất thường tài chính, dẫn đến hoàn tiền sai.
  2. **`delta <= 0.10` (inclusive):** Biên trên 0.10 vẫn thuộc phạm vi cho phép, đúng với ngôn ngữ nghiệp vụ "trong sai số 0.10 BRL".

- **Phương án đã chọn:** `reconciled = delta_brl <= RECONCILE_TOLERANCE_BRL` (inclusive).

- **Lý do:** README mục 4 ghi *"trong sai số 0.10 BRL"* — "trong" bao gồm biên. Exclusive sẽ khiến test `test_delta_exactly_at_tolerance_is_reconciled` (delta = 0.10) fail. Inclusive cũng đúng thực tế tài chính: BRL có 2 chữ số thập phân, delta 0.10 là mức rounding error điển hình.

- **Bằng chứng quyết định phù hợp:** `test_delta_exactly_at_tolerance_is_reconciled` và `test_delta_exactly_at_tolerance_negative_direction` đều PASSED với `assert finding.reconciled is True` khi `delta_brl == 0.10`.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:**
  ```
  ModuleNotFoundError: No module named 'src.agent'; 'src' is not a package
  ```
  Xuất hiện khi chạy `python -m pytest tests/test_payment.py`.

- **Lệnh hoặc bước tái hiện:**
  ```bash
  python -m pytest tests/test_payment.py -v
  ```

- **Nguyên nhân gốc:** File `tests/test_payment.py` import theo đường dẫn `from src.agent.payment import analyze` — sử dụng `agent` (số ít). Nhưng thư mục thực tế là `src/agents/` (số nhiều, có `__init__.py`). Python không tìm được subpackage `agent` trong `src`.

- **Cách xử lý:** Sửa dòng import trong `tests/test_payment.py`:
  ```python
  # Trước (sai):
  from src.agent.payment import analyze
  # Sau (đúng):
  from src.agents.payment import analyze
  ```

- **Cách xác minh sau khi sửa:**
  ```bash
  python -m pytest tests/test_payment.py -v
  # Kết quả: 16 passed in 0.25s
  ```

- **Điều học được:** Khi tạo package trong Python, phải nhất quán giữa tên thư mục (`agents/`), file `__init__.py` và tất cả import reference trong toàn bộ codebase. Sai lệch dù chỉ 1 ký tự (`agent` vs `agents`) gây toàn bộ test suite không chạy được.

## 7. Hiểu biết về luồng end-to-end

*(Câu hỏi gốc trong template không khớp với bài lab này — tôi trả lời theo đúng hệ thống Multi-Agent E-commerce Dispute Resolution.)*

**1. Dữ liệu đi từ CSV đến quyết định cuối như thế nào?**
Coordinator Agent nhận case JSON từ `input/EC_xxx.json`, trích `claimed_order_id`, giao cho data layer để join các file CSV (`orders`, `order_items`, `order_payments`, `sellers`…) thành `OrderFacts`. `OrderFacts` được truyền cho Order/Seller Agent, Payment Agent và Delivery Agent chạy song song. Mỗi agent trả về Finding tương ứng. Policy Agent nhận toàn bộ Finding, áp dụng `EC_POLICY_V1` theo bảng ưu tiên (README mục 4) để tạo `PolicyDecision`. Verifier Agent kiểm tra schema và giới hạn ID, rồi ghi ra `output/EC_xxx.json`.

**2. Làm sao xác minh kết quả đúng?**
Bài lab dùng leaderboard chấm tự động theo 6 thành phần có trọng số (README mục 8). Tại local, kiểm chứng từng agent bằng test suite — ví dụ: `python -m pytest tests/test_payment.py`. Trace đầy đủ ghi vào `trace.jsonl` qua `src/trace.py` sau mỗi lần chạy.

**3. Quality checks nằm ở đâu trong pipeline?**
Có hai lớp: (a) **Deterministic guard** trong từng agent — so sánh kết quả LLM với Python, override nếu lệch; (b) **Verifier Agent** ở cuối — kiểm tra giới hạn số lượng ID (`MAX_ENTITY_IDS=5`, `MAX_EVIDENCE_IDS=10`…), `confidence` trong `[0,1]`, `case_status` hợp lệ, schema đúng chuẩn trước khi ghi file.

**4. Tại sao cần test không phụ thuộc API key?**
Test được thiết kế chạy ở chế độ `deterministic-only` (không có `GROQ_API_KEY`) để đảm bảo hành vi có thể tái hiện (reproducible) trên mọi máy. Nếu test phụ thuộc LLM, kết quả có thể thay đổi theo model version hoặc rate limit, không thể dùng làm baseline tin cậy.

**5. Payment Agent được xem là thành công dựa trên artifact và metric nào?**
- **Artifact:** `PaymentFinding` với `reconciled`, `is_split`, `delta_brl` đúng theo deterministic rules.
- **Metric local:** `16 passed` trong `tests/test_payment.py` — bao gồm edge case: delta biên 0.10, float noise, installments không ảnh hưởng, order không có item/payment row.
- **Metric leaderboard:** Điểm "Financial resolution" (20%) và "Primary issue" (20%) — cả hai đều phụ thuộc trực tiếp vào `PaymentFinding.reconciled`, `payment_total_brl` và `is_split` mà Payment Agent cung cấp.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Lê Kim Nam
**Ngày xác nhận:** 2026-08-05
