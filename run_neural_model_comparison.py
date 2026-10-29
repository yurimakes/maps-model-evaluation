"""Actual pretrained inference and official Magneto matching on fixed MAPS data.

No model training or paid inference API. Checkpoint files/revisions are pinned.
"""
from pathlib import Path
import os,sys
HERE=Path(__file__).resolve().parent
os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='true'
os.environ['TOKENIZERS_PARALLELISM']='false'
sys.path.insert(0,str(HERE/'third_party'/'magneto_full'))
import argparse,collections,gc,hashlib,html,importlib.metadata,json,math,platform,time
import numpy as np
import pandas as pd
import psutil,torch
from magneto import Magneto
from magneto.embedding_matcher import EmbeddingMatcher
from phase2_original.data.maps_rag import knowledge as kn,recommend as legacy
from phase2_original.data.maps_rag.embeddings import VectorStore,chunk_text
from model_comparison_utils import metrics,cross_source_evaluate,baseline_from_log

LABELS={'cached_phase2_embedding':'2차 저장 임베딩 · 동일 분류기','dense_mpnet':'MPNet 실제 추론','dense_e5_multilingual':'다국어 E5 실제 추론','dense_ko_sroberta':'한국어 SRoBERTa 실제 추론','magneto_mpnet_schema_only':'공식 Magneto · MPNet · 컬럼명','magneto_mpnet_metadata':'공식 Magneto · MPNet · 메타 추가','magneto_e5_multilingual_metadata':'Magneto · 다국어 E5 · 메타 추가','magneto_ko_sroberta_metadata':'Magneto · 한국어 SRoBERTa · 메타 추가'}

def write_csv(path,rows):
    import csv
    rows=list(rows)
    if not rows:return
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def dump(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def matrix_records(scores,questions,targets):
    records=[]
    for i,q in enumerate(questions):
        valid=[j for j,t in enumerate(targets) if t['table']==('COMPLAINT' if q['system']=='HOMEPAGE' else 'COUNSEL') and np.isfinite(scores[i,j])]
        ordered=sorted(valid,key=lambda j:(-float(scores[i,j]),targets[j]['id']))
        ranked=[targets[j]['id'] for j in ordered]
        records.append({'id':q['id'],'query_id':q['profile']['query_id'],'system':q['system'],'table':q['table'],'column':q['column'],'gold':q['gold'],'ranked':ranked,'score':float(scores[i,ordered[0]]) if ordered else -1.})
    return records

class ReusableMagneto(Magneto):
    """Resource adapter only: reuse the live official matcher between source tables."""
    def __init__(self,matcher,**kwargs):super().__init__(**kwargs);self.live_matcher=matcher
    def apply_embedding_matches(self):
        if self.params['include_embedding_matches']:
            for (s,t),score in self.live_matcher.get_embedding_similarity_candidates(self.df_source,self.df_target).items():self.input_sim_map[s][t]=score

class TracedEmbeddingMatcher(EmbeddingMatcher):
    def __init__(self,*args,**kwargs):self.forward_texts=0;super().__init__(*args,**kwargs)
    def _get_embeddings(self,texts,*args,**kwargs):
        self.forward_texts+=len(texts)
        return super()._get_embeddings(texts,*args,**kwargs)

def official_magneto_scores(matcher,key,questions,targets,metadata):
    scores=np.full((len(questions),len(targets)),np.nan,dtype=float)
    groups=collections.defaultdict(list)
    for i,q in enumerate(questions):groups[(q['system'],q['table'])].append(i)
    params={**Magneto.DEFAULT_PARAMS,'embedding_model':matcher.params['embedding_model'],'encoding_mode':'header_only','sampling_mode':'frequent','sampling_size':1,'topk':20,'use_gpt_reranker':False,'use_bp_reranker':True,'include_equal_matches':True}
    matcher.params.update(params)
    # E5's model card specifies query: on both sides for symmetric similarity.
    prefix='query: ' if key=='e5_multilingual' else ''
    def header(col,desc,dtype):return prefix+(f'{col} | {desc} | {dtype}' if metadata else col)
    for (system,table),indices in groups.items():
        t_indices=[j for j,t in enumerate(targets) if t['table']==('COMPLAINT' if system=='HOMEPAGE' else 'COUNSEL')]
        src={header(questions[i]['column'],questions[i]['profile'].get('as_is_desc',''),questions[i]['profile'].get('as_is_dtype','')):i for i in indices}
        trg={header(targets[j]['column'],targets[j]['description'],targets[j]['dtype']):j for j in t_indices}
        if len(src)!=len(indices) or len(trg)!=len(t_indices):raise RuntimeError('Column representation collision')
        # One null row keeps official type/sampling helpers valid; header_only uses no values.
        left=pd.DataFrame({s:pd.Series([None],dtype=object) for s in src})
        right=pd.DataFrame({t:pd.Series([None],dtype=object) for t in trg})
        model=ReusableMagneto(matcher,**params)
        matches=model.get_matches(left,right)
        for ((_,s),(_,t)),score in matches.items():scores[src[s],trg[t]]=float(score)
        print('MAGNETO_GROUP',key,'metadata' if metadata else 'header',system,table,len(indices),len(matches),flush=True)
    return scores

def html_report(out,summary,common,baselines,model_meta,timing):
    esc=lambda x:html.escape(str(x));pct=lambda x:f'{x*100:.1f}%'
    def table(rows,model_label='model'):
        body=''.join('<tr><td>'+esc(LABELS.get(r[model_label],r[model_label]))+'</td><td>'+str(r['questions'])+'</td>'+''.join('<td>'+pct(r[k])+'</td>' for k in ['accuracy','precision','recall','f1'])+'</tr>' for r in rows)
        return '<div class="scroll"><table><thead><tr><th>모델 / 방법</th><th>질문</th><th>추천·제외 정확도</th><th>매핑 정밀도</th><th>매핑 재현율</th><th>매핑 F1</th></tr></thead><tbody>'+body+'</tbody></table></div>'
    dense=[r for r in summary if r['model'].startswith(('dense_','cached_'))];paper=[r for r in summary if r['model'].startswith('magneto_')]
    html_text='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MAPS 실제 모델 간 비교</title><style>body{margin:0;background:#edf3f5;color:#183440;font:15px/1.7 'Malgun Gothic',Arial,sans-serif}main{max-width:1250px;margin:auto;padding:35px 22px}h1{font-size:34px;line-height:1.35}h2{font-size:23px}.card{background:white;border:1px solid #d9e4e9;border-radius:15px;padding:25px;margin:23px 0}.notice{padding:17px 21px;border-left:5px solid #dfad35;background:#fff5dc}.success{padding:17px 21px;border-left:5px solid #168681;background:#e7f4ef}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:12px;border-bottom:1px solid #e2e9ed;text-align:left}th{background:#eef4f6;white-space:nowrap}code{background:#eaf0f4;padding:3px}a{color:#087b85}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.stats div{padding:18px;background:#153d50;color:white;border-radius:10px}.stats b{font-size:28px;display:block}.stats span{font-size:13px}li{margin:6px 0}@media(max-width:700px){.stats{grid-template-columns:1fr 1fr}.card{padding:16px}}</style><main><p>MAPS · PRETRAINED MODEL COMPARISON</p><h1>실제 신경망 모델을 실행해<br>매핑 성능을 비교했습니다</h1><div class="stats"><div><b>3</b><span>새로 추론한 사전학습 모델</span></div><div><b>93</b><span>원천 질문 · 정답 44 / 제외 49</span></div><div><b>25</b><span>원래 2차 Target 범위</span></div><div><b>0</b><span>유료 추론 API 호출</span></div></div>'''
    html_text+='<p class="success">실제 MPNet·다국어 E5·한국어 SRoBERTa 가중치를 로드해 CPU 추론했습니다. Magneto 공식 get_matches, 신경망 EmbeddingMatcher, 동일명 매칭, 이분 매칭 재정렬도 실행했습니다.</p>'
    html_text+='<section class="card"><h2>1. 같은 입력·같은 분류기로 임베딩 모델 비교</h2><p>원본 질문 문자열과 Target 카드 문자열을 그대로 사용합니다. 2차 임베딩은 원본 캐시, 나머지 세 모델은 새로 계산한 벡터입니다. 같은 코사인 분류기·채널 범위·추천 보류 기준 선택 절차를 사용해 백본 모델 차이를 비교합니다. E5에는 공식 사용법에 맞는 query: 접두사를 양쪽에 추가합니다.</p>'+table(dense)+'<p class="notice">여기서 ‘2차 저장 임베딩’은 기존 RAG의 LLM 최종 결과가 아닙니다. 같은 분류기에서 임베딩 모델만 비교하는 기준선입니다.</p></section>'
    html_text+='<section class="card"><h2>2. Magneto 논문 공식 구현으로 실제 매핑</h2><p>공식 비LLM 기본 모드를 실행했습니다. Target 실데이터 값이 없어 지원되는 header_only 설정을 사용합니다. 첫 행은 원래 컬럼명만 사용한 조건이고, 나머지는 원천·Target의 설명과 자료형을 컬럼 표현에 추가한 MAPS 적용 조건입니다. 신경망 추론·동일명 매칭·이분 매칭 재정렬이 모두 포함됩니다. 논문 GPT 재정렬·GDC 파인튜닝·원논문 벤치마크 전체의 재현은 아닙니다.</p>'+table(paper)+'</section>'
    html_text+='<section class="card"><h2>3. 기존 2차 저장 출력과 동일한 홈페이지 18문항 비교</h2><p>기존 출력은 rep=1의 1회 출력과 30회 최빈 출력을 각각 표시합니다. 신규 모델의 보류 기준은 홈페이지를 제외한 나머지 원천에서만 결정했습니다. 다른 조건에서 생성된 과거 출력이므로 동일 모델·동일 실행 시점의 완전한 A/B는 아닙니다.</p>'+table(baselines+common)+'<p class="notice">2차의 새 LLM 추론은 Azure 연결이 없어 실행하지 않았습니다. 540개 반복 출력을 540개의 독립 질문으로 세지 않습니다. 기존 18문항 이외의 2차 전체 최종 F1을 추정하지 않습니다.</p></section>'
    times=''.join('<tr><td>'+esc(r['stage'])+'</td><td>'+esc(r['model'])+'</td><td>'+f"{r['seconds']:.2f}"+'</td><td>'+str(r.get('texts',''))+'</td><td>0</td></tr>' for r in timing)
    html_text+='<section class="card"><h2>실행 시간·비용</h2><div class="scroll"><table><thead><tr><th>단계</th><th>모델</th><th>초</th><th>텍스트 수</th><th>유료 API 비용(USD)</th></tr></thead><tbody>'+times+'</tbody></table></div><p>설치·다운로드·모델 로드와 추론 시간을 구분했습니다. 전기·장비 비용은 측정하지 않았습니다. 기존 2차의 과거 토큰·비용 기록은 제공되지 않아 비교 비용을 0으로 가정하지 않았습니다.</p></section>'
    meta=''.join('<li>'+esc(m['repository'])+' · '+f"{m['parameters']:,}"+' parameters · revision '+esc(m['revision'])+' · '+esc(m['model_type'])+'</li>' for m in model_meta)
    html_text+='<section class="card"><h2>평가 조건과 재현 정보</h2><ul><li>정답표에 없는 컬럼을 제외 정답으로 만들지 않았습니다. 다른 Target만 정답인 21문항과 가상 생성 항목은 범위에서 분리했습니다.</li><li>원천 하나를 통째로 보류하고, 나머지 네 원천에서 F1을 최대화하는 점수 문턱을 선택했습니다. 가중치 학습·파인튜닝은 하지 않았습니다.</li><li>프로젝트를 이미 검토한 개발 평가셋입니다. 독립적인 새 데이터 검증은 별도로 필요합니다.</li><li>원본 데이터·원본 RAG·논문 소스는 수정하지 않았습니다. 모델 가중치는 Git 대신 모델명·리비전·파일 해시로 기록합니다.</li>'+meta+'</ul><p><a href="neural_model_metrics.csv">전체 성능표</a> · <a href="neural_common18_metrics.csv">동일 18문항</a> · <a href="neural_predictions.csv">질문별 예측</a> · <a href="neural_thresholds.csv">원천별 보류 기준</a> · <a href="neural_execution.json">실행·모델·소스 해시</a></p><p><a href="https://github.com/VIDA-NYU/magneto-matcher/tree/6620623265fc7feac0f053996e62b68a13a72a57">Magneto 공식 코드</a> · <a href="https://huggingface.co/intfloat/multilingual-e5-small">다국어 E5</a> · <a href="https://huggingface.co/jhgan/ko-sroberta-multitask">한국어 SRoBERTa</a></p></section></main></html>'
    (out/'neural_model_report.html').write_text(html_text,encoding='utf-8')

def run(out):
    start=time.perf_counter();out.mkdir(parents=True,exist_ok=True)
    np.random.seed(42);torch.manual_seed(42);torch.set_num_threads(min(4,psutil.cpu_count(logical=False) or 2))
    data=json.loads((HERE/'data'/'snapshot.json').read_text(encoding='utf-8'))
    profiles=json.loads((HERE/'data'/'phase2_profiles.json').read_text(encoding='utf-8'))
    lookup={(p['channel'],p['source_table'].lower(),p['source_column']):p for p in profiles}
    targets=sorted([t for t in data['targets'] if t['table'] in ['COUNSEL','COMPLAINT']],key=lambda t:t['id']);targetids={t['id'] for t in targets}
    questions=[]
    for q in data['queries']:
        gold=sorted(set(q['gold'])&targetids)
        if q['gold'] and not gold:continue
        profile=lookup.get((q['system'],q['table'].lower(),q['column']))
        if profile is None:raise RuntimeError('Missing original question profile: '+q['id'])
        questions.append({**q,'gold':gold,'profile':profile})
    if len(questions)!=93:raise RuntimeError('Unexpected scope; review before comparison')
    kb=kn.searchable(kn.load_chunks(HERE/'phase2_bundle'/'자료'/'4_지식조각_RAG용'/'지식조각'))
    cards={ref:c for c in kb if c['doc_type']=='TARGET_COLUMN' for ref in c.get('target_refs',[]) if ref in targetids}
    qtexts=[legacy.query_text(q['profile']) for q in questions];ttexts=[chunk_text(cards[t['id']]) for t in targets]
    store=VectorStore.load(HERE/'phase2_original'/'data'/'data'/'임베딩'/'embeddings.npz')
    qvectors=[store.get(t) for t in qtexts];tvectors=[store.get(t) for t in ttexts]
    if any(v is None for v in qvectors+tvectors):raise RuntimeError('Original embedding cache does not match common text inputs')
    def cosine(a,b):
        a=np.asarray(a,dtype=np.float32);b=np.asarray(b,dtype=np.float32)
        if not np.isfinite(a).all() or not np.isfinite(b).all():raise RuntimeError('Invalid original embeddings')
        a=a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12);b=b/np.maximum(np.linalg.norm(b,axis=1,keepdims=True),1e-12);return a@b.T
    records={'cached_phase2_embedding':matrix_records(cosine(qvectors,tvectors),questions,targets)}
    timing=[];model_meta=[];models=json.loads((HERE/'models'/'registry.json').read_text(encoding='utf-8'))
    for key in ['mpnet','e5_multilingual','ko_sroberta']:
        info=models[key];model_path=Path(info['path'])
        if not model_path.exists():model_path=HERE/'models'/key
        print('LOAD_REAL_MODEL',key,info['revision'],flush=True);tick=time.perf_counter()
        matcher=TracedEmbeddingMatcher({**Magneto.DEFAULT_PARAMS,'embedding_model':model_path.as_posix(),'encoding_mode':'header_only','sampling_mode':'frequent','sampling_size':1})
        actual=matcher.model._first_module().auto_model.config
        expected={'mpnet':'mpnet','e5_multilingual':'bert','ko_sroberta':'roberta'}[key]
        if actual.model_type!=expected:raise RuntimeError('Unexpected model/fallback: '+str(actual.model_type))
        matcher.model.max_seq_length=512
        if matcher.tokenizer.eos_token is None:matcher.tokenizer.eos_token=''
        model_meta.append({**{k:info[k] for k in ['repository','revision','license','files']},'parameters':sum(p.numel() for p in matcher.model.parameters()),'model_type':actual.model_type,'device':'cpu','dtype':'float32','max_seq_length':512,'e5_prefix':'query on both sides' if key=='e5_multilingual' else None,'tokenizer_eos_none_handling':'empty string in official column serializer'})
        timing.append({'stage':'load_model','model':key,'seconds':time.perf_counter()-tick,'texts':0})
        timing.append({'stage':'download_model','model':key,'seconds':info['download_seconds'],'texts':0})
        tick=time.perf_counter();prefix='query: ' if key=='e5_multilingual' else ''
        with torch.inference_mode():
            vectors=matcher.model.encode([prefix+t for t in qtexts+ttexts],batch_size=8,show_progress_bar=False,convert_to_numpy=True,normalize_embeddings=True)
        if not np.isfinite(vectors).all():raise RuntimeError('Invalid pretrained model output')
        timing.append({'stage':'real_forward_common_inputs','model':key,'seconds':time.perf_counter()-tick,'texts':len(qtexts)+len(ttexts)})
        records['dense_'+key]=matrix_records(vectors[:len(qtexts)]@vectors[len(qtexts):].T,questions,targets)
        print('REAL_FORWARD_COMPLETE',key,'texts',len(vectors),flush=True)
        np.savez_compressed(out/('embeddings_'+key+'.npz'),vectors=vectors,query_ids=np.array([q['id'] for q in questions]),target_ids=np.array([t['id'] for t in targets]))
        if key=='mpnet':
            before_count=matcher.forward_texts
            tick=time.perf_counter();scores=official_magneto_scores(matcher,key,questions,targets,metadata=False)
            records['magneto_mpnet_schema_only']=matrix_records(scores,questions,targets)
            timing.append({'stage':'official_magneto_header_only','model':key,'seconds':time.perf_counter()-tick,'texts':matcher.forward_texts-before_count})
        before_count=matcher.forward_texts
        tick=time.perf_counter();scores=official_magneto_scores(matcher,key,questions,targets,metadata=True)
        records['magneto_'+key+'_metadata']=matrix_records(scores,questions,targets)
        timing.append({'stage':'official_magneto_with_metadata','model':key,'seconds':time.perf_counter()-tick,'texts':matcher.forward_texts-before_count})
        dump(out/('raw_scores_'+key+'.json'),{k:v for k,v in records.items() if key in k})
        print('MODEL_PIPELINES_COMPLETE',key,flush=True)
        del matcher,vectors;gc.collect()
    predictions=[];thresholds=[];summary=[]
    for name,recs in records.items():
        rows,ths=cross_source_evaluate(recs,name);predictions.extend(rows);thresholds.extend(ths);summary.append({'model':name,**metrics(rows)})
        print('METRICS',name,json.dumps(metrics(rows)),flush=True)
    by_source_column=collections.defaultdict(list)
    for q in questions:by_source_column[(q['system'],q['column'].lower())].append(q)
    baselines=[];baseline_rows=[];common_ids=None
    for log_name,raw in data['old_runs'].items():
        for variant in ['first_rep','modal_30_repeats']:
            rows=baseline_from_log(raw,by_source_column,variant);name='2차 저장 출력 · '+log_name+' · '+variant
            baselines.append({'model':name,**metrics(rows)})
            baseline_rows.extend({**r,'model':name} for r in rows)
            ids={r['id'] for r in rows};common_ids=ids if common_ids is None else common_ids&ids
    common=[]
    for name in records:
        rows=[r for r in predictions if r['model']==name and r['id'] in common_ids]
        common.append({'model':name,**metrics(rows)})
    write_csv(out/'neural_model_metrics.csv',summary);write_csv(out/'neural_common18_metrics.csv',baselines+common);write_csv(out/'neural_thresholds.csv',thresholds);write_csv(out/'neural_timing.csv',timing)
    flat=[]
    for row in predictions+baseline_rows:
        flat.append({k:(' ; '.join(v) if isinstance(v,list) else v) for k,v in row.items()})
    fieldnames=sorted({k for r in flat for k in r});write_csv(out/'neural_predictions.csv',[{k:r.get(k) for k in fieldnames} for r in flat])
    versions={d.metadata['Name']:d.version for d in importlib.metadata.distributions()}
    dump(out/'neural_execution.json',{'python':sys.version,'platform':platform.platform(),'seed':42,'pythonhashseed':os.environ.get('PYTHONHASHSEED'),'threads':torch.get_num_threads(),'ram_total_gb':psutil.virtual_memory().total/1024**3,'peak_rss_gb_at_end':psutil.Process().memory_info().peak_wset/1024**3 if hasattr(psutil.Process().memory_info(),'peak_wset') else None,'model_checkpoints':model_meta,'upstream':json.loads((HERE/'third_party'/'magneto_full'/'PROVENANCE.json').read_text(encoding='utf-8')),'questions':len(questions),'positive_questions':sum(bool(q['gold']) for q in questions),'targets':len(targets),'paid_inference_api_calls':0,'paid_inference_api_cost_usd':0,'hardware_electricity_cost':'NOT_MEASURED','total_seconds':time.perf_counter()-start,'timing':timing,'versions':versions,'scope_notes':['Controlled dense models use exactly matching original query/card text, with required E5 prefix.','Magneto uses official supported schema-only mode; metadata is a MAPS input adaptation; GPT reranking and GDC fine-tuning are not run.','Historical phase-2 outputs are not a newly executed phase-2 LLM. Only 18 common questions can be compared.','Rejection threshold is selected from other source systems; no neural fine-tuning.','Development evaluation, not blinded external validation.'],'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'run_neural_model_comparison.py',HERE/'model_comparison_utils.py']}})
    dump(out/'neural_results.json',{'summary':summary,'common18':baselines+common})
    html_report(out,summary,common,baselines,model_meta,timing)
    (out/'requirements-models.lock.txt').write_text('\n'.join(sorted(k+'=='+v for k,v in versions.items()))+'\n',encoding='utf-8')
    print('NEURAL_REPORT',out/'neural_model_report.html',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/latest');a=p.parse_args();run(HERE/a.out)
