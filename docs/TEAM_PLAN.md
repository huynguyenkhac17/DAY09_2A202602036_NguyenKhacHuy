# DAY09 — Kế hoạch thi đấu 3 tiếng (Team 5 người)

> Tài liệu này là **nguồn sự thật duy nhất** về contract giữa các module.
> Ai sửa contract phải báo trước, không tự đổi.

---

## 0. Điều gì THỰC SỰ được chấm

Đọc kỹ mục 8 của `README.md`. Điểm là **exact-match trên số và ID**, không phải chấm văn phong:

| Thành phần | Trọng số | Bản chất |
| --- | ---: | --- |
| Primary issue + confidence | 20% | 1 trong 6 nhãn — sai nhãn mất luôn 20% |
| Affected entities | 20% | so khớp chuỗi ID, sai format = mất điểm |
| Root cause + responsible parties | 15% | code cố định + party_id |
| Evidence IDs | 15% | ID không tồn tại trong CSV = **false positive** |
| Financial resolution | 20% | số tiền làm tròn 2 chữ số |
| Resolution actions | 10% | 1 trong 6 action string |

**Hệ quả kiến trúc quan trọng nhất:** model ≤10B **không** cộng tiền chính xác tới 2 chữ số thập
phân, và **không** chép lại nổi `order_id` 32 ký tự hex. Nếu để LLM tự tính/tự chép ID, nhóm mất
55% điểm (entities + evidence + financial) ngay lập tức.

→ **Quy tắc vàng: mọi con số và mọi ID do Python tính, LLM chỉ suy luận và ra quyết định.**

---

## 1. Kiến trúc chốt: Deterministic Tools + LLM Agents + Guard

Mỗi agent là một **LLM call thật** (Groq, `llama-3.1-8b-instant`) nhận facts đã được tool tính sẵn,
trả về JSON kết luận. Ngay sau đó có một **guard deterministic** đối chiếu kết luận của LLM với giá
trị Python tính được:

- Khớp → nhận kết luận của agent, ghi `trace.jsonl` với `agreement: true`.
- Lệch → **override bằng giá trị deterministic**, hạ `confidence` 0.05, ghi trace `agreement: false`.

Đây vừa là bảo hiểm điểm số, vừa đúng yêu cầu "phải có kiểm chứng giữa các agent" của đề (mục 7:
*không có điểm cho việc chỉ đặt tên nhiều agent nhưng toàn bộ xử lý nằm trong một prompt*).

### Sơ đồ handoff

```
                       input/EC_xxx.json
                              |
                    [ Coordinator Agent ]  <-- LLM: lập kế hoạch điều tra
                              |
              +---------------+---------------+
              |               |               |
   [Order & Seller Agent] [Delivery Agent] [Payment Agent]
        (LLM + tools)     (LLM + tools)   (LLM + tools)
              |               |               |
              +------> SellerFinding /  ------+
                       DeliveryFinding /
                       PaymentFinding
                              |
                     [ Policy Agent ]  <-- LLM áp EC_POLICY_V1
                              |
                       PolicyDecision
                              |
                     [ Verifier Agent ]  <-- deterministic + LLM cross-check
                              |
                     output/EC_xxx.json
```

Mọi agent **chỉ đọc** dữ liệu qua `data_store`, không agent nào tự mở CSV.

### Cây thư mục

```
src/
  contracts.py        # pydantic models — ĐÓNG BĂNG, không ai sửa sau T+15
  data_store.py       # load CSV 1 lần, index theo order_id
  llm.py              # Groq client + retry + trace hook
  trace.py            # ghi logging/trace.jsonl
  agents/
    coordinator.py
    order_seller.py
    delivery.py
    payment.py
    policy.py
    verifier.py
main.py               # chạy toàn bộ input/ -> output/
tests/
  test_rules.py       # test rule engine bằng case tự dựng
```

---

## 2. Contract đóng băng (T+15 phải xong, mọi người code theo cái này)

### `OrderFacts` — output của `data_store.get_order_facts(order_id)`

```python
{
  "order_id": str,
  "exists": bool,                      # False nếu order_id không có trong CSV
  "order_status": str,                 # delivered | canceled | unavailable | shipped | ...
  "customer_id": str,
  "purchase_ts": str | None,
  "approved_at": str | None,
  "delivered_carrier_date": str | None,
  "delivered_customer_date": str | None,
  "estimated_delivery_date": str | None,
  "items": [
    {"order_item_id": int, "product_id": str, "seller_id": str,
     "shipping_limit_date": str, "price": float, "freight_value": float}
  ],
  "payments": [
    {"payment_sequential": int, "payment_type": str,
     "payment_installments": int, "payment_value": float}
  ],
  "seller_ids": [str],                 # unique, giữ thứ tự xuất hiện
  "item_total_brl": float,             # round(sum(price), 2)
  "freight_total_brl": float,          # round(sum(freight_value), 2)
  "payment_total_brl": float           # round(sum(payment_value), 2)
}
```

### Finding của từng agent

```python
DeliveryFinding = {
  "is_late": bool,                     # delivered_customer_date > estimated_delivery_date
  "delivered_customer_date": str|None,
  "estimated_delivery_date": str|None,
  "delivered_carrier_date": str|None,
  "days_late": int|None,
  "reasoning": str                     # do LLM viết, chỉ để trace
}

SellerFinding = {
  "any_handoff_after_limit": bool,
  "late_seller_ids": [str],
  "per_item": [{"order_item_id": int, "seller_id": str,
                "shipping_limit_date": str, "handoff_after_limit": bool}],
  "reasoning": str
}

PaymentFinding = {
  "payment_row_count": int,
  "payment_total_brl": float,
  "expected_total_brl": float,         # item_total + freight_total
  "delta_brl": float,                  # round(abs(payment_total - expected), 2)
  "reconciled": bool,                  # delta <= 0.10
  "is_split": bool,                    # payment_row_count >= 2
  "reasoning": str
}

PolicyDecision = {
  "primary_issue": str,
  "case_status": "action_required" | "no_action",
  "root_cause_code": str,
  "responsible_parties": [{"party_type": str, "party_id": str}],
  "recommended_refund_brl": float,
  "resolution_actions": [str],
  "confidence": float
}
```

### Rule engine — **thứ tự ưu tiên tuyệt đối**, dừng ở match đầu tiên

```
1. order_status == "canceled"    và payment_total > 0
     -> canceled_order_paid | platform/OLIST_PLATFORM
        | refund = payment_total | issue_full_refund
        | ORDER_CANCELED_AFTER_PAYMENT | action_required

2. order_status == "unavailable" và payment_total > 0
     -> unavailable_order_paid | platform/OLIST_PLATFORM
        | refund = payment_total | issue_full_refund
        | ORDER_UNAVAILABLE_AFTER_PAYMENT | action_required

3. is_late == True và any_handoff_after_limit == True
     -> late_delivery_seller | seller/<seller_id vi phạm>
        | refund = freight_total | refund_freight
        | SELLER_HANDOFF_AFTER_LIMIT | action_required

4. is_late == True và any_handoff_after_limit == False
     -> late_delivery_logistics | logistics_provider/LOGISTICS_PROVIDER
        | refund = freight_total | refund_freight
        | CARRIER_DELIVERED_AFTER_ESTIMATE | action_required

5. is_split == True và reconciled == True
     -> valid_split_payment | không có responsible party
        | refund = 0.0 | explain_valid_split_payment
        | MULTIPLE_PAYMENTS_RECONCILED | no_action

6. is_late == False và reconciled == True
     -> unsupported_late_claim | không có responsible party
        | refund = 0.0 | reject_late_refund
        | DELIVERY_WITHIN_ESTIMATE | no_action
```

`confidence` mặc định theo nhánh: rule 1–2 = `0.95`, rule 3–4 = `0.92`, rule 5 = `0.90`,
rule 6 = `0.88`. Guard trừ `0.05` mỗi lần LLM bất đồng với deterministic.

---

## 3. BẪY ĐIỂM — đọc kỹ, đây là chỗ mất điểm nhiều nhất

1. **`item_ids` và `payment_ids` KHÔNG có prefix, `evidence_ids` thì CÓ.**
   - `affected_entities.item_ids` = `"<order_id>:1"`
   - `affected_entities.payment_ids` = `"<order_id>:1"`
   - `evidence_ids` = `"item:<order_id>:1"`, `"payment:<order_id>:1"`
   Nhầm chỗ này mất 20% (entities) hoặc 15% (evidence).

2. **`evidence` chỉ 5 dạng hợp lệ**: `order:`, `item:`, `seller:`, `payment:`, `policy:`.
   ID bịa ra = false positive. Verifier phải drop mọi ID không dựng được từ `OrderFacts`.

3. **Giới hạn số lượng**: entity set ≤ 5, evidence ≤ 10, root cause ≤ 3, responsible party ≤ 3,
   action ≤ 5. Order nhiều item phải cắt bớt, không được nộp 20 item_id.

4. **Order không có item row** → `item_ids` và `seller_ids` để `[]`, `item_total_brl` và
   `freight_total_brl` = `0.0` (không phải `null`).

5. **Làm tròn 2 chữ số** cho mọi trường tiền, kể cả `0.0`. Dùng `round(x, 2)` sau khi cộng, không
   round từng phần tử.

6. **`case_status` chỉ 2 giá trị**: `action_required` (có refund) / `no_action` (refund = 0).
   Phải luôn nhất quán với `recommended_refund_brl`.

7. **Đúng 50 file output**, tên khớp input `EC_001.json`..`EC_050.json`. Case lỗi vẫn phải ghi file
   (fallback), không được thiếu — thiếu file là hard gate 0 điểm.

8. **Zip chỉ chứa folder `output/`** — không source, không `.env`, không file audit.

---

## 4. Phân công — mỗi người sở hữu 1 module, tự viết test của mình

| # | Người | Module sở hữu | File | Bàn giao cho |
| --- | --- | --- | --- | --- |
| 1 | **Huy (lead)** | Contract + Coordinator + tích hợp + git/CI | `src/contracts.py`, `src/llm.py`, `src/agents/coordinator.py`, `main.py` | tất cả |
| 2 | **Hoang** | Data layer | `src/data_store.py` | 3, 4, 5 |
| 3 | **Lam** | Order & Seller Agent + Delivery Agent | `src/agents/order_seller.py`, `src/agents/delivery.py` | 5 |
| 4 | **Nam** | Payment Agent + tính tài chính | `src/agents/payment.py` | 5 |
| 5 | **Hieu** | Policy Agent + Verifier + trace | `src/agents/policy.py`, `src/agents/verifier.py`, `src/trace.py` | lead |

### Mô tả chi tiết

**Hoang — Data layer (`data_store.py`)**
Load 4 CSV cần dùng (`orders`, `order_items`, `order_payments`, `sellers`) **một lần duy nhất** vào
dict index theo `order_id`, không dùng `df[df.order_id == x]` trong vòng lặp (50 case × nhiều lần
join sẽ rất chậm). Trả về đúng `OrderFacts`. Xử lý `NaN` → `None`, ép `order_item_id` và
`payment_sequential` về `int`. Deliverable: hàm chạy được `get_order_facts()` trả về facts đúng cho
5 order_id lấy tay từ CSV, có test.

**Lam — Order & Seller + Delivery**
So sánh timeline. `is_late` = `delivered_customer_date > estimated_delivery_date` (so sánh chuỗi ISO
là đủ, đề nói không cần đổi timezone). `handoff_after_limit` = `delivered_carrier_date >
shipping_limit_date` của **từng item**, gom `seller_id` của item vi phạm. Cẩn thận `None`: order
canceled/unavailable không có `delivered_customer_date` → `is_late = False`. Mỗi agent là 1 LLM
call trả JSON, kèm guard Python đối chiếu.

**Nam — Payment Agent**
Tính `payment_total`, đối soát với `item_total + freight_total`, sai số `<= 0.10` là `reconciled`.
Đếm `payment_row_count` để xác định `is_split`. Đây là module quyết định rule 5 và rule 6 — sai
tolerance là mất case. Chú ý: `payment_value` là tiền của **từng payment row**, không phải từng
installment (README mục 2).

**Hieu — Policy + Verifier**
Implement rule engine theo đúng thứ tự mục 2. Verifier: build evidence ID từ `OrderFacts`, drop ID
lạ, cắt theo giới hạn số lượng, validate bằng pydantic, ép `confidence` vào `[0,1]`, kiểm tra
`case_status` nhất quán với refund. Viết `trace.py` ghi `logging/trace.jsonl` — mỗi dòng 1 JSON:
`{case_id, agent, input_summary, output, agreement, latency_ms, ts}`.

**Huy (lead)**
Dựng skeleton + contract trong 15 phút đầu để 4 người có cái mà code. Coordinator gọi tuần tự
3 agent điều tra → policy → verifier. `llm.py` bọc Groq: retry, timeout, ép JSON output, đo latency.
`main.py` duyệt `input/`, ghi `output/`, luôn ghi file fallback khi case lỗi. Giữ git sạch, merge PR,
chạy final run.

---

## 5. Timeline 3 tiếng (T+0 = lúc có input)

| Thời gian | Việc | Ai |
| --- | --- | --- |
| **T+0 → T+15** | Lead push skeleton + `contracts.py` + stub. Cả team clone, tạo `.env` với `GROQ_API_KEY`, `pip install -r requirements.txt`. **Contract đóng băng ở T+15.** | Lead dựng, cả team setup |
| **T+15 → T+65** | Build song song 5 module. Không ai chờ ai vì stub đã có. Commit nhỏ, push thường xuyên. | 5 người |
| **T+65 → T+85** | Integration #1: chạy 5 case đầu end-to-end. Fix lỗi interface. | Lead chủ trì |
| **T+85 → T+110** | Chạy full 50 case. **Audit thủ công 5 case** (mỗi người 1 case): mở CSV, kiểm tay từng con số và ID. | 5 người |
| **T+110 → T+135** | Fix bug từ audit. Song song: `architecture.md` (TV3), `metadata.json` (TV5), báo cáo cá nhân (mỗi người tự viết). | song song |
| **T+135 → T+160** | Final run sạch (xóa `output/` và `trace.jsonl` trước khi chạy), zip `output/`, commit + push toàn bộ source. | Lead |
| **T+160 → T+180** | Buffer + tập demo. Không sửa code trong khoảng này trừ khi có bug chặn. | cả team |

**Quy tắc chống vỡ trận:** T+110 là điểm không quay đầu. Sau mốc đó chỉ sửa bug, **không thêm
tính năng mới**. Thà nộp bản đơn giản chạy đúng 50 case còn hơn bản thông minh chạy được 30 case.

---

## 6. Rủi ro và cách chặn

| Rủi ro | Chặn thế nào |
| --- | --- |
| Groq rate limit khi 5 người cùng test | Mỗi người dùng key riêng (free tier). Khi dev chỉ chạy 3–5 case, `--limit 5`. Full run chỉ lead chạy. |
| LLM trả JSON hỏng | `llm.py` retry 3 lần + `json_repair` thủ công; hết retry thì dùng thẳng kết quả deterministic. |
| LLM bịa số/ID | Guard override — đã thiết kế sẵn ở mục 1. Không bao giờ lấy số từ LLM. |
| Case lỗi → thiếu file output | `main.py` bọc `try/except` mỗi case, lỗi thì ghi output fallback hợp lệ schema (`unsupported_late_claim`, refund 0). |
| Merge conflict | Mỗi người 1 file riêng, không ai sửa file người khác. Sửa contract phải qua lead. |
| Quên `.env` vào git | Tạo `.gitignore` ngay ở T+0: `.env`, `.venv/`, `__pycache__/`, `*.pyc`. Repo hiện **chưa có** `.gitignore`. |

---

## 7. Checklist trước khi nộp

- [ ] `output/` có **đúng 50** file `EC_001.json` → `EC_050.json`, không file lạ
- [ ] Mọi file parse được bằng `json.load`, pass pydantic schema
- [ ] Không có evidence ID nào ngoài 5 dạng hợp lệ
- [ ] Mọi trường tiền là `float` đã `round(x, 2)`
- [ ] `case_status` nhất quán với `recommended_refund_brl` ở cả 50 case
- [ ] `architecture.md` ở root, có sơ đồ + vai trò + quyền truy cập + luồng handoff
- [ ] **5 file** `individual_<5 số cuối MSSV>_<HoVaTen>.md` ở root — mỗi người 1 file, tự viết
- [ ] `logging/trace.jsonl` là trace của **lần chạy cuối cùng**, không append chồng
- [ ] `logging/metadata.json` ghi rõ: model (`llama-3.1-8b-instant`), param size (8B ≤ 10B),
      framework, runtime
- [ ] `.env` **không** được commit; tên model **có** trong source code
- [ ] Source code đã push lên repo **trước khi** nộp zip
- [ ] Zip chỉ chứa `output/`