# Dùng AI

| # | Ai dùng | Công cụ | Prompt (tóm tắt) | AI sai ở đâu | Nhóm kiểm lại thế nào |
|---|---|---|---|---|---|
| 1 | Trần Gia Huy | Antigravity | Hỗ trợ lên kế hoạch chia việc nhóm 5 người và viết validator Pha 1 (`validator/validate.py`) bắt đủ 9 lỗi luật chỉ dùng thư viện chuẩn + `pngutil.py`, mở cổng cho module đối chiếu Pha 2. | Bản nháp ban đầu kiểm tra `duplicate_box` chỉ theo độ lệch tâm và kích thước mà chưa kiểm tra điều kiện hai box phải giao nhau (có nguy cơ báo nhầm 2 vật rất nhỏ đứng sát cạnh nhau), và `check_rules` mới chỉ kiểm hash file ảnh chưa kiểm hash file nhãn/mask. | Đọc lại từng hàm kiểm tra, bổ sung điều kiện hai box chồng nhau (`ix > 0 and iy > 0`) và kiểm hash đầy đủ 3 loại file; chạy kiểm thử trên lô sạch `runs/clean` (0 lỗi luật) và 2 seed `runs/r3056`, `runs/r11` bằng `score_findings.py` (cả hai đạt lỗi luật F1 ≈ 1.0). |
