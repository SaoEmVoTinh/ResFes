import hashlib
import heapq
import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

_TOKEN_RE = re.compile(r"\b\w+\b", re.UNICODE)


class HashEmbedding:
    """Lightweight embedding for on-device environments without heavy ML deps."""

    def __init__(self, dim: int = 384, model_name: str = "hash-emb-v1"):
        self.dim = max(64, int(dim))
        self.model_name = model_name

    def _tokenize(self, text: str) -> List[str]:
        return _TOKEN_RE.findall((text or "").lower())

    def embed(self, text: str) -> List[float]:
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.dim

        vec = [0.0] * self.dim
        n = len(tokens)
        for i, tok in enumerate(tokens):
            # Hashing trick with signed bucket updates.
            digest = hashlib.blake2b(tok.encode("utf-8", errors="ignore"), digest_size=16).digest()
            idx = int.from_bytes(digest[:8], "big") % self.dim
            sign = 1.0 if (digest[8] & 1) == 0 else -1.0

            # Slight position signal helps distinguish repeated patterns.
            pos_weight = 1.0 + (i / max(1, n - 1)) * 0.1
            vec[idx] += sign * pos_weight

            # Add a second bucket for a softer spread.
            idx2 = int.from_bytes(digest[8:], "big") % self.dim
            vec[idx2] += sign * 0.35

        norm = math.sqrt(sum(v * v for v in vec))
        if norm <= 1e-12:
            return vec
        return [v / norm for v in vec]


class SQLiteVectorDB:
    def __init__(
        self,
        db_path: Path,
        timeout_sec: float = 10.0,
        busy_ms: int = 10000,
        dim: int = 384,
        model_name: str = "hash-emb-v1",
    ):
        self.db_path = Path(db_path)
        self.timeout_sec = float(timeout_sec)
        self.busy_ms = int(busy_ms)
        self.embedding = HashEmbedding(dim=dim, model_name=model_name)

    @property
    def dim(self) -> int:
        return self.embedding.dim

    @property
    def model_name(self) -> str:
        return self.embedding.model_name

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_sec)
        conn.execute(f"PRAGMA busy_timeout = {self.busy_ms}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chunk_vectors (
                    chunk_id    INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                    doc_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    subject     TEXT DEFAULT '',
                    embedding   TEXT NOT NULL,
                    dim         INTEGER NOT NULL,
                    model_name  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chunk_vectors_doc_id
                    ON chunk_vectors(doc_id);

                CREATE INDEX IF NOT EXISTS idx_chunk_vectors_subject
                    ON chunk_vectors(subject);
                """
            )

    def upsert_document_chunks(
        self,
        doc_id: int,
        chunks: Sequence[sqlite3.Row],
        subject: str = "",
    ) -> int:
        subject = (subject or "").strip().lower()
        now = datetime.utcnow().isoformat() + "Z"

        rows = []
        for row in chunks:
            chunk_id = int(row["id"])
            text = row["text"] or ""
            emb = self.embedding.embed(text)
            rows.append(
                (
                    chunk_id,
                    int(doc_id),
                    subject,
                    json.dumps(emb, separators=(",", ":")),
                    self.dim,
                    self.model_name,
                    now,
                )
            )

        if not rows:
            return 0

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO chunk_vectors
                    (chunk_id, doc_id, subject, embedding, dim, model_name, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    subject = excluded.subject,
                    embedding = excluded.embedding,
                    dim = excluded.dim,
                    model_name = excluded.model_name,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def delete_document(self, doc_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chunk_vectors WHERE doc_id = ?", (int(doc_id),))

    def stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
            docs = conn.execute("SELECT COUNT(DISTINCT doc_id) FROM chunk_vectors").fetchone()[0]
            return {
                "ok": True,
                "vectors": int(total),
                "vector_docs": int(docs),
                "dim": self.dim,
                "model": self.model_name,
            }

    def search(self, query: str, top_k: int = 4, subject: Optional[str] = None, doc_ids: Optional[Sequence[int]] = None) -> List[dict]:
        q = self.embedding.embed(query)
        if not any(q):
            return []

        k = max(1, int(top_k))
        doc_id_list = [int(d) for d in (doc_ids or []) if str(d).strip().isdigit()]

        params: Iterable[object]
        sql = (
            "SELECT v.chunk_id, v.doc_id, v.subject, v.embedding, c.text "
            "FROM chunk_vectors v "
            "JOIN chunks c ON c.id = v.chunk_id "
        )

        clauses = []
        params_list: list[object] = []

        subject = (subject or "").strip().lower()
        if subject:
            clauses.append("v.subject = ?")
            params_list.append(subject)
        if doc_id_list:
            placeholders = ",".join("?" for _ in doc_id_list)
            clauses.append(f"v.doc_id IN ({placeholders})")
            params_list.extend(doc_id_list)

        if clauses:
            sql += "WHERE " + " AND ".join(clauses) + " "
        params = tuple(params_list)

        top_heap = []
        with self._connect() as conn:
            cursor = conn.execute(sql, tuple(params))
            for row in cursor:
                try:
                    v = json.loads(row["embedding"])
                    score = _dot(q, v)
                    if score <= 0:
                        continue
                    item = {
                        "chunk_id": int(row["chunk_id"]),
                        "doc_id": int(row["doc_id"]),
                        "text": row["text"] or "",
                        "subject": row["subject"] or "",
                        "score": round(float(score), 4),
                    }
                    if len(top_heap) < k:
                        heapq.heappush(top_heap, (score, item))
                    elif score > top_heap[0][0]:
                        heapq.heapreplace(top_heap, (score, item))
                except Exception:
                    continue

        top_heap.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in top_heap]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    return sum(float(a[i]) * float(b[i]) for i in range(n))
