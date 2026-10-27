"""Retrieve: find the documentation passages that bear on a ticket (FR-03, A4).

Chunking (ADR-03): every article has the same structure (title, applies-to, symptoms, common causes,
numbered resolution, notes). We chunk by *section*, never splitting the numbered resolution steps,
and prefix every chunk with the article title so a chunk read alone still says what it is about.
The alternative evaluated was the Setup Guide's fixed 800/120 character splitter; the comparison is
reproducible with `python -m evaluation.retrieval_experiment`.

Every passage carries a `chunk_id` of the form `DOC-XXX-NNN#section`, which resolves back to the real
corpus via `Corpus.resolve` - citations are checked against this, never invented (A6).

Backends:
  * `chroma`: Chroma persistent store with all-MiniLM-L6-v2 embeddings (the prescribed stack).
  * `tfidf`: a local TF-IDF index used automatically if Chroma or the embedding model cannot be
    loaded (no network on first run, CI). The active backend is recorded in every decision.

Ranking combines semantic similarity with a prior learned from the development labels
(P(document | predicted intent)), which helps when a customer's words do not match the article's
words - the exact problem Ines Varga describes, and the one that most affects non-fluent writers.
A relevance threshold is applied: if nothing clears it, *nothing* is returned (A4, FR-03).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .config import Settings
from .schemas import Passage, Retrieval

log = logging.getLogger(__name__)
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str  # text shown to people and to the model
    index_text: str  # text that is embedded / indexed


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "section"


def chunk_by_section(doc: dict) -> list[Chunk]:
    content = doc.get("content", "") or ""
    title = doc.get("title", doc.get("doc_id", ""))
    applies = doc.get("applies_to", "")
    matches = list(_SECTION.finditer(content))
    chunks: list[Chunk] = []
    if not matches:
        return [Chunk(f"{doc['doc_id']}#full", doc["doc_id"], title, "full", content.strip(), f"{title}\n{content}")]
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[m.end():end].strip()
        if not body:
            continue
        cid = f"{doc['doc_id']}#{_slug(name)}"
        chunks.append(Chunk(cid, doc["doc_id"], title, name, body, f"{title}. {name}. Applies to {applies}.\n{body}"))
    return chunks


def chunk_fixed(doc: dict, size: int = 800, overlap: int = 120) -> list[Chunk]:
    content = doc.get("content", "") or ""
    title = doc.get("title", doc["doc_id"])
    out, start, n = [], 0, 0
    while start < len(content):
        piece = content[start:start + size].strip()
        if piece:
            out.append(Chunk(f"{doc['doc_id']}#part{n}", doc["doc_id"], title, f"part {n}", piece, f"{title}\n{piece}"))
            n += 1
        start += size - overlap
    return out


class Corpus:
    def __init__(self, docs: list[dict], chunking: str = "section"):
        self.docs = {d["doc_id"]: d for d in docs}
        maker = chunk_by_section if chunking == "section" else chunk_fixed
        self.chunks: list[Chunk] = [c for d in docs for c in maker(d)]
        self.by_id = {c.chunk_id: c for c in self.chunks}
        self.chunking = chunking
        self.hash = hashlib.sha256(
            json.dumps([[c.chunk_id, c.index_text] for c in self.chunks]).encode("utf-8")
        ).hexdigest()[:12]

    @classmethod
    def load(cls, path: Path, chunking: str = "section") -> "Corpus":
        docs = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cls(docs, chunking)

    def resolve(self, chunk_id: str) -> Optional[Chunk]:
        return self.by_id.get(chunk_id)

    def resolution_chunk(self, doc_id: str) -> Optional[Chunk]:
        for c in self.chunks:
            if c.doc_id == doc_id and c.section.lower().startswith("resolution"):
                return c
        return None


# ------------------------------------------------------------------------------------- backends
class TfidfBackend:
    name = "tfidf"

    def __init__(self, corpus: Corpus):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.pipeline import make_union

        self.corpus = corpus
        self.vec = make_union(
            TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english"),
            TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True),
        )
        self.matrix = self.vec.fit_transform([c.index_text for c in corpus.chunks])
        norms = np.sqrt(self.matrix.multiply(self.matrix).sum(axis=1)).A1
        self.norms = np.where(norms == 0, 1.0, norms)

    def similarities(self, query: str) -> np.ndarray:
        q = self.vec.transform([query])
        qn = np.sqrt(q.multiply(q).sum())
        if qn == 0:
            return np.zeros(len(self.corpus.chunks))
        return (self.matrix @ q.T).toarray().ravel() / (self.norms * qn)


class ChromaBackend:
    """Chroma + all-MiniLM-L6-v2. Uses Chroma's bundled ONNX build of the model (no PyTorch needed);
    the model file (~90 MB) is downloaded once and cached on first use."""

    name = "chroma-minilm"

    def __init__(self, corpus: Corpus, settings: Settings):
        import chromadb  # noqa: WPS433 (optional heavy import)
        from chromadb.config import Settings as ChromaSettings
        from chromadb.utils import embedding_functions

        self.corpus = corpus
        if settings.embedding_model not in ("all-MiniLM-L6-v2", "sentence-transformers/all-MiniLM-L6-v2"):
            ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
        else:
            ef = embedding_functions.ONNXMiniLM_L6_V2()
        settings.chroma_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=str(settings.chroma_path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        name = f"cloudserve_{corpus.chunking}_{corpus.hash}"
        self.collection = client.get_or_create_collection(
            name=name, embedding_function=ef, metadata={"hnsw:space": "cosine"}
        )
        if self.collection.count() != len(corpus.chunks):
            ids = [c.chunk_id for c in corpus.chunks]
            existing = self.collection.get(ids=ids).get("ids", []) if self.collection.count() else []
            if existing:
                self.collection.delete(ids=existing)
            self.collection.add(
                ids=ids,
                documents=[c.index_text for c in corpus.chunks],
                metadatas=[{"doc_id": c.doc_id, "section": c.section} for c in corpus.chunks],
            )
        self._index = {c.chunk_id: i for i, c in enumerate(corpus.chunks)}
        # Smoke test so a broken embedding model fails here (and we fall back) rather than mid-run.
        self.similarities("health check")

    def similarities(self, query: str) -> np.ndarray:
        res = self.collection.query(query_texts=[query or " "], n_results=len(self.corpus.chunks))
        sims = np.zeros(len(self.corpus.chunks))
        for cid, dist in zip(res["ids"][0], res["distances"][0]):
            if cid in self._index:
                sims[self._index[cid]] = 1.0 - float(dist)  # cosine distance -> similarity
        return sims


def make_backend(corpus: Corpus, settings: Settings):
    choice = (settings.retrieval_backend or "auto").lower()
    if choice in ("auto", "chroma"):
        try:
            return ChromaBackend(corpus, settings)
        except Exception as exc:
            if choice == "chroma":
                log.error("Chroma backend requested but unavailable: %s", exc)
            log.warning("Chroma/MiniLM unavailable (%s: %s); using local TF-IDF retrieval", type(exc).__name__, exc)
    return TfidfBackend(corpus)


# ------------------------------------------------------------------------------------- retriever
class Retriever:
    """Ranks chunks for a query, combines with the intent prior, applies the relevance threshold."""

    PRIOR_WEIGHT = 0.35

    def __init__(self, corpus: Corpus, backend, intent_doc_prior: Optional[dict] = None, min_score: float = 0.2):
        self.corpus = corpus
        self.backend = backend
        self.prior = intent_doc_prior or {}
        self.min_score = min_score

    @property
    def backend_name(self) -> str:
        return getattr(self.backend, "name", "unknown")

    def doc_scores(self, query: str, intent: Optional[str] = None, intent_conf: float = 0.0) -> dict[str, tuple[float, float, str]]:
        """Return {doc_id: (combined_score, raw_similarity, best_chunk_id)}."""
        sims = self.backend.similarities(query)
        best: dict[str, tuple[float, str]] = {}
        for c, s in zip(self.corpus.chunks, sims):
            if c.doc_id not in best or s > best[c.doc_id][0]:
                best[c.doc_id] = (float(s), c.chunk_id)
        prior = self.prior.get(intent or "", {}) if intent_conf > 0 else {}
        out = {}
        for doc_id, (s, cid) in best.items():
            p = prior.get(doc_id, 0.0) * intent_conf
            out[doc_id] = ((1 - self.PRIOR_WEIGHT) * s + self.PRIOR_WEIGHT * p, s, cid)
        return out

    def retrieve(self, query: str, intent: Optional[str] = None, intent_conf: float = 0.0, k: int = 5) -> Retrieval:
        try:
            scores = self.doc_scores(query, intent, intent_conf)
        except Exception as exc:
            log.exception("retrieval failed")
            return Retrieval([], f"{self.backend_name}:error:{type(exc).__name__}", query, False, 0.0, self.min_score)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1][0])
        passages: list[Passage] = []
        for doc_id, (combined, raw, cid) in ranked:
            if combined < self.min_score or len(passages) >= k:
                break
            chunk = self.corpus.resolve(cid)
            res = self.corpus.resolution_chunk(doc_id)
            for c in [res, chunk] if res and res.chunk_id != cid else [chunk]:
                if c is not None and len(passages) < k:
                    passages.append(Passage(c.chunk_id, c.doc_id, c.title, c.section, c.text, round(combined, 4)))
        best = ranked[0][1][0] if ranked else 0.0
        return Retrieval(passages, self.backend_name, query, bool(passages), round(best, 4), self.min_score)


def learn_intent_doc_prior(tickets) -> dict:
    """P(doc | intent) from development labels (expected_doc_ids)."""
    counts: dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    for t in tickets:
        intent = t.labels.get("intent")
        if not intent:
            continue
        totals[intent] += 1
        for d in t.labels.get("expected_doc_ids") or []:
            counts[intent][d] += 1
    return {i: {d: n / totals[i] for d, n in c.items()} for i, c in counts.items()}
