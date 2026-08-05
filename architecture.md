# Kiến trúc hệ thống Multi-Agent — Dispute Resolution

Hệ thống điều tra khiếu nại thương mại điện tử trên dữ liệu Olist bằng 6 agent, mỗi agent phụ trách
một domain dữ liệu và bàn giao (handoff) bằng chứng cho agent kế tiếp.

## 1. Nguyên tắc thiết kế nền tảng

Điểm chấm của bài lab là **so khớp chính xác số tiền và ID** — 55% trọng số nằm ở affected entities,
evidence IDs và financial resolution. Một model ≤10B không cộng tiền chính xác tới 2 chữ số thập phân
và không sao chép nổi `order_id` dài 32 ký tự hex.

Vì vậy hệ thống tách bạch hai vai trò:

| | Ai làm | Ví dụ |
| --- | --- | --- |
| **Nguồn của sự thật** | Python deterministic (pandas) | mọi số tiền, mọi ID, mọi so sánh mốc thời gian |
| **Suy luận và quyết định** | LLM agent | phân loại vấn đề, giải thích nguyên nhân, lập kế hoạch điều tra |

Mỗi kết luận của LLM đều đi qua một **guard deterministic** đối chiếu với kết quả Python tính được.
Bất đồng thì lấy kết quả deterministic, trừ `confidence` 0.05 và ghi vào trace với `agreement: false`.
Nhờ vậy LLM không bao giờ làm hỏng con số, nhưng vẫn đóng vai trò thật trong luồng — đúng yêu cầu
"phải có phân công, handoff và kiểm chứng giữa các agent".

Hệ quả phụ có lợi: khi không có API key hoặc Groq rate-limit, pipeline vẫn chạy đủ 50 case ở chế độ
deterministic-only thay vì sập.

## 2. Sơ đồ agent và luồng handoff

```
                        input/EC_xxx.json
                                |
                                v
                     +---------------------+
                     |  Coordinator Agent  |  LLM: lập kế hoạch điều tra
                     +---------------------+
                                |
                    get_order_facts(order_id)
                                |
                                v
                     +---------------------+
                     |     data_store      |  pandas, thành phần DUY NHẤT đọc CSV
                     +---------------------+
                                |
                             OrderFacts
                                |
             +------------------+------------------+
             |                  |                  |
             v                  v                  v
   +------------------+ +---------------+ +----------------+
   | Order & Seller   | |   Delivery    | |    Payment     |
   |      Agent       | |     Agent     | |     Agent      |
   |  LLM + guard     | |  LLM + guard  | |  LLM + guard   |
   +------------------+ +---------------+ +----------------+
             |                  |                  |
      SellerFinding    DeliveryFinding      PaymentFinding
             |                  |                  |
             +------------------+------------------+
                                |
                                v
                     +---------------------+
                     |    Policy Agent     |  LLM áp EC_POLICY_V1 + rule engine
                     +---------------------+
                                |
                          PolicyDecision
                                |
                                v
                     +---------------------+
                     |   Verifier Agent    |  deterministic: dựng & lọc ID, kiểm schema
                     +---------------------+
                                |
                                v
                       output/EC_xxx.json
                                +
                       logging/trace.jsonl
```

## 3. Vai trò và quyền truy cập

| Agent | File | Quyền truy cập dữ liệu | Nhận vào | Bàn giao ra |
| --- | --- | --- | --- | --- |
| **Coordinator** | `src/agents/coordinator.py` | không đọc CSV; gọi `data_store` | `CaseInput` | `OrderFacts` cho 3 agent điều tra, `CaseOutput` cho `main` |
| **Order & Seller** | `src/agents/order_seller.py` | chỉ đọc `items`, `seller_ids`, `delivered_carrier_date` | `OrderFacts` | `SellerFinding` |
| **Delivery** | `src/agents/delivery.py` | chỉ đọc các mốc thời gian | `OrderFacts` | `DeliveryFinding` |
| **Payment** | `src/agents/payment.py` | chỉ đọc `payments` và các total | `OrderFacts` | `PaymentFinding` |
| **Policy** | `src/agents/policy.py` | không đọc dữ liệu thô, chỉ đọc 3 finding | 3 finding + `OrderFacts` | `PolicyDecision` |
| **Verifier** | `src/agents/verifier.py` | đọc `OrderFacts` để đối chiếu ID | `PolicyDecision` + `OrderFacts` | `CaseOutput` |

**Ràng buộc quyền truy cập:** chỉ `src/data_store.py` được phép mở file CSV. Không agent nào đọc
`data/` trực tiếp. Nhờ đó mọi con số trong output đều truy vết được về một điểm duy nhất, và không
agent nào có thể bịa ra thực thể không tồn tại.

## 4. Contract giữa các agent

Mọi handoff đi qua model pydantic khai báo trong `src/contracts.py`, không dùng dict tự do:

- `OrderFacts` — facts đã tính sẵn từ CSV (items, payments, seller_ids, 3 con số tổng)
- `DeliveryFinding` — `is_late`, các mốc thời gian, `days_late`
- `SellerFinding` — `any_handoff_after_limit`, `late_seller_ids`, `per_item`
- `PaymentFinding` — `reconciled`, `is_split`, `delta_brl`, `expected_total_brl`
- `PolicyDecision` — `primary_issue`, `root_cause_code`, `responsible_parties`, refund, actions
- `CaseOutput` — schema nộp bài, có ràng buộc `max_length` đúng giới hạn đề bài

Vi phạm contract bị pydantic chặn ngay tại ranh giới agent thay vì lọt xuống file output.

## 5. Rule engine (EC_POLICY_V1)

Policy Agent áp bảng luật theo **thứ tự ưu tiên tuyệt đối**, dừng ở match đầu tiên:

| # | Điều kiện | Primary issue | Bên chịu trách nhiệm | Refund |
| --- | --- | --- | --- | ---: |
| 1 | `canceled` và payment > 0 | `canceled_order_paid` | `platform` / `OLIST_PLATFORM` | tổng payment |
| 2 | `unavailable` và payment > 0 | `unavailable_order_paid` | `platform` / `OLIST_PLATFORM` | tổng payment |
| 3 | giao trễ và seller bàn giao quá hạn | `late_delivery_seller` | `seller` / seller vi phạm | tổng freight |
| 4 | giao trễ và seller bàn giao đúng hạn | `late_delivery_logistics` | `logistics_provider` / `LOGISTICS_PROVIDER` | tổng freight |
| 5 | ≥2 payment row và khớp trong 0.10 BRL | `valid_split_payment` | không có | 0 |
| 6 | còn lại | `unsupported_late_claim` | không có | 0 |

Thứ tự quan trọng: một đơn vừa bị hủy vừa giao trễ phải ra `canceled_order_paid`, không phải nhánh
late. Một đơn giao trễ mà có 2 payment row khớp vẫn phải ra nhánh late, không phải
`valid_split_payment`.

## 6. Verifier — lớp chặn cuối

Verifier là thành phần thuần deterministic, chịu trách nhiệm cho phần điểm dễ mất nhất:

1. **Dựng ID từ facts, không nhận ID từ LLM.** `item_ids` và `payment_ids` dạng `<order_id>:<n>`
   (không prefix); `evidence_ids` có prefix `order:` / `item:` / `payment:` / `seller:` / `policy:`.
2. **Lọc false positive.** Mọi evidence ID không truy được về `OrderFacts` bị loại bỏ.
3. **Cắt theo giới hạn đề bài** — entity ≤ 5, evidence ≤ 10, root cause ≤ 3, party ≤ 3, action ≤ 5.
4. **Kiểm tra nhất quán** — `case_status = action_required` khi và chỉ khi refund > 0;
   `confidence` clamp về `[0, 1]`; mọi trường tiền `round(x, 2)`.
5. **Validate schema** bằng pydantic trước khi cho ghi ra file.

Ngoài ra `main.py` bọc từng case trong `try/except`: case nào lỗi vẫn được ghi một output fallback
hợp lệ schema, vì thiếu file output là hard gate 0 điểm.

## 7. Các bất thường của dữ liệu đã xử lý

Khảo sát trên bộ CSV thật (99.441 order) trước khi code:

- **775 order không có item row** — không chỉ status `unavailable` (603) mà cả `canceled` (164),
  `created` (5), `invoiced` (2) và 1 order `shipped`. Với các order này `item_ids`, `seller_ids` để
  rỗng và `item_total_brl`, `freight_total_brl` = `0.0` theo đúng README mục 6.
- **1 order không có payment row nào** (`bfbd0f9b...`, status `delivered`) — `payment_total = 0.0`,
  không rơi vào rule 1/2 vì các rule đó đòi payment > 0, và rơi về nhánh mặc định thay vì crash.
- **`payment_sequential` trong CSV không theo thứ tự tăng dần** — data layer sort lại lúc warmup, nên
  mọi `payment_ids` đều dựng từ `OrderFacts.payments` chứ không đọc lại CSV.
- **Timestamp rỗng** ở `order_approved_at`, `order_delivered_carrier_date`,
  `order_delivered_customer_date` được chuyển `NaN` → `None`, tránh `nan` lọt vào JSON output.

## 8. Trace và khả năng tái hiện

`logging/trace.jsonl` ghi lại lượt chạy mới nhất (reset ở đầu mỗi run, không append chồng). Mỗi dòng
là một JSON event: `case_received`, `facts_loaded`, `plan`, `llm_call`, `guard`, `handoff_to_policy`,
`case_done`, kèm `agreement`, `latency_ms` và lỗi nếu có.

Trace cho phép trả lời được: agent nào đã chạy, LLM nói gì, guard có phải can thiệp không, và con số
cuối cùng đến từ đâu.

Tên model và tham số được khai báo trong `src/config.py` và đồng bộ sang `logging/metadata.json`.
API key chỉ nằm trong `.env` và không bao giờ được commit.
