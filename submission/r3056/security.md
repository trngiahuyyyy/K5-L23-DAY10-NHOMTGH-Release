# Bảo mật khi làm việc — Lô `lab250_647bff93997f` (seed 3056)

## 1. Ca USB: hết giờ, muốn chép lô về nhà làm tiếp

Tuyệt đối **không** chép dữ liệu lô `lab250_647bff93997f` (`runs/r3056/delivery/`) ra USB cá nhân, ổ cứng ngoài hay gửi qua email/chat cá nhân để mang về nhà làm tiếp. Việc chép ra USB làm mất kiểm soát bản sao, dễ thất lạc thiết bị vật lý và có nguy cơ lây nhiễm mã độc vào máy trạm công ty; gửi qua email cá nhân đẩy dữ liệu ra khỏi hạ tầng bảo mật của tổ chức; còn nhờ người khác làm hộ là vi phạm trực tiếp NDA, phân quyền truy cập và làm sai lệch nhật ký trách nhiệm (`jobs.csv`, `A01`–`A05`, `Q01`–`Q03`).

**Cách xử lý đúng:** Dừng công việc khi hết giờ, bàn giao trạng thái hiện tại trên hệ thống quản lý phiên bản nội bộ của công ty, hoặc nếu cần làm thêm giờ từ xa thì phải xin cấp quyền truy cập VPN/VDI chính thức để làm việc trực tiếp trên máy trạm/máy chủ công ty mà không tải file gốc về máy cá nhân. Nếu bắt gặp USB lạ trên máy trạm, phải rút/cô lập không mở file và báo ngay cho bộ phận IT/an ninh thông tin.

## 2. Năm việc: được hay không

1. **Mở job được giao trên máy công ty:** **ĐƯỢC** — đây là thao tác đúng quy trình trong phạm vi công việc (ví dụ các thành viên chỉ mở đúng các job `J01`–`J10` được phân công trên môi trường kiểm soát của công ty).
2. **Chụp màn hình gửi người quen:** **KHÔNG ĐƯỢC** — dù chỉ là ảnh chụp màn hình vẫn làm rò rỉ dữ liệu hình ảnh, thông tin nhãn và giao diện dự án ra ngoài phạm vi cho phép.
3. **Chép lô ra USB:** **KHÔNG ĐƯỢC** — tạo bản sao ngoài tầm kiểm soát, mất khả năng kiểm toán (`manifest.json`, SHA-256) và tiềm ẩn rủi ro lộ lọt dữ liệu hàng loạt hoặc lây nhiễm malware.
4. **Dán nhãn thật lên chatbot:** **KHÔNG ĐƯỢC** — với dữ liệu thật của dự án (ngoài bộ COCO công khai trong lab), việc dán ảnh, nhãn, ticket hay metadata lên các dịch vụ AI công cộng bên ngoài khiến dữ liệu có thể bị lưu trữ hoặc dùng huấn luyện lại bên thứ ba, vi phạm bảo mật khách hàng.
5. **Đưa tài khoản CVAT cho đồng nghiệp:** **KHÔNG ĐƯỢC** — vi phạm nguyên tắc định danh cá nhân; khi xảy ra sai sót nhãn sẽ không truy vết được người chịu trách nhiệm thực sự giữa annotator (`A01`–`A05`) và reviewer (`Q01`–`Q03`), phá vỡ tính minh bạch của `jobs.csv` và `truyvet.csv`.

## 3. Ca khuôn mặt: thấy mặt người rõ trong lô, guideline yêu cầu làm mờ

**Kết luận: Hold + báo người phụ trách.**

Khi rà soát lô `lab250_647bff93997f` (seed 3056), phát hiện nhiều ảnh chụp cận cảnh nhìn rất rõ khuôn mặt người thật kèm dữ liệu nhận diện trực tiếp, tiêu biểu như:
- `000000020992` (job `J09`, `scene_594`, split `train`, annotator `A05`, reviewer `Q01`): ảnh chân dung cận mặt người phụ nữ đang ăn bánh mì kẹp.
- `000000004395` (job `J02`, `scene_150`, split `val`, annotator `A01`, reviewer `Q02`): ảnh cận mặt nam thanh niên mặc sơ mi thắt cà vạt.
- `000000001296` (job `J01`, `scene_179`, split `train`, annotator `A05`, reviewer `Q02`): ảnh chân dung cận mặt người phụ nữ cầm điện thoại.

**Quy trình xử lý và lý do:** Chuyển trạng thái lô sang **Hold** (không phát hành/không đưa đi train) và **báo ngay cho người phụ trách** (Lead dự án / Data Governance / DPO) để xử lý tiền kiểm danh tính theo quy trình chuẩn. Tuyệt đối **không tự ý dùng công cụ ngoài làm mờ hay tự xóa ảnh khỏi lô** vì:
1. Tự ý sửa pixel ảnh sẽ làm thay đổi hash SHA-256 so với `manifest.json` và phá vỡ tính toàn vẹn của bản giao nhận v1 (vi phạm nguyên tắc không ghi đè).
2. Tự xóa ảnh làm sai lệch số lượng mẫu, phá vỡ cấu trúc cảnh (`scene_id` 5 ảnh/cảnh) và đồng bộ giữa detection (`labels/`) với panoptic (`masks/`).
3. Làm mờ thủ công không đúng pipeline chuẩn (blur/pixelate không đồng nhất) có thể tạo nhiễu phân phối ảnh và ảnh hưởng trực tiếp tới chất lượng model AI khi huấn luyện.
