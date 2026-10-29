"""Drop-in Retriever with explicit cache coverage and deterministic rank fusion."""
import numpy as np
from .legacy_retrieval import BM25,_norm

class Retriever:
    def __init__(self,chunks,vectors=None,w_bm25=.5,w_emb=.5,text_normalizer=None,rrf_k=60,fusion='weighted'):
        self.chunks=chunks;self.normalizer=text_normalizer or (lambda x:x)
        self.bm25=BM25([self.normalizer(c['text']) for c in chunks])
        if fusion not in ['weighted','rrf']:raise ValueError('Unknown fusion method')
        self.vectors={};self.w_bm25=w_bm25;self.w_emb=w_emb;self.rrf_k=rrf_k;self.fusion=fusion;self.last_status={}
        dimension=None
        for c in chunks:
            v=(vectors or {}).get(c['chunk_id'])
            if v is None:continue
            v=np.asarray(v,dtype=float)
            if v.ndim!=1 or not np.isfinite(v).all() or np.linalg.norm(v)==0:continue
            if dimension is None:dimension=len(v)
            if len(v)!=dimension:continue
            self.vectors[c['chunk_id']]=v/np.linalg.norm(v)

    def has_embeddings(self):return bool(self.vectors)

    def search(self,query_text,query_vec=None,mode='hybrid',k=6,allow=None):
        if mode not in ['bm25','embedding','hybrid']:raise ValueError('Unknown retrieval mode')
        idx=[i for i,c in enumerate(self.chunks) if allow is None or allow(c)]
        b=self.bm25.scores(self.normalizer(query_text));cos={}
        if query_vec is not None and self.vectors and mode!='bm25':
            q=np.asarray(query_vec,dtype=float)
            dim=len(next(iter(self.vectors.values())))
            if q.ndim!=1 or len(q)!=dim or not np.isfinite(q).all() or np.linalg.norm(q)==0:raise ValueError('Invalid query vector or embedding-space dimension mismatch')
            q=q/np.linalg.norm(q)
            for i in idx:
                v=self.vectors.get(self.chunks[i]['chunk_id'])
                if v is not None:cos[i]=float(v@q)
        lexical=sorted([i for i in idx if b[i]>0],key=lambda i:(-b[i],self.chunks[i]['chunk_id']))
        vector=sorted([i for i in idx if cos.get(i,0)>0],key=lambda i:(-cos[i],self.chunks[i]['chunk_id']))
        rank={}
        for stream,weight in [(lexical,self.w_bm25),(vector,self.w_emb)]:
            if stream is lexical and mode=='embedding':continue
            if stream is vector and mode=='bm25':continue
            for r,i in enumerate(stream,1):rank[i]=rank.get(i,0)+weight/(self.rrf_k+r)
        if self.fusion=='weighted' and idx:
            bs=_norm(np.array([b[i] for i in idx]));es=_norm(np.array([cos.get(i,0.) for i in idx]))
            if mode=='embedding':values=es
            elif mode=='bm25' or not cos:values=bs
            else:values=self.w_bm25*bs+self.w_emb*es
            rank={i:float(values[j]) for j,i in enumerate(idx) if float(values[j])>0 and (mode!='embedding' or i in cos)}
        self.last_status={'requested_mode':mode,'effective_mode':'hybrid' if lexical and vector and mode=='hybrid' else ('embedding' if vector and mode!='bm25' else ('bm25' if lexical and mode!='embedding' else 'unavailable')),'eligible_chunks':len(idx),'cached_chunks':sum(self.chunks[i]['chunk_id'] in self.vectors for i in idx),'query_embedding_supplied':query_vec is not None}
        order=sorted(rank,key=lambda i:(-rank[i],self.chunks[i]['chunk_id']))[:max(0,k)]
        return [{'chunk':self.chunks[i],'score':float(rank[i]),'bm25':float(b[i]),'cos':cos.get(i,0.),'retrieval_status':dict(self.last_status)} for i in order]
