"""
KB Server - Knowledge Base Server cho điện thoại
=================================================
Server Flask đơn giản chạy trên điện thoại để:
- Lưu trữ tài liệu học tập
- Cung cấp API search cho ResFes (chạy trên kính AR)

Chạy trên Termux hoặc Pydroid:
  python kb_server.py

Server sẽ chạy trên: http://<phone-ip>:5001
"""

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import os
import sqlite3
import base64
from datetime import datetime
from pathlib import Path
import socket

app = Flask(__name__)
CORS(app)  # Allow requests from ResFes web app

# Configuration
KB_DIR = Path("kb_data/uploads")
DB_FILE = "kb_data/knowledge.db"
PORT = 5001

# Ensure directories exist
KB_DIR.mkdir(parents=True, exist_ok=True)


def init_db():
    """Khởi tạo SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            subject TEXT,
            content_preview TEXT,
            upload_date TEXT NOT NULL,
            file_size INTEGER
        )
    ''')
    conn.commit()
    conn.close()


def save_file(file_data, original_name, file_type, subject=""):
    """Lưu file và metadata vào database."""
    try:
        # Decode base64
        file_bytes = base64.b64decode(file_data.split(',')[1] if ',' in file_data else file_data)
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in original_name if c.isalnum() or c in "._- ")
        filename = f"{timestamp}_{safe_name}"
        filepath = KB_DIR / filename
        
        # Save file
        with open(filepath, 'wb') as f:
            f.write(file_bytes)
        
        # Extract preview
        preview = ""
        if file_type == "txt":
            preview = file_bytes.decode('utf-8', errors='ignore')[:500]
        
        # Save to database
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO documents (filename, original_name, file_type, subject, content_preview, upload_date, file_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (filename, original_name, file_type, subject or "", preview, datetime.now().isoformat(), len(file_bytes)))
        
        doc_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "id": doc_id,
            "filename": filename,
            "file_size": len(file_bytes)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_documents(subject=None):
    """Lấy danh sách tài liệu."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if subject:
        c.execute("SELECT * FROM documents WHERE subject = ? ORDER BY upload_date DESC", (subject,))
    else:
        c.execute("SELECT * FROM documents ORDER BY upload_date DESC")
    
    docs = [dict(row) for row in c.fetchall()]
    conn.close()
    return docs


def delete_document(doc_id):
    """Xóa tài liệu."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT filename FROM documents WHERE id = ?", (doc_id,))
    row = c.fetchone()
    
    if row:
        filepath = KB_DIR / row[0]
        if filepath.exists():
            filepath.unlink()
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()
        return True
    
    conn.close()
    return False


def search_knowledge(query_text, subject=None):
    """Tìm kiếm tài liệu liên quan."""
    docs = list_documents(subject=subject)
    
    if not docs:
        return []
    
    # Simple search: return docs with matching keywords
    query_lower = query_text.lower()
    results = []
    
    for doc in docs[:10]:  # Limit to 10 docs
        # Check if query matches in preview
        if doc['content_preview'] and query_lower in doc['content_preview'].lower():
            results.append({
                "doc_id": doc['id'],
                "title": doc['original_name'],
                "subject": doc['subject'],
                "snippet": doc['content_preview'][:200],
                "relevance": 0.9
            })
        elif any(word in doc['original_name'].lower() for word in query_lower.split()):
            # Match by filename
            results.append({
                "doc_id": doc['id'],
                "title": doc['original_name'],
                "subject": doc['subject'],
                "snippet": doc['content_preview'][:200] if doc['content_preview'] else "",
                "relevance": 0.7
            })
    
    # Sort by relevance
    results.sort(key=lambda x: x['relevance'], reverse=True)
    return results[:5]  # Top 5


# ── API Endpoints ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Web UI để quản lý tài liệu."""
    return render_template_string(KB_SERVER_UI)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload tài liệu."""
    data = request.get_json()
    file_data = data.get("file") or data.get("file_data")
    
    if not file_data:
        return jsonify({"error": "No file data"}), 400
    
    result = save_file(
        file_data=file_data,
        original_name=data.get("filename", "untitled"),
        file_type=data.get("file_type", "txt"),
        subject=data.get("subject", "")
    )
    
    if result.get("success"):
        return jsonify(result)
    else:
        return jsonify(result), 500


@app.route("/api/documents", methods=["GET"])
def api_documents():
    """Danh sách tài liệu."""
    subject = request.args.get("subject")
    docs = list_documents(subject=subject)
    return jsonify({"documents": docs})


@app.route("/api/documents/<int:doc_id>", methods=["DELETE"])
def api_delete(doc_id):
    """Xóa tài liệu."""
    success = delete_document(doc_id)
    if success:
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Not found"}), 404


@app.route("/api/search", methods=["POST"])
def api_search():
    """Tìm kiếm kiến thức."""
    data = request.get_json()
    query = data.get("query") or data.get("query_text")
    
    if not query:
        return jsonify({"error": "No query"}), 400
    
    results = search_knowledge(
        query_text=query,
        subject=data.get("subject")
    )
    return jsonify({"results": results})


@app.route("/api/health", methods=["GET"])
def api_health():
    """Health check."""
    return jsonify({"status": "ok", "service": "KB Server"})


# ── Web UI Template ────────────────────────────────────────────────────────

KB_SERVER_UI = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📚 Knowledge Base Server</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: system-ui, -apple-system, sans-serif; background: #f5f5f5; padding: 20px; }
.container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
h1 { color: #333; margin-bottom: 10px; }
.info { color: #666; margin-bottom: 30px; padding: 15px; background: #e3f2fd; border-radius: 8px; }
.upload-area { border: 2px dashed #ccc; padding: 40px; text-align: center; border-radius: 8px; margin-bottom: 30px; cursor: pointer; }
.upload-area:hover { border-color: #2196F3; background: #f9f9f9; }
.upload-area input { display: none; }
.subject-select { margin: 15px 0; }
.subject-select select { padding: 10px; font-size: 16px; border-radius: 6px; border: 1px solid #ddd; }
.docs-list { margin-top: 30px; }
.doc-item { padding: 15px; border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
.doc-info { flex: 1; }
.doc-name { font-weight: 600; color: #333; }
.doc-meta { font-size: 14px; color: #666; margin-top: 5px; }
.btn-delete { background: #f44336; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; }
.btn-delete:hover { background: #d32f2f; }
.toast { position: fixed; top: 20px; right: 20px; padding: 15px 25px; background: #323232; color: white; border-radius: 8px; display: none; }
</style>
</head>
<body>
<div class="container">
  <h1>📚 Knowledge Base Server</h1>
  <div class="info">
    <strong>Server URL:</strong> <span id="serverUrl"></span><br>
    <strong>API Endpoint:</strong> <span id="apiUrl"></span>
  </div>
  
  <div class="upload-area" onclick="document.getElementById('fileInput').click()">
    <div>📁 Click để upload tài liệu</div>
    <div style="font-size:14px; color:#999; margin-top:10px;">PDF, TXT, hoặc hình ảnh</div>
    <input type="file" id="fileInput" accept=".pdf,.txt,.jpg,.jpeg,.png" onchange="handleUpload(event)">
  </div>
  
  <div class="subject-select">
    <label>Môn học:</label>
    <select id="subjectSelect">
      <option value="">Tất cả</option>
      <option value="Toán">Toán</option>
      <option value="Lý">Lý</option>
      <option value="Hóa">Hóa</option>
      <option value="Sinh">Sinh</option>
      <option value="Văn">Văn</option>
      <option value="Sử">Sử</option>
      <option value="Địa">Địa</option>
      <option value="Anh">Anh</option>
    </select>
  </div>
  
  <div class="docs-list">
    <h2 style="margin-bottom:15px;">Tài liệu đã upload (<span id="docCount">0</span>)</h2>
    <div id="docsList"></div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// Display server info
const hostname = window.location.hostname;
const port = window.location.port;
document.getElementById('serverUrl').textContent = `http://${hostname}:${port}`;
document.getElementById('apiUrl').textContent = `http://${hostname}:${port}/api`;

function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.style.display = 'block';
  setTimeout(() => toast.style.display = 'none', 3000);
}

async function handleUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  
  const fileType = file.type.includes('pdf') ? 'pdf' : 
                   file.type.includes('text') ? 'txt' : 'image';
  
  const reader = new FileReader();
  reader.onload = async function(e) {
    try {
      showToast('⏳ Đang upload...');
      
      const subject = document.getElementById('subjectSelect').value;
      const res = await fetch('/api/upload', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          file: e.target.result,
          filename: file.name,
          file_type: fileType,
          subject: subject
        })
      });
      
      const data = await res.json();
      
      if (data.success) {
        showToast('✅ Upload thành công!');
        loadDocuments();
        event.target.value = '';
      } else {
        showToast('❌ ' + data.error);
      }
    } catch (err) {
      showToast('❌ Lỗi: ' + err.message);
    }
  };
  reader.readAsDataURL(file);
}

async function loadDocuments() {
  try {
    const res = await fetch('/api/documents');
    const data = await res.json();
    
    const list = document.getElementById('docsList');
    document.getElementById('docCount').textContent = data.documents.length;
    
    if (data.documents.length === 0) {
      list.innerHTML = '<p style="color:#999; text-align:center; padding:20px;">Chưa có tài liệu nào</p>';
      return;
    }
    
    list.innerHTML = data.documents.map(doc => `
      <div class="doc-item">
        <div class="doc-info">
          <div class="doc-name">📄 ${doc.original_name}</div>
          <div class="doc-meta">
            ${doc.subject ? '📚 ' + doc.subject + ' • ' : ''}
            ${(doc.file_size / 1024).toFixed(1)} KB • 
            ${new Date(doc.upload_date).toLocaleDateString('vi-VN')}
          </div>
        </div>
        <button class="btn-delete" onclick="deleteDoc(${doc.id})">Xóa</button>
      </div>
    `).join('');
  } catch (err) {
    console.error(err);
  }
}

async function deleteDoc(id) {
  if (!confirm('Xóa tài liệu này?')) return;
  
  try {
    const res = await fetch(`/api/documents/${id}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('✅ Đã xóa');
      loadDocuments();
    } else {
      showToast('❌ Lỗi khi xóa');
    }
  } catch (err) {
    showToast('❌ ' + err.message);
  }
}

// Load on start
loadDocuments();
</script>
</body>
</html>
"""


# ── Main ───────────────────────────────────────────────────────────────────

def get_local_ip():
    """Lấy IP local của điện thoại."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"


if __name__ == "__main__":
    init_db()
    
    local_ip = get_local_ip()
    
    print("\n" + "=" * 60)
    print("  📚 KB SERVER - Knowledge Base Server")
    print("=" * 60)
    print(f"  🌐 Web UI:     http://{local_ip}:{PORT}")
    print(f"  🔌 API:        http://{local_ip}:{PORT}/api")
    print(f"  📂 Storage:    {KB_DIR.absolute()}")
    print(f"  🗄️  Database:   {DB_FILE}")
    print("=" * 60)
    print("\n  💡 Dùng URL này để config ResFes kết nối tới KB Server\n")
    
    app.run(host="0.0.0.0", port=PORT, debug=False)
