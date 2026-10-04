# VisionGuard — Nhận diện người khả nghi trên camera laptop

Chạy toàn bộ pipeline trên laptop (CPU/GPU), không cần thiết bị edge:

```
Webcam laptop ─► YOLOv8n-pose (người + keypoint mặt) ─► IoU tracker (ID cho từng người)
              ─► crop người + crop đầu/cổ ─► model thuộc tính (132 nhãn / 18 nhóm)
              ─► hậu xử lý (port 1:1 từ app C) ─► luật nguy hiểm (rules/rules.yaml)
              ─► Web dashboard (frontend/: realtime.html = webcam, upload.html = ảnh tải lên)
```

* **Luồng camera / YOLO** và **luồng thuộc tính** chạy riêng (giống app RB3): thuộc tính chậm cũng
  không làm giật video. Mỗi người được cập nhật thuộc tính ~1 s/lần, có làm mượt (EMA) theo track.
* Người được ưu tiên hiển thị: người **khả nghi** lớn nhất, nếu không có thì người lớn nhất.
* Khi một người lần đầu vi phạm luật → lưu ảnh + JSON vào `events/` và log `SUSPICIOUS`.

## Model thuộc tính

| Ưu tiên | Engine | Khi nào |
|---|---|---|
| 1 | `resnet18-onnx` — model đã train (`human_attr/model_68.onnx` + `model_68.onnx.json`) | Tự dùng nếu file tồn tại |
| 2 | `clip-zero-shot` — CLIP ViT-B/32, prompt cho đủ 132 nhãn | Mặc định khi chưa có ONNX (tự tải ~600 MB lần đầu) |

> Repo hiện **chỉ có bản `.bin` QNN** của ResNet18 (chỉ chạy được trên NPU Qualcomm), nên mặc định
> dùng CLIP. Có file `model_68.onnx` gốc thì chép vào `human_attr/` để có độ chính xác của model đã train.

## Luật nhận dạng (v3) — [rules/rules.yaml](rules/rules.yaml)

29 luật + 1 cảnh báo cảnh. Nhóm: hung khí (R01–R02, R18–R19), che kín mặt (R03–R09), trang phục / hành lý (R10–R12),
điểm che mặt tổng hợp (R13), hành vi (R14–R17: nhóm che mặt, lảng vảng, né camera…).

| Cải tiến | Cách làm |
|---|---|
| **Rộng hơn** | Điều kiện theo **nhóm nhãn** (`MASK`, `HEADCOVER`, `SCARF`, `WEAPON`…) với `all / any / none` thay vì liệt kê từng tổ hợp |
| Tín hiệu mới | `hoodUp`, `faceCovered`, `fullFaceHelmet` (CLIP so sánh có/không trên crop đầu); `weaponKnife/Bat/Scissors` + balo/túi/vali/ô do **YOLO COCO phát hiện thật** quanh người |
| Ngữ cảnh | `loitering` (ở trong khung > 45 s), `avoidingCamera` (quay lưng ≥ 70%), `groupConcealed` (≥ 2 người che mặt), `faceConcealedHigh` (điểm che mặt có trọng số ≥ 0.7) |
| **Hành vi (v3)** — [backend/behavior.py](backend/behavior.py) | Đo từ keypoint pose + lịch sử track (~12 khung/s): `handsCoveringFace` (tay che mặt, có CLIP dự phòng khi cổ tay ngoài khung), `lookingAround` (quay đầu trái↔phải ≥ 3 lần / 6 s), `hidingFaceDown` (cúi gằm mặt), `armsRaised` (giơ/vung tay), `running` (≥ 1.5 thân/s), `fastApproach` (box to ×1.8 trong 1.5 s), `pacing` (đi tới lui ≥ 3 lần / 20 s), `edgeLurking` (nấp mép khung) |
| **Vật cầm tay (v3)** | Crop bàn tay theo cổ tay–khuỷu: `weaponGun` (CLIP, cạnh tranh với điện thoại / cốc / tay không để giảm nhầm, cần xác nhận 2 lần), dao (gộp với YOLO), `wearingGloves` |
| **Cảnh (v3)** | `cameraOcclusion`: khung hình tối / đồng màu ≥ 2 s → cảnh báo CAO "Camera bị che", lưu ảnh sự kiện |
| **Khẩu trang / kính râm chính xác hơn (v3)** | Kiểm tra lại trên crop mặt sát (trán → cằm, không lấy cổ áo). Ảnh webcam thật: mặt không khẩu trang trước bị nhận 0.71–0.79 "khẩu trang vải", nay `maskNone` 0.78; có khẩu trang 0.98 |
| **Chính xác hơn** | `min_conf` cho từng luật; luật phải lặp lại `min_hits` lần (~2 s) mới cảnh báo, tắt sau `release` lần trượt; mức rủi ro tính từ **điểm** = 1 − ∏(1 − severity × độ tin cậy) |
| Giảm báo nhầm | Bỏ luật cũ "khẩu trang + áo khoác" (rất phổ biến ở VN); `faceCovered` bị loại nếu model thuộc tính thấy rõ miệng/mũi; không chạy cue khi đầu quá nhỏ (< 48 px) |

Luật chạy 1 lần/giây cho **mọi** người đang thấy (kể cả người ở xa chưa đủ lớn để phân tích thuộc tính),
nên luật hành vi như chạy / lao tới vẫn hoạt động. Hành vi đơn lẻ (chỉ chống tay lên mặt, chỉ nhìn quanh,
chỉ chạy) **không** cảnh báo — luật luôn cần kết hợp với dấu hiệu che giấu / hung khí / lảng vảng.
Ngưỡng hành vi nằm ở mục `behavior:` trong YAML.

Sửa ngưỡng / thêm luật chỉ cần sửa YAML rồi khởi động lại server. `/api/rules` trả về bộ luật đang chạy.
Vẫn chạy được bộ luật CSV cũ: `--rules rules/dangerous_attributes_rules.csv`.

## Cài đặt

**Yêu cầu:** Python 3.10 – 3.13, webcam (laptop), ~2 GB dung lượng trống (PyTorch + model).
Chạy được trên CPU; có GPU NVIDIA + CUDA thì tự dùng GPU.

### 1. Clone repo

```bash
git clone https://github.com/BuiHoangViet/Secure_and_Safety_Tracking.git
cd Secure_and_Safety_Tracking
```

### 2. Tạo môi trường ảo (khuyến nghị)

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Cài thư viện

```bash
pip install --upgrade pip
pip install -r backend/requirements.txt
```

> Muốn bản PyTorch chỉ-CPU nhẹ hơn (máy không có GPU NVIDIA), cài trước:
> `pip install torch --index-url https://download.pytorch.org/whl/cpu` rồi mới chạy lệnh trên.

### 4. Model (tự tải ở lần chạy đầu)

| Model | Dung lượng | Nguồn |
|---|---|---|
| `models/yolov8n-pose.pt` — phát hiện người + keypoint | ~7 MB | Ultralytics (tự tải) |
| `models/yolov8n.pt` — hung khí / túi / vali (COCO) | ~6 MB | Ultralytics (tự tải) |
| `openai/clip-vit-base-patch32` — thuộc tính zero-shot | ~600 MB | Hugging Face (tự tải vào cache) |
| `human_attr/model_68.onnx` + `.json` — ResNet18 đã train (tuỳ chọn) | ~45 MB | Tự chép vào nếu có |

Lần chạy đầu cần Internet và mất vài phút để tải; các lần sau chạy offline.

## Chạy

### Webcam laptop (thời gian thực)

```bash
python backend/server.py
```

Đợi log `Open http://127.0.0.1:8080/realtime.html` (khoảng 20–40 s để nạp model), rồi mở
<http://127.0.0.1:8080/> → chọn **Nhận diện Thời gian thực**.

### Phân tích ảnh tải lên

Cùng server trên, chọn **Tải ảnh lên** (hoặc mở <http://127.0.0.1:8080/upload.html>), kéo thả ảnh vào khung.
Mỗi người trong ảnh được đánh giá riêng, luật áp dụng tức thời (không cần lặp `min_hits`).

### Ví dụ khác

```bash
# Webcam ngoài (USB) thay vì webcam tích hợp
python backend/server.py --camera 1

# Chạy thử bằng file video / ảnh thay webcam
python backend/server.py --source path/to/video.mp4

# Cho máy khác trong mạng LAN xem dashboard (http://<IP-laptop>:8080/)
python backend/server.py --host 0.0.0.0

# Máy yếu: tắt bớt kiểm tra phụ để nhanh hơn
python backend/server.py --objects "" --no-cues

# Dùng bộ luật CSV cũ (15 luật v1)
python backend/server.py --rules rules/dangerous_attributes_rules.csv
```

Dừng server: `Ctrl + C`. Ảnh + JSON người khả nghi được lưu ở `events/` (không đưa lên git).

### Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Dashboard báo "Camera bị che" / hình đen, FPS rất thấp | Webcam đang bị app khác dùng (Zoom, Teams, một server khác…) hoặc nắp che camera đang đóng — tắt app đó / mở nắp rồi chạy lại |
| `Cannot read camera 0` | Thử `--camera 1`; kiểm tra quyền Camera trong Windows Settings → Privacy & security → Camera |
| `address already in use` / port 8080 bận | `--port 8081` |
| Tải model lỗi / chậm | Kiểm tra Internet; có thể đặt `HF_HUB_OFFLINE=1` sau khi đã tải xong một lần |
| Thuộc tính cập nhật chậm | Bình thường trên CPU (~0.5 s / người); video vẫn mượt. Dùng `--objects "" --no-cues` để nhanh hơn |

Tuỳ chọn hay dùng:

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `--camera` | `0` | Index webcam |
| `--source` | – | Dùng file video/ảnh thay webcam (demo/test) |
| `--width/--height` | `1280x720` | Độ phân giải camera |
| `--attr-interval` | `1.0` | Giây giữa 2 lần cập nhật thuộc tính / người |
| `--rule-interval` | `1.0` | Giây giữa 2 lần đánh giá luật / người |
| `--web-dir` | `frontend/` | Thư mục frontend |
| `--rules` | `rules/rules.yaml` | File luật (YAML v2 hoặc CSV cũ) |
| `--objects` | `models/yolov8n.pt` | YOLO COCO phát hiện hung khí / túi; `""` để tắt (nhanh hơn) |
| `--no-cues` | – | Tắt kiểm tra mũ trùm / trùm kín mặt / mũ bảo hiểm kín mặt |
| `--host 0.0.0.0` | `127.0.0.1` | Cho máy khác trong LAN xem |

## API (giữ tương thích app C cũ)

| Endpoint | Nội dung |
|---|---|
| `/stream_cam1` | MJPEG có vẽ box + ID (xanh = bình thường, đỏ = khả nghi) |
| `/dets` | FPS, latency YOLO, danh sách người (`track_id`, bbox, `dangerous`) |
| `/api/person` | Người mục tiêu: `positive_attributes`, `attributes_by_head`, `danger.matched_rules` |
| `/api/tracks` | Như trên cho tất cả người đang thấy |
| `/api/events` | 50 sự kiện khả nghi gần nhất (ảnh ở `/events/<file>.jpg`) |
| `/api/rules` | Bộ luật đang chạy |
| `POST /api/analyze` | Upload 1 ảnh (`file`) → ảnh đã vẽ box + kết quả từng người (sắp theo rủi ro) |

## Cấu trúc

```
Secure_and_Safety_Tracking/
├── backend/
│   ├── server.py         # webcam, YOLO + tracker, worker thuộc tính, FastAPI, /api/analyze
│   ├── attributes.py     # 18 head / 132 nhãn, hậu xử lý, engine ONNX / CLIP, cue CLIP, YOLO COCO vật thể
│   ├── rules.py          # engine luật: nhóm nhãn, độ tin cậy, duy trì theo thời gian, điểm rủi ro
│   ├── behavior.py       # hành vi từ pose + tracking, phát hiện che camera
│   └── requirements.txt
├── frontend/
│   ├── select.html / index.html   # chọn chế độ
│   ├── realtime.html     # camera laptop trực tiếp
│   ├── upload.html       # phân tích ảnh tải lên
│   ├── app.js, style.css
│   ├── README.md         # bảng nối ID HTML ↔ nhãn backend
│   └── testcase.json ... # dữ liệu mẫu cho chế độ ?file=
├── rules/
│   ├── rules.yaml        # 29 luật + nhóm nhãn + trọng số che mặt + tham số ngữ cảnh / hành vi (mặc định)
│   ├── dangerous_attributes_rules.csv   # 15 luật v1 (vẫn dùng được qua --rules)
│   └── check_danger.py   # script CLI kiểm tra luật v1 trên 1 file JSON
├── models/               # yolov8n-pose.pt, yolov8n.pt
├── human_attr/           # (đặt model_68.onnx + .json ở đây nếu có)
└── events/               # ảnh + JSON người khả nghi (tự tạo khi chạy)
```

## Giới hạn

* CLIP zero-shot kém hơn model đã train, nhất là màu quần/giày và tuổi; các nhãn quan trọng cho luật
  (khẩu trang, kính râm, mũ, khăn) được đánh giá trên crop đầu/cổ từ keypoint nên ổn định hơn.
* Webcam thường chỉ thấy nửa trên → model gán `bodyUpperHalf` và tự bỏ nhãn quần/giày (giống app C).
* Loại mũ vẫn dễ nhầm (vd. tóc dày bị nhận `hatHelmet` ~0.48); luật có mũ bảo hiểm luôn cần thêm khẩu trang + kính râm nên ít ảnh hưởng.
* `weaponGun` chỉ dựa vào CLIP trên crop bàn tay — cần cổ tay nằm trong khung; YOLO COCO không có lớp súng.
* Mỗi lần phân tích thuộc tính đầy đủ ~500–650 ms trên CPU (video vẫn mượt vì chạy luồng riêng).
