# Hướng Dẫn Nối Dữ Liệu Backend Sang Giao Diện Frontend (VisionGuard)

Tài liệu này hướng dẫn chi tiết cho lập trình viên Backend về **cách truyền dữ liệu từ chương trình AI/NPU sang từng thẻ HTML (UI Element) trên Frontend**.

> **Cập nhật:** frontend giờ được phục vụ bởi `backend/server.py` (camera laptop, không còn RB3).
> `app.js` đọc `/api/person` + `/dets` (realtime.html) và `POST /api/analyze` (upload.html); kết quả luật
> lấy từ backend (`rules/rules.yaml`). Bảng ánh xạ nhãn bên dưới vẫn đúng; phần luật 15 điều là bộ v1,
> chỉ còn dùng ở chế độ `?file=...`.

---

## 1. Cấu Trúc Tổng Thể Luồng Nối Dữ Liệu

```
[ Qualcomm RB3 NPU / Backend ]
   │
   ├─► 1. HTTP Stream (MJPEG) ──► <img id="video-feed-el">  (Hiển thị Video Realtime)
   │
   ├─► 2. API GET /dets ─────────► <span id="fps-val">       (Cập nhật FPS thực tế)
   │
   └─► 3. Attributes Output ────► app.js (Parser)
          (JSON Attribute/Label)        │
                                        ├─► #attr-gender, #attr-age (Thông tin chung)
                                        ├─► #attr-upper, #attr-lower (Trang phục)
                                        ├─► #accessories-list       (Phụ kiện phát hiện)
                                        └─► #risk-box, #alert-...   (Đánh giá rủi ro)
```

---

## 2. Chi Tiết Nối Từng Thẻ HTML (UI Element Binding)

Below is the exact mapping table connecting HTML element IDs to Backend JSON variables:

### 2.1. Khung Video & Camera Realtime
| Element ID HTML | Vị trí trên UI | Tên Biến / API Backend | Kiểu dữ liệu | Mô tả cách Backend nối vào Frontend |
| :--- | :--- | :--- | :--- | :--- |
| `video-feed-el` (`<img>`) | Màn hình xem camera | `http://<IP>:8080/stream_cam1` | `MJPEG Stream` | Thuộc tính `src` của thẻ `<img>` kết nối trực tiếp đến luồng MJPEG của `cam_yolo_web.c`. |
| `fps-val` (`<span>`) | Trên góc khung camera | `fps` trong `GET /dets` | `float` (ví dụ: `29.8`) | Frontend fetch `/dets` định kỳ và gán `document.getElementById('fps-val').textContent = j.fps.toFixed(1)`. |

---

### 2.2. Khối Thông Tin Nhân Dạng (General Information)
| Element ID HTML | Nhãn hiển thị | Biến Backend cần truyền (`label`) | Giá trị Backend hợp lệ | Kết quả hiển thị trên UI |
| :--- | :--- | :--- | :--- | :--- |
| `attr-gender` | Giới tính | `personalMale` <br> `personalFemale` | Confidence `prob >= 0.5` hoặc boolean `1` | `Nam` <br> `Nữ` |
| `attr-age` | Độ tuổi | `personalLess15`<br>`personalLess30`<br>`personalLess45`<br>`personalLess60`<br>`personalLarger60` | Confidence `prob >= 0.5` hoặc boolean `1` | `Dưới 15 tuổi`<br>`25-30`<br>`30-45`<br>`45-60`<br>`Trên 60 tuổi` |
| `attr-height` | Chiều cao ước tính | *(Tự động tính từ `gender` & `age`)* | - | Nếu `personalFemale` ➔ `~162cm`<br>Nếu `personalLess15` ➔ `~145cm`<br>Mặc định ➔ `~175cm` |

---

### 2.3. Khối Trang Phục (Clothing Attributes)
Frontend kết hợp **Kiểu dáng (`Style`) + Màu sắc (`Color`)** để tạo ra chuỗi mô tả trang phục:

#### A. Áo (`#attr-upper`)
*   **Thẻ HTML:** `<span id="attr-upper">`
*   **Biến Kiểu dáng (`upper_body_style`):** `upperBodyShortSleeve` (Ngắn tay), `upperBodyLongSleeve` (Dài tay), `upperBodyTshirt` (Áo thun), `upperBodyJacket` (Áo khoác), `upperBodySweater` (Áo hoodie/nỉ), `upperBodyCasual`, `upperBodyFormal`, `upperBodySuit`, `upperBodyLogo`, `upperBodyPlaid`, `upperBodyThinStripes`, `upperBodyThickStripes`.
*   **Biến Màu sắc (`upper_body_color`):** `upperBodyBlack`, `upperBodyGrey`, `upperBodyWhite`, `upperBodyBrown`, `upperBodyRed`, `upperBodyPink`, `upperBodyYellow`, `upperBodyOrange`, `upperBodyGreen`, `upperBodyBlue`, `upperBodyPurple`.
*   **Ví dụ nối:** Backend gửi `["upperBodyJacket", "upperBodyBlack"]` ➔ UI hiển thị: **`Áo khoác màu đen`**.

#### B. Quần (`#attr-lower`)
*   **Thẻ HTML:** `<span id="attr-lower">`
*   **Biến Kiểu dáng (`lower_body_style`):** `lowerBodyTrousers` (Quần dài), `lowerBodyJeans` (Quần jeans), `lowerBodyShorts` (Quần short), `lowerBodyCasual`, `lowerBodyFormal`, `lowerBodyShortSkirt`, `lowerBodyLongSkirt`, `lowerBodyCapri`, `lowerBodySuits`.
*   **Biến Màu sắc (`lower_body_color`):** `lowerBodyBlack`, `lowerBodyGrey`, `lowerBodyWhite`, `lowerBodyBrown`, `lowerBodyRed`, `lowerBodyBlue`, `lowerBodyGreen`, ...
*   **Ví dụ nối:** Backend gửi `["lowerBodyJeans", "lowerBodyBlue"]` ➔ UI hiển thị: **`Quần jean màu xanh đậm`**.

#### C. Giày (`#attr-footwear`)
*   **Thẻ HTML:** `<span id="attr-footwear">`
*   **Biến Kiểu dáng (`footwear_type`):** `footwearSneaker` (Giày thể thao), `footwearLeatherShoes` (Giày da), `footwearSandals` (Dép xăng-đan), `footwearBoots` (Ủng/Bốt), `footwearShoes`.
*   **Biến Màu sắc (`footwear_color`):** `footwearBlack`, `footwearWhite`, `footwearBrown`, ...
*   **Ví dụ nối:** Backend gửi `["footwearSneaker", "footwearWhite"]` ➔ UI hiển thị: **`Giày thể thao màu trắng`**.

---

### 2.4. Danh Sách Phụ Kiện & Vật Dụng (`#accessories-list`)

Khung `<div id="accessories-list">` và thẻ số lượng `<span id="accessories-count">` tự động sinh ra từng dòng phụ kiện khi Backend gửi các nhãn tương ứng:

| Nhóm Phụ Kiện | Biến Backend (`Label`) | Cách hiển thị dòng phụ kiện trên UI |
| :--- | :--- | :--- |
| **Mũ / Nón** | `hatCap` (Mũ lưỡi trai), `hatBeanie` (Mũ len), `hatHelmet` (Mũ bảo hiểm), `hatOthers` + các màu (`hatBlack`, `hatWhite`, ...) | **Mũ / Nón:** Mũ lưỡi trai (màu đen) |
| **Khẩu trang** | `maskSurgical` (Y tế), `maskClothN95` (N95 / Vải) | **Khẩu trang:** Khẩu trang y tế |
| **Kính mắt** | `glassesSunglasses` (Kính râm), `glassesEyeglasses` (Kính cận) | **Kính mắt:** Kính râm |
| **Phụ kiện cá nhân** | `accessoryMuffler` (Khăn quàng), `accessoryKerchief` (Khăn trùm), `accessoryHeadphone`, `accessoryHairBand` | **Phụ kiện:** Khăn quàng cổ |
| **Vật dụng mang theo** | `carryingBackpack` (Balo), `carryingSuitcase` (Vali), `carryingLuggageCase` (Hành lý), `carryingMessengerBag`, `carryingUmbrella`, `carryingPlasticBags` | **Vật dụng mang theo:** Balo |
| **Hung khí / Nghi vấn** | Chứa chuỗi `weapon`, `gun`, `knife` | **Hung khí / Vật nghi vấn:** Phát hiện vật nguy hiểm (knife) *(In màu đỏ)* |

---

## 3. Cơ Chế Kích Hoạt Cảnh Báo Nguy Hiểm (Danger Rules Execution)

Frontend kiểm tra danh sách nhãn Backend gửi về với bộ 15 Luật Cảnh Báo.
> ⚠️ **LƯU Ý QUAN TRỌNG DÀNH CHO BACKEND:**
> Một luật **CHỈ KÍCH HOẠT KHI BACKEND GỬI ĐỦ TẤT CẢ CÁC BIẾN** thuộc luật đó. Nếu thiếu dù chỉ 1 biến, luật sẽ **KHÔNG** kích hoạt (Hệ thống ở trạng thái An toàn).

### Danh Sách 15 Luật & Các Thẻ UI Kích Hoạt Tương Ứng:

| Rule ID | Tập biến Backend BẮT BUỘC PHẢI CÓ ĐỦ (`conditions`) | Chuỗi lý do hiển thị tại `#danger-signs-list` |
| :-: | :--- | :--- |
| **1** | `maskSurgical` + `glassesSunglasses` + `hatCap` | Che kín mặt hoàn toàn (Khẩu trang y tế + Kính râm + Mũ lưỡi trai) |
| **2** | `maskClothN95` + `glassesSunglasses` + `hatCap` | Che kín mặt hoàn toàn (Khẩu trang N95/vải + Kính râm + Mũ lưỡi trai) |
| **3** | `maskSurgical` + `glassesSunglasses` + `hatBeanie` | Che kín mặt (Khẩu trang y tế + Kính râm + Mũ len) |
| **4** | `maskClothN95` + `glassesSunglasses` + `hatBeanie` | Che kín mặt (Khẩu trang N95/vải + Kính râm + Mũ len) |
| **5** | `maskSurgical` + `glassesSunglasses` + `hatHelmet` | Đội mũ bảo hiểm kết hợp khẩu trang y tế và kính râm che diện mạo |
| **6** | `maskClothN95` + `glassesSunglasses` + `hatHelmet` | Đội mũ bảo hiểm kết hợp khẩu trang N95/vải và kính râm che diện mạo |
| **7** | `maskSurgical` + `accessoryMuffler` + `hatCap` | Che mặt bằng Khẩu trang y tế + Khăn quàng cổ + Mũ lưỡi trai |
| **8** | `maskClothN95` + `accessoryMuffler` + `hatCap` | Che mặt bằng Khẩu trang N95/vải + Khăn quàng cổ + Mũ lưỡi trai |
| **9** | `maskSurgical` + `accessoryKerchief` + `glassesSunglasses` | Khăn trùm đầu/cổ + Khẩu trang y tế + Kính râm |
| **10** | `maskClothN95` + `accessoryKerchief` + `glassesSunglasses` | Khăn trùm đầu/cổ + Khăn trùm/cổ + Kính râm |
| **11** | `maskSurgical` + `glassesSunglasses` + `upperBodyJacket` + `upperBodyBlack` | Trang phục đen ngụy trang (Áo khoác đen + Khẩu trang y tế + Kính râm) |
| **12** | `maskClothN95` + `glassesSunglasses` + `upperBodyJacket` + `upperBodyBlack` | Trang phục đen ngụy trang (Áo khoác đen + Khẩu trang N95/vải + Kính râm) |
| **13** | `maskSurgical` + `hatCap` + `carryingLuggageCase` | Mang hành lý/vali nguy vấn + Che mặt (Khẩu trang y tế + Mũ lưỡi trai) |
| **14** | `maskClothN95` + `hatCap` + `carryingSuitcase` | Mang vali nghi vấn + Che mặt (Khẩu trang N95/vải + Mũ lưỡi trai) |
| **15** | `glassesSunglasses` + `hatCap` + `accessoryMuffler` | Che phủ khuôn mặt không có khẩu trang (Kính râm + Mũ lưỡi trai + Khăn quàng cổ) |

### Tác động lên các thẻ UI khi thỏa mãn Luật (Danger State):
1. `<div id="alert-warning">`: Chuyển `display: flex` (Khung màu đỏ nhấp nháy trên cùng).
2. `<div id="alert-safe">`: Chuyển `display: none`.
3. `<span id="risk-level">`: Đổi text thành `CAO` hoặc `TRUNG BÌNH CAO`, class đổi thành `badge-red`.
4. `<div id="danger-signs-list">`: Sinh ra dòng chữ đỏ in đậm liệt kê chính xác luật bị vi phạm.
5. `<div id="target-box">`: Hiện khung HUD ngắm màu đỏ trên khung camera với chữ `DANGER DETECTED`.

---

## 4. Ví Dụ Payload JSON Thực Tế Cho Backend Truyền Vào

Để Frontend hiển thị đúng, Backend chỉ cần lưu output vào file `current_attributes.json` hoặc trả về qua API theo 1 trong các mẫu JSON dưới đây:

### Ví dụ 1: Đối tượng Bình thường (An toàn - Low Risk)
```json
{
  "positive_attributes": [
    { "head": "gender", "label": "personalMale", "prob": 0.98 },
    { "head": "age", "label": "personalLess30", "prob": 0.85 },
    { "head": "mask_type", "label": "maskNone", "prob": 0.99 },
    { "head": "glasses_type", "label": "glassesEyeglasses", "prob": 0.92 },
    { "head": "upper_body_style", "label": "upperBodyTshirt", "prob": 0.95 },
    { "head": "upper_body_color", "label": "upperBodyWhite", "prob": 0.91 },
    { "head": "lower_body_style", "label": "lowerBodyJeans", "prob": 0.88 },
    { "head": "lower_body_color", "label": "lowerBodyBlue", "prob": 0.90 },
    { "head": "footwear_type", "label": "footwearSneaker", "prob": 0.94 }
  ]
}
```

### Ví dụ 2: Đối tượng Nguy hiểm (Kích hoạt Rule 11: Áo khoác đen + Khẩu trang y tế + Kính râm)
```json
{
  "positive_attributes": [
    { "head": "gender", "label": "personalMale", "prob": 0.99 },
    { "head": "age", "label": "personalLess30", "prob": 0.75 },
    { "head": "mask_type", "label": "maskSurgical", "prob": 0.96 },
    { "head": "glasses_type", "label": "glassesSunglasses", "prob": 0.97 },
    { "head": "upper_body_style", "label": "upperBodyJacket", "prob": 0.94 },
    { "head": "upper_body_color", "label": "upperBodyBlack", "prob": 0.98 },
    { "head": "carrying", "label": "carryingBackpack", "prob": 0.89 }
  ]
}
```
*Kết quả trên Frontend:* Kích hoạt ngay **Rule 11**, bật Cảnh báo Đỏ, hiện khung ngắm HUD `DANGER DETECTED`, in dòng chữ đỏ `Trang phục đen ngụy trang (Áo khoác đen + Khẩu trang y tế + Kính râm)`.
