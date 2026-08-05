# Báo cáo cá nhân — Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyen Duy Lam |
| Mã học viên | 01073 (5 số cuối) |
| Khóa/Lớp | K3 |
| Vai trò chính | TV3 — Order & Seller Agent, Delivery Agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Order & Seller Agent | `src/agents/order_seller.py` — `analyze()` | `case_id`, `OrderFacts` | `SellerFinding` cho Coordinator/Policy Agent | Hoàn thành |
| Delivery Agent | `src/agents/delivery.py` — `analyze()` | `case_id`, `OrderFacts` | `DeliveryFinding` cho Coordinator/Policy Agent | Hoàn thành |
| Kiểm thử TV3 | `tests/test_delivery_seller.py` | Các `OrderFacts` được dựng độc lập | 10 test cho hai agent | Hoàn thành, 10/10 test pass |
| Tài liệu kiến trúc | `architecture.md` | Contract, kế hoạch nhóm và luồng tích hợp | Sơ đồ agent, quyền truy cập, contract và handoff | Hoàn thành |

Tôi chỉ nhận ownership cho hai agent TV3, bộ test tương ứng và tài liệu kiến trúc theo phân công. Tôi không nhận ownership cho Data Store, Payment Agent, Policy Agent hoặc Verifier Agent.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Viết tài liệu kiến trúc hệ thống | Toàn nhóm và lead tích hợp | Hoàn thiện `architecture.md` với sơ đồ 6 agent, quyền đọc dữ liệu, contract, rule engine, verifier và trace |
| Chuẩn hóa handoff | Coordinator và Policy Agent | Hai hàm `analyze()` trả đúng model Pydantic `SellerFinding` và `DeliveryFinding` đã đóng băng trong `src/contracts.py` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Phân tích thời gian giao hàng | `src/agents/delivery.py` — `analyze()` | Xác định `is_late`, giữ ba mốc thời gian và tính `days_late` | `test_delivery_within_estimate`, `test_delivery_exactly_on_estimate_is_not_late` và các test giao trễ |
| Xác định seller bàn giao quá hạn | `src/agents/order_seller.py` — `analyze()` | Tạo `per_item`, `any_handoff_after_limit` và danh sách `late_seller_ids` không trùng, giữ thứ tự | Các test seller/logistics và multi-item trong `tests/test_delivery_seller.py` |
| Bổ sung LLM call, guard và fallback | Hai file agent TV3 | LLM chỉ cung cấp reasoning; kết luận boolean luôn được Python kiểm chứng | Chạy test khi `GROQ_API_KEY` rỗng để xác minh nhánh deterministic-only |
| Kiểm thử trường hợp biên | `tests/test_delivery_seller.py` | Bao phủ timestamp thiếu, đơn hủy, order không có item, item thiếu hạn bàn giao và nhiều seller | `10 passed in 0.27s` |
| Mô tả kiến trúc toàn hệ thống | `architecture.md` | Tài liệu về agent, quyền truy cập, handoff, rule engine, verifier và trace | Kiểm tra nội dung file và commit TV3 |

Artifact cụ thể của phần việc là commit `71d5cd1` trên branch `TV3`, đã được đẩy lên `origin/TV3`. So với `main`, commit này bổ sung hoặc hoàn thiện đúng 4 file với tổng cộng 811 dòng: hai agent TV3, bộ test và `architecture.md`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Hai agent TV3 phải trả lời hai câu hỏi độc lập nhưng liên quan trực tiếp đến việc xác định trách nhiệm giao hàng:

1. Đơn có được giao cho khách sau ngày dự kiến hay không?
2. Nếu đơn giao trễ, seller có bàn giao hàng cho đơn vị vận chuyển sau `shipping_limit_date` của bất kỳ item nào hay không?

Hai kết quả này giúp Policy Agent phân biệt `late_delivery_seller` với `late_delivery_logistics`. Vì điểm chấm yêu cầu ID và kết luận chính xác, LLM không được tự tạo timestamp, seller ID hoặc thay đổi kết quả so sánh do Python tính.

### Cách triển khai Delivery Agent

1. Nhận `OrderFacts`, chỉ đọc các timestamp đã được Data Store chuẩn hóa.
2. Tính `is_late` bằng phép so sánh nghiêm ngặt:

   ```python
   delivered_customer_date > estimated_delivery_date
   ```

   Nếu hai mốc bằng nhau thì đơn không trễ. Nếu thiếu một trong hai mốc thì kết quả an toàn là `False`.
3. Chỉ tính `days_late` khi `is_late=True`; hàm parse trả `None` nếu timestamp rỗng hoặc không hợp lệ.
4. Gọi LLM một lần bằng `call_json()` để nhận kết luận và reasoning.
5. Guard đối chiếu `is_late` của LLM với kết quả deterministic. Khi LLM không khả dụng hoặc bất đồng, agent giữ kết quả Python và tạo reasoning fallback.

### Cách triển khai Order & Seller Agent

1. Lấy `delivered_carrier_date` cấp order và duyệt toàn bộ `facts.items`.
2. Với từng item, tính:

   ```python
   handoff_after_limit = delivered_carrier_date > shipping_limit_date
   ```

   Chỉ so sánh khi cả hai mốc đều tồn tại.
3. Tạo một `ItemHandoff` cho mỗi item, kể cả item không vi phạm.
4. Gom `late_seller_ids` duy nhất nhưng vẫn giữ thứ tự xuất hiện; `any_handoff_after_limit=True` khi có ít nhất một item vi phạm.
5. Prompt LLM chỉ chứa tối đa 10 item để giới hạn kích thước, trong khi kết quả deterministic vẫn xử lý đầy đủ mọi item.
6. Guard chỉ sử dụng reasoning của LLM khi kết luận boolean đồng thuận với Python; nếu không thì dùng fallback deterministic và ghi trace.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `case_id: str` và `OrderFacts` từ `src/contracts.py` |
| Output Delivery | `DeliveryFinding`: `is_late`, ba timestamp, `days_late`, `reasoning` |
| Output Seller | `SellerFinding`: `any_handoff_after_limit`, `late_seller_ids`, `per_item`, `reasoning` |
| Module phụ thuộc | `src/contracts.py`, `src/llm.py`, `src/trace.py`; dữ liệu đến gián tiếp từ `src/data_store.py` |
| Module sử dụng output | `src/agents/coordinator.py` bàn giao hai finding cho Policy Agent, sau đó Verifier tạo `CaseOutput` |
| Điều kiện lỗi đã xử lý | Timestamp `None`/không parse được, order không có item, item thiếu `shipping_limit_date`, LLM không khả dụng, LLM trả boolean không hợp lệ hoặc bất đồng |

Hai agent không tự mở CSV và không tự sửa contract. Mọi giao tiếp giữa module dùng model Pydantic đã thống nhất trong nhóm.

### Cách xác minh

```powershell
$env:GROQ_API_KEY=''
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_seller.py -q
```

- **Kết quả mong đợi:** 10 test của TV3 đều pass ở chế độ deterministic-only.
- **Kết quả thực tế:** `10 passed in 0.27s`, tiến trình trả exit code `0`.
- **Artifact:** `tests/test_delivery_seller.py`; commit `71d5cd1` trên `TV3` và `origin/TV3`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Model nhỏ có thể so sánh sai timestamp, bịa ID hoặc trả JSON không ổn định, trong khi bài chấm exact-match.
- **Các phương án đã cân nhắc:** (1) để LLM tự phân tích và quyết định toàn bộ; (2) dùng Python hoàn toàn; (3) để Python tính kết quả deterministic, LLM viết reasoning và dùng guard đối chiếu.
- **Phương án đã chọn:** Phương án 3 — kiến trúc kết hợp deterministic + LLM + guard.
- **Lý do:** Cách này giữ được vai trò LLM agent thật và trace handoff theo yêu cầu bài, đồng thời bảo đảm kết luận quan trọng có thể tái hiện và không phụ thuộc vào độ ổn định của model hoặc API.
- **Bằng chứng quyết định phù hợp:** Hai agent vẫn trả đầy đủ finding khi không có `GROQ_API_KEY`; toàn bộ 10 test pass ở chế độ deterministic-only. Khi có kết quả LLM, `_guard()` ghi `agreement` và chỉ chấp nhận reasoning khi boolean đồng thuận.

## 6. Một blocker đã xử lý

- **Triệu chứng:** Order bị hủy hoặc chưa giao có thể có `delivered_customer_date=None`; item cũng có thể thiếu `shipping_limit_date`. So sánh trực tiếp các giá trị này với chuỗi timestamp có thể gây lỗi hoặc gán nhầm trách nhiệm.
- **Bước tái hiện:** Chạy các test dành cho dữ liệu thiếu:

  ```powershell
  $env:GROQ_API_KEY=''
  .\.venv\Scripts\python.exe -m pytest tests\test_delivery_seller.py -q -k "canceled_order_without_delivery_date or missing_estimated_date_is_not_late or item_without_shipping_limit_is_not_violation"
  ```

- **Nguyên nhân gốc:** Các timestamp trong `OrderFacts` có kiểu `Optional[str]`; dữ liệu Olist thực tế không bảo đảm mọi mốc luôn tồn tại.
- **Cách xử lý:** Dùng phép kiểm tra short-circuit trước khi so sánh. Delivery Agent chỉ kết luận trễ khi cả ngày giao và ngày dự kiến tồn tại; Order & Seller Agent chỉ kết luận vi phạm khi cả ngày carrier nhận hàng và hạn item tồn tại. `_parse_date()` trả `None` thay vì làm pipeline lỗi khi dữ liệu ngày hỏng.
- **Cách xác minh sau khi sửa:** `3 passed, 7 deselected in 0.05s`, exit code `0`.
- **Điều học được:** Với dữ liệu thực tế, thiếu timestamp là trạng thái nghiệp vụ cần được mô hình hóa rõ ràng, không chỉ là lỗi kỹ thuật. Guard và test trường hợp biên phải được thiết kế ngay tại ranh giới module.

## 7. Hiểu biết về luồng end-to-end

1. `main.py` đọc từng `input/EC_xxx.json`, validate thành `CaseInput` và gửi case cho Coordinator Agent.
2. Coordinator lấy `claimed_order_id` và gọi `data_store.get_order_facts()`. Data Store là thành phần duy nhất được đọc CSV; nó chuẩn hóa dữ liệu và tạo `OrderFacts` chứa item, payment, seller và các tổng tiền.
3. Coordinator gọi ba agent điều tra: Order & Seller, Delivery và Payment. Phần TV3 nhận cùng một `OrderFacts` rồi bàn giao `SellerFinding` và `DeliveryFinding`.
4. Payment Agent bàn giao `PaymentFinding`. Policy Agent nhận ba finding cùng facts và áp dụng `EC_POLICY_V1` theo thứ tự ưu tiên tuyệt đối.
5. Với phần giao hàng, `is_late=True` và `any_handoff_after_limit=True` dẫn đến `late_delivery_seller`; nếu `is_late=True` nhưng seller bàn giao đúng hạn thì dẫn đến `late_delivery_logistics`.
6. Verifier dựng và lọc entity/evidence ID từ facts, làm tròn tiền, kiểm tra giới hạn số lượng, tính nhất quán giữa refund và `case_status`, rồi validate `CaseOutput` bằng Pydantic.
7. `main.py` ghi kết quả vào `output/EC_xxx.json`. Trace ghi lại các bước deterministic, LLM call, guard, handoff và lỗi; nếu một case lỗi, pipeline vẫn phải tạo output fallback hợp lệ để không thiếu file.

Phần tôi trực tiếp triển khai nằm ở bước 3 và tài liệu hóa toàn bộ luồng. Tôi hiểu các bước còn lại để bảo đảm hai finding của TV3 đúng contract và có thể tích hợp, nhưng không nhận ownership cho implementation của các module đó.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi chỉ ghi kết quả kiểm thử đã được chạy và xác minh thực tế.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo chung hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyen Duy Lam

**Ngày xác nhận:** 2026-08-05
