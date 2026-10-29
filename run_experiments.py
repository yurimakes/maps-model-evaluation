"""CPU-only MAPS schema matching benchmark with nested source-system holdouts."""
from __future__ import annotations
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'.packages'))
import argparse, csv, hashlib, html, json, platform, re, time, warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
warnings.filterwarnings('ignore',message='Using slow pure-python SequenceMatcher')
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from third_party.magneto_name import alignment_score_consecutive, fuzzy_similarity
from prepare_data import write_csv

METHODS=['magneto_name','metadata_tfidf','hybrid_dictionary','hybrid_type_rules','hybrid_transfer','maps_v3_candidate']
LABELS={'magneto_name':'Magneto 공개 코드 · 이름 비교','metadata_tfidf':'메타데이터 문자 TF-IDF','hybrid_dictionary':'약어사전 + BM25 + 문자 TF-IDF','hybrid_type_rules':'하이브리드 + 자료형 검사','hybrid_transfer':'하이브리드 + 다른 원천 승인 이력'}
LABELS['maps_v3_candidate']='2차 업무관계 규칙 + 하이브리드 + 이력'

def tokens(text):
    text=re.sub(r'([a-z])([A-Z])',r'\1 \2',str(text))
    return re.findall(r'[a-z0-9]+|[가-힣]+',text.lower())

class Features:
    def __init__(self,data):
        self.q=data['queries'];self.t=data['targets'];self.n=len(self.q);self.m=len(self.t)
        self.tids=[t['id'] for t in self.t]
        self.alias={}
        for abbr,full,ko in data['aliases']:
            canonical=' '.join(tokens(full))+' '+ko
            for key in [abbr,full]:self.alias[key.lower()]=canonical
        def expand(text):
            ts=tokens(text)
            return ' '.join(self.alias.get(x,x) for x in ts)
        self.expand=expand
        qraw=[q['column']+' '+q['description'] for q in self.q]
        traw=[t['column']+' '+t['description'] for t in self.t]
        self.qdocs=[expand(x) for x in qraw]
        self.tdocs=[expand(x+' '+t['term']) for x,t in zip(traw,self.t)]
        def cosine(qdocs,tdocs):
            v=TfidfVectorizer(analyzer='char',ngram_range=(2,4),sublinear_tf=True)
            tm=v.fit_transform(tdocs)
            return (v.transform(qdocs)@tm.T).toarray()
        raw=cosine(qraw,traw);expanded=cosine(self.qdocs,self.tdocs)
        names=np.array([[max(fuzzy_similarity(q['column'].lower(),t['column'].lower()),alignment_score_consecutive(q['column'],t['column'])) for t in self.t] for q in self.q])
        # BM25 parameters are frozen. IDF uses only the known target catalog.
        docs=[Counter(tokens(s)) for s in self.tdocs];N=len(docs)
        df=Counter(w for d in docs for w in d);avg=sum(sum(d.values()) for d in docs)/N
        bm=np.zeros((self.n,self.m))
        for i,s in enumerate(self.qdocs):
            for j,d in enumerate(docs):
                length=sum(d.values())
                bm[i,j]=sum(np.log(1+(N-df[w]+.5)/(df[w]+.5))*d[w]*2.5/(d[w]+1.5*(.25+.75*length/avg)) for w in set(tokens(s)) if d[w])
        bm=bm/np.maximum(bm.max(axis=1,keepdims=True),1e-12)
        def jacc(a,b):
            a,b=set(tokens(expand(a))),set(tokens(expand(b)))
            return len(a&b)/max(1,len(a|b))
        jac=np.array([[jacc(q['column'],t['column']) for t in self.t] for q in self.q])
        hybrid=.55*expanded+.35*bm+.10*jac
        penalty=np.ones_like(hybrid)
        def family(dtype):
            dtype=dtype.upper()
            if any(x in dtype for x in ['DATE','TIME']):return 'temporal'
            if any(x in dtype for x in ['INT','DECIMAL','NUMBER','FLOAT','DOUBLE']):return 'numeric'
            if any(x in dtype for x in ['VARCHAR','STRING','CHAR','TEXT']):return 'text'
            return 'unknown'
        for i,q in enumerate(self.q):
            for j,t in enumerate(self.t):
                a,b=family(q['dtype']),family(t['dtype'])
                # Text can encode dates/codes: leave it unpenalized. This is a soft rule.
                if a=='temporal' and b!='temporal':penalty[i,j]=.55
                elif a=='numeric' and b=='temporal':penalty[i,j]=.55
        self.base={'magneto_name':names,'metadata_tfidf':raw,'hybrid_dictionary':hybrid,'hybrid_type_rules':hybrid*penalty}
        self.gold=[set(q['gold']) for q in self.q]
        self.policy=json.loads((HERE/'maps_policy.json').read_text(encoding='utf-8'))

    def permitted(self,q,t):
        allowed=self.policy['table_overrides'].get(q['system']+'|'+q['table'].lower(),self.policy['allowed_tables'].get(q['system']))
        if allowed is not None and t['table'] not in allowed:return False
        source_tokens=set(tokens(q['column']))
        incompatible=set(self.policy['product_identifier_incompatible_tokens'])
        if t['column']=='PRD_ID' and source_tokens&incompatible:return False
        return True

    def scores(self,method,train):
        if method not in ['hybrid_transfer','maps_v3_candidate']:return self.base[method]
        train=list(train)
        if not train:return self.base['hybrid_type_rules']
        v=TfidfVectorizer(analyzer='char',ngram_range=(2,4),sublinear_tf=True)
        tm=v.fit_transform([self.qdocs[i] for i in train])
        sim=(v.transform(self.qdocs)@tm.T).toarray()
        mem=np.zeros((self.n,self.m));neg=np.zeros(self.n)
        lookup={t:i for i,t in enumerate(self.tids)}
        for k,i in enumerate(train):
            if not self.gold[i]:neg=np.maximum(neg,sim[:,k]);continue
            for t in self.gold[i]:
                target_indices=[lookup[t]] if method=='hybrid_transfer' else [j for j,col in enumerate(self.t) if col['column']==t.split('.',1)[1]]
                for j in target_indices:mem[:,j]=np.maximum(mem[:,j],sim[:,k])
        result=(.65*self.base['hybrid_type_rules']+.35*mem)*(1-.15*neg[:,None])
        if method=='maps_v3_candidate':
            for i,q in enumerate(self.q):
                for j,t in enumerate(self.t):
                    if not self.permitted(q,t):result[i,j]=0
        return result

def divide(a,b):return a/b if b else 0.
def prf(tp,fp,fn):
    p=divide(tp,tp+fp);r=divide(tp,tp+fn)
    return p,r,divide(2*p*r,p+r)

def summarize(rows):
    tp=fp=fn=itp=ifp=ifn=0;correct=exact=0;hits=defaultdict(int);pairs_at=defaultdict(int);npositive=0;ngold=0
    for r in rows:
        gold=set(r['gold']);pred=set(r['predicted']);ranked=r['ranked']
        tp+=len(gold&pred);fp+=len(pred-gold);fn+=len(gold-pred)
        itp+=bool(gold) and bool(pred);ifp+=not gold and bool(pred);ifn+=bool(gold) and not pred
        correct+=bool(gold&pred) if gold else not pred
        exact+=gold==pred
        if gold:
            npositive+=1;ngold+=len(gold)
            for k in (1,3,5):
                hits[k]+=bool(gold&set(ranked[:k]));pairs_at[k]+=len(gold&set(ranked[:k]))
    p,r,f=prf(tp,fp,fn);ip,ir,iff=prf(itp,ifp,ifn)
    return {'n_queries':len(rows),'n_positive_queries':npositive,'gold_pairs':ngold,'top1_accuracy':divide(hits[1],npositive),'top3_accuracy':divide(hits[3],npositive),'top5_accuracy':divide(hits[5],npositive),'pair_recall_at5':divide(pairs_at[5],ngold),'mapping_precision':p,'mapping_recall':r,'mapping_f1':f,'decision_accuracy':divide(correct,len(rows)),'exact_set_accuracy':divide(exact,len(rows)),'migration_precision':ip,'migration_recall':ir,'migration_f1':iff,'tp':tp,'fp':fp,'fn':fn,'proposed_queries':sum(bool(x['predicted']) for x in rows)}

def predict(features,scores,indices,threshold,method,fold):
    rows=[]
    for i in indices:
        order=np.argsort(-scores[i],kind='stable')
        best=float(scores[i,order[0]]);pred=[features.tids[order[0]]] if best>=threshold and best>0 else []
        q=features.q[i]
        rows.append({'method':method,'fold':fold,'query_id':q['id'],'system':q['system'],'table':q['table'],'column':q['column'],'description':q['description'],'gold':q['gold'],'predicted':pred,'score':best,'threshold':threshold,'ranked':[features.tids[j] for j in order[:5]],'correct':bool(set(pred)&set(q['gold'])) if q['gold'] else not pred})
    return rows

def tune_threshold(features,method,train):
    # Inner leave-one-system-out. No held-out outer labels are read here.
    prepared=[]
    for system in sorted({features.q[i]['system'] for i in train}):
        inner_train=[i for i in train if features.q[i]['system']!=system]
        validation=[i for i in train if features.q[i]['system']==system]
        prepared.append((features.scores(method,inner_train),validation))
    best=(-1.,-1.,-1.);selected=0.
    for threshold in np.linspace(0,1,51):
        rows=[]
        for scores,idx in prepared:rows.extend(predict(features,scores,idx,float(threshold),method,'inner'))
        m=summarize(rows)
        key=(m['mapping_f1'],m['mapping_precision'],-float(threshold))
        if key>best:best=key;selected=float(threshold)
    return selected

def historical(data,features,current):
    # The old logs contain repeated runs, not independent test samples.
    out=[];details=[]
    lookup=defaultdict(list)
    for q in features.q:lookup[(q['system'],q['column'].lower())].append(q)
    for log_name,raw in data['old_runs'].items():
        grouped=defaultdict(list)
        for r in raw:grouped[(r['query_id'],r['채널'],r['원천컬럼'])].append(r)
        comparable=[];correct_runs=0;total_runs=0;modal_correct=0;stability=[];modal_rows=[];repeat_rows=[];first_rows=[];tie_count=0
        for (qid,system,col),runs in grouped.items():
            qs=lookup.get((system,col.lower()),[])
            # Refuse ambiguous table identity instead of guessing.
            if len(qs)!=1:continue
            q=qs[0];counts=Counter(r['target'] for r in runs);modal,n=counts.most_common(1)[0]
            tie_count+=sum(v==n for v in counts.values())>1
            def evaluation_row(target):
                pred=[] if target.upper().strip() in ['NONE','NULL','EXCLUDE','NO_MATCH',''] else [target.strip()]
                return {'gold':q['gold'],'predicted':pred,'ranked':pred}
            modal_rows.append(evaluation_row(modal))
            repeat_rows.extend(evaluation_row(r['target']) for r in runs)
            first_rows.append(evaluation_row(sorted(runs,key=lambda r:int(r['rep']))[0]['target']))
            def right(t):return t in q['gold'] if q['gold'] else t.upper() in ['NONE','NULL','EXCLUDE','NO_MATCH','']
            c=sum(right(r['target']) for r in runs)
            correct_runs+=c;total_runs+=len(runs);modal_correct+=right(modal);stability.append(n/len(runs));comparable.append(q['id'])
            details.append({'log':log_name,'query_id':qid,'system':system,'column':col,'gold':' ; '.join(q['gold']),'modal_prediction':modal,'correct_runs':c,'runs':len(runs),'modal_correct':right(modal),'stability':n/len(runs)})
        mm=summarize(modal_rows);rm=summarize(repeat_rows);fm=summarize(first_rows)
        out.append({'log':log_name,'comparable_queries':len(comparable),'total_log_queries':len(grouped),'source_systems':sorted({system for _,system,_ in grouped}),'run_accuracy':divide(correct_runs,total_runs),'modal_accuracy':divide(modal_correct,len(comparable)),'mean_stability':float(np.mean(stability)) if stability else 0,'modal_tie_queries':tie_count,'modal_mapping_precision':mm['mapping_precision'],'modal_mapping_recall':mm['mapping_recall'],'modal_mapping_f1':mm['mapping_f1'],'repeat_mapping_precision':rm['mapping_precision'],'repeat_mapping_recall':rm['mapping_recall'],'repeat_mapping_f1':rm['mapping_f1'],'first_rep_mapping_f1':fm['mapping_f1'],'first_rep_accuracy':fm['decision_accuracy']})
        ids=set(comparable)
        for method in METHODS:
            rows=[r for r in current if r['method']==method and r['query_id'] in ids]
            if rows:out.append({'log':log_name,'local_method':method,**summarize(rows)})
    return out,details

def paired_bootstrap(rows,method_a,method_b,seed=42):
    a={r['query_id']:r for r in rows if r['method']==method_a};b={r['query_id']:r for r in rows if r['method']==method_b}
    ids=sorted(set(a)&set(b));rng=np.random.default_rng(seed);deltas=[]
    # Query bootstrap is descriptive; 5 source systems are too few for strong inference.
    for _ in range(1000):
        sample=rng.integers(0,len(ids),len(ids))
        am=summarize([a[ids[i]] for i in sample]);bm=summarize([b[ids[i]] for i in sample]);deltas.append(bm['mapping_f1']-am['mapping_f1'])
    return {'baseline':method_a,'comparison':method_b,'metric':'mapping_f1','delta':summarize(list(b.values()))['mapping_f1']-summarize(list(a.values()))['mapping_f1'],'query_bootstrap_ci95':list(map(float,np.quantile(deltas,[.025,.975]))),'warning':'Exploratory query bootstrap; source-system dependence is not accounted for.'}

def render_report(result,out):
    esc=lambda x:html.escape(str(x))
    pct=lambda x:f'{x*100:.1f}%'
    keys=['top1_accuracy','top5_accuracy','mapping_precision','mapping_recall','mapping_f1','decision_accuracy']
    trs=''.join('<tr><td>'+esc(LABELS[m['method']])+'</td>'+''.join('<td>'+pct(m[k])+'</td>' for k in keys)+'</tr>' for m in result['summary'])
    errors=[r for r in result['predictions'] if r['method']=='maps_v3_candidate' and not r['correct']]
    ers=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [r['system'],r['column'],' / '.join(r['gold']) or '이관 제외',' / '.join(r['predicted']) or '보류',' / '.join(r['ranked'][:3])])+'</tr>' for r in errors)
    old=''.join('<li>'+esc(x['log'])+': 비교 가능 '+str(x['comparable_queries'])+'건, 반복별 정답률 '+pct(x['run_accuracy'])+', 최빈 정답률 '+pct(x['modal_accuracy'])+', 일관성 '+pct(x['mean_stability'])+'</li>' for x in result['historical'] if 'local_method' not in x)
    old_table=''
    for x in result['historical']:
        if 'local_method' not in x:
            for kind,title in [('repeat','全 반복 출력'),('modal','질문별 최빈 출력')]:
                old_table+='<tr><td>'+esc(x['log'])+' · '+title+'</td>'+''.join('<td>'+pct(x[kind+'_mapping_'+k])+'</td>' for k in ['precision','recall','f1'])+'</tr>'
    for x in result['historical']:
        if x.get('log')=='self_consistency_raw.csv' and x.get('local_method') in ['magneto_name','hybrid_dictionary','hybrid_transfer','maps_v3_candidate']:
            old_table+='<tr><td>로컬 · '+esc(LABELS[x['local_method']])+'</td>'+''.join('<td>'+pct(x['mapping_'+k])+'</td>' for k in ['precision','recall','f1'])+'</tr>'
    audit=result['audit'];stats=result['summary'][0]
    bars=''.join('<div class="barrow"><span>'+esc(LABELS[m['method']])+'</span><div class="track"><div class="fill" style="width:'+str(m['mapping_f1']*100)+'%"></div></div><b>'+pct(m['mapping_f1'])+'</b></div>' for m in result['summary'])
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MAPS 로컬 성능 실험</title><style>
    :root{font-family:'Malgun Gothic',Arial,sans-serif;color:#172c39;background:#eff4f6}*{box-sizing:border-box}body{margin:0}main{max-width:1240px;margin:auto;padding:45px 25px}h1{font-size:36px;margin:8px 0 14px}h2{font-size:23px;margin-top:0}p,li{line-height:1.8}.eyebrow{color:#087f88;font-weight:700;letter-spacing:2px}.card{background:white;border:1px solid #d9e4e8;border-radius:16px;padding:26px;margin:24px 0}.notice{border-left:5px solid #e5a93d;background:#fff9ec;padding:16px 22px;border-radius:8px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin:25px 0}.stat{background:#163d4d;color:#fff;padding:22px;border-radius:13px}.stat b{font-size:33px;display:block}.stat span{font-size:14px;color:#cde5ec}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:13px;text-align:left;border-bottom:1px solid #e1e9ed;vertical-align:top}th{background:#edf4f6;white-space:nowrap}tbody tr:hover{background:#f2f9f8}.barrow{display:grid;grid-template-columns:330px 1fr 70px;gap:15px;align-items:center;font-size:14px;margin:18px 0}.track{height:20px;background:#eaf0f3;border-radius:7px;overflow:hidden}.fill{height:100%;background:#188c94}a{color:#087e8c}code{background:#edf3f5;padding:2px 6px;border-radius:4px}.muted{color:#556e7a}input{font:inherit;padding:10px;border:1px solid #abc0ca;border-radius:7px;width:100%;max-width:400px;margin-bottom:16px}@media(max-width:800px){.stats{grid-template-columns:1fr 1fr}.barrow{grid-template-columns:1fr}.card{padding:17px}h1{font-size:28px}}</style><main><div class="eyebrow">MAPS · LOCAL EXPERIMENT</div><h1>컬럼 매핑, 실제 정답으로 비교하기</h1><p class="muted">CPU 로컬 실행 · 유료 API 호출 0회 · 데이터는 외부로 전송하지 않음</p>'''
    page+='<div class="stats">'+''.join('<div class="stat"><b>'+str(v)+'</b><span>'+s+'</span></div>' for v,s in [(stats['n_queries'],'평가 원천 컬럼'),(stats['n_positive_queries'],'정답 매핑이 있는 컬럼'),(stats['gold_pairs'],'정답 Source–Target 쌍'),(78,'Target 후보')])+'</div>'
    page+='<div class="notice"><b>초기 탐색 실험입니다.</b> 기존 2차 RAG 전체를 다시 실행한 결과가 아닙니다. 승인 매핑의 동일 행을 검색하는 실험도 아닙니다. 현재 표준사전은 2차 설계 과정에서 만들어졌으므로 완전히 새로운 업체 데이터에 대한 독립 검증은 추가로 필요합니다.</div>'
    page+='<section class="card"><h2>실측 비교</h2><p>원천 시스템 5개를 번갈아 통째로 보류했습니다. 이력 모델은 나머지 4개 원천의 승인·제외 정보만 사용합니다. 추천 보류 기준은 그 4개 안에서 다시 원천별로 나누어 선택했습니다.</p><div class="scroll"><table><thead><tr><th>방법</th><th>Top-1 정확도</th><th>Top-5 정확도</th><th>매핑 정밀도</th><th>매핑 재현율</th><th>매핑 F1</th><th>추천·제외 정확도</th></tr></thead><tbody>'+trs+'</tbody></table></div><p class="muted">Top-1·Top-5는 정답이 있는 65컬럼의 순위 정확도입니다. 매핑 P/R/F1은 49개 제외 컬럼도 포함한 68개 정답 쌍 기준입니다. 1개만 추천하므로 복수 Target 정답을 모두 찾지 못하면 재현율에서 감점됩니다.</p>'+bars+'</section>'
    page+='<section class="card"><h2>자료 확인</h2><ul><li>매핑정의서 '+str(audit['mapping_rows'])+'행을 동일 원천·테이블·컬럼 단위로 묶어 114개 질문을 구성했습니다.</li><li>생성 값인 &lt;SOURCE_SYSTEM&gt;·&lt;DETAIL_TYPE&gt; '+str(audit['excluded_pseudo_rows'])+'행은 일반 컬럼 예측에서 제외했습니다.</li><li>메타데이터만 있고 정답표에는 없는 '+str(audit['unlabeled_metadata_columns'])+'컬럼은 오답이나 제외 정답으로 간주하지 않았습니다.</li><li>메타데이터를 정확히 연결하지 못한 컬럼: '+esc(', '.join(audit['missing_source_metadata']))+'. 해당 컬럼은 이름만 사용합니다.</li><li>SAMPLE_VALUE, 변환규칙, 이관 여부, 검토 코멘트는 테스트 입력에서 사용하지 않습니다.</li><li>원본 자료는 읽기만 수행했습니다. 입력 파일 해시는 data/manifest.csv에 기록했습니다.</li></ul></section>'
    page+='<section class="card"><h2>2차 반복 로그와의 제한된 비교</h2><ul>'+old+'</ul><div class="notice"><b>2차 전체의 성능 개선을 확정할 수는 없습니다.</b> 초기 단순 로컬 방법은 2차 로그보다 낮았고, 확정된 업무관계 규칙을 연결한 방법은 같은 18문항에서 높은 재현율을 보였습니다. 이 정책과 방법은 기존 오류를 살펴본 후 설계한 탐색안입니다. 독립 평가와 기존 RAG 코드의 A/B 재실행이 필요합니다.</div><div class="scroll"><table><thead><tr><th>동일한 홈페이지 18질문 비교</th><th>매핑 정밀도</th><th>매핑 재현율</th><th>매핑 F1</th></tr></thead><tbody>'+old_table+'</tbody></table></div><p>540회는 18질문을 30회 반복한 값입니다. 독립 표본 540건으로 해석하면 안 됩니다. 반복 일관성과 정답 정확도를 따로 계산했습니다. 최빈 출력은 30회 결과를 집계하므로 1회 로컬 예측과 실행 비용 조건이 다릅니다. 최빈 동률은 최초 관측 순서로 결정했으며 원본 로그에서 1질문에 해당합니다. 기존 로그가 어떤 승인 매핑·인덱스를 참조했는지 알 수 없어 완전히 동일한 실험 조건 비교는 아닙니다.</p></section>'
    page+='<section class="card"><h2>이력 결합 모델 · 틀린 추천과 보류</h2><input id="search" placeholder="원천명 또는 컬럼 검색"><div class="scroll"><table id="errors"><thead><tr><th>원천</th><th>컬럼</th><th>정답</th><th>예측</th><th>상위 후보 3개</th></tr></thead><tbody>'+ers+'</tbody></table></div></section>'
    page+='<section class="card"><h2>해석과 다음 실험</h2><p>문자 TF-IDF는 학습된 의미 임베딩 모델이 아닙니다. 하이브리드도 BM25와 문자 유사도를 결합한 로컬 구현입니다. 규칙은 자료형 불일치를 약하게 감점하며, 업무상 이관 제외 정책 전체를 구현하지는 않습니다. 자동 승인 기준으로 사용하기 전 오답·보류를 검토해야 합니다.</p><p>다음 단계는 같은 평가 인터페이스에서 한국어 임베딩과 실제 2차 RAG 예측을 추가하고, 새 업체 데이터 또는 사람이 별도로 검토한 정답셋으로 비교하는 것입니다. AI Hub 상담 코드화는 컬럼 매핑과 별도 과제이며, 이 실행에는 포함하지 않았습니다.</p><p>Magneto 공식 저장소의 문자열 비교 함수를 가져와 기준 방법으로 실제 실행했습니다. 신경망 검색·LLM 재정렬을 포함한 Magneto 전체나 LLMatch 전체를 재현한 것은 아닙니다. <a href="https://github.com/VIDA-NYU/magneto-matcher/tree/6620623265fc7feac0f053996e62b68a13a72a57">사용 코드 출처</a> · <a href="https://github.com/knowledge-fusion/LLMatch">검토한 LLMatch</a></p><p><a href="metrics.csv">성능표 CSV</a> · <a href="predictions.csv">전체 예측 CSV</a> · <a href="historical_comparison.json">2차 로그 비교</a> · <a href="costs.csv">실행 시간·비용</a> · <a href="run_manifest.json">재현 정보</a></p></section><p class="muted">'+esc(result['timestamp'])+' · seed 42 · 결과는 백분율로 표시</p></main><script>document.getElementById("search").addEventListener("input",e=>{const q=e.target.value.toLowerCase();document.querySelectorAll("#errors tbody tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));});</script></html>'
    (out/'report.html').write_text(page,encoding='utf-8')

def run():
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/latest');args=p.parse_args()
    out=HERE/args.out;out.mkdir(parents=True,exist_ok=True)
    snapshot=(HERE/'data'/'snapshot.json').read_bytes();data=json.loads(snapshot)
    start=time.perf_counter();f=Features(data);feature_sec=time.perf_counter()-start
    systems=sorted({q['system'] for q in f.q});allrows=[];fold_metrics=[];thresholds=[];costs=[]
    for method in METHODS:
        tick=time.perf_counter();rows=[]
        for heldout in systems:
            train=[i for i,q in enumerate(f.q) if q['system']!=heldout]
            test=[i for i,q in enumerate(f.q) if q['system']==heldout]
            assert not {f.q[i]['id'] for i in train}&{f.q[i]['id'] for i in test}
            threshold=tune_threshold(f,method,train)
            predictions=predict(f,f.scores(method,train),test,threshold,method,heldout)
            rows.extend(predictions)
            fold_metrics.append({'method':method,'heldout_system':heldout,**summarize(predictions)})
            thresholds.append({'method':method,'heldout_system':heldout,'threshold':threshold,'training_systems':','.join(s for s in systems if s!=heldout)})
        allrows.extend(rows)
        costs.append({'method':method,'cpu_elapsed_seconds':time.perf_counter()-tick,'shared_feature_seconds':feature_sec,'api_calls':0,'input_tokens':0,'output_tokens':0,'api_cost_usd':0,'electricity_and_hardware_cost':'NOT_MEASURED'})
        print(method,json.dumps(summarize(rows),ensure_ascii=False))
    summary=[{'method':m,**summarize([r for r in allrows if r['method']==m])} for m in METHODS]
    historical_results,hist_rows=historical(data,f,allrows)
    bootstrap=[paired_bootstrap(allrows,'magneto_name',m) for m in METHODS[1:]]
    timestamp=datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
    result={'timestamp':timestamp,'audit':data['audit'],'summary':summary,'predictions':allrows,'historical':historical_results,'bootstrap':bootstrap}
    write_csv(out/'metrics.csv',summary);write_csv(out/'metrics_by_system.csv',fold_metrics);write_csv(out/'thresholds.csv',thresholds);write_csv(out/'costs.csv',costs);write_csv(out/'historical_queries.csv',hist_rows)
    flat=[]
    for r in allrows:
        row={k:v for k,v in r.items() if k not in ['gold','predicted','ranked']}
        row.update(gold=' ; '.join(r['gold']),predicted=' ; '.join(r['predicted']),top5=' ; '.join(r['ranked']));flat.append(row)
    write_csv(out/'predictions.csv',flat);write_csv(out/'errors.csv',[r for r in flat if not r['correct']])
    (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'historical_comparison.json').write_text(json.dumps(historical_results,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'timestamp':timestamp,'seed':42,'python':sys.version,'platform':platform.platform(),'snapshot_sha256':hashlib.sha256(snapshot).hexdigest(),'protocol':'outer leave-one-source-system-out; threshold selected by inner leave-one-source-system-out mapping pair F1','models':METHODS,'threshold_grid':'0.00 to 1.00 step 0.02; ties prefer precision, then lower threshold','selection_warning':'Exploratory benchmark; method design and standard dictionaries were informed by this project, not a blinded external validation.','target_catalog_size':len(f.t),'query_count':len(f.q),'magneto_commit':'6620623265fc7feac0f053996e62b68a13a72a57','source_manifest':data['manifest'],'source_code_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'prepare_data.py',HERE/'run_experiments.py',HERE/'third_party'/'magneto_name.py']}}
    (out/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    render_report(result,out)
    print('REPORT',out/'report.html')

if __name__=='__main__':run()
