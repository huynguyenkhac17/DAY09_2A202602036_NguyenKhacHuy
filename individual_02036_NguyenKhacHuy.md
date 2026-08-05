# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                                 |
| --------------- | ---------------------------------------- |
| Họ và tên       | Nguyễn Khắc Huy                          |
| MSSV            | 2A202602036                              |
| Khóa/Lớp        | K3                                       |
| Vai trò chính   | Team Lead — Contract & Orchestration     |
| Ngày hoàn thành | 2026-08-05                               |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | --------------- | ---------- |
| Contract giữa các agent | `src/contracts.py` | schema đề bài (README mục 4, 6) | 12 pydantic model + hằng số nghiệp vụ dùng chung | Hoàn thành |
| Cấu hình runtime | `src/config.py` | ràng buộc model ≤10B | `LLM_MODEL`, đường dẫn, `llm_enabled()` | Hoàn thành |
| Wrapper LLM | `src/llm.py` — `call_json()` | system/user prompt | dict JSON hoặc `None` khi hỏng | Hoàn thành |
| Trace | `src/trace.py` — `log_event()`, `reset_trace()` | event từ mọi agent | `logging/trace.jsonl` | Hoàn thành |
| Coordinator Agent | `src/agents/coordinator.py` — `investigate()` | `CaseInput` | `CaseOutput` đã verify | Hoàn thành |
| Entrypoint | `main.py` — `run()`, `fallback_output()` | `input/EC_*.json` | `output/EC_*.json` | Hoàn thành |
| Bộ input mẫu | `tests/make_sample_input.py` | 9 file CSV Olist | 12 case mẫu + `expected_labels.json` | Hoàn thành |
| Kiểm tra & đóng gói | `tests/make_submission.py` | `output/` | `output.zip` sau 6 lớp kiểm tra | Hoàn thành |
| Kế hoạch & phân công | `docs/TEAM_PLAN.md` | đề bài | contract đóng băng + timeline + bảng phân công | Hoàn thành |
| Tích hợp | merge 4 nhánh, chạy final | nhánh của 4 thành viên | `main` chạy được end-to-end | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Khảo sát dữ liệu trước khi chia việc | cả 4 thành viên | Tìm được order_id thật cho đủ 6 nhánh rule, dựng thành 12 case mẫu để mọi người test trước khi đề công bố input |
| Phát hiện và gỡ file trùng lặp khi merge | Data layer | `data_store.py` ở root (294 dòng, dùng `csv`/`Decimal`, `INPUT_DIR` trỏ sai `input/input`) trùng chức năng với `src/data_store.py` và không được import ở đâu — đã xoá ở commit `878f9b6` |
| Dọn rác trace lẫn vào commit | Payment | 45 dòng `EC_TEST_*` sinh ra khi chạy pytest bị commit vào `logging/trace.jsonl`; đã xoá vì README mục 8 yêu cầu trace phải là của lượt chạy 50 case mới nhất |
| Sửa pin dependency sai | cả nhóm | `requirements.txt` ghi `groq==0.33.0` trong khi bản thực sự chạy test là `1.6.0` — pin một version chưa từng chạy là mầm lỗi cho người clone sau |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| Đóng băng contract để 4 người code song song không chờ nhau | `src/contracts.py`, `docs/TEAM_PLAN.md` mục 2 | 4 nhánh merge vào `main` **không một conflict nào** | `git merge --no-ff` × 4, exit code 0 |
| Dựng bộ input mẫu trước khi đề công bố input | `tests/make_sample_input.py`, `tests/sample_input/` | 12 case phủ đủ 6 nhánh rule, có nhãn kỳ vọng | `python tests/make_sample_input.py` |
| Điều phối pipeline 6 agent | `src/agents/coordinator.py` | Chạy 50 case, 0 case dùng fallback | `python main.py` |
| Bảo đảm không thiếu file output | `main.py` — `fallback_output()` | Case lỗi vẫn ghi output hợp lệ schema | đọc `main.py:96-104` |
| Tích hợp toàn hệ thống | merge 4 nhánh | 63 test pass sau merge | `python -m pytest tests/ -q` |
| Kiểm chứng LLM chạy thật | `src/llm.py`, `logging/trace.jsonl` | trace ghi `llm_call` và `guard`, không còn `llm_skipped` | đếm event trong `trace.jsonl` |

Một output cụ thể mà phần việc của tôi tạo ra hoặc giúp xác minh:

Chạy `python main.py --input-dir tests/sample_input && python tests/score_sample.py` cho kết quả **12/12 khớp hoàn toàn, 0 vi phạm schema, 0 case dùng fallback trong 2.3s**. Bộ 12 case này do tôi trích từ CSV thật trước khi đề công bố input, nên nó là thứ duy nhất cho phép 4 thành viên kiểm chứng module của mình ngay trong lúc chờ input.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Hai vấn đề tách biệt.

Thứ nhất, **55% điểm của bài này là so khớp chính xác số tiền và ID** (affected entities 20% + evidence 15% + financial resolution 20%). Ràng buộc của đề là model ≤10B. Một model 8B không cộng tiền chính xác tới 2 chữ số thập phân và không sao chép lại nổi `order_id` dài 32 ký tự hex. Nếu để LLM tự tính hoặc tự chép ID thì nhóm mất hơn nửa số điểm ngay từ đầu.

Thứ hai, đề nói rõ ở mục 7: *"không có điểm cho việc chỉ đặt tên nhiều agent nhưng toàn bộ xử lý nằm trong một prompt duy nhất"*. Nên không thể né bằng cách bỏ hẳn LLM đi và viết thuần Python.

Hai yêu cầu này kéo ngược chiều nhau. Phần việc của tôi là thiết kế kiến trúc thoả cả hai.

### Cách triển khai

Tôi tách bạch hai vai trò và đặt một lớp kiểm chứng ở giữa:

- **Nguồn của sự thật là Python deterministic.** Mọi con số, mọi ID, mọi so sánh mốc thời gian đều do pandas tính, đi qua `OrderFacts`.
- **LLM suy luận và ra quyết định.** Mỗi agent gọi `call_json()` một lần thật, nhận facts đã tính sẵn, trả về JSON kết luận.
- **Guard đối chiếu.** Ngay sau mỗi LLM call, agent so kết luận của model với giá trị Python tính được. Khớp thì giữ phần `reasoning` của model và ghi trace `agreement: true`. Lệch thì lấy giá trị deterministic, trừ `confidence` 0.05, ghi `agreement: false`.

Kết quả là LLM đóng vai trò thật trong luồng và có kiểm chứng giữa các agent đúng như đề yêu cầu, nhưng không bao giờ làm hỏng con số.

Ba quyết định cụ thể trong phần code của tôi:

1. **`call_json()` trả `None` thay vì ném exception** khi thiếu key, hết retry hoặc parse hỏng. Mọi agent bắt buộc phải xử lý được `None`. Nhờ vậy Groq rate-limit hay mất mạng không làm sập cả lượt chạy 50 case.
2. **`_parse_json()` có ba tầng cứu**: parse thẳng, bóc khối ```json, rồi cắt từ `{` đầu tới `}` cuối. Model 8B thỉnh thoảng bọc JSON trong văn bản thừa dù đã bật `response_format={"type": "json_object"}`.
3. **`fallback_output()` trong `main.py`**: mỗi case bọc trong `try/except`, case nào lỗi vẫn ghi ra một output hợp lệ schema với refund 0. Thiếu file output là hard gate 0 điểm, nên thà nộp một case sai còn hơn thiếu một file.

Coordinator vẫn gọi LLM để lập kế hoạch điều tra, nhưng **cố tình chạy đủ cả 3 agent điều tra bất kể kế hoạch nói gì**. Nếu để model quyết định bỏ qua agent nào thì có nguy cơ mất bằng chứng, mà evidence chiếm 15% điểm.

### Input, output và contract

| Thành phần | Mô tả |
| ---------- | ----- |
| Input | `input/EC_xxx.json` → `CaseInput` (case_id, customer_request.claimed_order_id, policy_version) |
| Output | `output/EC_xxx.json` → `CaseOutput` (assessment, affected_entities, root_cause_analysis, evidence_ids, financial_resolution, resolution_actions) |
| Module phụ thuộc | `src/data_store.py` (facts), `src/agents/{order_seller,delivery,payment,policy,verifier}.py` |
| Module sử dụng output | `tests/score_sample.py`, `tests/make_submission.py` |
| Điều kiện lỗi cần xử lý | order_id không có trong CSV; JSON input hỏng; LLM trả về `None` hoặc JSON sai schema; Groq rate-limit; agent ném exception giữa chừng |

### Cách xác minh

```bash
python -m pytest tests/ -q
python main.py --input-dir tests/sample_input
python tests/score_sample.py
python main.py
python tests/make_submission.py
```

- **Kết quả mong đợi:** test pass hết; 12 case mẫu khớp nhãn kỳ vọng và không vi phạm schema; 50 case thật sinh đủ 50 file; script đóng gói chấp nhận và tạo zip.
- **Kết quả thực tế:** 63 test pass. 12/12 khớp hoàn toàn, 0 vi phạm schema, 0 case dùng fallback, 2.3s. Chạy 50 case thật với LLM bật, trace ghi `llm_call` và `guard` thay vì `llm_skipped`.
- **Artifact/log:** `logging/trace.jsonl` (lượt chạy 50 case mới nhất), `output/EC_001.json` … `EC_050.json`. Không chứa secret — `GROQ_API_KEY` chỉ nằm trong `.env`, đã có trong `.gitignore` và `git log --all -- .env` xác nhận chưa từng bị track.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Phải chọn ai là nguồn của các con số và ID trong output, khi model bị giới hạn ≤10B nhưng đề lại yêu cầu phải có multi-agent thật.

- **Các phương án đã cân nhắc:**
  1. **LLM thuần** — đưa toàn bộ dữ liệu order vào prompt, để model tự tính tiền và tự xuất ID. Đúng tinh thần "agentic" nhất, ít code nhất.
  2. **Python thuần** — bỏ hẳn LLM, viết rule engine deterministic, chỉ đặt tên các hàm là "agent". Chính xác 100% về số.
  3. **Lai: Python tính, LLM quyết định, guard đối chiếu** — phương án đã chọn.

- **Phương án đã chọn:** Phương án 3.

- **Lý do:** Phương án 1 hỏng ở phần chiếm 55% điểm; model 8B không đáng tin cho số học 2 chữ số thập phân và chuỗi hex 32 ký tự. Phương án 2 an toàn về số nhưng vi phạm thẳng mục 7 của đề — không có handoff và kiểm chứng thật giữa các agent thì không được tính điểm phần multi-agent. Phương án 3 giữ được độ chính xác của Python đồng thời có LLM call thật ở mọi agent, và bản thân cơ chế guard chính là "kiểm chứng giữa các agent" mà đề đòi hỏi. Chi phí phải trả là mỗi agent phải viết thêm một lớp so sánh, khoảng 20 dòng.

- **Bằng chứng quyết định phù hợp:** Trên 3 case thật chạy với LLM bật, trace ghi 12 lượt guard: **9 lượt LLM đồng thuận với deterministic, 3 lượt bất đồng** (1 ở `order_seller`, 1 ở `delivery`, 1 ở `policy`). Tức model 8B kết luận sai khoảng 25% số lượt. Nếu chọn phương án 1 thì 25% số kết luận đó đã đi thẳng vào file nộp. Ngoài ra ở bước kiểm chứng key, model trả `is_late` đúng cả hai case nhưng phần `reasoning` cho case giao đúng hạn lại viết *"Giao trễ trong thời gian hạn dự kiến"* — một câu tự mâu thuẫn, cho thấy không thể tin phần diễn giải của nó để suy ra nhãn.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Pipeline chạy 12 case mẫu cho kết quả `12/12 khop hoan toan | Vi pham schema: 0/12`, mọi test pass, nhìn qua tưởng đã xong. Nhưng đếm event trong `logging/trace.jsonl` thì ra `llm_skipped=60, llm_call=0`.

- **Lệnh hoặc bước tái hiện:**
  ```bash
  python main.py --input-dir tests/sample_input
  python -c "print(open('logging/trace.jsonl',encoding='utf-8').read().count('llm_skipped'))"
  ```

- **Nguyên nhân gốc:** Chưa có `GROQ_API_KEY`, nên `call_json()` trả `None` ngay và mọi agent im lặng rơi xuống nhánh deterministic. Đây chính là cơ chế chống-sập do tôi thiết kế ở mục 4 — nó hoạt động đúng ý đồ. Nhưng vì rule engine deterministic vốn đã đủ chính xác để đạt 12/12, **mọi thước đo thành công của tôi đều xanh trong khi thành phần multi-agent chưa hề chạy**. Lỗi thực sự nằm ở chỗ tôi đo "kết quả đúng" mà không đo "LLM có được gọi hay không" — degradation im lặng thì phải có tín hiệu quan sát được, nếu không nó biến thành điểm mù.

- **Cách xử lý:** Thêm dòng in trạng thái ở đầu mỗi lượt chạy (`main.py` in `LLM BAT` hoặc `LLM TAT (deterministic-only)`), và coi số lượng event `llm_call` trong trace là điều kiện nghiệm thu bắt buộc, ngang hàng với số case khớp nhãn.

- **Cách xác minh sau khi sửa:** Sau khi nạp key thật vào `.env`, chạy `python main.py --limit 3` cho `LLM BAT` và trace ghi `llm_call=15, guard=12, llm_skipped=0`. Trong 12 lượt guard có 3 lượt bất đồng — bằng chứng LLM đã thực sự tham gia chứ không phải chỉ được gọi cho có.

- **Điều học được:** Một cơ chế fallback tốt sẽ che mất chính sự cố mà nó đang xử lý. Khi thiết kế đường suy giảm (degraded path), phải phát ra tín hiệu quan sát được và đưa tín hiệu đó vào tiêu chí nghiệm thu, nếu không thì "tất cả đều xanh" chỉ có nghĩa là "đường dự phòng chạy tốt".

## 7. Hiểu biết về luồng end-to-end

> Ghi chú: năm câu hỏi trong mẫu báo cáo nhắc tới Crossref, vector index và freshness monitoring — đó là nội dung của một biến thể lab khác. Tôi trả lời bằng cách ánh xạ từng câu sang pipeline thực tế của bài Day 9 này.

**Câu trả lời:**

**1. Dữ liệu đi từ nguồn đến nơi các agent sử dụng như thế nào?**
Nguồn là 9 file CSV Olist trong `data/`. `src/data_store.py` là thành phần **duy nhất** được phép mở CSV; lúc `warmup()` nó nạp 4 bảng cần dùng (orders, order_items, order_payments, sellers) và gom sẵn thành dict index theo `order_id`, mất khoảng 2.0 giây. Sau đó mỗi lần `get_order_facts(order_id)` chỉ là tra dict, 50 lần gọi tốn khoảng 0.5 mili-giây tổng. Kết quả trả về là `OrderFacts` — đã join xong items/payments/sellers, đã đổi `NaN` thành `None`, đã sort `payment_sequential` (trong CSV nó không tăng dần), và đã tính sẵn ba con số tổng. Từ đó trở đi không agent nào chạm vào CSV nữa; tất cả chỉ đọc `OrderFacts`. Ràng buộc một-cửa này là thứ bảo đảm không agent nào có thể bịa ra thực thể không tồn tại.

**2. Bộ case mẫu và nhãn kỳ vọng dùng để đo chất lượng ra sao?**
Trước khi đề công bố input, tôi quét CSV tìm order_id thật thoả từng nhánh rule và dựng 12 case (2 case mỗi nhánh) vào `tests/sample_input/`, kèm `tests/expected_labels.json` chứa nhãn kỳ vọng do một bản rule engine tham chiếu **độc lập** tính ra. `tests/score_sample.py` so output với nhãn đó trên 7 trường: `primary_issue`, `root_cause_code`, `case_status` và 4 trường tiền. Cần nói rõ giới hạn: đây không phải ground truth của ban tổ chức. Lệch nhau chỉ có nghĩa "phải mở CSV kiểm tay", không có nghĩa "chắc chắn sai".

**3. Kiểm tra tính hợp lệ khác kiểm tra tính đúng đắn ở điểm nào trong bài lab này?**
Hai lớp khác nhau. `score_sample.py` trả lời *"kết luận có đúng không"* — nhãn và số tiền có khớp kỳ vọng không. `make_submission.py` và Verifier trả lời *"file có nộp được không"* — đủ 50 file, pass schema, evidence đúng 1 trong 5 định dạng, `case_status` nhất quán với refund, tiền tròn 2 chữ số. Một case có thể sai nhãn nhưng vẫn hợp lệ về hình thức, và ngược lại một case đúng nhãn vẫn có thể bị loại vì evidence sai định dạng. Vì hard gate của đề đánh vào lớp thứ hai, tôi để nó chặn ở hai chỗ độc lập: Verifier chặn trước khi ghi file, script đóng gói chặn trước khi tạo zip.

**4. Vì sao phải dùng cùng một bộ case cho mọi lần đo?**
Vì chỉ khi cố định bộ case thì thay đổi trong kết quả mới quy được về thay đổi trong code. Trong lúc 4 thành viên sửa module song song, nếu mỗi người tự chọn case để test thì không ai biết một sai lệch là do module vừa sửa hay do case khác nhau. 12 case mẫu là mốc chung cho cả nhóm, dùng lại y nguyên trước và sau mỗi lần merge.

**5. Việc tích hợp được xem là thành công dựa trên artifact và metric nào?**
Bốn điều kiện, phải đủ cả bốn: (a) `python -m pytest tests/ -q` pass toàn bộ — sau merge là 63 test; (b) `score_sample.py` báo 12/12 khớp và 0 vi phạm schema; (c) `logging/trace.jsonl` có event `llm_call` và `guard`, không phải `llm_skipped` — tức multi-agent chạy thật, đây là điều kiện tôi thêm vào sau khi vấp phải blocker ở mục 6; (d) `make_submission.py` chấp nhận `output/` và tạo được zip. Artifact tương ứng là `output/EC_001.json`…`EC_050.json`, `logging/trace.jsonl` và `output.zip`.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [ ] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [ ] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [ ] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [ ] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [ ] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Khắc Huy
**Ngày xác nhận:** 2026-08-05
