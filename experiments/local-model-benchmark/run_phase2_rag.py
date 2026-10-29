"""Re-run genuine phase-2 retrieval with the supplied corpus and embedding cache.

No Azure or other model API calls are made. Ranking diagnostics are not end-to-end
mapping accuracy. Contract tests with scripted replies are not model experiments.
"""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'.packages'))
import argparse,collections,csv,hashlib,html,json,re,time
import numpy as np
from phase2_original.data.maps_rag import knowledge as kn,recommend as original
from phase2_original.data.maps_rag.embeddings import VectorStore,text_key
from phase2_original.data.maps_rag.facts import TargetCatalog,Lookups
from phase2_original.data.maps_rag.source_loader import CHANNEL_TO_TARGET
from phase2_original.data.maps_rag.retrieval import Retriever as OriginalRetriever
from phase2_upgrade.maps_rag.retrieval import Retriever as ImprovedRetriever
from phase2_upgrade.maps_rag import recommend as improved
from prepare_data import write_csv

def evaluate_rankings(rows):
    relevant=[r for r in rows if r['gold']]
    result={'n_positive_questions':len(relevant)}
    for k in [1,3,5]:result[f'any_gold_hit_at{k}']=sum(bool(set(r['ranked'][:k])&set(r['gold'])) for r in relevant)/max(1,len(relevant))
    result['mrr']=sum(next((1/(i+1) for i,t in enumerate(r['ranked']) if t in r['gold']),0.) for r in relevant)/max(1,len(relevant))
    return result

def html_report(result,out):
    esc=lambda v:html.escape(str(v));pct=lambda v:f'{v*100:.1f}%'
    summary=result['candidate_ranking_diagnostic'];evidence=result['evidence_proxy']
    tables=''.join('<tr><td>'+esc(r['method'])+'</td><td>'+str(r['n_positive_questions'])+'</td>'+''.join('<td>'+pct(r[k])+'</td>' for k in ['any_gold_hit_at1','any_gold_hit_at3','any_gold_hit_at5'])+'</tr>' for r in summary)
    ev=''.join('<tr><td>'+esc(r['method'])+'</td><td>'+str(r['eligible_positive_questions'])+'</td><td>'+pct(r['target_reference_hit_at5'])+'</td><td>'+f"{r['elapsed_seconds']:.3f}"+'</td></tr>' for r in evidence)
    comparisons=''.join('<tr><td>'+esc(r['case'])+'</td><td>'+esc(r['original_level'])+'</td><td>'+esc(r['original_confidence'])+'</td><td>'+esc(r['upgraded_level'])+'</td><td>'+esc(r['upgraded_confidence'])+'</td></tr>' for r in result['validation_diagnostics'])
    ready=result['readiness']
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MAPS 실제 2차 RAG · 로컬 검증</title><style>body{margin:0;background:#f0f4f6;color:#163342;font:16px/1.7 'Malgun Gothic',Arial,sans-serif}main{max-width:1150px;margin:auto;padding:36px 22px}h1{font-size:32px;line-height:1.35}h2{font-size:23px}.card{background:white;border:1px solid #dce5ea;border-radius:14px;padding:25px;margin:24px 0}.notice{background:#fff4db;border-left:5px solid #e4a326;padding:18px}.green{background:#e4f3ec;border-left:5px solid #238767;padding:18px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.stats div{background:#173f50;color:white;border-radius:10px;padding:18px}.stats b{font-size:30px;display:block}.stats span{font-size:13px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px;border-bottom:1px solid #e0e9ed;text-align:left}th{background:#edf3f6;white-space:nowrap}a{color:#057789}code{background:#eef3f5;padding:2px 4px}li{margin-bottom:7px}@media(max-width:700px){.stats{grid-template-columns:1fr 1fr}.card{padding:17px}h1{font-size:26px}}</style><main><p>MAPS · 실제 2차 소스 기준</p><h1>원본 RAG 검색을 재실행하고<br>검증 로직의 결함을 수정했습니다</h1>'''
    page+='<div class="stats">'+''.join('<div><b>'+str(v)+'</b><span>'+s+'</span></div>' for v,s in [(ready['knowledge_chunks'],'원본 지식 문서'),(ready['retrievable_chunks'],'검색 허용 문서'),(ready['cached_retrievable_chunks'],'일치하는 문서 임베딩'),(ready['cached_question_profiles'],'캐시에 있는 질문 / 120')])+'</div>'
    page+='<p class="green">원본 ZIP·묶음은 수정하지 않았습니다. 실제 2차 코드와 지식·캐시를 사용했으며, API 호출은 0회입니다.</p><p class="notice"><b>최종 매핑 정확도·정밀도·F1은 아직 새로 측정하지 않았습니다.</b> 아래는 실제 검색 재실행과 코드 검증 결과입니다. 최종 LLM 추천 재실행에는 Azure 연결 설정이 필요합니다. 과거 18문항 출력의 재생 결과를 이번 실행의 모델 성능으로 사용하지 않았습니다.</p>'
    page+='<section class="card"><h2>비교 기준을 바로잡았습니다</h2><ul><li>원본 2차에 이미 BM25+임베딩 하이브리드 검색과 채널별 Target 고정이 구현돼 있습니다. 이를 3차의 신규 효과로 주장하지 않습니다.</li><li>실제 2차 Target은 COUNSEL·COMPLAINT 25컬럼이며, 실제 채널에 따라 11개 또는 14개 후보를 모두 LLM에 보여 줍니다.</li><li>이 범위의 정답이 있는 실제 원천 질문은 44개입니다. 전체 매핑표에서 다른 Target만 정답인 21개 질문은 이번 범위에서 제외했습니다. 기존 78후보 실험과 직접 비교하지 않습니다.</li><li>검색은 후보 컬럼 카드 자체를 검색 근거에서 제외합니다. 아래의 후보 순위 진단은 그와 별개인 진단 실험입니다.</li></ul></section>'
    page+='<section class="card"><h2>실제 근거 검색 · 정답 Target 참조 적중 프록시</h2><p>원본 Recommender.gather를 실행했습니다. 검색 상위 5개 문서의 target_refs에 정답 Target이 들어 있는지 집계합니다. 사람이 판정한 문서 관련성 정답이나 최종 매핑 정확도가 아닙니다.</p><div class="scroll"><table><thead><tr><th>검색 방법</th><th>정답 참조 문서가 있는 질문</th><th>참조 적중 @5</th><th>로컬 실행 시간(초)</th></tr></thead><tbody>'+ev+'</tbody></table></div></section>'
    page+='<section class="card"><h2>후보 순위 진단 · 최종 추천과 별도</h2><p>동일한 25개 Target 카드 중 채널에 맞는 카드만 대상으로 검색 순위를 비교했습니다. 원본 운영 RAG는 후보 전체를 LLM에 보여 주므로 이 수치는 운영 RAG의 Top-1 정확도가 아닙니다. 개선판은 같은 임베딩을 유지하면서 약어 전개와 순위 결합을 적용합니다.</p><div class="scroll"><table><thead><tr><th>방법</th><th>정답이 있는 질문</th><th>정답 포함 @1</th><th>정답 포함 @3</th><th>정답 포함 @5</th></tr></thead><tbody>'+tables+'</tbody></table></div></section>'
    page+='<section class="card"><h2>실제 검증 함수 · 입력 고정 비교</h2><p>다음은 오류 상황을 만든 코드 테스트입니다. AI가 해당 응답을 얼마나 자주 내는지는 측정하지 않았습니다.</p><div class="scroll"><table><thead><tr><th>테스트 입력</th><th>원본 판정</th><th>원본 확신도</th><th>개선 판정</th><th>개선 확신도</th></tr></thead><tbody>'+comparisons+'</tbody></table></div><ul><li>근거가 빠진 점수를 N/A로 제외해 확신도를 높이지 않습니다. N/A에는 명시적 상태와 이유가 필요합니다.</li><li>필수 게이트가 PASS가 아니거나, 없는 근거를 인용하면 유효한 매핑으로 인정하지 않습니다.</li><li>불완전한 후보 채점은 이관 제외(EXCLUDE)와 구분해 판단 보류로 남깁니다.</li><li>부분 임베딩 캐시를 사용할 수 있게 하고, 벡터가 없는 임베딩 검색에서 가짜 순위가 나오지 않게 했습니다.</li></ul></section>'
    page+='<section class="card"><h2>판단과 다음 단계</h2><p>약어 전개+RRF는 근거 참조 적중이 32/35에서 33/35로 늘었지만, 후보 순위 @1은 28/44에서 26/44로 낮아졌습니다. 현재 기본 검색 방식에는 적용하지 않았습니다. 기본 개선판은 기존 가중합을 유지하며 캐시 누락 처리와 검증 로직을 보강합니다.</p><p>검증 개선이 최종 F1을 올리는지, 반대로 보류율을 높이는지는 실제 LLM A/B 실행으로 확인해야 합니다. 원본과 개선판은 별도 패키지로 보존했습니다. API 설정은 저장소에 넣지 않습니다.</p><p><a href="phase2_candidate_ranking.csv">후보 진단 결과</a> · <a href="phase2_evidence_proxy.csv">근거 검색 프록시</a> · <a href="phase2_retrieval_predictions.csv">질문별 결과</a> · <a href="phase2_validation_diagnostics.csv">검증 입력 비교</a> · <a href="phase2_run_manifest.json">원본 해시·조건</a></p></section></main></html>'
    (out/'phase2_report.html').write_text(page,encoding='utf-8')

def run(out):
    root=HERE/'phase2_bundle'/'자료';knowledge=root/'4_지식조각_RAG용'/'지식조각'
    chunks=kn.load_chunks(knowledge);visible=kn.searchable(chunks);retr=kn.retrievable(chunks)
    store=VectorStore.load(HERE/'phase2_original'/'data'/'data'/'임베딩'/'embeddings.npz')
    profiles=json.loads((HERE/'data'/'phase2_profiles.json').read_text(encoding='utf-8'))
    data=json.loads((HERE/'data'/'snapshot.json').read_text(encoding='utf-8'))
    catalog=TargetCatalog(root/'2_타겟_정의'/'2_타겟_물리모델_v1.0.csv');lookups=Lookups(visible)
    gold={(q['system'],q['table'].lower(),q['column']):q for q in data['queries']}
    alias={}
    for a,b,k in data['aliases']:
        for word in [a,b]:alias[word.lower()]=b.lower().replace('_',' ')+' '+k
    def expand(text):
        s=re.sub(r'([a-z])([A-Z])',r'\1 \2',str(text));return ' '.join(alias.get(w,w) for w in re.findall(r'[a-z0-9]+|[가-힣]+',s.lower()))
    modes={
        'phase2_original_hybrid':OriginalRetriever(retr,store.chunk_vectors(retr)),
        'phase2_hardening_same_weighted':ImprovedRetriever(retr,store.chunk_vectors(retr)),
        'experimental_rrf_alias_NOT_DEFAULT':ImprovedRetriever(retr,store.chunk_vectors(retr),text_normalizer=expand,fusion='rrf'),
    }
    all_details=[];evsummary=[];scope=[]
    for row in profiles:
        q=gold.get((row['channel'],row['source_table'].lower(),row['source_column']))
        if q and (not q['gold'] or set(q['gold'])&catalog.all_ids):scope.append((row,q))
    for method,retriever in modes.items():
        r=original.Recommender(catalog,lookups,retriever,client=None,query_vectors=store.vecs,embedder=None,mode='hybrid',k=5)
        eligible=hit=0;t=time.perf_counter()
        for row,q in scope:
            table,facts,hits=r.gather(row)
            valid_gold=set(q['gold'])&catalog.all_ids
            def allowed(c):
                refs=c.get('target_refs') or []
                return c['doc_type'] not in ['TARGET_COLUMN','DQ_RULE','SOURCE_CODE_MASTER'] and (not refs or table in {t.split('.')[0] for t in refs})
            relevant={c['chunk_id'] for c in retr if allowed(c) and set(c.get('target_refs') or [])&valid_gold}
            found=bool(relevant&{h['chunk']['chunk_id'] for h in hits})
            if valid_gold and relevant:eligible+=1;hit+=found
            all_details.append({'experiment':'actual_gather_evidence','method':method,'query_id':row['query_id'],'system':row['channel'],'source_column':row['source_column'],'gold':' ; '.join(sorted(valid_gold)),'ranked_ids':' ; '.join(h['chunk']['chunk_id'] for h in hits),'relevant_reference_ids':len(relevant),'target_reference_hit':found,'query_vector_cached':text_key(original.query_text(row)) in store.vecs,'effective_mode':getattr(retriever,'last_status',{}).get('effective_mode','hybrid' if retriever.has_embeddings() and text_key(original.query_text(row)) in store.vecs else 'bm25_fallback')})
        evsummary.append({'method':method,'scope_questions':len(scope),'eligible_positive_questions':eligible,'target_reference_hit_at5':hit/max(1,eligible),'elapsed_seconds':time.perf_counter()-t,'api_calls':0})
    target_cards=[c for c in visible if c['doc_type']=='TARGET_COLUMN']
    target_vectors=store.chunk_vectors(target_cards)
    target_retrievers={'phase2_original_hybrid':OriginalRetriever(target_cards,target_vectors),'phase2_hardening_same_weighted':ImprovedRetriever(target_cards,target_vectors),'experimental_rrf_alias_NOT_DEFAULT':ImprovedRetriever(target_cards,target_vectors,text_normalizer=expand,fusion='rrf')}
    candidates=[]
    for method,retriever in target_retrievers.items():
        ranking=[]
        for row,q in scope:
            valid_gold=set(q['gold'])&catalog.all_ids
            if not valid_gold:continue
            table=CHANNEL_TO_TARGET[row['channel']];query=original.query_text(row);qv=store.get(query)
            hits=retriever.search(query,qv,mode='hybrid',k=25,allow=lambda c:table in kn.target_table_of(c))
            order=[]
            for h in hits:
                for target in h['chunk'].get('target_refs') or []:
                    if target in catalog.all_ids and target not in order:order.append(target)
            ranking.append({'gold':sorted(valid_gold),'ranked':order})
            all_details.append({'experiment':'target_card_ranking_DIAGNOSTIC_ONLY','method':method,'query_id':row['query_id'],'system':row['channel'],'source_column':row['source_column'],'gold':' ; '.join(sorted(valid_gold)),'ranked_ids':' ; '.join(order[:5]),'relevant_reference_ids':len(valid_gold),'target_reference_hit':bool(valid_gold&set(order[:5])),'query_vector_cached':qv is not None,'effective_mode':getattr(retriever,'last_status',{}).get('effective_mode','hybrid' if qv is not None else 'bm25_fallback')})
        candidates.append({'method':method,**evaluate_rankings(ranking)})
    full={'target':'COMPLAINT.CMPL_ID','mapping_type':'RENAME','process_type':'COPY','gates':{'RELATION_FIT':'PASS','DATATYPE_CONVERTIBLE':'PASS'},'scores':dict.fromkeys(original.WEIGHTS,1.),'evidence':['TOBE-COMPLAINT.CMPL_ID']}
    import copy
    cases={}
    cases['Only NAME score; six criteria missing']=copy.deepcopy(full);cases['Only NAME score; six criteria missing']['scores']={'NAME':1.}
    cases['Mandatory relationship gate NA']=copy.deepcopy(full);cases['Mandatory relationship gate NA']['gates']['RELATION_FIT']='NA'
    cases['No cited evidence']=copy.deepcopy(full);cases['No cited evidence']['evidence']=[]
    cases['Valid complete mapping']=copy.deepcopy(full)
    diagnostics=[]
    for name,p in cases.items():
        a=original.validate(p,catalog,{'TOBE-COMPLAINT.CMPL_ID'});b=improved.validate(p,catalog,{'TOBE-COMPLAINT.CMPL_ID'})
        diagnostics.append({'case':name,'original_level':a['confidence_level'],'original_confidence':a['confidence_score'],'upgraded_level':b['confidence_level'],'upgraded_confidence':b['confidence_score']})
    readiness=json.loads((HERE/'data'/'phase2_readiness.json').read_text(encoding='utf-8'))
    result={'readiness':readiness,'candidate_ranking_diagnostic':candidates,'evidence_proxy':evsummary,'validation_diagnostics':diagnostics}
    out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'phase2_candidate_ranking.csv',candidates);write_csv(out/'phase2_evidence_proxy.csv',evsummary);write_csv(out/'phase2_retrieval_predictions.csv',all_details);write_csv(out/'phase2_validation_diagnostics.csv',diagnostics)
    manifest={'execution':'Actual original retrieval code, actual original corpus, original cached query/document embeddings; upgraded retrieval uses same vectors.','not_executed':'Azure chat/embedding API; final model mapping accuracy/precision/F1','api_calls':0,'actual_original_scope':'COUNSEL and COMPLAINT only; source channel target fixed','scoped_questions':len(scope),'positive_questions':len([q for _,q in scope if set(q['gold'])&catalog.all_ids]),'out_of_scope_ground_truth_questions':len(data['queries'])-len(scope),'original_target_columns':len(catalog.all_ids),'original_archive':json.loads((HERE/'phase2_original'/'archive_manifest.json').read_text(encoding='utf-8')),'bundle':json.loads((HERE/'phase2_bundle'/'archive_manifest.json').read_text(encoding='utf-8')),'upgrade_build':json.loads((HERE/'phase2_upgrade'/'build_manifest.json').read_text(encoding='utf-8')),'result':result}
    (out/'phase2_run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    html_report(result,out);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/latest');a=p.parse_args();run(HERE/a.out)
