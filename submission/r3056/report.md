# Báo cáo nhóm 3049

## 1. Số liệu luyện tập
- **F1 theo seed (`rule / cross_check / overall`):**
  - `seed 3056` *(đầy đủ P1 + P2 sau khi gộp `review_log.csv` của 5 thành viên, 19 lỗi nộp)*: **`1.0 / 0.5 / 0.8`** *(Truy vết F1: `tier_a 1.0 · tier_b 1.0 · notify 1.0`)*.
  - `seed 11` *(kiểm thử validator luật P1, 13 lỗi luật)*: **`1.0 / — / 0.8`**.
- **Số ứng viên trên lô sạch (`--no-faults`, 50 ảnh pool `calib`):** **`0` lỗi luật**, **`4` ứng viên đối chiếu** (`runs/clean/candidates.json`); **hàng đợi trên seed luyện tập (`3056`):** **`42` ứng viên trên `29` ảnh duy nhất** (`submission/r3056/candidates.json`), sau khi cả 5 thành viên mở ảnh xem trực tiếp thu được **`10 confirmed`** và **`19 rejected`** (`submission/r3056/review_log.csv`).
- **Ngưỡng đã chọn và cách chọn (không dùng `_private`):**
  - *Validator luật (`validator/validate.py`):*
    - `bbox_out_of_bounds`: dùng dung sai `BBOX_EDGE_EPS = 1e-3` để bỏ qua sai số làm tròn 6 chữ số thập phân ở mép `[0, 1]` mà vẫn bắt được box tràn mép nhỏ.
    - `duplicate_box`: kiểm tra hai box cùng lớp, thực sự chồng nhau (`ix > 0 and iy > 0`), chênh kích thước `w, h ≤ 1.0 px`, lệch tâm `≤ 3.5 px` (không dùng ngưỡng IoU thấp vì ảnh COCO có nhiều vật chồng lấp tự nhiên tới IoU ~0.66).
    - `thing_overlap`: giải mã mask PNG bằng `scripts/pngutil.py`, đếm số pixel thực của từng `segment_id = R + G·256 + B·65536` (bỏ nền `0`) và báo lỗi khi `area` khai báo lớn hơn số pixel đếm được.
    - Xác minh trên lô sạch `runs/clean` (50 ảnh): **0 báo giả**.
  - *Đối chiếu `detection ↔ panoptic` (`validator/crosscheck.py`):*
    - Bỏ qua các segment nền, `iscrowd = 1` và vật quá nhỏ (`MIN_AREA = 64 px`); ghép lớp qua **tên lớp** (`classes.txt` ↔ `panoptic.json["categories"]`); dùng **tỉ lệ pixel mask nằm trong box (`coverage`)** kết hợp IoU hộp bao:
      - `class_swap` / `category_swap`: khác lớp, `MATCH_IOU = 0.65`, `coverage ≥ 0.85` (và không có box cùng lớp nào phủ tốt).
      - `bbox_drift`: cùng lớp, `IoU ≥ 0.15`, `coverage < MAX_DRIFT_COVERAGE (0.85)` và không có box cùng lớp phủ `≥ 0.95`.
      - `instance_merge`: có ít nhất 2 box cùng lớp tách biệt (`IoU < 0.10`, phần giao `< 15%` diện tích box nhỏ hơn) cùng chứa `coverage ≥ 0.20` pixel của một segment.
      - `missing_box`: segment không có box nào đạt `IoU ≥ 0.15` hoặc `coverage ≥ 0.45`.
    - Cách chọn ngưỡng: thử trực tiếp trên lô sạch `runs/clean` (`--no-faults`, 50 ảnh) sao cho lượng nhiễu tự nhiên nhỏ (**4 ứng viên / 50 ảnh**, tương ứng 29 ảnh trên lô 250 ảnh — mỗi thành viên xem 5–6 ảnh) để cả nhóm mở ảnh kiểm hết trong thời gian cho phép mà không dựa vào `_private/`.

## 2. Vì sao báo hết ứng viên làm F1 giảm?
- Trên lô luyện tập `seed 3056`, hàng đợi đối chiếu có **42 ứng viên trên 29 ảnh duy nhất**. Khi cả 5 thành viên mở từng ảnh xem bằng `tools/visualizer.py` (`review_board.html`), chỉ có **10 ảnh là lỗi thật (`confirmed`)**, còn **19 ảnh (65,5% hàng đợi)** là **lệch tự nhiên của COCO (`rejected`)** — chủ yếu do nhiều vật đứng sát nhau, che khuất một phần hoặc ở vùng đông người (`crowd`) khiến mép box YOLO của vật lân cận cắt qua mask panoptic của vật bên cạnh (tương tự 4 ca lệch tự nhiên đo được trên lô sạch 50 ảnh).
- Công thức chấm điểm của lab phạt báo thừa (FP) nặng ngang bỏ sót (FN):
  $$\text{Precision} = \frac{TP}{TP + FP}, \quad \text{Recall} = \frac{TP}{TP + FN}, \quad F_1 = \frac{2 \cdot \text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$
- Nếu không xem ảnh mà nộp luôn cả **29 ảnh ứng viên** thay vì chỉ **10 ảnh `confirmed`**, nhóm sẽ tự cộng thêm ngay **19 báo giả (FP)** (chưa kể các cặp bất đồng lớp `class_swap` / `category_swap` nếu đoán bừa không mở ảnh sẽ ghi sai loại lỗi, vừa mất TP vừa tăng FP). Khi FP tăng mạnh mà TP không tăng tương ứng, **Precision tụt sâu** và kéo cả `cross_check F1` lẫn `overall F1` giảm rõ rệt (như thực nghiệm mẫu: chỉ kiểm luật đạt ~0,7, còn báo hết ứng viên không xem ảnh tụt xuống ~0,6).

## 3. Quyết định và lineage
- **Kết quả QC v1 (`seed 3056`):** **`19/250 = 7,6%`** ảnh/cảnh lỗi trong `errors.json`, gồm:
  - *9 lỗi luật:* `1 bbox_out_of_bounds` (`000000006954`), `1 duplicate_box` (`000000002299`), `2 guideline_mismatch` (`000000007977`, `000000014473`), `1 invalid_class` (`000000010977`), `1 scene_leak` (`scene_626`), `2 thing_overlap` (`000000001761`, `000000004134`), `1 wrong_hash` (`000000023937`).
  - *10 lỗi gán nhãn đã `confirmed` qua xem ảnh:* `1 class_swap` (`000000015497`), `2 category_swap` (`000000016451`, `000000018193`), `1 missing_box` (`000000001818`), `6 instance_merge` (`000000005001`, `000000008277`, `000000017115`, `000000017182`, `000000017627`, `000000017959`).
- **Quyết định theo ngưỡng Day 7 (2%):** Vì `7,6% > 2,0%`, lô v1 bị **`HOLD`** (không được phát hành cho training), ghi sự kiện `decision = HOLD` vào `lineage.jsonl`. Nhóm không sửa trực tiếp trong `delivery/` v1 mà tách bản sửa sang lô mới **`v2`** (ghi `release --parent <release_id v1>`):
  - Tách **5 ảnh lỗi nhãn detection** (`000000006954`, `000000002299`, `000000010977`, `000000015497`, `000000001818`) khỏi v2 đưa vào `rework_queue.csv` giao đúng `annotator`/`reviewer` theo `jobs.csv`.
  - Sửa trực tiếp trong v2: kiểm tra ảnh `000000023937.jpg` còn nguyên vẹn (JPEG 640×428 RGB hợp lệ) nên giữ lại và cập nhật đúng SHA-256 trong `manifest.csv`; sửa `guideline_mismatch` theo `jobs.csv` và đưa toàn bộ cảnh `scene_626` về cùng một split trong `truyvet.csv`.
  - Giữ lại **10 ảnh chỉ lỗi panoptic** (`2 thing_overlap`, `2 category_swap`, `6 instance_merge`) trong v2 vì sản phẩm bàn giao v2 là bộ detection (nhãn YOLO của các ảnh này không bị sai), đồng thời liệt kê trong phần `Ghi chú` của `README.txt` để báo team panoptic.
- **Vì sao training run `R-021` phải xem lại hoặc train lại (`lineage.py impact` → `R-021: affected=True action=review_or_retrain`):**
  - Theo `lineage.jsonl`, run `R-021` đã được huấn luyện trực tiếp trên dữ liệu v1 mang 7,6% lỗi (nhãn sai lớp, thiếu box, box trùng/tràn khung làm sai lệch trọng số model; riêng `scene_leak` ở `scene_626` làm rò dữ liệu cùng cảnh giữa `train` và `val`, khiến điểm đánh giá bị lạc quan giả).
  - Việc đóng gói và phát hành dataset mới **v2 không tự động cập nhật hay sửa lỗi trong trọng số model `R-021` đã học từ v1**. Vì vậy bắt buộc phải rà soát đánh giá lại trên tập kiểm định sạch hoặc **train lại model từ đầu trên v2**.

## 4. Hash chứng minh gì, không chứng minh gì?
- **Hash (SHA-256) chứng minh được:**
  1. **Tính toàn vẹn ở mức byte (integrity):** từng file ảnh, nhãn YOLO, mask và gói đóng gói `.zip` của v2 khớp từng bit với thời điểm lập `manifest.csv` / `.sha256`, không bị hỏng khi truyền tải, mất dữ liệu hay bị chỉnh sửa lén sau khi chốt bàn giao.
  2. **Tính bất biến và định danh phiên bản (immutability):** mọi hành vi sửa đè lên lô v1 (`manifest.json`, `metadata.json`, `labels/`, `masks/`) sẽ làm đổi `release_id` hoặc sai lệch hash ngay lập tức (`check_handover.py` phát hiện ở H1, H7, H8, H15).
- **Hash KHÔNG chứng minh được:**
  1. **Tính đúng đắn ngữ nghĩa của nhãn:** một file nhãn có lỗi `class_swap`, `bbox_drift` hay `missing_box` vẫn tạo ra mã SHA-256 hoàn toàn khớp nếu mã băm được tính từ chính file nhãn sai đó.
  2. **Chất lượng dữ liệu đạt chuẩn QC:** vượt qua toàn bộ kiểm tra hash và định dạng (`check_handover.py` PASS) chỉ khẳng định tính nhất quán của gói bàn giao, không thay thế được việc đối chiếu đa nguồn và mắt người xem ảnh.

## 5. Truy vết
- **Tiêu chí tách tầng (`trace.json` — chạy bằng `tools/trace_query.py`):**
  - Đọc `incoming/ticket.md` (team AI báo bỏ sót `cup` bị che/mép ảnh ở `scene_150` và `scene_393`) và `guideline/changelog.md` (chuyển từ `v1.2` sang `v1.3` cho lớp `cup`, `class_id = 41` trong `classes.txt`).
  - **`tier_a` (4 ảnh):** ảnh thuộc cảnh team AI nêu (`scene_150`, `scene_393`), thuộc job theo guideline cũ (`v1.2`), và có ít nhất 1 box detection lớp `cup` trong `labels/*.txt`: `000000002592`, `000000002685`, `000000003845`, `000000003934`.
  - **`tier_b` (3 ảnh):** các ảnh khác trong lô cùng thuộc job guideline cũ (`v1.2`) và có box detection lớp `cup` nhưng nằm ngoài hai cảnh đã báo: `000000002157`, `000000002431`, `000000003661`.
  - **`notify` (2 người):** mã người gán (`A01`) và người kiểm (`Q02`) của job bị ảnh hưởng (`J02`) lấy từ `jobs.csv`.
- **Vì sao lấy phiên bản guideline theo `jobs.csv`, không lấy theo `metadata.json` của từng ảnh:**
  - `metadata.json` của từng ảnh có thể bị lỗi `guideline_mismatch` (ghi sai phiên bản so với job thực hiện). Trong seed `3056`, hai ảnh `000000007977` (thuộc `J04`, guideline job là `v1.3`) và `000000014473` (thuộc `J06`, guideline job là `v1.3`) đều bị ghi nhầm `guideline_version = v1.2` trong `metadata.json`. Nếu lọc theo metadata ảnh, các ảnh lỗi `guideline_mismatch` (nếu có lớp bị đổi) sẽ bị truy vết nhầm sang `tier_a`/`tier_b`, hoặc ngược lại bỏ sót ảnh thuộc job `v1.2` bị ghi nhầm thành `v1.3`.
- **Tự kiểm tra:** `score_findings.py --run runs/r3056` đạt `Truy vết F1 ≈ tier_a 1.0 · tier_b 1.0 · notify 1.0`.

## 6. Bug hoặc điểm chưa rõ trong lab (nếu có)
- **Lưu ý môi trường Windows:** Máy Windows không có launcher `py` mà dùng trực tiếp `python` (Python 3.10.11); cần thêm cờ `-X utf8` khi chạy script để hiển thị chuẩn tiếng Việt trong PowerShell và luôn tính SHA-256 trên chế độ đọc bytes (`rb` / `read_bytes()`).
