"""
resfes.py — ResFes AR Learning (ALL-IN-ONE)
============================================
Demo trên điện thoại, sẵn sàng chuyển lên kính AR thật.

Kiến trúc:
  - Camera: điện thoại tự quay (getUserMedia) → chụp frame → gửi lên Flask
  - AI:     Groq LLaMA 4 Scout phân tích ảnh
  - UX:     Wake word / Gesture (MediaPipe) / TTS / STT — chạy 100% trên browser

Chạy:
    pip install flask flask-cors groq python-dotenv
    python resfes.py

Mở điện thoại (cùng WiFi):
    http://<IP_máy_tính>:5000

Khi lên kính AR thật:
    - Thêm ssl_context để dùng HTTPS (camera yêu cầu HTTPS ngoài localhost)
    - Đổi facingMode sang camera phù hợp của kính
"""

import os, base64, socket, requests
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
import knowledge_base as kb  # Fallback local KB

load_dotenv()

app    = Flask(__name__)
CORS(app)
client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
PORT   = 5050

# KB Server configuration
KB_SERVER_URL = os.getenv("KB_SERVER_URL", "").strip()
KB_MODE = os.getenv("RESFES_KB_MODE", "auto").strip().lower()

if KB_MODE == "local":
    USE_REMOTE_KB = False
elif KB_MODE == "remote":
    USE_REMOTE_KB = bool(KB_SERVER_URL)
else:
    USE_REMOTE_KB = bool(KB_SERVER_URL)


def collect_local_ips(primary_ip):
  """Collect local IPs so the self-signed cert can include SAN entries."""
  ips = {"127.0.0.1", primary_ip}
  try:
    for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
      if ip and not ip.startswith("127."):
        ips.add(ip)
  except Exception:
    pass
  return sorted(ips)


def collect_local_dns_names():
    """Collect hostnames for certificate SAN DNS entries."""
    names = {"localhost"}
    try:
        host = socket.gethostname().strip()
        if host:
            names.add(host)
            if "." in host:
                names.add(host.split(".")[0])
    except Exception:
        pass
    return sorted(names)


def _read_cert_san_and_expiry(cert_file):
    """Read SAN values and expiry from an existing PEM certificate."""
    from OpenSSL import crypto

    with open(cert_file, "rb") as f:
        cert = crypto.load_certificate(crypto.FILETYPE_PEM, f.read())

    san_dns = set()
    san_ips = set()
    for i in range(cert.get_extension_count()):
        ext = cert.get_extension(i)
        if ext.get_short_name() == b"subjectAltName":
            raw = str(ext)
            for item in [x.strip() for x in raw.split(",")]:
                if item.startswith("DNS:"):
                    san_dns.add(item.replace("DNS:", "", 1).strip())
                elif item.startswith("IP Address:"):
                    san_ips.add(item.replace("IP Address:", "", 1).strip())

    not_after = cert.get_notAfter().decode("ascii")
    expires_at = datetime.strptime(not_after, "%Y%m%d%H%M%SZ").replace(tzinfo=timezone.utc)

    return san_dns, san_ips, expires_at


def cert_is_usable(cert_file, required_dns, required_ips, rotate_before_days):
    """Return True when cert exists, not near expiry, and SAN covers required names."""
    if not os.path.exists(cert_file):
        return False

    try:
        san_dns, san_ips, expires_at = _read_cert_san_and_expiry(cert_file)
    except Exception:
        return False

    now_utc = datetime.now(timezone.utc)
    remaining = (expires_at - now_utc).days
    if remaining < rotate_before_days:
        return False

    if not set(required_dns).issubset(san_dns):
        return False

    if not set(required_ips).issubset(san_ips):
        return False

    return True


def cert_has_san_ip(cert_file, ip):
  """Return True if existing cert contains IP in subjectAltName."""
  try:
    from OpenSSL import crypto

    with open(cert_file, "rb") as f:
      cert = crypto.load_certificate(crypto.FILETYPE_PEM, f.read())

    for i in range(cert.get_extension_count()):
      ext = cert.get_extension(i)
      if ext.get_short_name() == b"subjectAltName":
        return f"IP Address:{ip}" in str(ext)
  except Exception:
    return False
  return False


def create_self_signed_cert(cert_file, key_file, primary_ip):
        """Create self-signed certificate with SAN for localhost, local DNS, and local IPs."""
        from OpenSSL import crypto

        local_ips = collect_local_ips(primary_ip)
        local_dns = collect_local_dns_names()
        san_entries = [f"DNS:{name}" for name in local_dns] + [f"IP:{ip}" for ip in local_ips]

        cert_valid_days = int(os.getenv("RESFES_CERT_VALID_DAYS", "365"))

        # Generate private key
        pkey = crypto.PKey()
        pkey.generate_key(crypto.TYPE_RSA, 2048)

        # Generate cert
        cert = crypto.X509()
        cert.get_subject().C = "VN"
        cert.get_subject().ST = "Vietnam"
        cert.get_subject().L = "Hanoi"
        cert.get_subject().O = "ResFes2026"
        cert.get_subject().OU = "AR Learning"
        cert.get_subject().CN = "localhost"
        cert.set_serial_number(int.from_bytes(os.urandom(16), "big") >> 1)
        cert.gmtime_adj_notBefore(0)
        cert.gmtime_adj_notAfter(cert_valid_days * 24 * 60 * 60)
        cert.set_issuer(cert.get_subject())
        cert.set_pubkey(pkey)
        cert.add_extensions([
                crypto.X509Extension(b"basicConstraints", True, b"CA:FALSE"),
                crypto.X509Extension(b"keyUsage", True, b"digitalSignature,keyEncipherment"),
                crypto.X509Extension(b"extendedKeyUsage", False, b"serverAuth"),
                crypto.X509Extension(b"subjectAltName", False, ", ".join(san_entries).encode("utf-8")),
        ])
        cert.sign(pkey, "sha256")

        with open(cert_file, "wb") as f:
                f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
        with open(key_file, "wb") as f:
                f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, pkey))

        return local_ips, local_dns

# ── Groq vision endpoint ──────────────────────────────────────────────────────
def kb_search_remote(query_text, subject=None):
    """Search knowledge from remote KB server."""
    if not KB_SERVER_URL:
        return []
    
    try:
        response = requests.post(
            f"{KB_SERVER_URL}/api/search",
            json={"query": query_text, "subject": subject},
            timeout=5
        )
        if response.ok:
            return response.json().get("results", [])
    except Exception as e:
        print(f"KB Server error: {e}")
    
    return []


def kb_search_local(query_text, subject=None):
    """Search knowledge from local KB."""
    return kb.search_knowledge(
        query_text=query_text,
        subject=subject,
        groq_client=client
    )


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "Không có ảnh."}), 400

    subject  = data.get("subject", "")
    note     = data.get("note", "")
    use_kb   = data.get("use_kb", True)  # Mặc định dùng knowledge base

    try:
        raw = data["image"]
        if "," in raw: raw = raw.split(",")[1]
        b64 = raw
    except Exception as e:
        return jsonify({"error": f"Lỗi decode ảnh: {e}"}), 400

    parts = []
    if subject: parts.append(f"Môn học: {subject}")
    if note:    parts.append(f"Câu hỏi học sinh: {note}")
    parts.append(
        "Phân tích ảnh và TRẢ VỀ JSON (không thêm gì khác):\n"
        '{"ocr_text":"nội dung văn bản/công thức trong ảnh (tối đa 200 ký tự)",'
        '"subject":"môn học phát hiện được",'
        '"hint":"2-3 câu hỏi Socratic ngắn gọn, KHÔNG đưa đáp án, chỉ gợi mở tư duy",'
        '"flashcard":"1 câu hỏi ngắn kích thích tư duy"}\n'
        "Viết bằng tiếng Việt. Nếu không có văn bản, để ocr_text rỗng."
    )

    try:
        import json
        res = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            max_tokens=500,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text",      "text": "\n".join(parts)}
            ]}]
        )
        raw_text = res.choices[0].message.content.strip()
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"): raw_text = raw_text[4:]
        result = json.loads(raw_text.strip())
        
        # Base response
        response = {
            "ocr_text":  result.get("ocr_text",  "")[:300],
            "subject":   result.get("subject",   subject),
            "hint":      result.get("hint",      ""),
            "flashcard": result.get("flashcard", ""),
        }
        
        # Search knowledge base nếu có OCR text
        if use_kb and response["ocr_text"]:
            # Use remote KB if configured, otherwise local
            if USE_REMOTE_KB:
                kb_results = kb_search_remote(
                    query_text=response["ocr_text"],
                    subject=response["subject"]
                )
            else:
                kb_results = kb_search_local(
                    query_text=response["ocr_text"],
                    subject=response["subject"]
                )
            response["knowledge"] = kb_results
        else:
            response["knowledge"] = []
        
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "model": "llama-4-scout-17b"})

# ── Knowledge Base API ─────────────────────────────────────────────────────────
@app.route("/kb/upload", methods=["POST"])
def kb_upload():
    """Upload tài liệu vào knowledge base."""
    data = request.get_json()
    
    # Accept both "file" and "file_data" for compatibility
    file_data = data.get("file") or data.get("file_data")
    
    if not data or not file_data:
        return jsonify({"error": "No file data"}), 400
    
    try:
        result = kb.save_file(
            file_data=file_data,
            original_name=data.get("filename", "untitled"),
            file_type=data.get("file_type", "txt"),
            subject=data.get("subject", "")
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kb/documents", methods=["GET"])
def kb_list_documents():
    """Lấy danh sách tài liệu."""
    subject = request.args.get("subject")
    try:
        docs = kb.list_documents(subject=subject)
        return jsonify({"documents": docs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kb/documents/<int:doc_id>", methods=["DELETE"])
def kb_delete_document(doc_id):
    """Xóa tài liệu."""
    try:
        success = kb.delete_document(doc_id)
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Document not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kb/search", methods=["POST"])
def kb_search():
    """Tìm kiếm kiến thức liên quan."""
    data = request.get_json()
    
    # Accept both "query" and "query_text" for compatibility
    query = data.get("query") or data.get("query_text") if data else None
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    try:
        results = kb.search_knowledge(
            query_text=query,
            subject=data.get("subject"),
            groq_client=client
        )
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Frontend is served from templates/ar_hud.html

@app.route("/")
def index():
  return render_template("ar_hud.html")

@app.route("/test")
def test_camera():
    """Camera debug test page"""
    try:
        with open('test_camera.html', 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return "<h1>test_camera.html not found</h1>", 404

# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "localhost"

    # HTTPS certificate policy (production-friendly for packaged app)
    cert_dir = Path(os.getenv("RESFES_CERT_DIR", ".")).resolve()
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_file = str(cert_dir / "cert.pem")
    key_file = str(cert_dir / "key.pem")

    rotate_before_days = int(os.getenv("RESFES_CERT_ROTATE_BEFORE_DAYS", "14"))
    force_regen = os.getenv("RESFES_REGEN_CERT", "false").strip().lower() in {"1", "true", "yes", "on"}

    required_dns = collect_local_dns_names()
    required_ips = ["127.0.0.1", local_ip]

    need_new_cert = force_regen or not os.path.exists(key_file) or (not cert_is_usable(
        cert_file=cert_file,
        required_dns=required_dns,
        required_ips=required_ips,
        rotate_before_days=rotate_before_days,
    ))

    if need_new_cert:
        print("\n🔒 Tạo HTTPS certificate cho camera...")
        try:
            covered_ips, covered_dns = create_self_signed_cert(cert_file, key_file, local_ip)
            print("✅ Đã tạo certificate có SAN!")
            print("   SAN IPs:", ", ".join(covered_ips))
            print("   SAN DNS:", ", ".join(covered_dns))
            print("   Cert dir:", cert_dir)
        except ImportError:
            print("⚠️  Cần cài pyOpenSSL: pip install pyOpenSSL")
            print("💡 Hoặc chạy: python create_cert.py\n")
            cert_file = None
            key_file = None
    else:
        print("\n🔒 HTTPS certificate hợp lệ, tiếp tục sử dụng cert hiện tại.")
        print("   Cert file:", cert_file)

    protocol = "https" if (cert_file and os.path.exists(cert_file) and key_file and os.path.exists(key_file)) else "http"
    
    # KB Server info
    kb_status = f"📚 KB Server: {KB_SERVER_URL}" if USE_REMOTE_KB else "📦 KB: Local storage"
    data_dir = os.getenv("RESFES_DATA_DIR", "knowledge")
    
    print(f"""
╔═══════════════════════════════════════════════╗
║         ResFes AR — Learning Assistant         ║
╠═══════════════════════════════════════════════╣
║  💻 Laptop     → {protocol}://localhost:{PORT}           ║
║  📱 Điện thoại → {protocol}://{local_ip}:{PORT}
║                                               ║
║  {kb_status}             
║  📁 Data dir: {data_dir}
║                                               ║
║  Tính năng:                                   ║
║  ✅ Camera điện thoại (rear cam)              ║
║  ✅ Gesture control (MediaPipe)               ║
║  ✅ Wake word "Hey ResFes"                    ║
║  ✅ Mic STT tiếng Việt                        ║
║  ✅ TTS đọc gợi ý Socratic                   ║
║  ✅ Chọn môn học                              ║
║                                               ║
║  Cử chỉ tay:                                  ║
║  ☝️  Chỉ ngón trỏ  → di cursor               ║
║  🤏 Nhón (Pinch)   → bấm nút                 ║
║  🖐️  Mở bàn tay   → bật mic                  ║
║  ✌️  Chữ V         → Scan ngay               ║
║                                               ║
║  ⚠️  Điện thoại và laptop phải cùng WiFi      ║""")
    
    if protocol == "https":
        print("""║  ⚠️  Chấp nhận certificate warning lần đầu   ║""")
    else:
        print("""║  ⚠️  Camera có thể KHÔNG hoạt động (cần HTTPS)║""")
    
    print("""╚═══════════════════════════════════════════════╝
""")
    
    # Chạy với HTTPS nếu có certificate
    if cert_file and key_file and os.path.exists(cert_file):
        ssl_context = (cert_file, key_file)
        app.run(host="0.0.0.0", port=PORT, debug=False, ssl_context=ssl_context)
    else:
        print("⚠️  Chạy HTTP - Camera sẽ KHÔNG hoạt động qua network!")
        print("💡  Cài pyOpenSSL và chạy lại: pip install pyOpenSSL\n")
        app.run(host="0.0.0.0", port=PORT, debug=False)
