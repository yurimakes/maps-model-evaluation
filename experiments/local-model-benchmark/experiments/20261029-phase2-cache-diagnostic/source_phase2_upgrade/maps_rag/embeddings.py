# -*- coding: utf-8 -*-
"""임베딩(글 → 숫자 1,536개) 저장소.

- 글 내용의 지문(sha1)을 열쇠로 저장한다 → 글이 바뀌면 지문이 달라져 자동으로 '다시 계산 대상'이 된다.
- 파일 하나(.npz)에 [열쇠 목록, 숫자표]를 담는다. Databricks 에는 이 파일을 올려 두고 읽기만 한다.
"""
import hashlib
from pathlib import Path

import numpy as np


def text_key(text):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def chunk_text(c):
    return f"{c.get('title', '')}\n{c.get('text', '')}"


class VectorStore:
    def __init__(self):
        self.vecs = {}   # 열쇠 → 벡터(list)

    @classmethod
    def load(cls, path):
        s = cls()
        p = Path(path)
        if p.exists():
            z = np.load(p, allow_pickle=False)
            for k, v in zip(z["keys"].tolist(), z["vecs"]):
                s.vecs[k] = v.astype(np.float32)
        return s

    def save(self, path):
        keys = sorted(self.vecs)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, keys=np.array(keys), vecs=np.array([self.vecs[k] for k in keys], dtype=np.float32))

    def get(self, text):
        return self.vecs.get(text_key(text))

    def missing(self, texts):
        seen, out = set(), []
        for t in texts:
            k = text_key(t)
            if k not in self.vecs and k not in seen:
                seen.add(k)
                out.append(t)
        return out

    def add(self, texts, vectors):
        for t, v in zip(texts, vectors):
            self.vecs[text_key(t)] = np.asarray(v, dtype=np.float32)

    def chunk_vectors(self, chunks):
        """{chunk_id: 벡터} — 저장된 벡터 중 내용이 같은 것만."""
        out = {}
        for c in chunks:
            v = self.get(chunk_text(c))
            if v is not None:
                out[c["chunk_id"]] = v
        return out
