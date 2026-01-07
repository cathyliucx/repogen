from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore


@dataclass
class RagChunk:
    text: str
    source: str
    idx: int


class LocalRag:
    """Small local RAG helper.

    Uses sentence-transformers if available; FAISS if available; otherwise substring search.
    Designed to be dependency-light and robust.
    """

    def __init__(self, *, device: str = "cpu", chunk_size: int = 1200, overlap: int = 150):
        self.device = device
        self.chunk_size = chunk_size
        self.overlap = overlap

        self._chunks: List[RagChunk] = []
        self._embeddings = None

        self._model = None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device=device)
        except Exception:
            self._model = None

        self._faiss = None
        try:
            import faiss  # type: ignore

            self._faiss = faiss
        except Exception:
            self._faiss = None

        self._index = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def _chunk(self, text: str) -> list[str]:
        if self.chunk_size <= 0:
            return [text]
        chunks: list[str] = []
        i = 0
        while i < len(text):
            j = min(len(text), i + self.chunk_size)
            chunks.append(text[i:j])
            if j >= len(text):
                break
            i = max(0, j - self.overlap)
        return chunks

    def add_text(self, text: str, *, source: str) -> None:
        for i, ch in enumerate(self._chunk(text)):
            self._chunks.append(RagChunk(text=ch, source=source, idx=i))

    def build(self) -> None:
        if not self._chunks:
            self._embeddings = None
            return

        if self._model is None or np is None:
            self._embeddings = None
            return

        texts = [c.text for c in self._chunks]
        embs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        embs = np.asarray(embs, dtype=np.float32)
        self._embeddings = embs

        if self._faiss is not None:
            dim = embs.shape[1]
            index = self._faiss.IndexFlatIP(dim)
            index.add(embs)
            self._index = index

    def query(self, q: str, *, k: int = 4) -> list[RagChunk]:
        q = q.strip()
        if not q:
            return []

        if self._model is None or self._embeddings is None or np is None:
            ql = q.lower()
            scored: List[Tuple[int, RagChunk]] = []
            for c in self._chunks:
                s = c.text.lower().count(ql)
                if s:
                    scored.append((s, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [c for _, c in scored[:k]]

        q_emb = self._model.encode([q], normalize_embeddings=True, show_progress_bar=False)
        q_emb = np.asarray(q_emb, dtype=np.float32)

        if self._index is not None:
            _, idxs = self._index.search(q_emb, k)
            hits: list[RagChunk] = []
            for i in idxs[0]:
                if i < 0:
                    continue
                hits.append(self._chunks[int(i)])
            return hits

        sims = (self._embeddings @ q_emb[0]).tolist()
        pairs = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)[:k]
        return [self._chunks[i] for i, _ in pairs]
