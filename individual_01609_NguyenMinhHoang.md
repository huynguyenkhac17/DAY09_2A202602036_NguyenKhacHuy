# Member Role Report — Day 9: Multi Agent A2A

> Báo cáo cá nhân của Nguyễn Minh Hoàng, MSSV 2A202601609.

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                   |
| --------------- | -------------------------- |
| Họ và tên       | Nguyễn Minh Hoàng          |
| MSSV            | 2A202601609                |
| Khóa/Lớp        | K3                         |
| Vai trò chính   | Data layer / Data Store    |
| Ngày hoàn thành | 2026-08-05                 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách            | Input nhận vào                        | Output bàn giao                     | Trạng thái      |
| ------------------ | ----------------------------- | ------------------------------------- | ----------------------------------- | --------------- |
| Data layer         | `data_store.py`               | `data/olist_*.csv`, `input/input/EC_*.json` | `OrderFacts`, `CaseInput`, `get_case_order_data()` | Hoàn thành      |
| Data contract      | `data_store.py`               | CSV và JSON raw                       | Schema deterministic cho agent      | Hoàn thành      |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                 | Thành viên/module được hỗ trợ | Kết quả                                 |
| ------------------------- | ----------------------------- | --------------------------------------- |
| Hỗ trợ debug contract     | TV3, TV4, TV5                 | Cung cấp facts ổn định, giảm lỗi interface |
| Kiểm tra đầu vào output   | Policy / Verifier             | Dữ liệu `item_total_brl`, `freight_total_brl`, `payment_total_brl` tính đúng |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao                                  | Cách xác minh                         |
| --------------------- | --------------------------- | ------------------------------------------------- | ------------------------------------- |
| Tạo data loader       | `data_store.py`             | Load CSV và JSON vào `OrderFacts`                 | `python data_store.py`                |
| Định nghĩa schema     | `data_store.py`             | `OrderFacts` trả về totals và entity IDs chính xác | Kiểm tra sample order bằng runtime    |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

- Artifact: `OrderFacts` deterministic từ `data_store.py`
- Kết quả: `item_total_brl`, `freight_total_brl`, `payment_total_brl` tính bằng Python, chỉ tiếp tục sang agent khi đã chắc chắn

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Phần của tôi đảm bảo toàn bộ hệ thống agent không tự truy xuất CSV, không tính sai số tiền và không bịa ID. `data_store.py` là nguồn dữ liệu duy nhất cho mọi agent.

### Cách triển khai

- Load toàn bộ file CSV cần thiết một lần khi khởi tạo.
- Index theo `order_id` để truy xuất nhanh cho 50 case.
- Parse datetime, parse decimal chính xác, round tổng tiền về 2 chữ số.
- Cung cấp `get_order_facts(order_id)` trả về cấu trúc dữ liệu chuẩn:
  - `items`, `payments`, `seller_ids`
  - `item_total_brl`, `freight_total_brl`, `payment_total_brl`
  - `order_status`, `estimated_delivery_date`, `delivered_carrier_date`
- Đảm bảo order không có item vẫn trả về schema hợp lệ.

### Input, output và contract

| Thành phần              | Mô tả                                                                 |
| ----------------------- | --------------------------------------------------------------------- |
| Input                   | `input/input/EC_*.json`, `data/olist_orders_dataset.csv`, `data/olist_order_items_dataset.csv`, `data/olist_order_payments_dataset.csv`, `data/olist_order_reviews_dataset.csv` |
| Output                  | `OrderFacts`, `CaseInput`, `get_case_order_data(case_id)`             |
| Module phụ thuộc        | Không có module khác phụ thuộc trực tiếp vào CSV trong layer này      |
| Module sử dụng output   | `src/agents/order_seller.py`, `src/agents/delivery.py`, `src/agents/payment.py`, `src/agents/policy.py` |
| Điều kiện lỗi cần xử lý | `order_id` không tồn tại, order không có item row, payment missing    |

### Cách xác minh

```bash
python data_store.py
```

- **Kết quả mong đợi:** Load thành công 50 case, in được sample facts cho case đầu tiên.
- **Kết quả thực tế:** Đang phát triển module, hiện đã tạo file và đảm bảo schema đầu vào cho agent.
- **Artifact/log:** `data_store.py` trong root repo.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần bảo đảm mọi số tiền và ID đến từ Python, không từ LLM.
- **Các phương án đã cân nhắc:**
  1. Để agent LLM tính tổng và xem xét values.
  2. Tính toàn bộ giá trị tiền và chuẩn hoá ID trong `data_store.py`.
- **Phương án đã chọn:** Tính tiền và chuẩn hoá dữ liệu hoàn toàn ở `data_store.py`.
- **Lý do:** Correctness của financial resolution là trọng yếu, LLM dễ bịa hoặc làm tròn sai. Data layer deterministic giải quyết ngay nỗi đau điểm số lớn nhất.
- **Bằng chứng quyết định phù hợp:** Số tiền `item_total_brl`, `freight_total_brl`, `payment_total_brl` sẽ được đưa trực tiếp vào các agent, giảm sai lệch output.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `order_item_id` và `payment_sequential` có thể được đọc là chuỗi từ CSV.
- **Lệnh hoặc bước tái hiện:** `python data_store.py` với sample order.
- **Nguyên nhân gốc:** CSV reader trả về giá trị chuỗi, agent cần ID số nguyên để format đúng `order:<order_id>`, `item:<order_id>:<order_item_id>`.
- **Cách xử lý:** Parse `order_item_id` và `payment_sequential` về `int` trong data layer.
- **Cách xác minh sau khi sửa:** Kiểm tra `OrderFacts.items[0].order_item_id` và `OrderFacts.payments[0].payment_sequential` trả về int.
- **Điều học được:** Data contract phải chuẩn hoá kiểu dữ liệu ngay từ lớp thấp nhất, không để lỗi kiểu lan tới agent.

## 7. Hiểu biết về luồng end-to-end

Giải thích ngắn gọn bằng lời của bạn:

1. Dữ liệu đi từ `input/EC_*.json` và CSV Olist vào `data_store.py`, nơi được parse và index theo `order_id`.
2. `OrderFacts` là ground truth cho agent; các agent dùng facts này để suy luận chính xác và không làm lại join.
3. Quality checks trong bài lab là kiểm tra định dạng ID, totals và evidence ID, khác với freshness monitoring ở chỗ đây là xác thực business rule và schema.
4. Cùng test set cho baseline/repaired giúp đảm bảo output so sánh được với rule deterministic và không lệ thuộc vào đầu vào từng lần.
5. Repair thành công khi `output/EC_*.json` thỏa schema, evidence ID hợp lệ, action đúng và financial totals khớp.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Minh Hoàng
**Ngày xác nhận:** 2026-08-05
