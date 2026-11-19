# Báo cáo nhóm <<XX>>

## 1. Số liệu luyện tập
- F1 theo seed (rule / cross_check / overall): <<seed: ... / ... / ...>>
- Số ứng viên trên lô sạch (`--no-faults`): <<...>>; hàng đợi trên seed luyện tập: <<... ảnh>>
- Ngưỡng đã chọn và cách chọn (không dùng `_private`): <<...>>

## 2. Vì sao báo hết ứng viên làm F1 giảm?
<<Trả lời bằng số của nhóm.>>

## 3. Quyết định và lineage
<<QC v1 a/b, kết luận, vì sao R-021 phải xem lại hoặc train lại.>>

## 4. Hash chứng minh gì, không chứng minh gì?
<<>>

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
<<>>
