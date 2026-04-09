# ResFes 2026 - Setup Guide

## New Launcher Mode (recommended)

`main.py` is now a Kivy launcher app:
- Starts `resfes.py` automatically
- Manages local documents (upload/list/delete)
- Uses shared local KB data via `RESFES_DATA_DIR`

Quick run:

```bash
pip install -r requirements.txt
python main.py
```

When launcher opens:
- ResFes server starts in background on port `5050`
- AR URL is shown in launcher UI
- Phone/AR glasses on same WiFi can open that URL

Default local shared data path:
- `app_data/uploads`
- `app_data/knowledge.db`

## 📱 Kiến trúc 2-app

### 1. **KB Server** (chạy trên điện thoại)
- Python Flask app đơn giản
- Lưu trữ tài liệu học tập
- Cung cấp API search
- Port: 5001

### 2. **ResFes Web App** (chạy trên kính AR / laptop)
- Flask + Groq AI
- Camera + Gesture control
- Kết nối tới KB Server để lấy knowledge
- Port: 5050

---

## 🚀 Setup KB Server trên Điện thoại

### Cách 1: Termux (Android)

```bash
# 1. Cài Termux từ F-Droid
# https://f-droid.org/en/packages/com.termux/

# 2. Setup Python
pkg update
pkg install python
pip install flask flask-cors

# 3. Copy file kb_server.py vào điện thoại
# Dùng Termux:API hoặc adb push hoặc copy manual

# 4. Chạy server
python kb_server.py
```

Server sẽ hiện:
```
📚 KB SERVER - Knowledge Base Server
🌐 Web UI:     http://192.168.1.XXX:5001
🔌 API:        http://192.168.1.XXX:5001/api
```

### Cách 2: Pydroid 3 (Android)

```bash
# 1. Cài Pydroid 3 từ Play Store
# 2. Cài thêm Flask trong Pydroid:
#    Menu → Pip → Install: flask flask-cors
# 3. Mở kb_server.py trong Pydroid
# 4. Nhấn Play ▶️
```

### Cách 3: Python trên iOS (Pythonista)

```python
# 1. Cài Pythonista từ App Store
# 2. Install dependencies bằng StaSh
# 3. Copy kb_server.py vào Pythonista
# 4. Run
```

---

## 🖥️ Setup ResFes trên Laptop/Kính

### 1. Cài dependencies

```bash
cd D:\FPT\ResFes2026
pip install flask flask-cors groq python-dotenv pyOpenSSL requests
```

### 2. Tạo file `.env`

```bash
GROQ_API_KEY=your_groq_api_key_here
KB_SERVER_URL=http://192.168.1.XXX:5001
```

> **Lưu ý:** Thay `192.168.1.XXX` bằng IP thực của điện thoại chạy KB Server

### 3. Chạy ResFes

```bash
python resfes.py
```

Mở browser:
- Laptop: `https://localhost:5050`
- Điện thoại khác/kính: `https://192.168.1.YYY:5050`

---

## 📖 Workflow Sử dụng

### Bước 1: Upload tài liệu học tập

1. Mở `http://<phone-ip>:5001` trên điện thoại chạy KB Server
2. Click vào vùng upload
3. Chọn file PDF/TXT từ Drive/Downloads
4. Chọn môn học (Toán, Lý, Hóa...)
5. Upload!

File sẽ lưu vào `kb_data/uploads/` trên điện thoại.

### Bước 2: Sử dụng ResFes trên kính AR

1. Mở ResFes web app
2. Cho phép truy cập camera
3. Hướng camera vào bài tập
4. Làm cử chỉ **✌️** (Victory) để scan

### Bước 3: Nhận kết quả

ResFes sẽ hiển thị:
- **OCR Text**: Nội dung đọc được từ ảnh
- **Socratic Hint**: Câu hỏi dẫn dắt tư duy (không đưa đáp án)
- **📚 Knowledge**: Kiến thức liên quan từ tài liệu đã upload

---

## 🔧 Troubleshooting

### KB Server không chạy được

**Lỗi: Module not found**
```bash
# Cài lại dependencies
pip install flask flask-cors
```

**Lỗi: Address already in use**
```bash
# Port 5001 đã bị chiếm, đổi port trong kb_server.py:
PORT = 5002  # Thay đổi số port
```

### ResFes không kết nối được KB Server

**Kiểm tra KB_SERVER_URL trong .env**
```bash
# Đảm bảo URL đúng format:
KB_SERVER_URL=http://192.168.1.100:5001

# KHÔNG có dấu / ở cuối
```

**Kiểm tra firewall**
```bash
# Trên điện thoại chạy KB Server, cho phép:
# - Port 5001 incoming connections
# - Python app có quyền network
```

**Test kết nối**
```bash
# Từ laptop, test xem có kết nối được KB Server không:
curl http://192.168.1.XXX:5001/api/health
# Kết quả: {"status":"ok","service":"KB Server"}
```

### Camera không hoạt động

**Cần HTTPS**
- ResFes tự động tạo self-signed certificate
- Lần đầu mở web, chấp nhận certificate warning

**Không có quyền camera**
- Check Settings → Camera permissions
- Reload trang và cho phép lại

---

## 📂 File Structure

```
ResFes2026/
├── kb_server.py          # KB Server app (chạy trên điện thoại)
├── resfes.py             # ResFes web app (chạy trên kính/laptop)
├── knowledge_base.py     # Local KB fallback
├── vision_module.py      # Groq AI integration
├── .env                  # Config (GROQ_API_KEY, KB_SERVER_URL)
├── kb_data/              # KB Server data (trên điện thoại)
│   ├── knowledge.db      # SQLite database
│   └── uploads/          # Uploaded documents
└── knowledge/            # Local KB data (fallback)
    ├── knowledge.db
    └── uploads/
```

---

## 🎯 Demo Scenario

### Setup ban đầu:

1. **Điện thoại A**: Chạy KB Server
   - Upload giáo trình Toán (PDF về đạo hàm)
   - Server: `http://192.168.1.100:5001`

2. **Laptop**: Chạy ResFes
   - Config KB_SERVER_URL=http://192.168.1.100:5001
   - Server: `https://192.168.1.50:5050`

3. **Điện thoại B** (giả lập kính AR):
   - Mở `https://192.168.1.50:5050`
   - Camera quay ra ngoài (environment)

### Sử dụng:

1. Điện thoại B hướng camera vào bài tập Toán
2. Làm cử chỉ ✌️ để scan
3. ResFes:
   - OCR đọc text từ ảnh
   - Gọi API tới KB Server (điện thoại A)
   - Tìm kiến thức liên quan trong giáo trình
   - Hiện kết quả: Hint + Knowledge

---

## 🔮 Tương lai - Khi có kính AR thật

### Thay đổi tối thiểu:

1. **Hardware**: 
   - Thay điện thoại B → Kính AR thực
   - Kính có camera + browser

2. **Software**:
   - Không cần thay đổi code
   - Chỉ cần mở web trên kính
   - Camera config có thể cần điều chỉnh facingMode

3. **Network**:
   - Kính AR kết nối WiFi
   - Truy cập ResFes qua HTTPS
   - ResFes gọi API tới KB Server (điện thoại)

### Kiến trúc không đổi:
```
Kính AR → ResFes Web (Laptop) → KB Server (Phone)
         └─ Camera, Gesture      └─ Documents storage
         └─ Groq AI
```

---

## 📞 Support

Vấn đề gì cứ hỏi! Các file quan trọng:
- `kb_server.py` - Standalone server cho điện thoại
- `resfes.py` - Main web app
- `.env` - Config KB_SERVER_URL

Logs để debug:
- KB Server: print ra console
- ResFes: print ra console
- Browser: F12 → Console tab
