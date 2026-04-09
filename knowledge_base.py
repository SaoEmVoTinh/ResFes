"""
knowledge_base.py - Quản lý kiến thức học tập (giống NotebookLM)
================================================================
Lưu trữ tài liệu học tập và tìm kiếm nội dung liên quan khi scan.

Features:
- Upload files (PDF, TXT, images)
- Extract text content
- Search relevant knowledge với Groq RAG
- SQLite database tracking
"""

import os
import sqlite3
import base64
from datetime import datetime
from pathlib import Path

def _resolve_storage_paths():
    """Resolve KB storage paths from environment or fallback defaults."""
    base_dir = os.getenv("RESFES_DATA_DIR", "knowledge").strip() or "knowledge"
    root = Path(base_dir)
    return root / "uploads", root / "knowledge.db"


KNOWLEDGE_DIR, DB_PATH = _resolve_storage_paths()
DB_FILE = str(DB_PATH)

# Ensure directories exist
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def init_db():
    """Khởi tạo database SQLite cho knowledge base."""
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
            file_size INTEGER,
            page_count INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()


def save_file(file_data, original_name, file_type, subject=""):
    """
    Lưu file vào knowledge base.
    
    Args:
        file_data: bytes or base64 string
        original_name: tên file gốc
        file_type: pdf, txt, image
        subject: môn học (optional)
    
    Returns:
        dict: thông tin file đã lưu
    """
    init_db()
    
    # Decode base64 nếu cần
    if isinstance(file_data, str):
        if ',' in file_data:
            file_data = file_data.split(',')[1]
        file_data = base64.b64decode(file_data)
    
    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = Path(original_name).suffix
    filename = f"{timestamp}_{Path(original_name).stem}{ext}"
    filepath = KNOWLEDGE_DIR / filename
    
    # Save file
    with open(filepath, 'wb') as f:
        f.write(file_data)
    
    file_size = len(file_data)
    
    # Extract content preview
    content_preview = ""
    page_count = 0
    
    try:
        if file_type == "txt":
            content_preview = file_data.decode('utf-8')[:500]
            page_count = 1
        elif file_type == "pdf":
            # Will implement PDF extraction
            content_preview = f"PDF document: {original_name}"
            page_count = 0  # TODO: count PDF pages
        elif file_type == "image":
            content_preview = f"Image: {original_name}"
            page_count = 1
    except Exception as e:
        content_preview = f"Error extracting content: {e}"
    
    # Save to database
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO documents (filename, original_name, file_type, subject, 
                             content_preview, upload_date, file_size, page_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (filename, original_name, file_type, subject, content_preview,
          datetime.now().isoformat(), file_size, page_count))
    
    doc_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return {
        "id": doc_id,
        "filename": filename,
        "original_name": original_name,
        "file_type": file_type,
        "subject": subject,
        "content_preview": content_preview[:200],
        "upload_date": datetime.now().isoformat(),
        "file_size": file_size,
        "page_count": page_count
    }


def list_documents(subject=None):
    """Lấy danh sách tài liệu."""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if subject:
        c.execute('SELECT * FROM documents WHERE subject = ? ORDER BY upload_date DESC', (subject,))
    else:
        c.execute('SELECT * FROM documents ORDER BY upload_date DESC')
    
    docs = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return docs


def delete_document(doc_id):
    """Xóa tài liệu."""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get filename first
    c.execute('SELECT filename FROM documents WHERE id = ?', (doc_id,))
    row = c.fetchone()
    
    if row:
        filename = row[0]
        filepath = KNOWLEDGE_DIR / filename
        
        # Delete file
        if filepath.exists():
            filepath.unlink()
        
        # Delete from DB
        c.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        conn.commit()
        conn.close()
        return True
    
    conn.close()
    return False


def get_document_content(doc_id):
    """Lấy nội dung đầy đủ của tài liệu để RAG search."""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('SELECT * FROM documents WHERE id = ?', (doc_id,))
    doc = c.fetchone()
    conn.close()
    
    if not doc:
        return None
    
    filepath = KNOWLEDGE_DIR / doc['filename']
    
    if not filepath.exists():
        return None
    
    content = ""
    
    try:
        if doc['file_type'] == 'txt':
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        elif doc['file_type'] == 'pdf':
            # TODO: implement PDF reading with PyPDF2
            content = f"[PDF content extraction not implemented yet: {doc['original_name']}]"
        elif doc['file_type'] == 'image':
            # Images will be processed separately with OCR
            content = f"[Image file: {doc['original_name']}]"
    except Exception as e:
        content = f"[Error reading file: {e}]"
    
    return {
        "id": doc['id'],
        "filename": doc['filename'],
        "original_name": doc['original_name'],
        "file_type": doc['file_type'],
        "subject": doc['subject'],
        "content": content
    }


def search_knowledge(query_text, subject=None, groq_client=None):
    """
    Tìm kiếm kiến thức liên quan với Groq RAG.
    
    Args:
        query_text: nội dung scan được (OCR text)
        subject: môn học
        groq_client: Groq client instance
    
    Returns:
        list: các đoạn kiến thức liên quan
    """
    docs = list_documents(subject=subject)
    
    if not docs:
        return []
    
    # Đơn giản: lấy content_preview của tất cả docs
    # TODO: implement smart RAG với Groq
    
    results = []
    for doc in docs[:5]:  # Giới hạn 5 docs đầu
        results.append({
            "doc_id": doc['id'],
            "title": doc['original_name'],
            "subject": doc['subject'],
            "snippet": doc['content_preview'][:200],
            "relevance": 0.8  # Placeholder
        })
    
    return results


# Initialize DB on import
init_db()
