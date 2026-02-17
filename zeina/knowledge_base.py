"""
Local knowledge base for Zeina AI Assistant.

Scans data/knowledge_base/ for .txt and .md files, chunks them by paragraph,
embeds them with sentence-transformers, and answers queries via cosine similarity.
No external API or vector database required — all processing is local.

The embedding model (all-MiniLM-L6-v2, ~100 MB) is downloaded from HuggingFace
on first use and cached in ~/.cache/huggingface/.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

_CHUNK_TARGET = 512        # Target characters per chunk
_MIN_SIMILARITY = 0.25     # Minimum cosine similarity to include a result
_TOP_K = 3                 # Number of results to return


class KnowledgeBase:
    """Manages a local vector store built from text and markdown files.

    Thread-safe: indexing runs in the background and search waits for it.
    """

    def __init__(self, kb_dir: str):
        self._kb_dir = Path(kb_dir)
        self._model = None          # SentenceTransformer, lazy-loaded
        self._chunks: list[dict] = []       # [{text, source}]
        self._embeddings: Optional[np.ndarray] = None
        self._indexed = False
        self._index_lock = threading.Lock()
        self._index_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = _TOP_K) -> str:
        """Return the top-k most relevant chunks for query as a formatted string."""
        self._ensure_indexed()

        if not self._chunks or self._embeddings is None:
            return (
                "The knowledge base is empty. "
                "Add .txt or .md files to data/knowledge_base/ to use this feature."
            )

        model = self._get_model()
        query_emb = model.encode([query], normalize_embeddings=True)
        sims = np.dot(self._embeddings, query_emb.T).squeeze()

        # Handle single-chunk case (sims is a scalar)
        if sims.ndim == 0:
            sims = np.array([float(sims)])

        top_indices = np.argsort(sims)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(sims[idx])
            if score < _MIN_SIMILARITY:
                break
            chunk = self._chunks[idx]
            results.append(f"[From {chunk['source']}]\n{chunk['text']}")

        if not results:
            return "No relevant information found in the knowledge base for that query."

        return "\n\n---\n\n".join(results)

    def reindex(self) -> None:
        """Force a fresh scan and re-embedding of all documents."""
        with self._index_lock:
            self._indexed = False
            self._index_event.clear()
        self._ensure_indexed()

    def document_count(self) -> int:
        """Return the number of source files currently indexed."""
        if not self._indexed:
            return 0
        sources = {c['source'] for c in self._chunks}
        return len(sources)

    def chunk_count(self) -> int:
        """Return the total number of text chunks indexed."""
        return len(self._chunks)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _ensure_indexed(self) -> None:
        """Build the index if not already done. Blocks until indexing completes."""
        if self._indexed:
            return
        with self._index_lock:
            if self._indexed:
                return
            self._build_index()
            self._indexed = True

    def _build_index(self) -> None:
        """Scan kb_dir, chunk all files, embed them, store in memory."""
        self._kb_dir.mkdir(parents=True, exist_ok=True)

        chunks: list[dict] = []
        for pattern in ("**/*.txt", "**/*.md"):
            for fpath in self._kb_dir.glob(pattern):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                    for chunk in self._chunk_text(text, fpath.name):
                        chunks.append(chunk)
                except OSError:
                    continue

        for fpath in self._kb_dir.glob("**/*.pdf"):
            try:
                text = self._read_pdf(fpath)
                if text:
                    for chunk in self._chunk_text(text, fpath.name):
                        chunks.append(chunk)
            except Exception:
                continue

        self._chunks = chunks
        if not chunks:
            self._embeddings = None
            return

        model = self._get_model()
        texts = [c['text'] for c in chunks]
        self._embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    def _chunk_text(self, text: str, source: str) -> list[dict]:
        """Split text into paragraph-based chunks of roughly _CHUNK_TARGET chars."""
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        chunks: list[dict] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 <= _CHUNK_TARGET:
                current = (current + "\n\n" + para).strip() if current else para
            else:
                if current:
                    chunks.append({"text": current, "source": source})
                # If the paragraph itself exceeds the target, split by line
                if len(para) > _CHUNK_TARGET:
                    for line in para.splitlines():
                        line = line.strip()
                        if line:
                            chunks.append({"text": line, "source": source})
                    current = ""
                else:
                    current = para

        if current:
            chunks.append({"text": current, "source": source})

        return chunks

    def _read_pdf(self, fpath: Path) -> str:
        """Extract text from a PDF file using pypdf."""
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError(
                "pypdf is not installed. Run: pip install pypdf"
            )
        reader = PdfReader(str(fpath))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        return "\n\n".join(pages)

    def _get_model(self):
        """Return the SentenceTransformer model, loading it on first call."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers is not installed. "
                    "Run: pip install sentence-transformers"
                )
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
        return self._model


# Module-level singleton — lazily created when the tool is first called.
_kb_instance: Optional[KnowledgeBase] = None


def get_kb() -> KnowledgeBase:
    """Return the shared KnowledgeBase instance, creating it on first call."""
    global _kb_instance
    if _kb_instance is None:
        from zeina import config as _cfg
        _kb_instance = KnowledgeBase(_cfg.KB_DIR)
    return _kb_instance
