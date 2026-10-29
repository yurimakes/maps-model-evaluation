# -*- coding: utf-8 -*-
"""검색: ① 키워드(BM25)  ② 임베딩(뜻 비슷한 것)  ③ 둘을 합친 하이브리드.

쉬운 설명
- 키워드 검색: 질문에 나온 낱말이 카드에 얼마나 들어 있나(글자 조각까지 봄).
- 임베딩 검색: 카드와 질문을 숫자 1,536개짜리 좌표로 바꿔서, 좌표가 가까운 카드를 찾음(뜻이 비슷하면 가까움).
- 하이브리드: 두 점수를 0~1로 맞춰 반반 섞음.
"""
import math
import re
from collections import Counter

import numpy as np


def tokens(text):
    text = (text or "").lower()
    out = []
    for w in re.findall(r"[a-z0-9]+|[가-힣]+", text):
        out.append(w)
        if re.match(r"[가-힣]", w) and len(w) > 1:
            out += [w[i:i + 2] for i in range(len(w) - 1)]
    return out


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokens(d)) for d in docs]
        self.len = [sum(c.values()) for c in self.docs]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 1.0
        df = Counter()
        for c in self.docs:
            df.update(c.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query):
        q = Counter(tokens(query))
        out = np.zeros(len(self.docs))
        for i, c in enumerate(self.docs):
            s = 0.0
            for t in q:
                if t in c:
                    f = c[t]
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            out[i] = s
        return out


def _norm(a):
    a = np.asarray(a, dtype=float)
    if a.size == 0:
        return a
    lo, hi = a.min(), a.max()
    return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)


class Retriever:
    """chunks: 검색해도 되는 카드 목록. vectors: {chunk_id: 임베딩 벡터}(없으면 임베딩 검색은 건너뜀)."""

    def __init__(self, chunks, vectors=None, w_bm25=0.5, w_emb=0.5):
        self.chunks = chunks
        self.bm25 = BM25([c["text"] for c in chunks])
        self.vectors = vectors or {}
        self.w_bm25, self.w_emb = w_bm25, w_emb
        self._mat = None
        if self.vectors and all(c["chunk_id"] in self.vectors for c in chunks):
            m = np.array([self.vectors[c["chunk_id"]] for c in chunks], dtype=np.float32)
            m /= (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
            self._mat = m

    def has_embeddings(self):
        return self._mat is not None

    def search(self, query_text, query_vec=None, mode="hybrid", k=6, allow=None):
        """mode: 'bm25' | 'embedding' | 'hybrid'.  allow(chunk)->bool 로 후보를 미리 걸러 낸다."""
        idx = [i for i, c in enumerate(self.chunks) if (allow is None or allow(c))]
        if not idx:
            return []
        b = self.bm25.scores(query_text)[idx]
        e = np.zeros(len(idx))
        if mode in ("embedding", "hybrid") and self._mat is not None and query_vec is not None:
            qv = np.asarray(query_vec, dtype=np.float32)
            qv = qv / (np.linalg.norm(qv) + 1e-9)
            e = (self._mat[idx] @ qv)
        else:
            mode = "bm25" if mode != "embedding" else "embedding"
        if mode == "bm25":
            s = _norm(b)
        elif mode == "embedding":
            s = _norm(e)
        else:
            s = self.w_bm25 * _norm(b) + self.w_emb * _norm(e)
        order = np.argsort(-s)[:k]
        return [{"chunk": self.chunks[idx[j]], "score": float(s[j]), "bm25": float(b[j]), "cos": float(e[j])} for j in order]
