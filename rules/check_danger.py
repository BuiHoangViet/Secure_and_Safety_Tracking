import json
import sys
import os
import io

# Thiết lập UTF-8 cho terminal để không bị lỗi UnicodeEncodeError trên Windows
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def evaluate_danger(json_path, prob_threshold=0.5):
    # Kiểm tra file có tồn tại không
    if not os.path.exists(json_path):
        print(f"\033[91m[LỖI] Không tìm thấy file tại đường dẫn: {json_path}\033[0m")
        return
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"\033[91m[LỖI] Không thể đọc hoặc phân tích cú pháp JSON: {e}\033[0m")
        return

    # Lấy danh sách các thuộc tính dương tính (positive_attributes)
    positive_attrs = data.get("positive_attributes", [])
    active_labels = {}
    
    # Lọc các nhãn có độ tin cậy lớn hơn hoặc bằng ngưỡng
    for attr in positive_attrs:
        label = attr.get("label")
        prob = attr.get("prob", 0)
        if prob >= prob_threshold:
            active_labels[label] = prob

    # In thông tin cơ bản
    print(f"\n==================================================")
    print(f"📊 ĐANG PHÂN TÍCH ĐẶC ĐIỂM ĐỐI TƯỢNG")
    print(f"📁 File nguồn: {os.path.basename(json_path)}")
    print(f"🖼️ Ảnh phân tích: {data.get('image', 'Không có thông tin')}")
    print(f"⚙️ Ngưỡng độ tin cậy (Confidence threshold): {prob_threshold:.0%}")
    print(f"--------------------------------------------------")
    
    if not active_labels:
        print("⚠️ Không phát hiện đặc điểm nổi bật nào vượt ngưỡng.")
    else:
        print("🔍 Các đặc điểm nhận dạng nổi bật phát hiện được:")
        for label, prob in active_labels.items():
            print(f"  • {label:<25} -> Độ tin cậy: {prob:.2%}")
            
    # Áp dụng các quy tắc đánh giá rủi ro nguy hiểm (Dangerous Rules)
    is_dangerous = False
    reasons = []

    # 1. Kiểm tra khẩu trang
    has_mask = "maskClothN95" in active_labels or "maskSurgical" in active_labels

    # 2. Kiểm tra áo hoodie, áo khoác hoặc đội mũ trùm đầu
    has_hoodie = "upperBodySweater" in active_labels
    has_jacket = "upperBodyJacket" in active_labels
    has_hat = any(h in active_labels for h in ["hatCap", "hatBeanie", "hatOthers", "hatHelmet"])
    
    hoodie_jacket_hat_active = []
    if has_hoodie: hoodie_jacket_hat_active.append("Áo hoodie (Sweater)")
    if has_jacket: hoodie_jacket_hat_active.append("Áo khoác (Jacket)")
    if has_hat:
        active_hats = [h for h in ["hatCap", "hatBeanie", "hatOthers", "hatHelmet"] if h in active_labels]
        hoodie_jacket_hat_active.append(f"Mũ ({', '.join(active_hats)})")

    # Quy tắc 1: Che kín mặt (Khẩu trang) + Trùm đầu (Hoodie/Jacket/Hat)
    if has_mask and (has_hoodie or has_jacket or has_hat):
        is_dangerous = True
        mask_type = "N95/Vải" if "maskClothN95" in active_labels else "Y tế"
        reasons.append(
            f"Đối tượng đeo khẩu trang ({mask_type}) kết hợp trùm đầu hoặc đội mũ ({', '.join(hoodie_jacket_hat_active)})"
        )

    # Quy tắc 2: Phát hiện hung khí (Nếu có nhãn đặc thù trong tương lai)
    has_weapon = any(
        "weapon" in label.lower() or "gun" in label.lower() or "knife" in label.lower() 
        for label in active_labels
    )
    if has_weapon:
        is_dangerous = True
        weapons = [l for l in active_labels if "weapon" in l.lower() or "gun" in l.lower() or "knife" in l.lower()]
        reasons.append(f"Phát hiện vật nghi ngờ là hung khí: {', '.join(weapons)}")

    # In kết quả đánh giá nguy hiểm
    print(f"--------------------------------------------------")
    print(f"🚨 KẾT QUẢ ĐÁNH GIÁ RỦI RO:")
    if is_dangerous:
        # In chữ màu ĐỎ đậm trên terminal
        print("\033[1;31m[CẢNH BÁO] ĐỐI TƯỢNG CÓ NGUY CƠ NGUY HIỂM CAO!\033[0m")
        print("Chi tiết hành vi nguy hiểm phát hiện:")
        for reason in reasons:
            print(f"  \033[91m-> {reason}\033[0m")
    else:
        # In chữ màu XANH LÁ trên terminal
        print("\033[1;32m[AN TOÀN] Không phát hiện hành vi nguy hiểm đáng ngờ.\033[0m")
    print(f"==================================================\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Cách sử dụng: python rules/check_danger.py <đường_dẫn_file_json>")
        print("Ví dụ: python rules/check_danger.py frontend/photo_6167715827998724074_x.aihub_attr.json")
        sys.exit(1)
        
    evaluate_danger(sys.argv[1])
