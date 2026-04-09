# 🎓 ResFes AR Learning Assistant (ResFes 2026)

> **AI-powered AR learning tool với Socratic method**  
> Scan bài tập → Nhận gợi ý thông minh (KHÔNG đưa đáp án)

Built for **ResFes 2026** — sẵn sàng chuyển lên kính AR thật.

---

## 🏗️ Kiến trúc 2-app

### 📱 KB Server (điện thoại)
- Python Flask app đơn giản - chạy được trên Termux/Pydroid
- Upload & lưu trữ tài liệu học tập (PDF, TXT, images)
- Cung cấp API search cho ResFes
- **Port:** 5001

### 🥽 ResFes Web App (kính AR / laptop)
- Camera + Gesture control (MediaPipe) - điều khiển bằng tay
- Groq LLaMA 4 Scout AI - phân tích ảnh & Socratic hints
- Kết nối KB Server để tìm kiến thức liên quan từ tài liệu
- **Port:** 5050

### 🔗 Workflow
```
Kính AR/Phone → ResFes → Groq AI (Vision) → Socratic hint
                  ↓
              KB Server (Phone) → Search tài liệu → Knowledge snippets
```

---

## ⚡ Quick Start

### 1. Setup KB Server (điện thoại)

**Termux (Android):**
```bash
pkg install python
pip install flask flask-cors
python kb_server.py
```

**Pydroid 3 (Android):**
1. Install from Play Store
2. Menu → Pip → Install: `flask flask-cors`
3. Open `kb_server.py` → Run ▶️

→ Server chạy tại: `http://<phone-ip>:5001`

### 2. Setup ResFes (laptop/kính)

```bash
pip install flask flask-cors groq python-dotenv pyOpenSSL requests
python resfes.py
```

**Tạo file `.env`:**
```bash
GROQ_API_KEY=your_groq_api_key_here
KB_SERVER_URL=http://192.168.1.XXX:5001  # Thay XXX bằng IP điện thoại
```

→ Server chạy tại: `https://localhost:5050`

### 3. Sử dụng

1. **Upload tài liệu** qua KB Server: Mở `http://<phone-ip>:5001`
   - Click upload → Chọn PDF/TXT → Chọn môn học → Upload
2. **Mở ResFes** trên kính/điện thoại khác: `https://<laptop-ip>:5050`
3. **Scan bài tập** bằng cử chỉ tay ✌️ (Victory)
4. **Nhận kết quả**: 
   - OCR text đọc được
   - Socratic hint (câu hỏi gợi mở)
   - 📚 Knowledge từ tài liệu liên quan

---

## 🎯 Tính năng

### 📸 Camera + Gesture Control
- Camera điện thoại/kính AR (rear camera)
- Điều khiển 100% bằng cử chỉ tay (MediaPipe):
  - ☝️ **Pointing** → Di chuyển cursor
  - 🤏 **Pinch** → Click/bấm nút
  - 🖐️ **Open Palm** → Bật mic
  - ✌️ **Victory** → Scan ngay

### 🤖 AI Vision + Socratic Method
- Groq LLaMA 4 Scout (multimodal 17B)
- OCR text/công thức toán từ ảnh
- Tự động nhận diện môn học
- **Chỉ đưa câu hỏi gợi mở, KHÔNG đưa đáp án**
- TTS đọc gợi ý (tiếng Việt)

### 🎤 Voice Control
- Wake word: "**Hey ResFes**"
- STT tiếng Việt (Web Speech API)
- Hỏi bằng giọng nói

### 📚 Knowledge Base
- Upload tài liệu học tập (PDF, TXT, images)
- Tự động tìm kiến thức liên quan khi scan
- Lưu trữ local trên điện thoại
- Simple RAG search (có thể nâng cấp thành smart RAG với Groq)

---

## How it works

1. Student uploads or photographs a textbook page
2. The image is sent to **Groq** (LLaMA 4 Scout — multimodal)
3. The AI reads the content — text, math formulas, diagrams
4. Returns a **Socratic hint** that guides thinking, never solves the problem
5. Results appear in a clean web UI running on localhost

```
Image upload / camera
       ↓
Flask backend (app.py)
       ↓
Groq LLaMA 4 Scout — vision
       ↓
Socratic hint → Web UI
```

---

## Tech stack

| Layer    | Technology                          |
|----------|-------------------------------------|
| Backend  | Python · Flask · Flask-CORS         |
| AI       | Groq API · LLaMA 4 Scout (17B)      |
| Frontend | HTML · CSS · Vanilla JS             |
| Config   | python-dotenv                       |

No local AI models. No GPU required. Runs on any laptop.

---

## Project structure

```
ar-learning/
├── app.py               # Flask server — routes and request handling
├── vision_module.py     # Groq vision pipeline + Socratic system prompt
├── requirements.txt     # Python dependencies
├── .env                 # API keys (not committed)
├── .gitignore
└── static/
    ├── index.html       # Markup
    ├── styles.css       # Dark theme, collapsible panel, animations
    └── app.js           # Upload, camera, fetch, render logic
```

---

## Setup

### Prerequisites

- Python 3.10+
- A free [Groq API key](https://console.groq.com) — no credit card required

### Install

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/ar-learning.git
cd ar-learning

# 2. Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# Mac / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env file
echo GROQ_API_KEY=your_key_here > .env
```

### Run

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## API

### `POST /analyze`

Analyzes a textbook image and returns AI guidance.

**Request body**
```json
{
  "image":   "<base64 encoded image>",
  "subject": "Mathematics",
  "note":    "I don't understand step 2"
}
```

`subject` and `note` are optional.

**Response**
```json
{
  "extracted_text": "Exercise 2.4.3 — solve the system of equations...",
  "hint":           "What do you think the coefficient matrix looks like here?",
  "subject":        "Mathematics"
}
```

### `GET /health`

Returns server status and active model name.

---

## Design principles

**Socratic guidance only.** The AI is strictly instructed never to give direct answers. It asks questions, points to relevant concepts, and encourages the student to reason through the problem independently.

**No answer leaking.** The system prompt enforces this at the model level — responses are capped at 3–5 sentences and must take the form of guiding questions.

**Offline-friendly demo.** The only external dependency at runtime is the Groq API. No database, no auth, no session storage. Each request is fully stateless.

---

## Research context

This project is the **Phase 1 software prototype** for a larger research study on AI-assisted learning. The research question:

> Does AI-powered Socratic guidance improve learning outcomes for high school students compared to traditional self-study?

Phase 2 (post-competition) will integrate the software with an **AR headset** (ESP32-CAM + micro-display + beamsplitter) to deliver hints as a heads-up display overlay while the student reads their textbook.

The study will compare pre/post test scores between a control group (no AI) and an experimental group (using this system) across 20–30 students.

---

## Roadmap

- [x] Groq vision pipeline
- [x] Flask REST API
- [x] Web UI with collapsible results panel
- [x] Camera capture support
- [ ] Student experiment (20–30 participants)
- [ ] Research paper submission — 16/4/2026
- [ ] AR headset hardware integration (Phase 2)
- [ ] Session history / flashcard generation

---

## License

MIT
