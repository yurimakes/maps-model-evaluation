"""Fixed-parameter graph ablation. Test source labels never construct a fold graph."""
from __future__ import annotations
import csv, hashlib, html, json, platform, sys, time
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
HERE=Path(__file__).resolve().parent;LAB=HERE.parent/'maps-local-lab'
sys.path[:0]=[str(LAB),str(LAB/'.packages')]
import numpy as np
from scipy.sparse import csr_matrix,diags
from sklearn.feature_extraction.text import TfidfVectorizer
from run_experiments import Features,predict,summarize,tune_threshold,paired_bootstrap,tokens
from prepare_data import write_csv
from build_graph import dump

METHODS=['metadata_tfidf','hybrid_type_rules','hybrid_transfer','graph_catalog','graph_history']
LABELS={'metadata_tfidf':'메타데이터 TF-IDF','hybrid_type_rules':'사전·BM25·자료형','hybrid_transfer':'기존 승인 이력 결합','graph_catalog':'용어·단어·도메인 그래프','graph_history':'그래프 + 다른 원천 승인 이력'}

class GraphFeatures(Features):
    def __init__(self,data,catalog):
        super().__init__(data);self.catalog=catalog;self.cache={};self.audit={}
        docs=[];ids=[];links=[]
        def add(id,text):ids.append(id);docs.append(self.expand(text));return len(ids)-1
        for t,s in zip(self.t,self.tdocs):add('target:'+t['id'],s)
        words={}
        for w in catalog['words']:
            words[w['표준단어명']]=add('word:'+w['표준단어명'],' '.join(w[k] for k in ('표준단어명','표준단어약어','영문FullName','정의')))
        domains={}
        for d in catalog['domains']:domains[d['도메인명']]=add('domain:'+d['도메인명'],d['도메인명']+' '+d['도메인설명'])
        for j,r in enumerate(catalog['terms']):
            term=add('term:'+str(j),' '.join(r[k] for k in ('표준용어명','논리영문FullName','정의')))
            for w in r['구성표준단어'].split('+'):
                if w in words:links.append((term,words[w],1.))
            if r['도메인'] in domains:links.append((term,domains[r['도메인']],.25))
            for k,t in enumerate(self.t):
                import re
                if t['column']==r['표준용어영문명_물리컬럼명'] and t['table'] in re.split(r'[,/\s]+',r['적용Entity']):links.append((k,term,1.))
        self.ids=ids;self.links=links
        v=TfidfVectorizer(analyzer='char',ngram_range=(2,4),sublinear_tf=True)
        mat=v.fit_transform(docs)
        self.concept_sim=(v.transform(self.qdocs)@mat.T).toarray()
        # History lexical similarity is label-free; fitting uses only allowed training documents per fold.

    def scores(self,method,train):
        train=tuple(sorted(train));key=(method,train)
        if key in self.cache:return self.cache[key]
        if method not in ('graph_catalog','graph_history'):
            result=super().scores(method,train)
            self.cache[key]=result;return result
        use_history=method=='graph_history';n=len(self.ids)+(len(train) if use_history else 0)
        links=list(self.links);seed=np.zeros((self.n,n))
        seed[:,:len(self.ids)]=self.concept_sim
        # Target lexical seed stays the same for both graph variants.
        seed[:,:self.m]=self.base['hybrid_type_rules']
        approved=[];train_systems=sorted({self.q[i]['system'] for i in train})
        if use_history and train:
            v=TfidfVectorizer(analyzer='char',ngram_range=(2,4),sublinear_tf=True)
            mat=v.fit_transform([self.qdocs[i] for i in train])
            sim=(v.transform(self.qdocs)@mat.T).toarray()
            lookup={t:i for i,t in enumerate(self.tids)}
            for k,i in enumerate(train):
                idx=len(self.ids)+k
                seed[:,idx]=sim[:,k]
                for t in self.gold[i]:links.append((idx,lookup[t],2.));approved.append((i,t))
        rr=[];cc=[];vv=[]
        for a,b,w in links:rr.extend((a,b));cc.extend((b,a));vv.extend((w,w))
        # Self-loops handle dangling nodes and preserve probability mass.
        for i in range(n):rr.append(i);cc.append(i);vv.append(.1)
        a=csr_matrix((vv,(rr,cc)),shape=(n,n));p=diags(1/np.asarray(a.sum(axis=1)).ravel())@a
        seed/=np.maximum(seed.sum(axis=1,keepdims=True),1e-12)
        ranks=seed.copy()
        for _ in range(24):ranks=.65*seed+.35*(p.T@ranks.T).T
        gs=ranks[:,:self.m];gs=gs/np.maximum(gs.max(axis=1,keepdims=True),1e-12)
        result=.75*self.base['hybrid_type_rules']+.25*gs
        self.audit[key]={'train_systems':train_systems,'nodes':n,'undirected_links':len(links),'approved_edges':len(approved),'approved_source_ids':[self.q[i]['id'] for i,t in approved],'uses_document_chunks':False,'uses_source_code_mapping_rules':False}
        assert all(i in train for i,t in approved)
        self.cache[key]=result;return result

def catalog_checks(catalog):
    issues=[];terms=catalog['terms'];codes={(r['CODE_GROUP_ID'],r['CODE_VALUE']) for r in catalog['codes']}
    import re
    for p in catalog['physical']:
        matches=[r for r in terms if r['표준용어영문명_물리컬럼명']==p['COLUMN_NAME'] and p['TABLE_NAME'] in re.split(r'[,/\s]+',r['적용Entity'])]
        if not matches:issues.append({'kind':'missing_standard_term','item':p['TABLE_NAME']+'.'+p['COLUMN_NAME'],'detail':'표준용어를 정확히 연결하지 못함'})
        for r in matches:
            d=next((d for d in catalog['domains'] if d['도메인명']==r['도메인']),None)
            if d and d['물리데이터유형'].upper()!=p['DATA_TYPE'].upper():issues.append({'kind':'domain_type_difference','item':p['TABLE_NAME']+'.'+p['COLUMN_NAME'],'detail':p['DATA_TYPE']+' / domain '+d['물리데이터유형']+' (검토 필요; 오류 확정 아님)'})
            if d and 'NOT NULL' in d['검증기준'].upper() and p['NULLABLE']!='N':issues.append({'kind':'domain_nullable_difference','item':p['TABLE_NAME']+'.'+p['COLUMN_NAME'],'detail':'도메인 NOT NULL / 물리모델 NULL 허용 (검토 필요)'})
    for i,r in enumerate(catalog['codemaps']):
        if r['TARGET_CODE'] and (r['TARGET_CODE_GROUP_ID'],r['TARGET_CODE']) not in codes:issues.append({'kind':'missing_target_code','item':'codemap:'+str(i),'detail':r['TARGET_CODE_GROUP_ID']+'|'+r['TARGET_CODE']+'; '+r['MAPPING_STATUS']})
    return issues

def render(result):
    out=HERE/'results';b=result['build'];pct=lambda x:f'{100*x:.1f}%';e=lambda x:html.escape(str(x))
    rows=''.join('<tr><td>'+LABELS[r['method']]+'</td>'+''.join('<td>'+pct(r[k])+'</td>' for k in ['top1_accuracy','top5_accuracy','mapping_precision','mapping_recall','mapping_f1'])+'</tr>' for r in result['summary'])
    best=max(result['summary'],key=lambda r:r['mapping_f1']);base=next(r for r in result['summary'] if r['method']=='hybrid_transfer');graph=next(r for r in result['summary'] if r['method']=='graph_history')
    delta=100*(graph['mapping_f1']-base['mapping_f1'])
    errors=[r for r in result['predictions'] if r['method']=='graph_history' and not r['correct']]
    errorrows=''.join('<tr>'+''.join('<td>'+e(x)+'</td>' for x in [r['system'],r['column'],' / '.join(r['gold']) or '이관 제외',' / '.join(r['predicted']) or '보류',' / '.join(r['ranked'][:3])])+'</tr>' for r in errors)
    inv=json.loads((out/'inventory.json').read_text(encoding='utf8'))
    invrows=''.join('<tr><td>'+e(r['path'])+'</td><td>'+e(r['status'])+'</td><td>'+str(r['bytes'])+'</td></tr>' for r in inv)
    costs=''.join('<tr><td>'+LABELS[r['method']]+'</td><td>'+f"{r['evaluation_seconds']:.3f}"+'</td><td>'+f"{r['cold_batch_score_seconds']*1000:.3f}"+'</td><td>'+f"{r['warm_rank_p95_ms']:.3f}"+'</td></tr>' for r in result['costs'])
    issues=''.join('<tr><td>'+e(r['kind'])+'</td><td>'+e(r['item'])+'</td><td>'+e(r['detail'])+'</td></tr>' for r in result['catalog_issues'])
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MAPS 경량 온톨로지 실측</title><style>
    *{box-sizing:border-box}body{margin:0;font-family:'Malgun Gothic',sans-serif;color:#183347;background:#edf3f6}main{max-width:1280px;margin:auto;padding:36px 24px}h1{font-size:34px;line-height:1.4}h2{font-size:23px}p,li{line-height:1.85}.tag{color:#087e87;letter-spacing:2px;font-weight:bold}.card{background:white;border:1px solid #d9e4e9;border-radius:16px;padding:25px;margin:22px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.stat{padding:22px;background:#123e50;color:white;border-radius:14px}.stat b{display:block;font-size:31px}.stat span{font-size:14px;color:#c5e3ec}.notice{padding:18px 22px;background:#fff6df;border-left:5px solid #dfa52d;border-radius:8px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px;text-align:left;border-bottom:1px solid #e1e9ed;vertical-align:top}th{background:#eef5f7;white-space:nowrap}td:first-child{overflow-wrap:anywhere}input,select,button{font:inherit;padding:10px 14px;border:1px solid #b4cbd3;border-radius:8px;margin:5px}input{min-width:280px}button{background:#087e87;color:white;cursor:pointer}a{color:#077c87}.muted{color:#58717e;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 monospace}.paths{display:flex;flex-wrap:wrap;gap:10px}.paths span{background:#e2f4f1;border:1px solid #b4dcd5;border-radius:9px;padding:12px}#detail{max-height:500px;overflow:auto}svg{max-width:100%;height:auto}.bar{height:22px;background:#128b91;border-radius:4px}.barrow{display:grid;grid-template-columns:280px 1fr 70px;gap:14px;align-items:center;margin:16px 0;font-size:14px}@media(max-width:750px){.stats{grid-template-columns:1fr 1fr}.barrow{grid-template-columns:1fr}h1{font-size:27px}.card{padding:16px}}
    </style><main><div class="tag">MAPS / LIGHTWEIGHT ONTOLOGY / LOCAL BENCHMARK</div><h1>경량 그래프를 구축하고,<br>같은 정답으로 성능을 비교했습니다.</h1>'''
    page+='<p class="muted">'+e(result['timestamp'])+' · 로컬 CPU · 외부 API 호출 0회 · Fabric 서비스 배포 전 로컬 검증</p>'
    page+='<div class="stats">'+''.join('<div class="stat"><b>'+str(v)+'</b><span>'+s+'</span></div>' for v,s in [(b['physical_files'],'원본 파일 · ZIP 포함'),(b['nodes'],'그래프 노드'),(b['edges'],'그래프 관계'),(114,'평가 컬럼 / Target 78개')])+'</div>'
    page+='<section class="card"><h2>측정 결과</h2><p>매핑 F1 최고: <b>'+LABELS[best['method']]+' '+pct(best['mapping_f1'])+'</b>. 그래프+이력은 기존 이력 결합보다 <b>'+f'{delta:+.1f}'+'%p</b>입니다. 그래프 채택 여부는 이 차이와 원천별 결과를 함께 보고 결정해야 합니다.</p><div class="scroll"><table><tr><th>방법</th><th>Top-1</th><th>Top-5</th><th>정밀도</th><th>재현율</th><th>매핑 F1</th></tr>'+rows+'</table></div>'
    for r in result['summary']:page+='<div class="barrow"><span>'+LABELS[r['method']]+'</span><div style="background:#edf3f5;border-radius:4px"><div class="bar" style="width:'+str(r['mapping_f1']*100)+'%"></div></div><b>'+pct(r['mapping_f1'])+'</b></div>'
    page+='<p class="muted">Top-1·5: 정답이 있는 65컬럼 기준. 정밀도·재현율·F1: 이관 제외 49컬럼 포함, 정답 68쌍 기준. 컬럼마다 최대 1개를 추천하므로 복수 Target 정답 3쌍은 추가로 놓칠 수 있습니다.</p></section>'
    ci=result['bootstrap']['query_bootstrap_ci95']
    page+='<p class="muted">기존 이력 대비 그래프+이력 F1 차이의 탐색적 95% 구간: '+f'{ci[0]*100:+.1f} ~ {ci[1]*100:+.1f}'+'%p. 질문 단위 bootstrap이며 원천 의존성은 반영하지 않았습니다. 외부 데이터에 대한 우위를 입증한 결과가 아닙니다.</p>'
    page+='<div class="notice"><b>평가 조건과 한계</b><p>5개 원천을 하나씩 통째로 보류하고, 추천·보류 임계값은 나머지 4개 원천 안에서 다시 원천별 교차검증으로 선택했습니다. 가중치는 이번 실험에서 고정했습니다. 자료를 보고 설계한 탐색 실험이며, 이미 프로젝트에 맞춰 작성된 표준사전을 사용하므로 외부 신규 데이터에 대한 독립 검증은 아닙니다.</p><p>전체 저장 그래프에는 승인 정답 68쌍이 들어 있습니다. 벤치마크는 이 저장 파일을 검색하지 않고, 허용된 원천의 승인 이력만으로 평가용 그래프를 매번 구성합니다. 문서 본문, 원천별 코드 매핑표, 변환 규칙, 검토 코멘트는 순위 점수 입력에서 제외했습니다. 문서 검색 정확도·실제 LLM RAG·Fabric 처리량은 측정하지 않았습니다.</p></div>'
    page+='<section class="card"><h2>구축한 관계와 탐색</h2><div class="paths"><span>원천 시스템 → 테이블 → 컬럼</span><span>승인 매핑 → Target 컬럼</span><span>Target → 표준용어 → 표준단어</span><span>표준용어 → 도메인 → 검증기준</span><span>코드변환 → 표준코드</span><span>정의 → 근거 파일</span></div><p>아래에서 컬럼을 선택하면 실제 저장된 관계와 근거를 확인할 수 있습니다. 평가 그래프는 단어·용어·도메인 관계에서 24회 확산한 점수를 기존 하이브리드 점수와 25:75로 결합합니다. 문서 검색 결과는 순위 평가와 별도입니다.</p><input id="nodeFilter" placeholder="컬럼명 또는 용어 검색"><select id="nodeSelect"></select><div id="detail"></div></section>'
    page+='<section class="card"><h2>시간과 크기</h2><p>원본 읽기·프로파일링·SQLite 저장: <b>'+f"{b['build_seconds']:.3f}초"+'</b>, DB '+f"{b['database_bytes']/1024/1024:.2f} MiB"+', 공통 검색 특징 준비 '+f"{result['feature_seconds']:.3f}초"+'. 단일 컴퓨터에서 측정한 값으로 운영 환경 처리량과 다를 수 있습니다.</p><div class="scroll"><table><tr><th>방법</th><th>5-fold 평가(초)</th><th>114컬럼 점수 조회·추가 계산(ms)</th><th>준비된 점수의 단일 순위 p95(ms)</th></tr>'+costs+'</table></div><p class="muted">배치 시간은 공통 전처리 후 측정했습니다. TF-IDF·사전 점수는 준비된 행렬 조회이고, 이력·그래프는 추가 계산이 포함되므로 이 열만으로 전체 계산 속도를 비교하면 안 됩니다. 순위 p95는 정렬·보류 결정만 100회×114컬럼 반복한 값이며, 새 요청의 전체 응답시간이 아닙니다. 유료 API 비용 0원; 전력·장비 비용과 LLM 대비 절감액은 계산하지 않았습니다.</p></section>'
    page+='<section class="card"><h2>정의·조건 검토 항목</h2><p>도메인과 물리모델의 자료형·길이·NULL 조건, 표준용어 연결, 코드 변환의 목적 코드 존재 여부를 검사했습니다. 차이는 업무상 허용될 수 있어 자동 오류로 확정하지 않았습니다. 검증기준 원문은 모두 보존했으나, 정규식·업무 조건 전체를 자동 실행하는 엔진은 구현 범위 밖입니다.</p><div class="scroll"><table><tr><th>검사</th><th>항목</th><th>차이</th></tr>'+issues+'</table></div></section>'
    if (out/'query_latency.json').exists():
        lat=json.loads((out/'query_latency.json').read_text(encoding='utf8'))
        page+='<section class="card"><h2>새 컬럼 실제 추천 요청 시간</h2><p>명령행을 새로 시작해 특징 준비·그래프 계산·추천까지 <b>'+f"{lat['cold_cli_process_seconds']:.2f}초"+'</b>. 같은 프로세스에서 특징을 매번 다시 준비한 10회 요청의 중앙값 '+f"{lat['in_process_full_request_p50_seconds']:.2f}초"+', p95 '+f"{lat['in_process_full_request_p95_seconds']:.2f}초"+'였습니다. 첫 반복에는 모델 라이브러리 불러오기가 포함됩니다. 작은 반복 수·동일 질문·해당 컴퓨터 부하에 따른 초기 측정으로 운영 SLA를 뜻하지 않습니다.</p><p class="muted">현재 CLI는 요청마다 전체 특징을 다시 만듭니다. 배치 순위 정렬 시간과 실제 새 요청 응답시간은 다릅니다. <a href="query_latency.json">전체 측정값</a></p></section>'
    page+='<section class="card"><h2>그래프+이력: 틀린 추천과 보류</h2><input class="filter" data-table="errors" placeholder="원천 또는 컬럼 검색"><div class="scroll"><table id="errors"><tr><th>원천</th><th>컬럼</th><th>정답</th><th>예측</th><th>상위 후보 3개</th></tr>'+errorrows+'</table></div></section>'
    page+='<section class="card"><h2>전체 파일 반영 범위</h2><p>현재 sources 폴더는 비어 있어 이전 실험이 참조한 원본 폴더 50파일과 백업 ZIP 1개를 읽었습니다. ZIP 내부까지 '+str(b['inventory_entries'])+'항목을 확인하고 SHA-256으로 '+str(b['unique_contents'])+'개 고유 내용을 구분했습니다. 문서는 본문을 색인하고, 표·샘플데이터는 구조를 프로파일링했습니다. 고객 단위 값은 그래프에 복사하지 않았습니다. 영상은 파일 정보만 등록했습니다.</p><p class="muted">처리 상태: '+e(json.dumps(b['statuses'],ensure_ascii=False))+'</p><input class="filter" data-table="inventory" placeholder="파일명 또는 처리 상태 검색"><div class="scroll" style="max-height:450px"><table id="inventory"><tr><th>파일 / 압축 내부 경로</th><th>처리 상태</th><th>바이트</th></tr>'+invrows+'</table></div></section>'
    page+='<section class="card"><h2>결과 파일</h2><p><a href="metrics.csv">성능표</a> · <a href="metrics_by_system.csv">원천별 성능</a> · <a href="predictions.csv">전체 예측</a> · <a href="errors.csv">오답</a> · <a href="costs.csv">측정 시간</a> · <a href="knowledge.sqlite">SQLite 그래프</a> · <a href="graph.json">그래프 JSON</a> · <a href="inventory.json">파일별 처리·해시</a> · <a href="run_manifest.json">실험 재현 정보</a> · <a href="verification.json">검증 결과</a></p></section></main>'
    graph_data=json.loads((out/'graph.json').read_text(encoding='utf8'))
    # Embed data so this report works from disk with no server and no network.
    jsdata=json.dumps(graph_data,ensure_ascii=False).replace('<','\\u003c')
    page+='<script>const G='+jsdata+''';const byId=new Map(G.nodes.map(n=>[n.id,n]));const sel=document.getElementById('nodeSelect');const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function fill(){let q=document.getElementById('nodeFilter').value.toLowerCase();sel.innerHTML=G.nodes.filter(n=>['SourceColumn','TargetColumn','StandardTerm','Domain','CodeSet'].includes(n.kind)&&JSON.stringify(n).toLowerCase().includes(q)).slice(0,350).map(n=>'<option value="'+esc(n.id)+'">'+esc(n.kind+' · '+n.label)+'</option>').join('');show()}function show(){let n=byId.get(sel.value);if(!n){document.getElementById('detail').textContent='일치하는 항목이 없습니다.';return}let edges=G.edges.filter(e=>e.source===n.id||e.target===n.id);document.getElementById('detail').innerHTML='<h3>'+esc(n.label)+'</h3><pre>'+esc(JSON.stringify(n.properties,null,2))+'</pre><table><tr><th>관계</th><th>연결 항목</th></tr>'+edges.map(e=>{let other=e.source===n.id?e.target:e.source;let x=byId.get(other);return '<tr><td>'+esc(e.source===n.id?'→ '+e.relation:'← '+e.relation)+'</td><td><a href="#" data-id="'+esc(other)+'">'+esc(x.label)+'</a></td></tr>'}).join('')+'</table>';document.querySelectorAll('[data-id]').forEach(a=>a.onclick=ev=>{ev.preventDefault();let id=a.dataset.id;if(!Array.from(sel.options).some(o=>o.value===id)){let o=new Option(byId.get(id).label,id);sel.add(o)}sel.value=id;show()})}document.getElementById('nodeFilter').oninput=fill;sel.onchange=show;document.querySelectorAll('.filter').forEach(x=>x.oninput=()=>document.querySelectorAll('#'+x.dataset.table+' tr').forEach((r,i)=>{if(i)r.hidden=!r.textContent.toLowerCase().includes(x.value.toLowerCase())}));fill();</script></html>'''
    (out/'report.html').write_text(page,encoding='utf8')

def run():
    out=HERE/'results';out.mkdir(exist_ok=True)
    raw=(HERE/'data/snapshot.json').read_bytes();data=json.loads(raw);catalog=json.loads((HERE/'data/catalog.json').read_text(encoding='utf8'))
    start=time.perf_counter();f=GraphFeatures(data,catalog);feature_sec=time.perf_counter()-start
    systems=sorted({q['system'] for q in f.q});allrows=[];folds=[];thresholds=[];costs=[];audits=[]
    for method in METHODS:
        start=time.perf_counter();rows=[]
        for system in systems:
            train=[i for i,q in enumerate(f.q) if q['system']!=system];test=[i for i,q in enumerate(f.q) if q['system']==system]
            threshold=tune_threshold(f,method,train)
            scores=f.scores(method,train);rr=predict(f,scores,test,threshold,method,system);rows.extend(rr)
            folds.append({'method':method,'heldout_system':system,**summarize(rr)})
            thresholds.append({'method':method,'heldout_system':system,'threshold':threshold})
            if method.startswith('graph_'):
                audit=f.audit[(method,tuple(train))]
                assert system not in audit['train_systems']
                audits.append({'method':method,'heldout_system':system,**audit})
        elapsed=time.perf_counter()-start;allrows.extend(rows)
        # No score cache for cold batch timing. Common feature initialization is recorded separately.
        train=list(range(f.n));f.cache.pop((method,tuple(train)),None)
        tick=time.perf_counter();scores=f.scores(method,train);cold=time.perf_counter()-tick
        samples=[]
        for _ in range(100):
            for row in scores:
                tick=time.perf_counter_ns();order=np.argsort(-row,kind='stable')[:5];bool(row[order[0]]>=.5);samples.append((time.perf_counter_ns()-tick)/1e6)
        costs.append({'method':method,'evaluation_seconds':elapsed,'cold_batch_score_seconds':cold,'warm_rank_p50_ms':float(np.median(samples)),'warm_rank_p95_ms':float(np.quantile(samples,.95)),'rank_samples':len(samples),'api_calls':0,'api_cost_usd':0})
        print(method,json.dumps(summarize(rows)),flush=True)
    summary=[{'method':m,**summarize([r for r in allrows if r['method']==m])} for m in METHODS]
    result={'timestamp':datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),'build':json.loads((out/'build_summary.json').read_text(encoding='utf8')),'summary':summary,'feature_seconds':feature_sec,'costs':costs,'predictions':allrows,'catalog_issues':catalog_checks(catalog),'bootstrap':paired_bootstrap(allrows,'hybrid_transfer','graph_history')}
    write_csv(out/'metrics.csv',summary);write_csv(out/'metrics_by_system.csv',folds);write_csv(out/'thresholds.csv',thresholds);write_csv(out/'costs.csv',costs)
    flat=[{**{k:v for k,v in r.items() if k not in ('gold','predicted','ranked')},'gold':' ; '.join(r['gold']),'predicted':' ; '.join(r['predicted']),'top5':' ; '.join(r['ranked'])} for r in allrows]
    write_csv(out/'predictions.csv',flat);write_csv(out/'errors.csv',[r for r in flat if not r['correct']]);write_csv(out/'catalog_issues.csv',result['catalog_issues'])
    dump(out/'results.json',result);dump(out/'fold_graph_audit.json',audits)
    manifest={'timestamp':result['timestamp'],'python':sys.version,'platform':platform.platform(),'snapshot_sha256':hashlib.sha256(raw).hexdigest(),'protocol':'nested leave-one-source-system-out; fixed graph weights; threshold inner LOSO 0..1 step .02','test_queries':114,'positive_queries':65,'gold_pairs':68,'target_candidates':78,'graph_walk':{'iterations':24,'restart':.65,'base_weight':.75,'graph_weight':.25,'domain_edge_weight':.25,'approved_edge_weight':2.},'prediction_limit':1,'transductive_metadata':'Known target catalog and unlabeled query metadata allowed; heldout labels excluded from every training graph.','nonindependent_standards':'Project dictionaries may encode design decisions informed by source schemas. Exploratory only.','runtime_note':'Existing scikit-learn dependencies require the installed Python 3.13 interpreter; bundled Python 3.12 is used for PDF extraction.','excluded_from_scoring':['document chunks','source code mappings','mapping transformation rules','review comments','customer row values'],'source_code_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'build_graph.py',HERE/'benchmark.py',LAB/'run_experiments.py']}}
    deployment={m:tune_threshold(f,m,list(range(f.n))) for m in ('hybrid_transfer','graph_history')}
    dump(out/'deployment_thresholds.json',deployment)
    dump(out/'run_manifest.json',manifest);render(result)
    print('REPORT',out/'report.html',flush=True)

if __name__=='__main__':run()
