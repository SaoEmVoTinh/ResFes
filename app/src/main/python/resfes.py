"""
resfes.py — DALAP AR Learning + RAG Backend (ALL-IN-ONE)
==========================================================
Demo trên điện thoại, sẵn sàng chuyển lên kính AR thật.

Kiến trúc:
  - Camera : getUserMedia → chụp frame → gửi Flask → Groq vision
  - RAG    : upload tài liệu → chunk → TF-IDF embed → cosine search → Groq answer
  - UX     : Wake word / Gesture (MediaPipe) / TTS / STT — chạy 100% browser

Chạy:
    pip install flask flask-cors groq python-dotenv
    python resfes.py

Mở điện thoại (cùng WiFi):
    https://<IP_máy_tính>:5000
"""

# ==============================================================================
# ==== IMPORTS =================================================================
# ==============================================================================

import os, re, math, json, base64, binascii, hashlib, sqlite3, socket, shutil, requests, ipaddress, importlib, time, threading
from collections import OrderedDict
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from flask import Flask, request, jsonify, render_template, Response, stream_with_context, g, has_app_context
from werkzeug.utils import secure_filename
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
from vector_db import SQLiteVectorDB
from werkzeug.exceptions import RequestEntityTooLarge

BASE_DIR = Path(__file__).resolve().parent


def _load_env() -> str:
    """Load .env with predictable priority across desktop and Chaquopy runtime."""
    configured = os.getenv("RESFES_DOTENV_PATH", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(BASE_DIR / "assets" / ".env")
    candidates.append(BASE_DIR / ".env")
    candidates.append(Path.cwd() / ".env")

    for env_path in candidates:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            return str(env_path)

    load_dotenv(override=False)
    return ""


_loaded_env_path = _load_env()
if _loaded_env_path:
    print("[DALAP] Loaded .env:", _loaded_env_path)
else:
    print("[DALAP] .env not found (using process environment only)")

# ==============================================================================
# ==== CONFIG ==================================================================
# ==============================================================================


PORT           = int(os.getenv("RESFES_PORT", "5000"))

import sys


def _is_android_runtime() -> bool:
    # Chaquopy may not always expose a stable "chaquopy" module marker.
    if os.getenv("ANDROID_ARGUMENT"):
        return True
    try:
        importlib.import_module("android.storage")
        return True
    except Exception:
        return False

def _get_data_dir():
    _data_dir_env = os.getenv("RESFES_DATA_DIR", "").strip()
    if _data_dir_env:
        return Path(_data_dir_env)
    # Ưu tiên app_internal_dir để dữ liệu bền vững qua lần mở app.
    if _is_android_runtime():
        try:
            storage_mod = importlib.import_module("android.storage")
            return Path(storage_mod.app_internal_dir) / "knowledge"
        except Exception:
            # Fallback Android: tránh cache dir nếu có thể.
            private_dir = os.environ.get("ANDROID_PRIVATE", "").strip()
            if private_dir:
                return Path(private_dir).resolve() / "knowledge"
            return Path(os.environ.get("HOME", ".")).resolve() / "knowledge"
    # Desktop hoặc môi trường khác
    return Path(os.environ.get("HOME", ".")).resolve() / "knowledge"

DATA_DIR = _get_data_dir()
print("[DALAP] DATA_DIR:", DATA_DIR)
# Use DB from DATA_DIR to be consistent with UPLOAD_DIR
_db_path_env = os.getenv("RESFES_DB_PATH", "").strip()
if _db_path_env:
    DB_PATH = Path(_db_path_env)
else:
    DB_PATH = DATA_DIR / "knowledge.db"
print("[DALAP] DB_PATH:", DB_PATH)
UPLOAD_DIR     = DATA_DIR / "uploads"
CHUNK_SIZE     = int(os.getenv("RESFES_CHUNK_SIZE",   "220"))  # số từ ước lượng mỗi chunk
CHUNK_OVERLAP  = int(os.getenv("RESFES_CHUNK_OVERLAP", "40"))   # số từ overlap giữa chunks
TOP_K          = int(os.getenv("RESFES_TOP_K",          "4"))  # số chunks trả về
# Nếu một chunk quá dài (so với CHUNK_SIZE * CHUNK_AUGMENT_THRESHOLD),
# cho phép tạo các sub-chunks sliding-window vào cache để cải thiện recall
CHUNK_AUGMENT_THRESHOLD = float(os.getenv("RESFES_CHUNK_AUGMENT_THRESHOLD", "2.0"))
CHUNK_AUGMENT_MAX_PER_CHUNK = int(os.getenv("RESFES_CHUNK_AUGMENT_MAX_PER_CHUNK", "6"))
GROQ_MODEL     = "meta-llama/llama-4-scout-17b-16e-instruct"
RAG_AGENTIC_DEFAULT = os.getenv("RESFES_RAG_AGENTIC", "1").strip().lower() not in {"0", "false", "no"}
RAG_FILTER_TOP_K = int(os.getenv("RESFES_RAG_FILTER_TOP_K", "3"))
RAG_CACHE_MAX_GROUPS = int(os.getenv("RESFES_RAG_CACHE_MAX_GROUPS", "16"))
RAG_CACHE_TTL_SEC = int(os.getenv("RESFES_RAG_CACHE_TTL_SEC", "1800"))
CONTEXTUAL_MAX_FILE_MB = int(os.getenv("RESFES_CONTEXTUAL_MAX_FILE_MB", "5"))
CONTEXTUAL_MAX_EST_CHUNKS = int(os.getenv("RESFES_CONTEXTUAL_MAX_EST_CHUNKS", "300"))
EXPAND_CACHE_TTL_SEC = int(os.getenv("RESFES_EXPAND_CACHE_TTL_SEC", "1800"))
LOW_MEMORY_MODE = os.getenv("RESFES_LOW_MEMORY_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
if not os.getenv("RESFES_LOW_MEMORY_MODE", "").strip():
    LOW_MEMORY_MODE = _is_android_runtime()
EXPAND_CACHE_MAX = int(os.getenv("RESFES_EXPAND_CACHE_MAX", "64"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

KB_SERVER_URL = os.getenv("KB_SERVER_URL", "").strip()
KB_MODE       = os.getenv("RESFES_KB_MODE", "local").strip().lower()
USE_REMOTE_KB = (KB_MODE == "remote" and bool(KB_SERVER_URL)) or \
                (KB_MODE == "auto"   and bool(KB_SERVER_URL))
EXTRACTOR_SERVER_URL = os.getenv("RESFES_EXTRACTOR_SERVER_URL", "").strip()
SQLITE_TIMEOUT_SEC = float(os.getenv("RESFES_SQLITE_TIMEOUT", "10"))
SQLITE_BUSY_MS = int(os.getenv("RESFES_SQLITE_BUSY_TIMEOUT_MS", "10000"))
KB_REMOTE_TIMEOUT_SEC = float(os.getenv("RESFES_REMOTE_TIMEOUT", "2.5"))
EXTRACTOR_REMOTE_TIMEOUT_SEC = float(os.getenv("RESFES_EXTRACTOR_TIMEOUT", "8"))
VECTOR_DB_ENABLED = os.getenv("RESFES_VECTOR_DB_ENABLED", "1").strip() not in {"0", "false", "False"}
VECTOR_DIM = int(os.getenv("RESFES_VECTOR_DIM", "384"))
VECTOR_MODEL_NAME = os.getenv("RESFES_VECTOR_MODEL", "hash-emb-v1").strip() or "hash-emb-v1"
ANDROID_SAFE_CHAT = _is_android_runtime() and (
    os.getenv("RESFES_ANDROID_SAFE_CHAT", "1").strip().lower() not in {"0", "false", "no"}
)
ANALYZE_MIN_INTERVAL_SEC = float(os.getenv("RESFES_ANALYZE_MIN_INTERVAL_SEC", "1.2"))
CHAT_MIN_INTERVAL_SEC = float(os.getenv("RESFES_CHAT_MIN_INTERVAL_SEC", "0.8"))
ALLOW_OPEN_API = os.getenv("RESFES_ALLOW_OPEN_API", "0").strip().lower() in {"1", "true", "yes", "on"}
QUIZ_MIN_INTERVAL_SEC = float(os.getenv("RESFES_QUIZ_MIN_INTERVAL_SEC", "2.0"))
ANALYZE_HOURLY_LIMIT = int(os.getenv("RESFES_ANALYZE_HOURLY_LIMIT", "120"))
CHAT_HOURLY_LIMIT = int(os.getenv("RESFES_CHAT_HOURLY_LIMIT", "240"))
QUIZ_HOURLY_LIMIT = int(os.getenv("RESFES_QUIZ_HOURLY_LIMIT", "60"))
HOURLY_WINDOW_SEC = 3600
SESSION_TTL_SEC = int(os.getenv("RESFES_SESSION_TTL_SEC", "86400"))
SESSION_MAX_TURNS = int(os.getenv("RESFES_SESSION_MAX_TURNS", "40"))
MAX_CONTENT_LENGTH_MB = int(os.getenv("RESFES_MAX_CONTENT_LENGTH_MB", "250"))
API_KEY = os.getenv("RESFES_API_KEY", "").strip()

_cors_origins_raw = os.getenv("RESFES_CORS_ORIGINS", "").strip()
ALLOWED_CORS_ORIGINS = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

_analyze_last_hit = {}
_chat_last_hit = {}
_quiz_last_hit = {}
_analyze_hourly_hits = {}
_chat_hourly_hits = {}
_quiz_hourly_hits = {}
_rate_limit_lock = threading.Lock()
_ingest_status_lock = threading.Lock()
_ingest_status_by_doc: Dict[int, Dict[str, Any]] = {}

_session_append_count = 0

_ANALYZE_IMAGE_MAX_CHARS = int(os.getenv("RESFES_ANALYZE_IMAGE_MAX_CHARS", str(max(1, MAX_CONTENT_LENGTH_MB) * 1024 * 1024)))

app    = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = max(1, MAX_CONTENT_LENGTH_MB) * 1024 * 1024
if ALLOWED_CORS_ORIGINS:
    CORS(app, resources={r"/*": {"origins": ALLOWED_CORS_ORIGINS}}, supports_credentials=False)
else:
    print("[SECURITY] CORS disabled (same-origin only). Set RESFES_CORS_ORIGINS to allow specific origins.")
_groq_key = os.getenv("GROQ_API_KEY", "").strip()
if not _groq_key:
    print("[WARN] GROQ_API_KEY is empty. Endpoints using Groq may fail.")
client = None
_groq_init_error = ""


def _init_groq_client():
    global client, _groq_init_error
    if not _groq_key:
        client = None
        _groq_init_error = "GROQ_API_KEY is empty"
        return
    try:
        client = Groq(api_key=_groq_key)
        _groq_init_error = ""
    except TypeError as e:
        # Common on Android when groq/httpx versions are mismatched.
        client = None
        _groq_init_error = f"Groq init TypeError: {e}"
        print(f"[WARN] {_groq_init_error}")
    except Exception as e:
        client = None
        _groq_init_error = f"Groq init error: {e}"
        print(f"[WARN] {_groq_init_error}")


def _require_groq_client():
    if client is None:
        raise RuntimeError(_groq_init_error or "Groq client is not initialized")
    return client


_init_groq_client()


def _json_error(message: str, status: int = 400, **extra):
    payload = {"error": message, **extra}
    return jsonify(payload), status


def _set_ingest_status(doc_id: Optional[int], stage: str, message: str = "", progress: int = 0) -> None:
    if not doc_id:
        return
    payload = {
        "stage": (stage or "").strip(),
        "message": (message or "").strip(),
        "progress": max(0, min(int(progress or 0), 100)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _ingest_status_lock:
        _ingest_status_by_doc[int(doc_id)] = payload


def _get_ingest_status(doc_id: Optional[int]) -> Dict[str, Any]:
    if not doc_id:
        return {}
    with _ingest_status_lock:
        return dict(_ingest_status_by_doc.get(int(doc_id), {}))


@app.errorhandler(RequestEntityTooLarge)
def _handle_request_too_large(_err):
    return _json_error(
        "Payload quá lớn.",
        413,
        code="payload_too_large",
        max_mb=max(1, MAX_CONTENT_LENGTH_MB),
    )


def _is_protected_path(path: str) -> bool:
    protected_prefixes = (
        "/analyze",
        "/ask",
        "/chat",
        "/quiz",
        "/kb",
        "/db",
        "/session",
        "/extractor/health",
    )
    return any(path.startswith(prefix) for prefix in protected_prefixes)


def _extract_api_key() -> str:
    candidate = (request.headers.get("X-API-Key") or "").strip()
    if candidate:
        return candidate
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


@app.before_request
def _enforce_api_key_if_configured():
    if not API_KEY:
        return None
    if request.method == "OPTIONS":
        return None
    if not _is_protected_path(request.path):
        return None
    if _extract_api_key() != API_KEY:
        return _json_error("Unauthorized", 401, code="unauthorized")
    return None


@app.before_request
def _mark_request_start():
    g._request_start_ts = time.perf_counter()


@app.after_request
def _attach_response_time(response):
    start = getattr(g, "_request_start_ts", None)
    if start is not None:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()")
    return response

# ==============================================================================
# ==== DATABASE ================================================================
# ==============================================================================

def _open_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=SQLITE_TIMEOUT_SEC)
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def get_db() -> sqlite3.Connection:
    if has_app_context():
        if "db" not in g:
            g.db = _open_db_connection()
        return g.db
    return _open_db_connection()


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Hàm trả về thông tin health (số lượng tài liệu và chunks)
def get_health_info():
    with get_db() as conn:
        docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {"docs": docs, "chunks": chunks}


def get_db_status() -> dict:
    """Trả về trạng thái kết nối DB + thống kê cơ bản."""
    status = {
        "ok": False,
        "db_path": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
        "db_size": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "docs": 0,
        "chunks": 0,
        "vectors": 0,
        "error": "",
    }
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
            status["docs"] = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            status["chunks"] = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            status["vectors"] = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='chunk_vectors'"
            ).fetchone()[0]
            if status["vectors"]:
                status["vectors"] = conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
        status["ok"] = True
    except Exception as e:
        status["error"] = str(e)
    return status


def init_db():
    if not API_KEY and not ALLOW_OPEN_API:
        raise RuntimeError(
            "RESFES_API_KEY is required for protected endpoints. Set RESFES_API_KEY in .env "
            "or enable RESFES_ALLOW_OPEN_API=1 only for local development."
        )
    if not API_KEY and ALLOW_OPEN_API:
        print("[SECURITY] RESFES_API_KEY is empty but RESFES_ALLOW_OPEN_API is enabled. API remains open.")

    conn = _open_db_connection()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            filename      TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_type     TEXT NOT NULL DEFAULT 'txt',
            subject       TEXT DEFAULT '',
            upload_date   TEXT NOT NULL,
            file_size     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_idx INTEGER NOT NULL,
            text      TEXT NOT NULL,
            subject   TEXT DEFAULT '',
            token_count INTEGER NOT NULL DEFAULT 0,
            char_count  INTEGER NOT NULL DEFAULT 0,
            chunk_hash  TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS session_turns (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            timestamp  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_doc  ON chunks(doc_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_subj ON chunks(subject);
        CREATE INDEX IF NOT EXISTS idx_session_turns_sid ON session_turns(session_id, id);
        CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at);
        """)
    finally:
        conn.close()
    print("[DB] Initialized:", DB_PATH)


init_db()


def _migrate_original_names():
    """Backfill original_name from filename for documents lacking it."""
    try:
        conn = _open_db_connection()
        try:
            # Find docs with NULL or empty original_name
            affected = conn.execute(
                "SELECT id, filename FROM documents WHERE original_name IS NULL OR original_name = ''"
            ).fetchall()
            if affected:
                print(f"[DB] Migrating {len(affected)} docs: backfilling original_name from filename...")
                for row in affected:
                    doc_id, filename = row["id"], row["filename"]
                    conn.execute(
                        "UPDATE documents SET original_name = ? WHERE id = ?",
                        (filename, doc_id)
                    )
                conn.commit()
                print(f"[DB] ✅ Migration complete: {len(affected)} docs updated")
        finally:
            conn.close()
    except Exception as e:
        print(f"[DB] Migration warning (safe): {e}")


def _migrate_chunk_metadata():
    """Add chunk metadata columns and backfill useful values for old rows."""
    try:
        conn = _open_db_connection()
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
            if "token_count" not in cols:
                conn.execute("ALTER TABLE chunks ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0")
            if "char_count" not in cols:
                conn.execute("ALTER TABLE chunks ADD COLUMN char_count INTEGER NOT NULL DEFAULT 0")
            if "chunk_hash" not in cols:
                conn.execute("ALTER TABLE chunks ADD COLUMN chunk_hash TEXT NOT NULL DEFAULT ''")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_tokens ON chunks(token_count)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(chunk_hash)")

            affected = conn.execute(
                "SELECT id, text FROM chunks WHERE token_count = 0 OR char_count = 0 OR chunk_hash = ''"
            ).fetchall()
            if affected:
                print(f"[DB] Migrating {len(affected)} chunks: backfilling metadata...")
                updates = []
                for row in affected:
                    normalized_text = re.sub(r'\s+', ' ', row["text"] or "").strip()
                    token_count = len(re.findall(r'\b[\w]+\b', normalized_text.lower()))
                    updates.append((
                        token_count,
                        len(normalized_text),
                        hashlib.sha1(normalized_text.encode("utf-8", errors="ignore")).hexdigest(),
                        row["id"],
                    ))
                conn.executemany(
                    "UPDATE chunks SET token_count = ?, char_count = ?, chunk_hash = ? WHERE id = ?",
                    updates,
                )
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[DB] Chunk metadata migration warning (safe): {e}")


_migrate_original_names()
_migrate_chunk_metadata()
vector_db = None
if VECTOR_DB_ENABLED:
    try:
        vector_db = SQLiteVectorDB(
            db_path=DB_PATH,
            timeout_sec=SQLITE_TIMEOUT_SEC,
            busy_ms=SQLITE_BUSY_MS,
            dim=VECTOR_DIM,
            model_name=VECTOR_MODEL_NAME,
        )
        vector_db.init_schema()
        print(f"[VectorDB] Enabled model={VECTOR_MODEL_NAME} dim={VECTOR_DIM}")
    except Exception as e:
        print(f"[VectorDB] Disabled due to init error: {e}")
        vector_db = None

# ==============================================================================
# ==== RAG PIPELINE ============================================================
# ==============================================================================

# ── Chunking ──────────────────────────────────────────────────────────────────

def split_chunks(text: str, size: int = CHUNK_SIZE,
                 overlap: int = CHUNK_OVERLAP) -> list:
    """Chia văn bản thành chunks theo cửa sổ token, có overlap."""
    # Preserve paragraph breaks as sentence boundaries before collapsing whitespace
    text = re.sub(r'\n{2,}', ' . ', text)   # double newline → sentence break
    text = re.sub(r'\n', ' ', text)           # single newline → space
    text = re.sub(r'[ \t]{2,}', ' ', text).strip()  # collapse spaces only
    if not text:
        return []

    size = max(1, int(size))
    overlap = max(0, min(int(overlap), size - 1))
    step = max(1, size - overlap)

    chunks = []
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÀÁẠẢÃÂẦẤẤẬẨẪĂẰẮẶẲẴĐÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸ])', text)
    current_tokens: list[str] = []

    def flush_current() -> None:
        nonlocal current_tokens
        if current_tokens:
            chunk = " ".join(current_tokens).strip()
            if len(chunk) > 20:
                chunks.append(chunk)
        current_tokens = []

    def seed_from_previous(previous_tokens: list[str]) -> list[str]:
        if overlap <= 0 or not previous_tokens:
            return []
        return previous_tokens[-overlap:]

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        sent_tokens = sent.split()
        if not sent_tokens:
            continue

        if len(sent_tokens) > size:
            prev_tokens = current_tokens.copy()
            flush_current()
            for i in range(0, len(sent_tokens), step):
                part = sent_tokens[i:i + size]
                if len(part) > 0:
                    chunk = " ".join(part).strip()
                    if len(chunk) > 20:
                        chunks.append(chunk)
            current_tokens = prev_tokens[-overlap:] if overlap > 0 else []
            continue

        if len(current_tokens) + len(sent_tokens) <= size:
            current_tokens.extend(sent_tokens)
        else:
            prev_tokens = current_tokens.copy()
            flush_current()
            seed = seed_from_previous(prev_tokens)
            if seed:
                current_tokens = seed + sent_tokens
                if len(current_tokens) > size:
                    current_tokens = sent_tokens.copy()
            else:
                current_tokens = sent_tokens.copy()

    flush_current()
    return chunks


def _build_chunk_records(text: str, file_type: str = "", original_name: str = "",
                         subject: str = "", size: int = CHUNK_SIZE,
                         overlap: int = CHUNK_OVERLAP, skip_contextual: bool = False) -> list[dict]:
    records = []
    for chunk_idx, chunk_text in enumerate(split_chunks(text, size=size, overlap=overlap)):
        normalized_text = re.sub(r'\s+', ' ', chunk_text).strip()
        if original_name and not skip_contextual:
            normalized_text = _generate_chunk_context(normalized_text, original_name, subject)
        if not normalized_text:
            continue
        token_count = len(_tokenize(normalized_text))
        char_count = len(normalized_text)
        chunk_hash = hashlib.sha1(normalized_text.encode("utf-8", errors="ignore")).hexdigest()
        records.append({
            "chunk_idx": chunk_idx,
            "text": normalized_text,
            "subject": (subject or "").strip(),
            "file_type": (file_type or "").strip().lower(),
            "original_name": original_name or "",
            "token_count": token_count,
            "char_count": char_count,
            "chunk_hash": chunk_hash,
        })
    return records


# ── Contextual Retrieval ──────────────────────────────────────────────────────

ENABLE_CONTEXTUAL_RETRIEVAL = os.getenv("RESFES_CONTEXTUAL_RETRIEVAL", "1") == "1"
_contextual_groq_client = None


def _get_contextual_groq_client():
    global _contextual_groq_client
    if _contextual_groq_client is not None:
        return _contextual_groq_client

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is empty")

    _contextual_groq_client = Groq(api_key=api_key)
    return _contextual_groq_client

def _generate_chunk_context(chunk_text: str, doc_name: str, subject: str) -> str:
    """Prepend a Groq-generated context sentence to improve retrieval accuracy."""
    if not ENABLE_CONTEXTUAL_RETRIEVAL:
        return chunk_text
    try:
        time.sleep(0.15)   # ~6 calls/sec, stay under free tier limit
        prompt = (
            f"Tài liệu: '{doc_name}' (môn: {subject or 'chung'})\n"
            f"Đoạn trích: {chunk_text[:400]}\n\n"
            f"Viết 1 câu ngắn (tối đa 20 từ) mô tả đoạn này thuộc phần nào "
            f"của tài liệu. Chỉ trả về câu đó, không giải thích thêm."
        )
        resp = _get_contextual_groq_client().chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            temperature=0.1,
        )
        ctx = resp.choices[0].message.content.strip()
        if ctx:
            return f"[{ctx}] {chunk_text}"
    except Exception as e:
        print(f"[Contextual] Skipped chunk context: {e}")
    return chunk_text


# ── Tokenizer ─────────────────────────────────────────────────────────────────

# Stopwords tiếng Việt thường gặp — lọc bớt noise cho TF-IDF và BM25
_VI_STOPWORDS = {
    "là","và","của","có","trong","với","được","cho","các","một","không","này",
    "đó","từ","để","như","theo","về","khi","thì","bị","hay","ra","vào","đã",
    "sẽ","đang","những","mà","nên","tại","rằng","còn","lại","nhưng","cũng",
    "đây","vì","nếu","sau","trên","dưới","trước","qua","bởi","tuy","dù",
    "the","a","an","is","are","was","were","in","on","at","to","of","and",
    "or","but","for","with","by","from","that","this","it","be","as",
}

def _tokenize(text: str) -> list:
    """Tokenize + bỏ stopwords + giữ số và ký hiệu toán học."""
    tokens = re.findall(r'\b[\w]+\b', text.lower())
    return [t for t in tokens if t not in _VI_STOPWORDS and len(t) > 1]


# ── TF-IDF + Cosine Similarity ────────────────────────────────────────────────

def _compute_tf(tokens: list) -> dict:
    tf: dict = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    total = len(tokens) or 1
    return {t: c / total for t, c in tf.items()}


def _build_tfidf(chunks: list) -> tuple:
    """Trả về (tf_docs, idf) cho một tập chunks."""
    tf_docs = [_compute_tf(_tokenize(c)) for c in chunks]
    N = len(chunks)
    idf: dict = {}
    vocab: set = set()
    for tf in tf_docs:
        vocab.update(tf.keys())
    for term in vocab:
        df = sum(1 for tf in tf_docs if term in tf)
        idf[term] = math.log((N + 1) / (df + 1)) + 1
    return tf_docs, idf


def _tfidf_vec(tf: dict, idf: dict) -> dict:
    return {t: tf[t] * idf.get(t, 1.0) for t in tf}


def _cosine(a: dict, b: dict) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na  = math.sqrt(sum(v * v for v in a.values())) or 1e-9
    nb  = math.sqrt(sum(v * v for v in b.values())) or 1e-9
    return dot / (na * nb)


# ── BM25 (thuần Python, không cần cài thêm) ───────────────────────────────────
# BM25 xử lý tốt hơn TF-IDF khi chunks có độ dài khác nhau nhiều.
# k1=1.5: tần suất từ tăng thêm, b=0.75: normalize độ dài document.

_BM25_K1 = float(os.getenv("RESFES_BM25_K1", "1.5"))
_BM25_B  = float(os.getenv("RESFES_BM25_B",  "0.75"))

def _bm25_score(query_tokens: list, doc_tokens: list,
                idf: dict, avgdl: float) -> float:
    """BM25 score cho 1 document với 1 query."""
    dl   = len(doc_tokens) or 1
    freq: dict = {}
    for t in doc_tokens:
        freq[t] = freq.get(t, 0) + 1
    score = 0.0
    for term in query_tokens:
        if term not in idf:
            continue
        f  = freq.get(term, 0)
        tf = (f * (_BM25_K1 + 1)) / (f + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avgdl))
        score += idf[term] * tf
    return score


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────
# Kết hợp kết quả từ nhiều ranker khác nhau.
# RRF(d) = Σ 1/(k + rank_i(d)) — k=60 là giá trị chuẩn từ paper gốc.

_RRF_K = int(os.getenv("RESFES_RRF_K", "60"))

def _rrf_fuse(ranked_lists: list[list], top_k: int) -> list:
    """
    Nhận nhiều list đã sort theo điểm, trả về list fused theo RRF.
    Mỗi phần tử trong ranked_lists là list của (chunk_id, chunk_dict).
    """
    scores: dict = {}
    for ranked in ranked_lists:
        for rank, (cid, chunk) in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
    # Sort theo RRF score giảm dần
    sorted_ids = sorted(scores, key=lambda x: -scores[x])
    return sorted_ids[:top_k]


# ── In-memory cache (lazy rebuild khi DB thay đổi) ────────────────────────────

_vec_cache: dict = {}
_cache_dirty     = True
_vec_cache_built_at = 0.0


def _invalidate_cache():
    global _cache_dirty
    _cache_dirty = True


def _cache_is_stale() -> bool:
    if _cache_dirty:
        return True
    if RAG_CACHE_TTL_SEC <= 0:
        return False
    return (time.time() - _vec_cache_built_at) > RAG_CACHE_TTL_SEC


def _prune_expand_cache(now: Optional[float] = None) -> None:
    if not _EXPAND_CACHE:
        return
    current = now if now is not None else time.time()
    ttl = max(1, EXPAND_CACHE_TTL_SEC)
    expired = [key for key, value in _EXPAND_CACHE.items() if current - value[0] > ttl]
    for key in expired:
        _EXPAND_CACHE.pop(key, None)


def _ensure_cache():
    global _vec_cache, _cache_dirty, _vec_cache_built_at
    if not _cache_is_stale():
        return
    print("[RAG] Rebuilding hybrid cache (TF-IDF + BM25)...")

    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.id, c.doc_id, c.text, c.subject, c.token_count, c.char_count, c.chunk_hash,
                      d.file_type, d.original_name
               FROM chunks c
               JOIN documents d ON d.id = c.doc_id"""
        ).fetchall()

    by_group: dict = {"__all__": []}
    for row in rows:
        if _is_extraction_placeholder(row["text"], ""):
            continue
        text_value = row["text"] or ""
        token_count = int(row["token_count"] or len(_tokenize(text_value)))
        char_count = int(row["char_count"] or len(text_value))
        chunk_hash = row["chunk_hash"] or hashlib.sha1(
            re.sub(r'\s+', ' ', text_value).strip().encode("utf-8", errors="ignore")
        ).hexdigest()
        chunk = {"id": row["id"], "doc_id": row["doc_id"],
                 "text": text_value, "subject": row["subject"],
                 "file_type": (row["file_type"] or "").strip().lower(),
                 "original_name": row["original_name"] or "",
                 "token_count": token_count,
                 "char_count": char_count,
                 "chunk_hash": chunk_hash}
        by_group["__all__"].append(chunk)
        s = (row["subject"] or "").lower().strip()
        if s:
            by_group.setdefault(s, []).append(chunk)

    new_cache: dict = {}
    group_sizes: dict[str, int] = {}
    for key, chunk_list in by_group.items():
        augmented_chunks = list(chunk_list)
        if not LOW_MEMORY_MODE:
            token_docs_preview = [_tokenize(c["text"]) for c in chunk_list]
            for idx, c in enumerate(chunk_list):
                tok = token_docs_preview[idx]
                if len(tok) > int(CHUNK_SIZE * CHUNK_AUGMENT_THRESHOLD):
                    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
                    words = c["text"].split()
                    added = 0
                    for i in range(0, max(1, len(words) - CHUNK_SIZE + 1), step):
                        if added >= CHUNK_AUGMENT_MAX_PER_CHUNK:
                            break
                        part = words[i:i + CHUNK_SIZE]
                        subtext = " ".join(part).strip()
                        if subtext and len(subtext) > 20:
                            synth = {
                                "id": int(c["id"]) * 1000 + 1 + added,
                                "doc_id": c["doc_id"],
                                "text": subtext,
                                "subject": c.get("subject", ""),
                            }
                            augmented_chunks.append(synth)
                            added += 1

        texts = [c["text"] for c in augmented_chunks]
        token_docs = [_tokenize(t) for t in texts]
        tf_docs, idf = _build_tfidf(texts)
        avgdl = (sum(len(td) for td in token_docs) / len(token_docs)) if token_docs else 1.0

        new_cache[key] = {
            "chunks": augmented_chunks,
            "tf_docs": tf_docs,
            "idf": idf,
            "token_docs": token_docs,
            "avgdl": avgdl,
        }
        group_sizes[key] = len(augmented_chunks)

    if LOW_MEMORY_MODE or (RAG_CACHE_MAX_GROUPS > 0 and len(new_cache) > RAG_CACHE_MAX_GROUPS):
        keep_keys = ["__all__"]
        subject_keys = [k for k in new_cache.keys() if k != "__all__"]
        subject_keys.sort(key=lambda k: group_sizes.get(k, 0), reverse=True)
        keep_keys.extend(subject_keys[: max(0, RAG_CACHE_MAX_GROUPS - 1)])
        new_cache = {k: new_cache[k] for k in keep_keys if k in new_cache}

    _vec_cache   = new_cache
    _cache_dirty = False
    _vec_cache_built_at = time.time()
    total = len(by_group.get("__all__", []))
    print(f"[RAG] Cache ready — {total} chunks, {len(new_cache)} groups")


def _normalize_file_types(file_types: Optional[List[str]]) -> set[str]:
    normalized = set()
    for file_type in file_types or []:
        value = str(file_type or "").strip().lower()
        if value:
            normalized.add(value)
    return normalized


def _chunk_matches_filters(chunk: dict, file_types: Optional[set[str]] = None,
                           min_chunk_tokens: int = 0,
                           max_chunk_tokens: int = 0) -> bool:
    if file_types:
        chunk_file_type = (chunk.get("file_type") or "").strip().lower()
        if chunk_file_type not in file_types:
            return False

    token_count = int(chunk.get("token_count") or len(_tokenize(chunk.get("text", ""))))
    if min_chunk_tokens > 0 and token_count < min_chunk_tokens:
        return False
    if max_chunk_tokens > 0 and token_count > max_chunk_tokens:
        return False
    return True


# ── Query expansion (paraphrase bằng Groq) ────────────────────────────────────
# Sinh thêm 2 biến thể query → tăng recall khi học sinh hỏi theo cách khác.
# Chỉ gọi khi query đủ ngắn (< 120 ký tự) để tiết kiệm token.

_EXPAND_CACHE: OrderedDict[str, tuple[float, list[str]]] = OrderedDict()   # query → (ts, [variant1, variant2])


def _expand_cache_get(query: str) -> Optional[list[str]]:
    _prune_expand_cache()
    cached = _EXPAND_CACHE.get(query)
    if cached is None:
        return None
    cached_at, result = cached
    if EXPAND_CACHE_TTL_SEC > 0 and (time.time() - cached_at) > EXPAND_CACHE_TTL_SEC:
        _EXPAND_CACHE.pop(query, None)
        return None
    _EXPAND_CACHE.move_to_end(query)
    return result


def _expand_cache_set(query: str, result: list[str]) -> None:
    _EXPAND_CACHE[query] = (time.time(), result)
    _EXPAND_CACHE.move_to_end(query)
    _prune_expand_cache()
    while len(_EXPAND_CACHE) > max(1, EXPAND_CACHE_MAX):
        _EXPAND_CACHE.popitem(last=False)


def _expand_query(query: str) -> list[str]:
    """Trả về [query gốc] + tối đa 2 paraphrase từ Groq. Fail-safe."""
    if len(query) > 120 or client is None:
        return [query]
    cached = _expand_cache_get(query)
    if cached is not None:
        return cached

    try:
        res = _require_groq_client().chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=120,
            temperature=0.4,
            messages=[{
                "role": "user",
                "content": (
                    f'Viết lại câu hỏi sau theo 2 cách khác, ngắn gọn, '
                    f'chỉ trả về 2 dòng, không đánh số, không giải thích:\n"{query}"'
                )
            }]
        )
        raw    = res.choices[0].message.content.strip()
        extras = [ln.strip().strip('"').strip("'")
                  for ln in raw.splitlines() if ln.strip()][:2]
        result = [query] + [e for e in extras if e and e != query]
        _expand_cache_set(query, result)
        print(f"[RAG] Query expanded: {result}")
        return result
    except Exception as e:
        print(f"[RAG] Query expand failed (ok): {e}")
        return [query]


# ── Hybrid semantic search: TF-IDF + BM25 + RRF + optional query expansion ────

def semantic_search(query: str, subject: Optional[str] = None,
                    doc_ids: Optional[List[int]] = None,
                    file_types: Optional[List[str]] = None,
                    min_chunk_tokens: int = 0,
                    max_chunk_tokens: int = 0,
                    top_k: int = TOP_K,
                    expand: bool = False) -> list:
    """
    Hybrid search: TF-IDF cosine + BM25 → fuse bằng RRF.
    expand=True: sinh thêm query variants, search song song, merge kết quả.
    Kết quả trả về đã dedup, sorted by RRF score, kèm cả tfidf_score và bm25_score.
    """
    doc_id_set = {int(d) for d in (doc_ids or []) if str(d).strip().isdigit()}
    file_type_set = _normalize_file_types(file_types)
    min_chunk_tokens = max(0, int(min_chunk_tokens or 0))
    max_chunk_tokens = max(0, int(max_chunk_tokens or 0))

    _ensure_cache()

    key = (subject or "").lower().strip() if subject else "__all__"
    if key not in _vec_cache:
        key = "__all__"
    if key not in _vec_cache:
        return []

    cache      = _vec_cache[key]
    idf        = cache["idf"]
    avgdl      = cache["avgdl"]
    chunks     = cache["chunks"]
    tf_docs    = cache["tf_docs"]
    token_docs = cache["token_docs"]
    vector_ranked: list[list] = []
    vector_scores: dict[int, float] = {}

    if doc_id_set or file_type_set or min_chunk_tokens > 0 or max_chunk_tokens > 0:
        filtered_chunks = []
        filtered_tf_docs = []
        filtered_token_docs = []
        for idx, chunk in enumerate(chunks):
            if doc_id_set and chunk.get("doc_id") not in doc_id_set:
                continue
            if not _chunk_matches_filters(chunk, file_type_set or None, min_chunk_tokens, max_chunk_tokens):
                continue
            filtered_chunks.append(chunk)
            filtered_tf_docs.append(tf_docs[idx])
            filtered_token_docs.append(token_docs[idx])
        if not filtered_chunks:
            return []
        chunks = filtered_chunks
        tf_docs = filtered_tf_docs
        token_docs = filtered_token_docs

    if vector_db is not None:
        try:
            v_results = vector_db.search(
                query=query,
                top_k=max(top_k * 2, top_k),
                subject=subject,
                doc_ids=sorted(doc_id_set) if doc_id_set else None,
                file_types=sorted(file_type_set) if file_type_set else None,
                min_chunk_tokens=min_chunk_tokens,
                max_chunk_tokens=max_chunk_tokens,
            )
            v_results = [r for r in v_results if not _is_extraction_placeholder(r.get("text", ""), "")]
            if v_results:
                chunk_by_id = {c["id"]: c for c in chunks}
                for r in v_results:
                    cid = int(r.get("chunk_id", 0))
                    vector_scores[cid] = float(r.get("score", 0.0) or 0.0)
                vector_ranked.append([
                    (int(r["chunk_id"]), chunk_by_id.get(int(r["chunk_id"]), {
                        "id": int(r["chunk_id"]),
                        "doc_id": int(r.get("doc_id", 0)),
                        "text": r.get("text", "") or "",
                        "subject": r.get("subject", "") or "",
                    }))
                    for r in v_results
                    if int(r.get("chunk_id", 0)) in chunk_by_id
                ])
                top = v_results[0]["score"] if v_results else 0
                print(f"[RAG:VectorDB] '{query[:50]}' → {len(v_results)} (top={top:.3f})")
        except Exception as e:
            print(f"[RAG:VectorDB] fallback hybrid due to: {e}")

    # Lấy danh sách queries (với hoặc không expansion)
    queries = _expand_query(query) if expand else [query]

    # Thu thập rank list cho mỗi query, mỗi method
    all_ranked: list[list] = []

    for q in queries:
        q_tokens  = _tokenize(q)
        tf_q      = _compute_tf(q_tokens)
        vec_q     = _tfidf_vec(tf_q, idf)

        tfidf_scored: list[tuple] = []
        bm25_scored:  list[tuple] = []

        for i, chunk in enumerate(chunks):
            cid = chunk["id"]
            # TF-IDF cosine
            vec_c       = _tfidf_vec(tf_docs[i], idf)
            tfidf_score = _cosine(vec_q, vec_c)
            if tfidf_score > 0:
                tfidf_scored.append((tfidf_score, cid))

            # BM25
            bm25_score = _bm25_score(q_tokens, token_docs[i], idf, avgdl)
            if bm25_score > 0:
                bm25_scored.append((bm25_score, cid))

        # Sort giảm dần và chuyển thành (cid, chunk) cho RRF
        tfidf_scored.sort(key=lambda x: -x[0])
        bm25_scored.sort( key=lambda x: -x[0])

        chunk_by_id = {c["id"]: c for c in chunks}
        all_ranked.append([(cid, chunk_by_id[cid]) for _, cid in tfidf_scored if cid in chunk_by_id])
        all_ranked.append([(cid, chunk_by_id[cid]) for _, cid in bm25_scored  if cid in chunk_by_id])

    if vector_ranked:
        all_ranked.extend(vector_ranked)

    # RRF fusion
    chunk_by_id = {c["id"]: c for c in chunks}
    fused_ids   = _rrf_fuse(all_ranked, top_k=top_k * 2)   # lấy rộng để rerank

    # Build result — tính điểm final = trung bình tfidf+bm25 của query gốc
    # (chỉ dùng để hiển thị, sort thực tế đã theo RRF)
    q0_tokens = _tokenize(queries[0])
    tf_q0     = _compute_tf(q0_tokens)
    vec_q0    = _tfidf_vec(tf_q0, idf)
    chunk_idx = {c["id"]: i for i, c in enumerate(chunks)}

    results = []
    for cid in fused_ids[:top_k]:
        if cid not in chunk_by_id:
            continue
        chunk = chunk_by_id[cid]
        idx   = chunk_idx.get(cid, 0)
        ts    = _cosine(vec_q0, _tfidf_vec(tf_docs[idx], idf))
        bs    = _bm25_score(q0_tokens, token_docs[idx], idf, avgdl)
        vs    = vector_scores.get(cid, 0.0)
        parts = [ts, min(bs / 10, 1.0)]
        if vs > 0:
            parts.append(vs)
        results.append({
            "chunk_id":    cid,
            "doc_id":      chunk["doc_id"],
            "text":        chunk["text"],
            "subject":     chunk["subject"],
            "file_type":   chunk.get("file_type", ""),
            "original_name": chunk.get("original_name", ""),
            "token_count": int(chunk.get("token_count", len(_tokenize(chunk.get("text", "")))) or 0),
            "char_count":  int(chunk.get("char_count", len(chunk.get("text", ""))) or 0),
            "chunk_hash":  chunk.get("chunk_hash", ""),
            "score":       round(sum(parts) / len(parts), 4),
            "tfidf_score": round(ts, 4),
            "bm25_score":  round(bs, 4),
            "vector_score": round(vs, 4),
        })

    deduped = []
    seen_hashes: set[str] = set()
    for item in results:
        chunk_hash = item.get("chunk_hash") or hashlib.sha1(
            re.sub(r'\s+', ' ', item.get("text", "")).strip().encode("utf-8", errors="ignore")
        ).hexdigest()
        if chunk_hash in seen_hashes:
            continue
        seen_hashes.add(chunk_hash)
        deduped.append(item)

    mode = f"hybrid+expand({len(queries)}q)" if expand else "hybrid"
    top  = deduped[0]["score"] if deduped else 0
    print(f"[RAG:{mode}] '{query[:50]}' → {len(deduped)} chunks (top={top:.3f})")
    return deduped


# ── Document ingestion ────────────────────────────────────────────────────────

def _infer_file_type(filename: str, mime_type: str = "", declared_type: str = "") -> str:
    """Ưu tiên file type phía client, fallback theo đuôi file/mime."""
    declared = (declared_type or "").strip().lower()
    if declared in {
        "pdf", "txt", "md", "csv", "json", "html", "xml", "rtf",
        "docx", "xlsx", "pptx", "doc", "xls", "ppt",
        "jpg", "jpeg", "png", "webp", "bmp", "gif", "image"
    }:
        return "jpg" if declared == "image" else declared

    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext:
        return ext

    mime = (mime_type or "").lower()
    if "pdf" in mime:
        return "pdf"
    if "word" in mime:
        return "docx"
    if "spreadsheet" in mime or "excel" in mime:
        return "xlsx"
    if "presentation" in mime or "powerpoint" in mime:
        return "pptx"
    if "json" in mime:
        return "json"
    if "xml" in mime:
        return "xml"
    if "html" in mime:
        return "html"
    if "csv" in mime:
        return "csv"
    if "markdown" in mime:
        return "md"
    if mime.startswith("text/"):
        return "txt"
    if mime.startswith("image/"):
        return "jpg"
    return "txt"


def _decode_text_bytes(file_bytes: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return file_bytes.decode(enc)
        except Exception:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def _extract_text_via_remote(file_bytes: bytes, file_type: str, filename: str, retries: int = 2) -> str:
    """Gọi extractor service (nếu có) để đọc các định dạng khó trên Android (DOCX, PPTX, hình ảnh).
    
    Args:
        file_bytes: Nội dung tệp nhị phân
        file_type: Loại tệp (docx, pptx, jpg, v.v.)
        filename: Tên tệp gốc
        retries: Số lần thử lại nếu thất bại
        
    Returns:
        Text được trích xuất, hoặc chuỗi rỗng nếu không thành công
    """
    if not EXTRACTOR_SERVER_URL:
        return ""
    
    payload = {
        "file": base64.b64encode(file_bytes).decode("ascii"),
        "filename": filename,
        "file_type": file_type,
    }
    
    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{EXTRACTOR_SERVER_URL.rstrip('/')}/extract",
                json=payload,
                timeout=EXTRACTOR_REMOTE_TIMEOUT_SEC,
            )
            if not resp.ok:
                if attempt < retries - 1:
                    print(f"[Extractor] Attempt {attempt+1}/{retries} failed (status={resp.status_code}), retrying...")
                    continue
                else:
                    print(f"[Extractor] Final attempt failed (status={resp.status_code})")
                    return ""
            
            data = resp.json() if resp.content else {}
            text = (data.get("text") or "").strip()
            if text:
                print(f"[Extractor] SUCCESS for {filename} ({file_type}) on attempt {attempt+1}")
                return text
            else:
                print(f"[Extractor] No text extracted for {filename}")
                return ""
        except requests.Timeout:
            if attempt < retries - 1:
                print(f"[Extractor] Timeout on attempt {attempt+1}/{retries}, retrying...")
                continue
            else:
                print(f"[Extractor] Timeout after {retries} attempts")
                return ""
        except Exception as e:
            if attempt < retries - 1:
                print(f"[Extractor] Error on attempt {attempt+1}/{retries}: {e}, retrying...")
                continue
            else:
                print(f"[Extractor] Final error after {retries} attempts: {e}")
                return ""
    
    return ""


def _extract_text(file_bytes: bytes, file_type: str, filename: str) -> str:
    """Trích text từ nhiều định dạng tài liệu để index RAG."""
    f = (file_type or "").strip().lower()
    android_runtime = _is_android_runtime()
    try:
        if f == "pdf":
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(BytesIO(file_bytes))
                return "\n".join(p.extract_text() or "" for p in reader.pages).strip()
            except ImportError:
                return f"[PDF: {filename} — pip install PyPDF2 để đọc nội dung]"

        if f in {"txt", "md", "csv", "json", "html", "xml", "rtf", "log", "yaml", "yml"}:
            return _decode_text_bytes(file_bytes)

        if f == "docx":
            if android_runtime:
                remote_text = _extract_text_via_remote(file_bytes, f, filename)
                if remote_text:
                    return remote_text
                return f"[DOCX: {filename} — parser DOCX local tắt trên Android. Hãy bật RESFES_EXTRACTOR_SERVER_URL hoặc xuất sang PDF/TXT.]"
            try:
                docx_mod = importlib.import_module("docx")
                doc = docx_mod.Document(BytesIO(file_bytes))
                lines = [p.text for p in doc.paragraphs if (p.text or "").strip()]
                return "\n".join(lines).strip()
            except ImportError:
                return f"[DOCX: {filename} — thiếu python-docx]"

        if f == "xlsx":
            try:
                openpyxl_mod = importlib.import_module("openpyxl")
                wb = openpyxl_mod.load_workbook(BytesIO(file_bytes), data_only=True, read_only=True)
                rows = []
                for sheet in wb.worksheets:
                    rows.append(f"[Sheet: {sheet.title}]")
                    for row in sheet.iter_rows(values_only=True):
                        vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
                        if vals:
                            rows.append(" | ".join(vals))
                return "\n".join(rows).strip()
            except ImportError:
                return f"[XLSX: {filename} — thiếu openpyxl]"

        if f == "pptx":
            if android_runtime:
                remote_text = _extract_text_via_remote(file_bytes, f, filename)
                if remote_text:
                    return remote_text
                return f"[PPTX: {filename} — parser PPTX local tắt trên Android. Hãy bật RESFES_EXTRACTOR_SERVER_URL hoặc xuất sang PDF/TXT.]"
            try:
                pptx_mod = importlib.import_module("pptx")
                prs = pptx_mod.Presentation(BytesIO(file_bytes))
                lines = []
                for i, slide in enumerate(prs.slides, start=1):
                    lines.append(f"[Slide {i}]")
                    for shape in slide.shapes:
                        text = getattr(shape, "text", "")
                        if text and text.strip():
                            lines.append(text.strip())
                return "\n".join(lines).strip()
            except ImportError:
                return f"[PPTX: {filename} — thiếu python-pptx]"

        if f in {"doc", "xls", "ppt"}:
            remote_text = _extract_text_via_remote(file_bytes, f, filename)
            if remote_text:
                return remote_text
            return (
                f"[{f.upper()}: {filename} — định dạng Office cũ chưa hỗ trợ trực tiếp. "
                "Vui lòng chuyển sang DOCX/XLSX/PPTX.]"
            )

        if f in {"jpg", "jpeg", "png", "webp", "bmp", "gif"}:
            remote_text = _extract_text_via_remote(file_bytes, f, filename)
            if remote_text:
                return remote_text
            return f"[IMAGE: {filename} — ảnh được lưu, chưa OCR trong pipeline upload tài liệu.]"

        return _decode_text_bytes(file_bytes)
    except Exception as e:
        return f"[Lỗi đọc {filename}: {e}]"


def _default_ext_for_type(file_type: str) -> str:
    f = (file_type or "").lower().strip()
    if f in {"pdf", "txt", "md", "csv", "json", "html", "xml", "rtf", "docx", "xlsx", "pptx", "doc", "xls", "ppt"}:
        return f".{f}"
    if f in {"image", "img", "png", "jpg", "jpeg", "webp", "bmp", "gif"}:
        return ".jpg"
    return ".txt"


def _normalize_upload_name(filename: str, display_name: str, file_type: str) -> str:
    """Chuẩn hóa tên tài liệu hiển thị trong DB và đảm bảo có đuôi file."""
    raw_filename = (filename or "").strip()
    raw_display = (display_name or "").strip()

    ext = Path(raw_filename).suffix.strip()
    if not ext and raw_display:
        ext = Path(raw_display).suffix.strip()
    if not ext:
        ext = _default_ext_for_type(file_type)

    base_source = raw_display or Path(raw_filename).stem or "tai_lieu"
    base = re.sub(r"\s+", " ", base_source).strip()
    base = re.sub(r"[\\/:*?\"<>|]+", "_", base).strip(" ._") or "tai_lieu"
    if len(base) > 80:
        base = base[:80].rstrip(" ._")

    ext_lower = ext.lower()
    if ext_lower and base.lower().endswith(ext_lower):
        return base
    return f"{base}{ext_lower}"


def _is_extraction_placeholder(text: str, file_type: str) -> bool:
    """Detect placeholder/error text which should not be indexed into RAG."""
    t = (text or "").strip()
    f = (file_type or "").strip().lower()
    if not t:
        return True
    if not t.startswith("["):
        return False
    if t.startswith("[Lỗi đọc"):
        return True
    if t.startswith(("[DOCX:", "[PPTX:", "[IMAGE:", "[DOC:", "[XLS:", "[PPT:", "[PDF:", "[XLSX:")):
        return True
    if f == "docx" and t.startswith("[DOCX:"):
        return True
    if f == "pptx" and t.startswith("[PPTX:"):
        return True
    if f in {"doc", "xls", "ppt"} and t.startswith(f"[{f.upper()}:"):
        return True
    if f in {"jpg", "jpeg", "png", "webp", "bmp", "gif", "image"} and t.startswith("[IMAGE:"):
        return True
    return False


def _build_ingest_warning(text: str, file_type: str, filename: str, extraction_warning: str = "") -> str:
    if extraction_warning:
        if extraction_warning.startswith("[PDF:") and "pip install PyPDF2" in extraction_warning:
            return (
                f"[PDF: {filename} — file này có thể là bản scan/ảnh nên chưa trích được văn bản để tạo chunks. "
                "Nếu đây là PDF chữ, hãy kiểm tra file có bị hỏng hoặc thiếu thư viện đọc PDF.]"
            )
        return extraction_warning

    if (text or "").strip():
        return ""

    ext = (file_type or "").strip().upper() or "FILE"
    if (file_type or "").strip().lower() == "pdf":
        return (
            f"[PDF: {filename} — file này có thể là bản scan/ảnh nên chưa trích được văn bản để tạo chunks. "
            "Nếu đây là PDF chữ, hãy kiểm tra file có bị hỏng hoặc thử xuất lại từ nguồn gốc.]"
        )
    return (
        f"[{ext}: {filename} — không trích được nội dung để tạo chunks. "
        "Có thể file là scan/image-only, file hỏng, hoặc định dạng chưa được parser hỗ trợ.]"
    )


def _extractive_chat_reply(user_message: str, kb_context: str, scan_context: str = "") -> str:
    """Lightweight no-LLM fallback reply for Android stability mode."""
    primary = (kb_context or "").strip()
    secondary = (scan_context or "").strip()
    source_text = primary or secondary
    if not source_text:
        return "Mình chưa tìm thấy nội dung phù hợp trong tài liệu đã index. Hãy kiểm tra lại file đã upload hoặc thử hỏi cụ thể hơn."

    q_tokens = _tokenize(user_message)
    candidates = [ln.strip() for ln in re.split(r"[\n\r]+", source_text) if ln.strip() and ln.strip() != "---"]
    if not candidates:
        return "Mình chưa tìm thấy đoạn phù hợp trong tài liệu."

    scored = []
    for ln in candidates:
        ln_tokens = set(_tokenize(ln))
        overlap = sum(1 for t in q_tokens if t in ln_tokens)
        scored.append((overlap, len(ln), ln))

    scored.sort(key=lambda x: (-x[0], -x[1]))
    best_lines = [x[2] for x in scored[:2] if x[2]]
    if not best_lines:
        best_lines = [candidates[0]]

    condensed = " ".join(best_lines)
    if len(condensed) > 280:
        condensed = condensed[:280].rstrip() + "..."

    return f"Theo tài liệu đã tải lên: {condensed}"


def ingest_document(file_bytes: bytes, original_name: str,
                    file_type: str = "txt", subject: str = "") -> dict:
    """Lưu file, chunk, index vào SQLite. Trả về metadata."""
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe     = re.sub(r'[^\w.\-]', '_', original_name)
    filename = f"{ts}_{safe}"
    (UPLOAD_DIR / filename).write_bytes(file_bytes)

    normalized_type = _infer_file_type(original_name, declared_type=file_type)
    text   = _extract_text(file_bytes, normalized_type, original_name)
    extraction_warning = ""
    if _is_extraction_placeholder(text, normalized_type):
        extraction_warning = text
        chunk_records = []
    else:
        chunk_records = _build_chunk_records(text, file_type=normalized_type, original_name=original_name, subject=subject, skip_contextual=True)
    print(f"[INGEST] {original_name}: {len(text)} chars → {len(chunk_records)} chunks")

    chunk_rows = []
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO documents "
            "(filename, original_name, file_type, subject, upload_date, file_size) "
            "VALUES (?,?,?,?,?,?)",
              (filename, original_name, normalized_type, subject,
             datetime.now().isoformat(), len(file_bytes))
        )
        doc_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO chunks (doc_id, chunk_idx, text, subject, token_count, char_count, chunk_hash) VALUES (?,?,?,?,?,?,?)",
            [(
                doc_id,
                item["chunk_idx"],
                item["text"],
                item["subject"],
                item["token_count"],
                item["char_count"],
                item["chunk_hash"],
            ) for item in chunk_records]
        )

        if vector_db is not None and chunk_records:
            chunk_rows = conn.execute(
                "SELECT id, text FROM chunks WHERE doc_id=? ORDER BY chunk_idx ASC",
                (doc_id,),
            ).fetchall()

    vector_count = 0
    if vector_db is not None:
        try:
            vector_count = vector_db.upsert_document_chunks(
                doc_id=doc_id,
                chunks=chunk_rows,
                subject=subject,
            )
        except Exception as e:
            print(f"[VectorDB] Index warning for doc_id={doc_id}: {e}")

    _invalidate_cache()
    warning = _build_ingest_warning(text, normalized_type, original_name, extraction_warning)
    return {"id": doc_id, "filename": filename,
            "chunks": len(chunk_records), "file_size": len(file_bytes),
            "vector_chunks": vector_count,
            "original_name": original_name,
            "indexed": bool(chunk_records),
            "warning": warning}


# ── Answer generation ─────────────────────────────────────────────────────────

def generate_answer(question: str, chunks: list, subject: str = "") -> str:
    """Gọi Groq sinh câu trả lời từ retrieved chunks, có citation số đoạn."""
    if not chunks:
        return "Không tìm thấy tài liệu liên quan trong knowledge base."

    # Đánh số đoạn để model có thể cite
    context_parts = []
    for i, c in enumerate(chunks):
        score_info = f" [BM25={c.get('bm25_score',0):.2f}]" if c.get("bm25_score") else ""
        context_parts.append(f"[Đoạn {i+1}{score_info}]\n{c['text']}")
    context = "\n\n".join(context_parts)

    subject_ctx = f"Môn học: {subject}.\n" if subject else ""

    system_msg = (
        "Bạn là trợ lý học tập AR. Nhiệm vụ: trả lời câu hỏi DỰA HOÀN TOÀN vào tài liệu được cung cấp.\n"
        "Quy tắc:\n"
        "- Chỉ dùng thông tin có trong các đoạn tài liệu. Nếu không đủ thông tin, nói rõ.\n"
        "- Trả lời ngắn gọn (tối đa 4 câu), tiếng Việt, không dùng markdown.\n"
        "- Có thể ghi '(theo đoạn N)' để học sinh biết nguồn.\n"
        "- KHÔNG bịa thêm thông tin ngoài tài liệu."
    )
    prompt = (
        f"{subject_ctx}Tài liệu tham khảo:\n\n{context}\n\n"
        f"Câu hỏi của học sinh: {question}"
    )

    try:
        res = _require_groq_client().chat.completions.create(
            model=GROQ_MODEL, max_tokens=600, temperature=0.2,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": prompt},
            ]
        )
        answer = res.choices[0].message.content.strip()
        print(f"[RAG] Answer ({len(chunks)} chunks): {answer[:80]!r}")
        return answer
    except Exception as e:
        print(f"[RAG] Groq error: {e}")
        return f"Lỗi sinh câu trả lời: {e}"


def _safe_json_from_llm(raw_text: str) -> dict:
    text = (raw_text or "").strip()
    if not text:
        return {}
    if "```" in text:
        for part in text.split("```"):
            cand = part.strip()
            if cand.startswith("json"):
                cand = cand[4:].strip()
            if cand.startswith("{") and cand.endswith("}"):
                text = cand
                break
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                return {}
        return {}


def _llm_json_call(system_msg: str, user_msg: str,
                   max_tokens: int = 500,
                   temperature: float = 0.2) -> dict:
    if client is None:
        return {}
    try:
        res = _require_groq_client().chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        raw = (res.choices[0].message.content or "").strip()
        return _safe_json_from_llm(raw)
    except Exception as e:
        print(f"[RAG] LLM JSON call failed: {e}")
        return {}


def _compact_evidence(chunks: list, max_chars: int = 420) -> list:
    compact = []
    for i, c in enumerate(chunks, start=1):
        text = (c.get("text") or "").strip().replace("\n", " ")
        compact.append({
            "id": i,
            "subject": c.get("subject", ""),
            "score": round(float(c.get("score", 0)), 4),
            "text": text[:max_chars],
        })
    return compact


def _fallback_filter(question: str, chunks: list,
                     keep_k: int,
                     tag: str) -> Tuple[list, str]:
    q_tokens = set(_tokenize(question))
    scored = []
    for c in chunks:
        ct = c.get("text", "")
        overlap = len(q_tokens & set(_tokenize(ct)))
        blend = 0.65 * overlap + 0.35 * float(c.get("score", 0))
        scored.append((blend, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [item[1] for item in scored[:keep_k]]
    note = f"{tag} fallback picked top {len(selected)} by token-overlap+retrieval-score"
    return selected, note


def _run_filter_agent(agent_name: str,
                      question: str,
                      chunks: list,
                      keep_k: int) -> Tuple[list, str]:
    if not chunks:
        return [], "no evidence"

    compact = _compact_evidence(chunks)
    strategy = {
        "summarizer": "Ưu tiên đoạn có thể tóm tắt ý chính để trả lời nhanh.",
        "extractor": "Ưu tiên đoạn có dữ kiện, định nghĩa, số liệu, mệnh đề trực tiếp.",
        "reasoner": "Ưu tiên đoạn giúp suy luận nhiều bước hoặc giải thích quan hệ nguyên nhân-kết quả.",
    }.get(agent_name, "Ưu tiên đoạn liên quan nhất.")

    payload = {
        "question": question,
        "keep_k": keep_k,
        "strategy": strategy,
        "evidence": compact,
    }
    system_msg = (
        "Bạn là Filter Agent của hệ RAG. "
        "Chỉ trả về JSON hợp lệ: {\"selected_ids\":[...],\"notes\":\"...\"}. "
        "selected_ids phải theo id trong evidence và tối đa keep_k phần tử."
    )
    data = _llm_json_call(system_msg, json.dumps(payload, ensure_ascii=False),
                          max_tokens=260, temperature=0.1)
    selected_ids = data.get("selected_ids") if isinstance(data, dict) else []
    if not isinstance(selected_ids, list):
        selected_ids = []

    by_id = {i + 1: c for i, c in enumerate(chunks)}
    selected = [by_id[i] for i in selected_ids if isinstance(i, int) and i in by_id][:keep_k]
    if not selected:
        return _fallback_filter(question, chunks, keep_k=keep_k, tag=agent_name)
    notes = (data.get("notes") or "").strip() if isinstance(data, dict) else ""
    return selected, (notes or f"{agent_name} selected {len(selected)} evidence chunks")


def _run_answer_agent(question: str,
                      subject: str,
                      chunks: list,
                      agent_name: str) -> dict:
    if not chunks:
        return {
            "agent": agent_name,
            "answer": "Không đủ bằng chứng để trả lời.",
            "confidence": 0.0,
            "used_evidence": [],
        }

    numbered = []
    for i, c in enumerate(chunks, start=1):
        numbered.append(f"[E{i}] {c.get('text','')[:500]}")
    subject_ctx = f"Môn học: {subject}.\n" if subject else ""
    user_prompt = (
        f"{subject_ctx}Câu hỏi: {question}\n\n"
        f"Evidence:\n" + "\n\n".join(numbered) + "\n\n"
        "Trả JSON: {\"answer\":\"...\",\"confidence\":0.0,\"used_evidence\":[1,2],\"reasoning\":\"...\"}."
    )
    system_msg = (
        "Bạn là QA assistant trong pipeline RAG. "
        "Trả lời đầy đủ ý, rõ ràng thành câu hoàn chỉnh bằng tiếng Việt, tuyệt đối bám evidence, không bịa. "
        "Chỉ trả JSON hợp lệ."
    )
    data = _llm_json_call(system_msg, user_prompt, max_tokens=420, temperature=0.2)
    answer = (data.get("answer") or "").strip() if isinstance(data, dict) else ""
    confidence = data.get("confidence", 0.0) if isinstance(data, dict) else 0.0
    used_ids = data.get("used_evidence") if isinstance(data, dict) else []
    reasoning = (data.get("reasoning") or "").strip() if isinstance(data, dict) else ""

    if not isinstance(used_ids, list):
        used_ids = []
    used_ids = [i for i in used_ids if isinstance(i, int) and 1 <= i <= len(chunks)]
    if not answer:
        answer = generate_answer(question, chunks, subject=subject)
    try:
        confidence = max(0.0, min(float(confidence), 1.0))
    except Exception:
        confidence = 0.0

    return {
        "agent": agent_name,
        "answer": answer,
        "confidence": round(confidence, 3),
        "used_evidence": used_ids,
        "reasoning": reasoning,
    }


def _run_synthesis_agent(question: str,
                         subject: str,
                         candidates: list,
                         all_chunks: list) -> dict:
    valid_candidates = [c for c in candidates if (c.get("answer") or "").strip()]
    if not valid_candidates:
        final_answer = generate_answer(question, all_chunks, subject=subject)
        return {
            "final_answer": final_answer,
            "picked_candidate": None,
            "notes": "fallback classic generator",
        }

    payload = {
        "question": question,
        "subject": subject,
        "candidates": [
            {
                "id": i + 1,
                "agent": c.get("agent"),
                "answer": c.get("answer"),
                "confidence": c.get("confidence", 0),
                "reasoning": c.get("reasoning", ""),
            }
            for i, c in enumerate(valid_candidates)
        ],
        "evidence": _compact_evidence(all_chunks, max_chars=280),
    }
    system_msg = (
        "Bạn là Synthesis Agent. Hãy chọn và viết lại candidate tốt nhất thành một câu trả lời hoàn chỉnh, đầy đủ ý và tự nhiên dựa trên bằng chứng. "
        "Chỉ trả JSON hợp lệ: {\"final_answer\":\"...\",\"picked_candidate\":1,\"notes\":\"...\"}."
    )
    data = _llm_json_call(system_msg, json.dumps(payload, ensure_ascii=False),
                          max_tokens=460, temperature=0.15)

    final_answer = (data.get("final_answer") or "").strip() if isinstance(data, dict) else ""
    picked = data.get("picked_candidate") if isinstance(data, dict) else None
    notes = (data.get("notes") or "").strip() if isinstance(data, dict) else ""
    if not final_answer:
        best = sorted(valid_candidates, key=lambda x: float(x.get("confidence", 0)), reverse=True)[0]
        final_answer = best.get("answer", "")
        picked = valid_candidates.index(best) + 1
        notes = "fallback pick highest confidence candidate"

    if isinstance(picked, int) and 1 <= picked <= len(valid_candidates):
        picked_agent = valid_candidates[picked - 1].get("agent")
    else:
        picked_agent = None

    return {
        "final_answer": final_answer,
        "picked_candidate": picked if isinstance(picked, int) else None,
        "picked_agent": picked_agent,
        "notes": notes,
    }


def generate_answer_agentic(question: str,
                            chunks: list,
                            subject: str = "",
                            filter_top_k: int = RAG_FILTER_TOP_K) -> dict:
    if not chunks:
        answer = "Không tìm thấy tài liệu liên quan trong knowledge base."
        return {
            "answer": answer,
            "filtered_evidence": {"summarizer": [], "extractor": [], "reasoner": []},
            "candidates": [],
            "synthesis": {
                "final_answer": answer,
                "picked_candidate": None,
                "picked_agent": None,
                "notes": "no retrieval evidence",
            },
        }

    k = max(1, min(int(filter_top_k or 1), len(chunks)))
    s_chunks, s_note = _run_filter_agent("summarizer", question, chunks, keep_k=k)
    e_chunks, e_note = _run_filter_agent("extractor", question, chunks, keep_k=k)
    r_chunks, r_note = _run_filter_agent("reasoner", question, chunks, keep_k=k)

    cand_s = _run_answer_agent(question, subject, s_chunks, "summarizer")
    cand_e = _run_answer_agent(question, subject, e_chunks, "extractor")
    cand_r = _run_answer_agent(question, subject, r_chunks, "reasoner")
    candidates = [cand_s, cand_e, cand_r]

    synthesis = _run_synthesis_agent(question, subject, candidates, chunks)
    return {
        "answer": synthesis.get("final_answer") or generate_answer(question, chunks, subject=subject),
        "filtered_evidence": {
            "summarizer": s_chunks,
            "extractor": e_chunks,
            "reasoner": r_chunks,
        },
        "filter_notes": {
            "summarizer": s_note,
            "extractor": e_note,
            "reasoner": r_note,
        },
        "candidates": candidates,
        "synthesis": synthesis,
    }


# ==============================================================================
# ==== HTTPS CERT ==============================================================
# ==============================================================================

def collect_local_ips(primary_ip: str) -> list:
    ips = {"127.0.0.1", primary_ip}
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip and not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def collect_local_dns_names() -> list:
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


def _read_cert_san_and_expiry(cert_file: str):
    from OpenSSL import crypto
    with open(cert_file, "rb") as f:
        cert = crypto.load_certificate(crypto.FILETYPE_PEM, f.read())
    san_dns, san_ips = set(), set()
    for i in range(cert.get_extension_count()):
        ext = cert.get_extension(i)
        if ext.get_short_name() == b"subjectAltName":
            for item in [x.strip() for x in str(ext).split(",")]:
                if item.startswith("DNS:"):
                    san_dns.add(item[4:].strip())
                elif item.startswith("IP Address:"):
                    san_ips.add(item[11:].strip())
    not_after  = cert.get_notAfter().decode("ascii")
    expires_at = datetime.strptime(not_after, "%Y%m%d%H%M%SZ").replace(tzinfo=timezone.utc)
    return san_dns, san_ips, expires_at


def cert_is_usable(cert_file: str, required_dns: list,
                   required_ips: list, rotate_before_days: int = 14) -> bool:
    if not os.path.exists(cert_file):
        return False
    try:
        san_dns, san_ips, expires_at = _read_cert_san_and_expiry(cert_file)
        remaining = (expires_at - datetime.now(timezone.utc)).days
        return (remaining >= rotate_before_days
                and set(required_dns).issubset(san_dns)
                and set(required_ips).issubset(san_ips))
    except ImportError:
        # Nếu thiếu pyOpenSSL (môi trường mobile), giữ cert hiện có để vẫn chạy HTTPS.
        return True
    except Exception:
        return False


def create_self_signed_cert(cert_file: str, key_file: str, primary_ip: str):
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime

    local_ips = collect_local_ips(primary_ip)
    local_dns = collect_local_dns_names()
    san_list = [x509.DNSName(n) for n in local_dns] + [x509.IPAddress(ipaddress.IPv4Address(ip)) for ip in local_ips]
    days = int(os.getenv("RESFES_CERT_VALID_DAYS", "365"))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"VN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Vietnam"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"DALAP"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])
    cert = x509.CertificateBuilder()
    cert = cert.subject_name(subject)
    cert = cert.issuer_name(issuer)
    cert = cert.public_key(key.public_key())
    cert = cert.serial_number(x509.random_serial_number())
    cert = cert.not_valid_before(datetime.datetime.utcnow())
    cert = cert.not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=days))
    cert = cert.add_extension(x509.SubjectAlternativeName(san_list), critical=False)
    cert = cert.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    cert = cert.add_extension(x509.KeyUsage(
        digital_signature=True,
        key_encipherment=True,
        content_commitment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=False,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False
    ), critical=True)
    cert = cert.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    cert = cert.sign(key, hashes.SHA256())

    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_file, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    return local_ips, local_dns


def copy_packaged_cert_if_needed(cert_file: str, key_file: str) -> bool:
    """Copy cert/key được bundle trong app vào DATA_DIR nếu đích chưa có."""
    cert_path = Path(cert_file)
    key_path = Path(key_file)
    if cert_path.exists() and key_path.exists():
        return True

    packaged_dir = Path(__file__).resolve().parent / "knowledge" / "certs"
    src_cert = packaged_dir / "cert.pem"
    src_key = packaged_dir / "key.pem"
    if not (src_cert.exists() and src_key.exists()):
        return False

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    if not cert_path.exists():
        shutil.copyfile(src_cert, cert_path)
    if not key_path.exists():
        shutil.copyfile(src_key, key_path)
    return cert_path.exists() and key_path.exists()


# ==============================================================================
# ==== CHAT HELPERS ============================================================
# ==============================================================================

CHAT_SYSTEM_PROMPT = """Bạn là DALAP AI — trợ lý học tập tích hợp trong kính AR học đường.

QUY TẮC:
- Ưu tiên trả lời TRỰC TIẾP câu hỏi của người dùng trước.
- Nếu có [NỘI DUNG BÀI VỪA SCAN] hoặc [Tài liệu tham khảo], ưu tiên bám vào các nguồn đó.
- Nếu không có đủ ngữ cảnh từ scan/tài liệu, vẫn trả lời bằng kiến thức nền đáng tin cậy và nói rõ phạm vi trả lời.
- Sau câu trả lời trực tiếp, có thể thêm 1 câu gợi mở ngắn để người học hiểu sâu hơn.
- Ngắn gọn, rõ ràng: tối đa 4 câu mỗi lượt, tiếng Việt tự nhiên, không markdown."""


def _build_chat_messages(user_message: str, history: list, subject: str,
                         kb_context: str, scan_context: str = "") -> list:
    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for turn in history[-8:]:
        if turn.get("role") in {"user", "assistant"} and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})

    ctx = []
    if scan_context:
        ctx.append(f"[NỘI DUNG BÀI VỪA SCAN:\n{scan_context}]")
    if subject:
        ctx.append(f"[Môn học: {subject}]")
    if kb_context:
        ctx.append(f"[Tài liệu tham khảo:\n{kb_context}]")

    body = ("\n".join(ctx) + "\n\nHọc sinh hỏi: " + user_message
            if ctx else user_message)
    messages.append({"role": "user", "content": body})
    return messages


def _fetch_kb_context(query: str, subject: Optional[str], doc_ids: Optional[List[int]] = None) -> str:
    """Lấy RAG context — ưu tiên remote KB server nếu được cấu hình."""
    try:
        results = []
        if USE_REMOTE_KB and KB_SERVER_URL:
            try:
                resp = requests.post(
                    f"{KB_SERVER_URL.rstrip('/')}/kb/search",
                    json={"query": query, "subject": subject, "doc_ids": doc_ids or []},
                    timeout=KB_REMOTE_TIMEOUT_SEC,
                )
                if resp.ok:
                    results = resp.json().get("results", [])
                else:
                    print(f"[KB context] remote status={resp.status_code}, fallback local")
            except Exception as e:
                print(f"[KB context] remote error={e}, fallback local")

        if not results:
            results = semantic_search(query, subject=subject, doc_ids=doc_ids or None, top_k=3)

        snippets = []
        snippet_limit = max(320, min(CHUNK_SIZE, 400))
        for r in results[:3]:
            text = r.get("text") or r.get("content") or r.get("snippet") or ""
            if text:
                snippets.append(text[:snippet_limit].strip())
        return "\n---\n".join(snippets)
    except Exception as e:
        print(f"[KB context] {e}")
        return ""


def _get_client_ip() -> str:
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return (request.remote_addr or "unknown").strip() or "unknown"


def ingest_document_from_path(file_path: Path, original_name: str = None, file_type: str = "txt", subject: str = "", doc_id: int = None) -> dict:
    """Process an already-saved file on disk: extract text, chunk and index.
    This avoids rewriting the file into UPLOAD_DIR and is intended for background
    processing of files received via multipart upload.
    """
    if original_name is None:
        original_name = file_path.name

    try:
        _set_ingest_status(doc_id, "extracting", "Đang đọc và trích xuất văn bản...", 5)
        with file_path.open('rb') as f:
            file_bytes = f.read()

        # Use similar logic to ingest_document but do not write the file again.
        normalized_type = _infer_file_type(original_name, declared_type=file_type)
        text = _extract_text(file_bytes, normalized_type, original_name)
        extraction_warning = ""
        if _is_extraction_placeholder(text, normalized_type):
            extraction_warning = text
            chunk_records = []
        else:
            word_count = len((text or "").split())
            step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
            est_chunks = max(1, int(math.ceil(word_count / step))) if word_count > 0 else 1
            size_mb = len(file_bytes) / (1024 * 1024)
            skip_contextual = (size_mb >= CONTEXTUAL_MAX_FILE_MB) or (est_chunks >= CONTEXTUAL_MAX_EST_CHUNKS)
            if skip_contextual:
                print(
                    f"[Contextual] auto-skip for {original_name}: "
                    f"size={size_mb:.1f}MB, est_chunks={est_chunks}"
                )
            _set_ingest_status(doc_id, "chunking", f"Đang tách chunks... (ước tính {est_chunks})", 15)
            chunk_records = _build_chunk_records(
                text,
                file_type=normalized_type,
                original_name=original_name,
                subject=subject,
                skip_contextual=skip_contextual,
            )
        print(f"[INGEST_FROM_PATH] {original_name}: {len(text)} chars → {len(chunk_records)} chunks")

        with get_db() as conn:
            if doc_id is None:
                cur = conn.execute(
                    "INSERT INTO documents (filename, original_name, file_type, subject, upload_date, file_size) VALUES (?,?,?,?,?,?)",
                    (file_path.name, original_name, normalized_type, subject, datetime.now().isoformat(), file_path.stat().st_size)
                )
                doc_id = cur.lastrowid
                print(f"[INGEST_FROM_PATH] inserted doc_id={doc_id} for {file_path.name}")
            else:
                print(f"[INGEST_FROM_PATH] updating existing doc_id={doc_id} for {file_path.name}")

            if chunk_records:
                conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
                conn.executemany(
                    "INSERT INTO chunks (doc_id, chunk_idx, text, subject, token_count, char_count, chunk_hash) VALUES (?,?,?,?,?,?,?)",
                    [(
                        doc_id,
                        item["chunk_idx"],
                        item["text"],
                        item["subject"],
                        item["token_count"],
                        item["char_count"],
                        item["chunk_hash"],
                    ) for item in chunk_records]
                )
            try:
                conn.commit()
            except Exception:
                # Some sqlite wrappers auto-commit on context exit; ignore commit failures
                pass

        vector_count = 0
        if vector_db is not None and chunk_records:
            try:
                _set_ingest_status(doc_id, "indexing", f"Đang vector hóa {len(chunk_records)} chunks...", 70)
                chunk_rows = []
                with get_db() as conn:
                    chunk_rows = conn.execute("SELECT id, text FROM chunks WHERE doc_id=? ORDER BY chunk_idx ASC", (doc_id,)).fetchall()
                vector_count = vector_db.upsert_document_chunks(doc_id=doc_id, chunks=chunk_rows, subject=subject)
            except Exception as e:
                print(f"[INGEST_FROM_PATH] Vector upsert failed: {e}")

        _invalidate_cache()
        warning = _build_ingest_warning(text, normalized_type, original_name, extraction_warning)
        _set_ingest_status(doc_id, "done", f"Hoàn tất: {len(chunk_records)} chunks", 100)

        return {
            "id": doc_id,
            "filename": file_path.name,
            "original_name": original_name,
            "file_type": normalized_type,
            "chunks": len(chunk_records),
            "vectors": vector_count,
            "warning": warning,
        }
    except Exception as e:
        _set_ingest_status(doc_id, "error", f"Lỗi xử lý: {e}", 0)
        print(f"[INGEST_FROM_PATH] Error processing {file_path}: {e}")
        raise


def _endpoint_rate_limited(bucket: dict, min_interval_sec: float, key: str) -> float:
    """Return retry-after seconds if limited, otherwise 0."""
    if min_interval_sec <= 0:
        return 0.0

    now = time.monotonic()
    with _rate_limit_lock:
        last = bucket.get(key)
        if last is None:
            bucket[key] = now
            return 0.0

        elapsed = now - last
        if elapsed < min_interval_sec:
            return min_interval_sec - elapsed

        bucket[key] = now
        return 0.0


def _analyze_rate_limited() -> float:
    ip = _get_client_ip()
    return _endpoint_rate_limited(_analyze_last_hit, ANALYZE_MIN_INTERVAL_SEC, ip)


def _chat_rate_limited() -> float:
    ip = _get_client_ip()
    return _endpoint_rate_limited(_chat_last_hit, CHAT_MIN_INTERVAL_SEC, ip)


def _quiz_rate_limited() -> float:
    ip = _get_client_ip()
    return _endpoint_rate_limited(_quiz_last_hit, QUIZ_MIN_INTERVAL_SEC, ip)


def _hourly_quota_check(bucket: dict, limit: int, key: str):
    """Return (blocked, retry_after_sec, used, reset_at_iso) for a rolling 1h window."""
    if limit <= 0:
        return False, 0.0, 0, None

    now_ts = time.time()
    window_start = now_ts - HOURLY_WINDOW_SEC
    with _rate_limit_lock:
        hits = [ts for ts in bucket.get(key, []) if ts >= window_start]

        if len(hits) >= limit:
            oldest = min(hits) if hits else now_ts
            retry_after = max(0.0, (oldest + HOURLY_WINDOW_SEC) - now_ts)
            reset_at = datetime.fromtimestamp(now_ts + retry_after, timezone.utc).isoformat()
            bucket[key] = hits
            return True, retry_after, len(hits), reset_at

        hits.append(now_ts)
        bucket[key] = hits
        reset_at = datetime.fromtimestamp(now_ts + HOURLY_WINDOW_SEC, timezone.utc).isoformat()
        return False, 0.0, len(hits), reset_at


def _validate_analyze_image_payload(image_value: object) -> tuple[bool, str, str]:
    if not isinstance(image_value, str):
        return False, "Trường image phải là chuỗi base64.", ""

    raw = image_value.strip()
    if not raw:
        return False, "Thiếu ảnh.", ""

    if len(raw) > _ANALYZE_IMAGE_MAX_CHARS:
        return False, "Ảnh quá lớn.", ""

    b64 = raw.split(",", 1)[1] if "," in raw else raw
    if not b64.strip():
        return False, "Ảnh không hợp lệ.", ""

    try:
        base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return False, "Ảnh base64 không hợp lệ.", ""

    return True, "", b64


def _hourly_limited_analyze():
    return _hourly_quota_check(_analyze_hourly_hits, ANALYZE_HOURLY_LIMIT, _get_client_ip())


def _hourly_limited_chat():
    return _hourly_quota_check(_chat_hourly_hits, CHAT_HOURLY_LIMIT, _get_client_ip())


def _hourly_limited_quiz():
    return _hourly_quota_check(_quiz_hourly_hits, QUIZ_HOURLY_LIMIT, _get_client_ip())


def _cleanup_sessions() -> None:
    if SESSION_TTL_SEC <= 0:
        return
    cutoff = datetime.fromtimestamp(
        time.time() - SESSION_TTL_SEC,
        timezone.utc,
    ).isoformat()
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))


def _session_append(session_id: str, role: str, content: str) -> None:
    sid = (session_id or "").strip()
    if not sid or not content:
        return
    global _session_append_count
    _session_append_count += 1
    if _session_append_count % 100 == 0:
        _cleanup_sessions()
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO sessions (session_id, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET updated_at=excluded.updated_at
            """,
            (sid, now_iso, now_iso),
        )
        conn.execute(
            "INSERT INTO session_turns (session_id, role, content, timestamp) VALUES (?,?,?,?)",
            (sid, role, content, now_iso),
        )
        conn.execute(
            """
            DELETE FROM session_turns
            WHERE id IN (
                SELECT id FROM session_turns
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (sid, SESSION_MAX_TURNS),
        )


def _session_get(session_id: str) -> Optional[Dict[str, Any]]:
    sid = (session_id or "").strip()
    if not sid:
        return None
    _cleanup_sessions()
    with get_db() as conn:
        sess_row = conn.execute(
            "SELECT session_id, created_at, updated_at FROM sessions WHERE session_id=?",
            (sid,),
        ).fetchone()
        if not sess_row:
            return None
        turns = conn.execute(
            """
            SELECT role, content, timestamp
            FROM session_turns
            WHERE session_id=?
            ORDER BY id ASC
            """,
            (sid,),
        ).fetchall()
    return {
        "session_id": sess_row["session_id"],
        "created_at": sess_row["created_at"],
        "updated_at": sess_row["updated_at"],
        "turns": [dict(r) for r in turns],
    }


# ==============================================================================
# ==== SELECTED KB DOC IDS (Server-side storage for cross-device sync) ========
# ==============================================================================

_server_selected_doc_ids: List[int] = []

def _session_get_selected_doc_ids() -> List[int]:
    """Return currently selected doc IDs stored server-side."""
    return list(_server_selected_doc_ids)

def _session_set_selected_doc_ids(ids: List[int]) -> None:
    """Store selected doc IDs server-side for cross-device access."""
    global _server_selected_doc_ids
    _server_selected_doc_ids = ids


# ==============================================================================
# ==== ROUTES ==================================================================
# ==============================================================================

@app.route("/")
def index():
    # Inject packaged API key into the web UI so clients served by the backend
    # automatically use the bundled key instead of requiring manual entry.
    try:
        key = API_KEY or ""
    except Exception:
        key = ""
    return render_template("index.html", api_key=key)


@app.route("/health")
def health():
    db = get_db_status()
    vdb = {}
    if vector_db is not None:
        try:
            vdb = vector_db.stats()
        except Exception as e:
            vdb = {"ok": False, "error": str(e)}
    else:
        vdb = {"ok": False, "enabled": False}
    
    # Kiểm tra extractor server health
    extractor_info = {"enabled": bool(EXTRACTOR_SERVER_URL)}
    if EXTRACTOR_SERVER_URL:
        try:
            resp = requests.get(
                f"{EXTRACTOR_SERVER_URL.rstrip('/')}/health",
                timeout=max(1, EXTRACTOR_REMOTE_TIMEOUT_SEC // 2)
            )
            extractor_info["ok"] = resp.ok
            extractor_info["status_code"] = resp.status_code
        except Exception as e:
            extractor_info["ok"] = False
            extractor_info["error"] = str(e)
    
    return jsonify({
        "status": "ok",
        "model": GROQ_MODEL,
        "docs": db["docs"],
        "chunks": db["chunks"],
        "vectors": db["vectors"],
        "db_ok": db["ok"],
        "db_path": db["db_path"],
        "db_size_mb": round(db.get("db_size", 0) / (1024 * 1024), 2),
        "extractor": extractor_info,
        "vector_db": vdb,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@app.route("/db/status")
def db_status():
    db = get_db_status()
    code = 200 if db["ok"] else 500
    return jsonify(db), code


@app.route("/db/cleanup", methods=["POST"])
def db_cleanup():
    """Xóa orphaned chunks và rebuild vector index nếu cần."""
    cleanup_report = {
        "orphaned_chunks_deleted": 0,
        "vector_index_rebuilt": False,
        "errors": []
    }
    
    try:
        with get_db() as conn:
            # Xóa orphaned chunks (doc_id không tồn tại)
            cursor = conn.execute("""
                DELETE FROM chunks 
                WHERE doc_id NOT IN (SELECT id FROM documents)
            """)
            cleanup_report["orphaned_chunks_deleted"] = cursor.rowcount
            
            # Xóa orphaned vectors nếu vector_db tồn tại
            if vector_db:
                try:
                    # Lấy list valid chunk_ids
                    valid_ids = conn.execute(
                        "SELECT id FROM chunks"
                    ).fetchall()
                    valid_chunk_ids = {r[0] for r in valid_ids}
                    
                    # Nếu cần, có thể implement cleanup trong vector_db
                    # Hiện tại chỉ log thôi
                    cleanup_report["vector_index_rebuilt"] = False
                    cleanup_report["notes"] = f"Vector index has {len(valid_chunk_ids)} valid chunks (rebuild not implemented)"
                except Exception as e:
                    cleanup_report["errors"].append(f"Vector cleanup error: {e}")
        
        _invalidate_cache()
        return jsonify({
            "success": True,
            "cleanup_report": cleanup_report,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    except Exception as e:
        cleanup_report["errors"].append(str(e))
        return jsonify({
            "success": False,
            "cleanup_report": cleanup_report,
            "error": str(e)
        }), 500


# ── Vision analyze ────────────────────────────────────────────────────────────

@app.route("/analyze", methods=["POST"])
def analyze():
    """Ảnh → OCR → gợi ý Socratic bám sát nội dung + RAG context."""
    data = request.get_json(silent=True)
    if not data or "image" not in data:
        return _json_error("Không có ảnh.", 400)

    ok, error_message, b64 = _validate_analyze_image_payload(data.get("image"))
    if not ok:
        return _json_error(error_message, 400, code="analyze_invalid_image")

    blocked, retry_after, used, reset_at = _hourly_limited_analyze()
    if blocked:
        return _json_error(
            "Đã vượt quá số lượt /analyze trong 1 giờ.",
            429,
            code="analyze_hourly_limit",
            retry_after_sec=round(retry_after, 2),
            used=used,
            limit=ANALYZE_HOURLY_LIMIT,
            reset_at=reset_at,
        )

    retry_after = _analyze_rate_limited()
    if retry_after > 0:
        return _json_error(
            "Bạn thao tác quá nhanh. Vui lòng thử lại sau giây lát.",
            429,
            retry_after_sec=round(retry_after, 2),
        )

    subject = data.get("subject", "").strip()
    note    = data.get("note", "").strip()

    subject_ctx = f"Môn học: {subject}." if subject else "Tự phát hiện môn học."
    note_ctx    = f'\nCâu hỏi của học sinh: "{note}"' if note else ""

    system_msg = (
        "Bạn là trợ lý học tập AR. Phân tích ảnh bài tập/sách giáo khoa "
        "và sinh câu hỏi Socratic BÁM SÁT nội dung cụ thể trong ảnh. "
        "KHÔNG trả lời chung chung. "
        "Nếu ảnh có phương trình → hỏi về phương trình đó. "
        "Nếu có đoạn văn → hỏi về đoạn văn đó. "
        "Nếu có bài toán → hỏi về bước giải cụ thể."
    )
    user_msg = (
        f"{subject_ctx}{note_ctx}\n\n"
        "1. Đọc và trích xuất CHÍNH XÁC văn bản/công thức/số liệu quan trọng nhất.\n"
        "2. Dựa vào nội dung VỪA ĐỌC, viết 2-3 câu hỏi Socratic cụ thể "
        "(gợi mở tư duy, KHÔNG đưa đáp án).\n"
        "3. Viết 1 flashcard hỏi thẳng vào khái niệm/bước quan trọng nhất.\n\n"
        "Trả về JSON (không thêm gì khác):\n"
        '{"ocr_text":"văn bản/công thức chính (tối đa 250 ký tự)",'
        '"subject":"môn học",'
        '"hint":"câu hỏi Socratic cụ thể, bám sát nội dung vừa đọc",'
        '"flashcard":"1 câu hỏi flashcard ngắn"}\n'
        "Tiếng Việt. Nếu không đọc được, ocr_text để rỗng."
    )

    print(f"[ANALYZE] subject={subject!r} note={note!r}")
    try:
        res = _require_groq_client().chat.completions.create(
            model=GROQ_MODEL, max_tokens=700, temperature=0.3,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": user_msg}
                ]}
            ]
        )
        raw_text = res.choices[0].message.content.strip()

        # Robust JSON extraction
        if "```" in raw_text:
            for part in raw_text.split("```"):
                part = part.strip().lstrip("json").strip()
                if part.startswith("{"):
                    raw_text = part
                    break
        if not raw_text.startswith("{"):
            m = re.search(r'\{[^{}]+\}', raw_text, re.DOTALL)
            if m:
                raw_text = m.group(0)

        result   = json.loads(raw_text)
        ocr_text = result.get("ocr_text", "")[:300]
        print(f"[ANALYZE] OCR: {ocr_text[:80]!r}")

        # RAG lookup ngay khi có OCR text
        knowledge = []
        if ocr_text:
            chunks = semantic_search(ocr_text, subject=subject or None, top_k=3)
            knowledge = [{"title": f"Đoạn {i+1}", "snippet": c["text"][:200],
                          "score": c["score"]} for i, c in enumerate(chunks)]

        return jsonify({
            "ocr_text":  ocr_text,
            "subject":   result.get("subject", subject),
            "hint":      result.get("hint", ""),
            "flashcard": result.get("flashcard", ""),
            "knowledge": knowledge,
        })
    except json.JSONDecodeError as e:
        print(f"[ANALYZE] JSON error: {e}")
        return _json_error("AI trả về định dạng không hợp lệ.", 500)
    except Exception as e:
        print(f"[ANALYZE] Error: {e}")
        return _json_error(str(e), 500)


# ── RAG /ask ─────────────────────────────────────────────────────────────────

@app.route("/ask", methods=["POST"])
def ask():
    """
    RAG pipeline: retrieval -> filter agents -> answer agents -> synthesis -> final answer.

    Request : { "question": "...", "subject": "...", "top_k": 4, "expand": false, "agentic": true }
    Response: { "answer": "...", "sources": [...], "chunks_used": N, "mode": "...", "pipeline": {...} }
    - expand=true: sinh thêm query variants để tăng recall (tốn thêm ~1 Groq call nhỏ)
    """
    data = request.get_json(silent=True)
    if not data or not (data.get("question") or "").strip():
        return jsonify({"error": "Thiếu câu hỏi."}), 400

    question = data["question"].strip()
    subject  = data.get("subject", "").strip()
    doc_ids  = _parse_doc_ids(data.get("doc_ids"))
    file_types = _normalize_file_types(data.get("file_types") or data.get("file_type") or [])
    min_chunk_tokens = int(data.get("min_chunk_tokens", 0) or 0)
    max_chunk_tokens = int(data.get("max_chunk_tokens", 0) or 0)
    top_k    = int(data.get("top_k", TOP_K))
    expand   = bool(data.get("expand", False))
    agentic  = bool(data.get("agentic", RAG_AGENTIC_DEFAULT))
    filter_k = int(data.get("filter_top_k", RAG_FILTER_TOP_K) or RAG_FILTER_TOP_K)

    print(f"[ASK] '{question[:80]}' subject={subject!r} doc_ids={doc_ids[:8]} file_types={sorted(file_types)[:6]} expand={expand} agentic={agentic}")

    chunks = semantic_search(question, subject=subject or None,
                             doc_ids=doc_ids or None,
                             file_types=sorted(file_types) if file_types else None,
                             min_chunk_tokens=min_chunk_tokens,
                             max_chunk_tokens=max_chunk_tokens,
                             top_k=top_k, expand=expand)
    pipeline = None
    if agentic:
        pipeline = generate_answer_agentic(question, chunks, subject=subject, filter_top_k=filter_k)
        answer = pipeline.get("answer") or generate_answer(question, chunks, subject=subject)
    else:
        answer = generate_answer(question, chunks, subject=subject)
    sources = [{
        "text":        c["text"],
        "score":       c["score"],
        "tfidf_score": c.get("tfidf_score", 0),
        "bm25_score":  c.get("bm25_score", 0),
        "subject":     c.get("subject", ""),
    } for c in chunks]

    mode = f"hybrid+expand" if expand else "hybrid"
    response = {
        "answer": answer,
        "sources": sources,
        "chunks_used": len(chunks),
        "mode": mode,
        "agentic": agentic,
    }
    if pipeline is not None:
        response["pipeline"] = {
            "document_retrieval": {
                "query": question,
                "subject": subject,
                    "doc_ids": doc_ids,
                "file_types": sorted(file_types),
                "min_chunk_tokens": min_chunk_tokens,
                "max_chunk_tokens": max_chunk_tokens,
                "top_k": top_k,
                "retrieved_count": len(chunks),
                "mode": mode,
            },
            "filter_agent": {
                "filtered_evidence": {
                    "summarizer": [{"text": c.get("text", ""), "score": c.get("score", 0)}
                                   for c in pipeline.get("filtered_evidence", {}).get("summarizer", [])],
                    "extractor": [{"text": c.get("text", ""), "score": c.get("score", 0)}
                                  for c in pipeline.get("filtered_evidence", {}).get("extractor", [])],
                    "reasoner": [{"text": c.get("text", ""), "score": c.get("score", 0)}
                                 for c in pipeline.get("filtered_evidence", {}).get("reasoner", [])],
                },
                "notes": pipeline.get("filter_notes", {}),
            },
            "answer_agent": {
                "candidates": pipeline.get("candidates", []),
            },
            "synthesis_agent": pipeline.get("synthesis", {}),
        }

    return jsonify(response)


# ── Knowledge Base CRUD ───────────────────────────────────────────────────────

@app.route("/kb/upload", methods=["POST"])
def kb_upload():
    """Upload tài liệu, chunk và index vào RAG pipeline."""
    # Support multipart/form-data uploads (preferred for large files)
    if request.files and request.files.get('file'):
        f = request.files.get('file')
        if not f:
            return _json_error("Thiếu file", 400, code="kb_missing_file")
        filename = secure_filename(f.filename or f"upload_{int(time.time())}")
        dst = UPLOAD_DIR / filename
        try:
            f.save(str(dst))
            try:
                size_bytes = dst.stat().st_size
            except Exception:
                size_bytes = 0
            print(f"[KB upload] saved to {dst} ({size_bytes} bytes)")
        except Exception as e:
            print(f"[KB upload] save failed: {e}")
            return _json_error(f"Save failed: {e}", 500, code="kb_save_failed")

        # Decide sync vs async processing based on file size
        subj = request.form.get('subject', '')
        ftype = request.form.get('file_type', '')
        display_name = request.form.get('display_name') or filename

        try:
            size_bytes = dst.stat().st_size
        except Exception:
            size_bytes = 0

        sync_mb = int(os.getenv('RESFES_SYNC_UPLOAD_MB', '1'))
        sync_threshold = sync_mb * 1024 * 1024

        if size_bytes <= sync_threshold:
            # Process synchronously so client sees file in DB immediately
            print(f"[KB upload] processing synchronously (<= {sync_threshold} bytes)")
            try:
                result = ingest_document_from_path(dst, original_name=display_name, file_type=ftype or 'auto', subject=subj)
                return jsonify(result), 200
            except Exception as e:
                print(f"[KB upload] sync processing failed for {dst}: {e}")
                return _json_error(f"Processing failed: {e}", 500, code="kb_processing_failed")
        else:
            # Background processing for large files
            print(f"[KB upload] processing in background (> {sync_threshold} bytes)")
            # Create the document row immediately so the upload is visible in the list,
            # then finish chunking/indexing in the background.
            try:
                import sqlite3 as _sqlite3
                _pre_conn = _sqlite3.connect(str(DB_PATH), timeout=SQLITE_TIMEOUT_SEC)
                _pre_conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_MS}")
                _pre_conn.execute("PRAGMA foreign_keys = ON")
                _pre_conn.execute("PRAGMA journal_mode = WAL")
                try:
                    cur = _pre_conn.execute(
                        "INSERT INTO documents (filename, original_name, file_type, subject, upload_date, file_size) VALUES (?,?,?,?,?,?)",
                        (filename, display_name, ftype or 'auto', subj, datetime.now().isoformat(), size_bytes)
                    )
                    doc_id = cur.lastrowid
                    _pre_conn.commit()
                except Exception as e:
                    _pre_conn.close()
                    print(f"[KB upload] pre-insert document failed: {e}")
                    return _json_error(f"Processing failed: {e}", 500, code="kb_processing_failed")
                finally:
                    _pre_conn.close()
            except Exception as e:
                print(f"[KB upload] pre-insert document failed: {e}")
                return _json_error(f"Processing failed: {e}", 500, code="kb_processing_failed")

            # Create a detached app context to manage g.db cleanup securely
            app_ctx = app.app_context()
            
            def _bg(ctx):
                with ctx:
                    try:
                        _set_ingest_status(doc_id, "queued", "Đã upload, đang chờ xử lý nền...", 1)
                        import time as _time
                        _time.sleep(0.2)   # ensure pre-insert commit is visible
                        res = ingest_document_from_path(dst, original_name=display_name, file_type=ftype or 'auto', subject=subj, doc_id=doc_id)
                        print(f"[KB upload bg] success for {dst}: {res.get('chunks')} chunks indexed.")
                    except Exception as e:
                        print(f"[KB upload bg] processing failed for {dst}: {e}")

            threading.Thread(target=_bg, args=(app_ctx,), daemon=True).start()
            return jsonify({"success": True, "id": doc_id, "filename": filename, "note": f"Processing in background; file size {size_bytes} bytes"}), 202

    # Fallback: accept base64-in-json for backward compatibility
    data = request.get_json(silent=True)
    file_data = (data.get("file") or data.get("file_data")) if data else None
    if not file_data:
        return _json_error("Thiếu dữ liệu file.", 400, code="kb_missing_file_data")

    raw = file_data.split(",")[1] if "," in file_data else file_data
    try:
        file_bytes = base64.b64decode(raw)
    except Exception as e:
        return _json_error(
            f"Base64 decode error: {e}",
            400,
            code="kb_invalid_base64",
        )

    try:
        normalized_type = _infer_file_type(
            filename=data.get("filename", "untitled"),
            mime_type=data.get("mime_type", ""),
            declared_type=data.get("file_type", ""),
        )

        normalized_name = _normalize_upload_name(
            filename=data.get("filename", "untitled"),
            display_name=data.get("display_name", ""),
            file_type=normalized_type,
        )

        result = ingest_document(
            file_bytes    = file_bytes,
            original_name = normalized_name,
            file_type     = normalized_type,
            subject       = data.get("subject", ""),
        )
        return jsonify(result)
    except Exception as e:
        print(f"[KB upload] {e}")
        return _json_error(str(e), 500, code="kb_upload_failed")


@app.route("/kb/documents", methods=["GET"])
def kb_list_documents():
    subject = request.args.get("subject")
    with get_db() as conn:
        if subject:
            rows = conn.execute(
                """
                SELECT d.*, COUNT(c.id) as chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.doc_id = d.id
                WHERE d.subject = ?
                GROUP BY d.id
                ORDER BY d.upload_date DESC
                """,
                (subject,)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT d.*, COUNT(c.id) as chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.doc_id = d.id
                GROUP BY d.id
                ORDER BY d.upload_date DESC
                """
            ).fetchall()
    return jsonify({"documents": [dict(r) for r in rows]})


@app.route("/kb/documents/<int:doc_id>", methods=["GET", "DELETE", "PUT"])
def kb_manage_document(doc_id):
    """Quản lý tài liệu: GET chi tiết, DELETE xóa, PUT cập nhật metadata."""
    
    if request.method == "DELETE":
        with get_db() as conn:
            row = conn.execute(
                "SELECT filename FROM documents WHERE id=?", (doc_id,)
            ).fetchone()
            if not row:
                return _json_error("Document not found", 404, code="kb_document_not_found")
            fpath = UPLOAD_DIR / row["filename"]
            if fpath.exists():
                fpath.unlink()
            conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        _invalidate_cache()
        return jsonify({"success": True})
    
    elif request.method == "GET":
        with get_db() as conn:
            doc_row = conn.execute(
                "SELECT * FROM documents WHERE id=?", (doc_id,)
            ).fetchone()
            if not doc_row:
                return _json_error("Document not found", 404, code="kb_document_not_found")
            
            chunk_rows = conn.execute(
                "SELECT id, chunk_idx, text FROM chunks WHERE doc_id=? ORDER BY chunk_idx",
                (doc_id,)
            ).fetchall()
        
        # Compute vector_count if chunk_vectors table exists
        vector_count = 0
        try:
            with get_db() as vconn:
                vector_count = vconn.execute("SELECT COUNT(*) FROM chunk_vectors WHERE doc_id=?", (doc_id,)).fetchone()[0]
        except Exception:
            vector_count = 0

        doc = dict(doc_row)
        doc["chunks"] = [dict(r) for r in chunk_rows]
        doc["chunk_count"] = len(chunk_rows)
        doc["vector_count"] = int(vector_count)
        ingest_status = _get_ingest_status(doc_id)
        if ingest_status:
            doc["ingest_status"] = ingest_status
            doc["ingest_stage"] = ingest_status.get("stage", "")
            doc["ingest_message"] = ingest_status.get("message", "")
            doc["ingest_progress"] = int(ingest_status.get("progress", 0) or 0)
        return jsonify(doc)
    
    elif request.method == "PUT":
        data = request.get_json(silent=True)
        if not data:
            return _json_error("No JSON body", 400, code="kb_missing_json")
        
        with get_db() as conn:
            doc_row = conn.execute(
                "SELECT id FROM documents WHERE id=?", (doc_id,)
            ).fetchone()
            if not doc_row:
                return _json_error("Document not found", 404, code="kb_document_not_found")
            
            # Cập nhật các trường được phép
            updates = {}
            if "subject" in data:
                updates["subject"] = data["subject"]
            
            if updates:
                set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
                values = list(updates.values()) + [doc_id]
                conn.execute(
                    f"UPDATE documents SET {set_clause} WHERE id=?",
                    values
                )
                # Cập nhật chunk.subject nếu thay đổi subject
                if "subject" in updates:
                    conn.execute(
                        "UPDATE chunks SET subject=? WHERE doc_id=?",
                        (updates["subject"], doc_id)
                    )
        
        _invalidate_cache()
        return jsonify({"success": True, "updated_fields": list(updates.keys())})


@app.route("/kb/documents/<int:doc_id>/chunks", methods=["GET"])
def kb_get_document_chunks(doc_id):
    """Liệt kê all chunks của tài liệu theo trang."""
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))
    except (TypeError, ValueError):
        return _json_error("Invalid pagination params", 400, code="kb_invalid_pagination")
    
    if page < 1 or page_size < 1 or page_size > 100:
        return _json_error("Invalid pagination params", 400, code="kb_invalid_pagination")
    
    offset = (page - 1) * page_size
    
    with get_db() as conn:
        # Kiểm tra tài liệu tồn tại
        doc_row = conn.execute(
            "SELECT id FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        if not doc_row:
            return _json_error("Document not found", 404, code="kb_document_not_found")
        
        # Lấy tổng số chunks
        total = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE doc_id=?", (doc_id,)
        ).fetchone()[0]
        
        # Lấy chunks theo trang
        chunks = conn.execute(
            """SELECT c.id, c.chunk_idx, c.text, c.subject, c.token_count, c.char_count, c.chunk_hash,
                      d.file_type, d.original_name
               FROM chunks c
               JOIN documents d ON d.id = c.doc_id
               WHERE c.doc_id=?
               ORDER BY c.chunk_idx
               LIMIT ? OFFSET ?""",
            (doc_id, page_size, offset)
        ).fetchall()
    
    return jsonify({
        "doc_id": doc_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "chunks": [dict(r) for r in chunks]
    })




@app.route("/kb/statistics", methods=["GET"])
def kb_statistics():
    """Thống kê chi tiết RAG system."""
    with get_db() as conn:
        # Tổng kết
        total_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        
        # Thống kê theo subject
        subjects = conn.execute("""
            SELECT subject, COUNT(DISTINCT doc_id) as doc_count, COUNT(*) as chunk_count
            FROM chunks
            GROUP BY subject
            ORDER BY doc_count DESC
        """).fetchall()
        
        # Thống kê tệp
        file_types = conn.execute("""
            SELECT file_type, COUNT(*) as doc_count, SUM(file_size) as total_size
            FROM documents
            GROUP BY file_type
            ORDER BY doc_count DESC
        """).fetchall()
        
        # Kích thước DB
        db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
        
        # Vector DB stats
        vector_stats = None
        if vector_db:
            try:
                vector_stats = vector_db.stats()
            except Exception:
                vector_stats = None
    
    return jsonify({
        "summary": {
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "db_size_bytes": db_size,
            "db_path": str(DB_PATH),
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        "by_subject": [
            {"subject": r[0] or "(None)", "documents": r[1], "chunks": r[2]}
            for r in subjects
        ],
        "by_file_type": [
            {"file_type": r[0], "document_count": r[1], "total_size_bytes": r[2] or 0}
            for r in file_types
        ],
        "vector_db": vector_stats or {"status": "disabled"}
    })


@app.route("/extractor/health", methods=["GET"])
def extractor_health():
    """Kiểm tra trạng thái extractor server."""
    if not EXTRACTOR_SERVER_URL:
        return jsonify({
            "status": "disabled",
            "message": "RESFES_EXTRACTOR_SERVER_URL not configured"
        }), 200
    
    try:
        resp = requests.get(
            f"{EXTRACTOR_SERVER_URL.rstrip('/')}/health",
            timeout=EXTRACTOR_REMOTE_TIMEOUT_SEC
        )
        if resp.ok:
            data = resp.json() if resp.content else {}
            return jsonify({
                "status": "healthy",
                "url": EXTRACTOR_SERVER_URL,
                "remote_response": data,
                "timeout_sec": EXTRACTOR_REMOTE_TIMEOUT_SEC
            }), 200
        else:
            return jsonify({
                "status": "error",
                "url": EXTRACTOR_SERVER_URL,
                "http_status": resp.status_code,
                "message": f"HTTP {resp.status_code}"
            }), 503
    except requests.Timeout:
        return jsonify({
            "status": "timeout",
            "url": EXTRACTOR_SERVER_URL,
            "timeout_sec": EXTRACTOR_REMOTE_TIMEOUT_SEC,
            "message": f"Connection timeout after {EXTRACTOR_REMOTE_TIMEOUT_SEC}s"
        }), 503
    except Exception as e:
        return jsonify({
            "status": "error",
            "url": EXTRACTOR_SERVER_URL,
            "error": str(e),
            "message": "Failed to connect to extractor server"
        }), 503


@app.route("/kb/search", methods=["POST"])
def kb_search():
    data  = request.get_json(silent=True)
    query = (data.get("query") or data.get("query_text") or "") if data else ""
    if not query.strip():
        return _json_error("No query", 400, code="kb_missing_query")
    results = semantic_search(query, subject=data.get("subject"), doc_ids=_parse_doc_ids(data.get("doc_ids")), top_k=TOP_K)
    return jsonify({"results": results})


# ── Chat (voice + text) ───────────────────────────────────────────────────────

def _chat_core(data: dict, force_stream: bool = False):
    if not data or not (data.get("message") or "").strip():
        return _json_error("Thiếu nội dung câu hỏi.", 400)

    user_message = data["message"].strip()
    history = data.get("history", [])
    subject = data.get("subject", "").strip()
    doc_ids = _parse_doc_ids(data.get("doc_ids"))
    scan_context = data.get("scan_context", "").strip()
    use_kb = data.get("use_kb", True)
    streaming = force_stream or data.get("stream", False)
    session_id = (data.get("session_id") or "").strip()

    _session_append(session_id, "user", user_message)

    kb_context = _fetch_kb_context(user_message, subject or None, doc_ids or None) if use_kb else ""
    messages = _build_chat_messages(user_message, history, subject,
                                    kb_context, scan_context)

    print(f"[CHAT] '{user_message[:60]}' kb={bool(kb_context)} doc_ids={doc_ids[:8]} scan={bool(scan_context)}")

    # Android stability mode: skip Groq call for chat to avoid native crashes in some runtimes.
    if ANDROID_SAFE_CHAT:
        reply = _extractive_chat_reply(user_message, kb_context, scan_context)
        _session_append(session_id, "assistant", reply)
        if streaming:
            return Response(stream_with_context(iter([reply])),
                            mimetype="text/plain; charset=utf-8",
                            headers={"X-Accel-Buffering": "no"})
        return jsonify({"reply": reply, "used_kb": bool(kb_context),
                        "safe_mode": True,
                        "kb_context": kb_context if data.get("debug") else None})

    if streaming:
        def generate():
            chunks: List[str] = []
            try:
                stream = _require_groq_client().chat.completions.create(
                    model=GROQ_MODEL, max_tokens=800, temperature=0.7,
                    messages=messages, stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        chunks.append(delta)
                        yield delta
            except Exception as e:
                yield f"\n[Lỗi: {e}]"
            finally:
                if chunks:
                    _session_append(session_id, "assistant", "".join(chunks).strip())
        return Response(stream_with_context(generate()),
                        mimetype="text/plain; charset=utf-8",
                        headers={"X-Accel-Buffering": "no"})

    try:
        res = _require_groq_client().chat.completions.create(
            model=GROQ_MODEL, max_tokens=800, temperature=0.7, messages=messages
        )
        reply = res.choices[0].message.content.strip()
        print(f"[CHAT] Reply: {reply[:80]!r}")
        _session_append(session_id, "assistant", reply)
        return jsonify({"reply": reply, "used_kb": bool(kb_context),
                        "kb_context": kb_context if data.get("debug") else None})
    except Exception as e:
        print(f"[CHAT] Groq error: {e}")
        fallback_reply = _extractive_chat_reply(user_message, kb_context, scan_context)
        _session_append(session_id, "assistant", fallback_reply)
        return jsonify({"reply": fallback_reply,
                        "used_kb": bool(kb_context),
                        "safe_mode": True,
                        "fallback_error": str(e),
                        "kb_context": kb_context if data.get("debug") else None})


@app.route("/kb/selected-docs", methods=["GET"])
def kb_get_selected_docs():
    """Return currently selected doc IDs stored server-side."""
    ids = _session_get_selected_doc_ids()
    return jsonify({"doc_ids": ids})


@app.route("/kb/selected-docs", methods=["POST"])
def kb_set_selected_docs():
    """Store selected doc IDs server-side so browser can read them."""
    data = request.get_json(force=True, silent=True) or {}
    ids = [int(x) for x in (data.get('doc_ids') or []) if str(x).strip().lstrip('-').isdigit()]
    _session_set_selected_doc_ids(ids)
    return jsonify({"ok": True, "doc_ids": ids})


@app.route("/session", methods=["GET"])
def session_state():
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return _json_error("Thiếu session_id.", 400)

    sess = _session_get(session_id)
    if not sess:
        return _json_error("Session không tồn tại hoặc đã hết hạn.", 404)

    return jsonify({
        "session_id": session_id,
        "created_at": sess["created_at"],
        "updated_at": sess["updated_at"],
        "turn_count": len(sess["turns"]),
        "turns": sess["turns"],
    })


def _as_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,;\n]", value)
        return [p.strip() for p in parts if p and p.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _parse_doc_ids(value: Any) -> List[int]:
    if value is None:
        return []
    if isinstance(value, str):
        items = re.split(r"[,;\n]", value)
    elif isinstance(value, list):
        items = value
    else:
        items = [value]

    doc_ids: List[int] = []
    for item in items:
        try:
            doc_id = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if doc_id >= 0:
            doc_ids.append(doc_id)
    return sorted(set(doc_ids))


def _quiz_build_source_text(
    source_text: str,
    query: str,
    subject: str,
    doc_ids: Optional[List[int]],
    scan_context: str,
    session_id: str,
) -> str:
    chunks: List[str] = []
    if source_text:
        chunks.append(source_text.strip())
    if scan_context:
        chunks.append(scan_context.strip())
    if query:
        kb_ctx = _fetch_kb_context(query, subject or None, doc_ids or None)
        if kb_ctx:
            chunks.append(kb_ctx.strip())
    if session_id:
        sess = _session_get(session_id)
        if sess and sess.get("turns"):
            recent_user_turns = [
                (t.get("content") or "").strip()
                for t in sess["turns"]
                if t.get("role") == "user" and (t.get("content") or "").strip()
            ][-4:]
            if recent_user_turns:
                chunks.append("\n".join(recent_user_turns))

    merged = "\n\n---\n\n".join(c for c in chunks if c)
    return merged[:4200]


def _quiz_pick_source_span(question_text: str, source_text: str) -> str:
    lines = [ln.strip() for ln in re.split(r"[\n\r]+", source_text) if ln.strip()]
    if not lines:
        return ""
    q_tokens = set(_tokenize(question_text))
    best_line = lines[0]
    best_score = -1.0
    for line in lines:
        line_tokens = set(_tokenize(line))
        overlap = len(q_tokens & line_tokens)
        density = overlap / max(1, len(q_tokens))
        score = overlap + density
        if score > best_score:
            best_score = score
            best_line = line
    return best_line[:220]


def _quiz_relevance_score(question: Dict[str, Any], source_text: str, user_need_tokens: set) -> float:
    q_text = (question.get("question") or "").strip()
    exp = (question.get("explanation") or "").strip()
    q_tokens = set(_tokenize(q_text + " " + exp))
    src_tokens = set(_tokenize(source_text[:2400]))

    if not q_tokens:
        return 0.0

    relevance = len(q_tokens & src_tokens) / max(1, len(q_tokens))
    need_fit = len(q_tokens & user_need_tokens) / max(1, len(user_need_tokens)) if user_need_tokens else 0.5

    diff = (question.get("difficulty") or "").strip().lower()
    difficulty_fit = 1.0 if diff in {"easy", "medium", "hard", "de"} else 0.7

    return 0.5 * relevance + 0.3 * need_fit + 0.2 * difficulty_fit


@app.route("/quiz", methods=["POST"])
def quiz_generate():
    blocked, retry_after, used, reset_at = _hourly_limited_quiz()
    if blocked:
        return _json_error(
            "Đã vượt quá số lượt /quiz trong 1 giờ.",
            429,
            code="quiz_hourly_limit",
            retry_after_sec=round(retry_after, 2),
            used=used,
            limit=QUIZ_HOURLY_LIMIT,
            reset_at=reset_at,
        )

    retry_after = _quiz_rate_limited()
    if retry_after > 0:
        return _json_error(
            "Bạn thao tác quá nhanh ở /quiz. Vui lòng thử lại sau giây lát.",
            429,
            code="quiz_rate_limited",
            retry_after_sec=round(retry_after, 2),
        )

    data = request.get_json(silent=True) or {}
    try:
        num_questions = int(data.get("num_questions", 3) or 3)
    except (TypeError, ValueError):
        return _json_error("num_questions phải là số nguyên.", 400, code="quiz_invalid_num_questions")
    num_questions = max(1, min(num_questions, 10))
    subject = (data.get("subject") or "").strip()
    doc_ids = _parse_doc_ids(data.get("doc_ids"))
    query = (data.get("query") or "").strip()
    source_text = (data.get("source_text") or "").strip()
    scan_context = (data.get("scan_context") or "").strip()
    session_id = (data.get("session_id") or "").strip()
    goal = (data.get("goal") or data.get("intent") or "").strip()
    difficulty = (data.get("difficulty") or "medium").strip().lower()
    focus_terms = _as_string_list(data.get("focus_terms"))
    weak_topics = _as_string_list(data.get("weak_topics"))

    if difficulty not in {"easy", "medium", "hard", "de"}:
        difficulty = "medium"

    source_text = _quiz_build_source_text(
        source_text=source_text,
        query=query,
        subject=subject,
        doc_ids=doc_ids,
        scan_context=scan_context,
        session_id=session_id,
    )

    if not source_text:
        return _json_error(
            "Thiếu ngữ cảnh để tạo quiz. Hãy truyền source_text, query, scan_context hoặc session_id.",
            400,
            code="quiz_missing_context",
        )

    user_need_tokens = set(_tokenize(" ".join([goal] + focus_terms + weak_topics + [query])))
    level_vi = {"easy": "dễ", "medium": "trung bình", "hard": "khó", "de": "dễ"}.get(difficulty, "trung bình")

    # Fallback nhanh cho môi trường không gọi được Groq.
    if ANDROID_SAFE_CHAT or client is None:
        raw_lines = [ln.strip() for ln in re.split(r"[\n\.\!\?]+", source_text) if ln.strip()]
        lines = raw_lines[:num_questions] if raw_lines else ["Nội dung bài học"]
        questions = []
        for i, line in enumerate(lines, start=1):
            stem = line[:120]
            source_span = _quiz_pick_source_span(stem, source_text)
            questions.append({
                "id": i,
                "question": f"Mệnh đề nào đúng nhất theo tài liệu: '{stem}'?",
                "options": [
                    f"Khẳng định: {stem}",
                    "Không thể kết luận từ tài liệu",
                    "Khẳng định ngược lại với tài liệu",
                    "Đáp án khác",
                ],
                "answer_index": 0,
                "explanation": "Dựa trực tiếp vào đoạn văn nguồn.",
                "source_span": source_span or stem,
                "skill_tag": "comprehension",
                "difficulty": level_vi,
            })
        return jsonify({
            "questions": questions,
            "count": len(questions),
            "safe_mode": True,
            "goal": goal,
            "difficulty": level_vi,
            "grounded": True,
        })

    prompt = (
        "Bạn là trợ lý tạo quiz bám sát nguồn. Yêu cầu bắt buộc:\n"
        f"- Sinh đúng {max(num_questions * 2, num_questions + 2)} câu để hệ thống rerank chọn câu tốt nhất.\n"
        "- Mỗi câu có 4 lựa chọn, chỉ 1 đáp án đúng.\n"
        "- Câu hỏi phải bám nội dung nguồn, không bịa ngoài nguồn.\n"
        "- explanation ngắn, rõ vì sao đáp án đúng.\n"
        "- source_span: trích nguyên văn 1-2 câu ngắn từ nguồn làm căn cứ.\n"
        "- skill_tag một trong: recall, comprehension, application, analysis.\n"
        f"- Độ khó mục tiêu: {level_vi}.\n"
        f"- Mục tiêu người học: {goal or 'ôn tập trọng tâm từ nội dung vừa học'}.\n"
        f"- Chủ đề yếu cần ưu tiên: {', '.join(weak_topics) if weak_topics else 'không có'}.\n"
        f"- Từ khóa ưu tiên: {', '.join(focus_terms) if focus_terms else 'không có'}.\n"
        "\nTrả về JSON duy nhất dạng:\n"
        '{"questions":[{"id":1,"question":"...","options":["A","B","C","D"],"answer_index":0,"explanation":"...","source_span":"...","skill_tag":"comprehension","difficulty":"dễ"}]}'
        "\n\nNguồn (ground truth):\n"
        + source_text[:3800]
    )

    try:
        res = _require_groq_client().chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=1800,
            temperature=0.35,
            messages=[
                {"role": "system", "content": "Chỉ trả về JSON hợp lệ, không markdown."},
                {"role": "user", "content": prompt},
            ],
        )
        raw = (res.choices[0].message.content or "").strip()
        if "```" in raw:
            for part in raw.split("```"):
                cand = part.strip().lstrip("json").strip()
                if cand.startswith("{"):
                    raw = cand
                    break
        payload = json.loads(raw)
        raw_questions = payload.get("questions") or []

        normalized = []
        for idx, q in enumerate(raw_questions, start=1):
            options = q.get("options") or []
            if not isinstance(options, list) or len(options) < 4:
                continue

            question_text = (q.get("question") or "").strip()
            if not question_text:
                continue

            answer_index = q.get("answer_index", 0)
            try:
                answer_index = int(answer_index)
            except (TypeError, ValueError):
                answer_index = 0
            answer_index = max(0, min(answer_index, 3))

            source_span = (q.get("source_span") or "").strip()
            if not source_span:
                source_span = _quiz_pick_source_span(question_text, source_text)

            difficulty_out = (q.get("difficulty") or level_vi).strip().lower()
            if difficulty_out not in {"dễ", "trung bình", "khó", "easy", "medium", "hard"}:
                difficulty_out = level_vi

            item = {
                "id": idx,
                "question": question_text,
                "options": [str(opt) for opt in options[:4]],
                "answer_index": answer_index,
                "explanation": (q.get("explanation") or "").strip(),
                "source_span": source_span,
                "skill_tag": (q.get("skill_tag") or "comprehension").strip().lower(),
                "difficulty": difficulty_out,
            }
            item["_score"] = _quiz_relevance_score(item, source_text, user_need_tokens)
            normalized.append(item)

        if not normalized:
            return _json_error("Không thể tạo bộ câu hỏi hợp lệ từ ngữ cảnh hiện tại.", 500, code="quiz_generation_empty")

        normalized.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
        selected = normalized[:num_questions]
        for i, q in enumerate(selected, start=1):
            q["id"] = i
            q.pop("_score", None)

        return jsonify({
            "questions": selected,
            "count": len(selected),
            "goal": goal,
            "difficulty": level_vi,
            "grounded": True,
        })
    except Exception as e:
        return _json_error(f"Không thể tạo quiz: {e}", 500, code="quiz_generation_failed")

@app.route("/chat", methods=["POST"])
def chat():
    """Voice/text chat với RAG context tự động."""
    blocked, retry_after, used, reset_at = _hourly_limited_chat()
    if blocked:
        return _json_error(
            "Đã vượt quá số lượt /chat trong 1 giờ.",
            429,
            code="chat_hourly_limit",
            retry_after_sec=round(retry_after, 2),
            used=used,
            limit=CHAT_HOURLY_LIMIT,
            reset_at=reset_at,
        )

    retry_after = _chat_rate_limited()
    if retry_after > 0:
        return _json_error(
            "Bạn thao tác quá nhanh ở /chat. Vui lòng thử lại sau giây lát.",
            429,
            code="chat_rate_limited",
            retry_after_sec=round(retry_after, 2),
        )

    data = request.get_json(silent=True) or {}
    return _chat_core(data, force_stream=False)


@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    blocked, retry_after, used, reset_at = _hourly_limited_chat()
    if blocked:
        return _json_error(
            "Đã vượt quá số lượt /chat/stream trong 1 giờ.",
            429,
            code="chat_hourly_limit",
            retry_after_sec=round(retry_after, 2),
            used=used,
            limit=CHAT_HOURLY_LIMIT,
            reset_at=reset_at,
        )

    retry_after = _chat_rate_limited()
    if retry_after > 0:
        return _json_error(
            "Bạn thao tác quá nhanh ở /chat/stream. Vui lòng thử lại sau giây lát.",
            429,
            code="chat_rate_limited",
            retry_after_sec=round(retry_after, 2),
        )

    data = request.get_json(silent=True) or {}
    return _chat_core(data, force_stream=True)


@app.route("/test")
def test_camera():
    return render_template("index.html")


# ==============================================================================
# ==== START ===================================================================
# ==============================================================================

_server_has_started = False


def start_dalap_server():
    """Start Flask server for Chaquopy and direct Python execution."""
    global _server_has_started
    if _server_has_started:
        print("[START] DALAP server already running")
        return

    _server_has_started = True

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"

    try:
        host_name = socket.gethostname().strip().split('.')[0]
    except Exception:
        host_name = "dalap"
    host_name = host_name or "dalap"

    force_http = os.getenv("RESFES_FORCE_HTTP", "false").strip().lower() in {"1", "true", "yes"}
    public_url = os.getenv("RESFES_PUBLIC_URL", "").strip()
    cert_default = str((DATA_DIR / "certs").resolve())
    cert_dir  = Path(os.getenv("RESFES_CERT_DIR", cert_default)).resolve()
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_file = str(cert_dir / "cert.pem")
    key_file  = str(cert_dir / "key.pem")
    if not force_http:
        copy_packaged_cert_if_needed(cert_file, key_file)

    if force_http:
        cert_file = key_file = None
        print("🌐 RESFES_FORCE_HTTP=1 → chạy upstream HTTP (dùng tunnel/proxy bên ngoài).")
    else:
        rotate_before = int(os.getenv("RESFES_CERT_ROTATE_BEFORE_DAYS", "14"))
        force_regen   = os.getenv("RESFES_REGEN_CERT", "false").lower() in {"1","true","yes"}

        need_cert = force_regen or not os.path.exists(cert_file) or not os.path.exists(key_file) or not cert_is_usable(
            cert_file, collect_local_dns_names(), ["127.0.0.1", local_ip], rotate_before
        )

        if need_cert:
            print("\n🔒 Tạo HTTPS certificate...")
            try:
                # Remove stale or malformed files before regenerating.
                for p in (cert_file, key_file):
                    try:
                        if p and os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                create_self_signed_cert(cert_file, key_file, local_ip)
                print("✅ Certificate OK")
            except ImportError:
                if copy_packaged_cert_if_needed(cert_file, key_file):
                    print("⚠️  pyOpenSSL chưa có, dùng certificate đã bundle.")
                else:
                    print("⚠️  pyOpenSSL chưa có và không tìm thấy certificate bundle.")
                    cert_file = key_file = None
            except Exception as e:
                print(f"⚠️  Tạo certificate thất bại: {e}")
                cert_file = key_file = None
        else:
            print("🔒 Certificate hợp lệ, dùng lại.")

    proto = "https" if cert_file and os.path.exists(cert_file) else "http"
    stable_host_url = f"{proto}://{host_name}:{PORT}"
    stable_mdns_url = f"{proto}://{host_name}.local:{PORT}"

    print(f"""
╔══════════════════════════════════════════════════╗
║      DALAP AR — Learning Assistant + RAG         ║
╠══════════════════════════════════════════════════╣
║  💻  {proto}://localhost:{PORT}
║  📱  {proto}://{local_ip}:{PORT}
║  🔗  {stable_mdns_url}
║  🏷️  {stable_host_url}
║  🌍  {public_url or '(not set)'}
║                                                  ║
║  POST /analyze  → Vision OCR + Socratic hint     ║
║  POST /ask      → RAG: hỏi từ tài liệu          ║
║  POST /chat     → Voice/text chat + KB context   ║
║  POST /kb/upload → Upload & index tài liệu       ║
╚══════════════════════════════════════════════════╝
""")

    ssl_ctx = (cert_file, key_file) if (cert_file and os.path.exists(cert_file)) else None
    if not ssl_ctx:
        if public_url.startswith("https://"):
            print("✅ HTTP upstream + HTTPS public URL: camera sẽ hoạt động qua tunnel/proxy.")
        else:
            print("⚠️  HTTP mode — camera sẽ KHÔNG hoạt động qua network nếu URL không phải HTTPS.")

    print(f"[START] Flask running on port {PORT}...")
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, ssl_context=ssl_ctx, threaded=True)
    except Exception as e:
        print(f"[CRITICAL] Flask failed to start: {e}")
        raise e


def start_resfes_server():
    """Backward compatibility entry point for older Android/Kotlin callers."""
    return start_dalap_server()


if __name__ == "__main__":
    start_dalap_server()