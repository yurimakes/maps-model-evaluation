"""Prepare or run a bounded, local-output-only A/B of the real recommendation code.

Default is a dry run. Paid requests require --execute-api plus existing Azure
endpoint/key/deployment environment variables. No Databricks tables are written.
"""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'.packages'))
import argparse,csv,json,os,time
import requests
from phase2_original.data.maps_rag.azure_client import AzureClient
from phase2_original.data.maps_rag import knowledge as kn,recommend as original
from phase2_upgrade.maps_rag import recommend as upgraded
from phase2_original.data.maps_rag.embeddings import VectorStore
from phase2_original.data.maps_rag.facts import TargetCatalog,Lookups
from phase2_original.data.maps_rag.retrieval import Retriever as OriginalRetriever
from phase2_upgrade.maps_rag.retrieval import Retriever as ImprovedRetriever
from prepare_data import write_csv

class BudgetReached(RuntimeError):pass

class BoundedAzureClient(AzureClient):
    def __init__(self,endpoint,key,deployment,budget,sender=None):
        super().__init__(endpoint,key,chat_deployment=deployment,log=lambda *_:None)
        self.budget=budget;self.sender=sender or requests.post

    def _post(self,dep,op,body,thr,need,kind):
        if self.budget['used']>=self.budget['max_requests']:raise BudgetReached('Request budget reached')
        if kind!='chat':raise RuntimeError('This comparison may only use cached embeddings')
        body=dict(body);body['max_completion_tokens']=min(int(body.get('max_completion_tokens',0)),self.budget['max_output_tokens'])
        self.budget['used']+=1;tick=time.perf_counter()
        try:
            response=self.sender(self._url(dep,op),headers={'api-key':self.key,'Content-Type':'application/json'},json=body,timeout=45)
            entry={'kind':kind,'status':response.status_code,'sec':time.perf_counter()-tick,'max_completion_tokens':body['max_completion_tokens']}
            self.calls.append(entry)
            if response.status_code!=200:raise RuntimeError('Azure request failed with HTTP '+str(response.status_code)+'; no automatic retry')
            data=response.json();entry['usage']=data.get('usage') or {}
            return data
        except requests.RequestException:
            self.calls.append({'kind':kind,'status':'NETWORK_ERROR','sec':time.perf_counter()-tick})
            raise RuntimeError('Azure network error; request counted against budget') from None

def metrics(rows):
    tp=fp=fn=correct=errors=0
    for row in rows:
        g=set(row['gold']);pred=set(row['predicted']) if row['status']=='OK' else set();tp+=len(g&pred);fp+=len(pred-g);fn+=len(g-pred)
        if row['status']!='OK':errors+=1;continue
        correct+=g==pred
    precision=tp/(tp+fp) if tp+fp else 0.;recall=tp/(tp+fn) if tp+fn else 0.
    return {'scheduled_questions':len(rows),'successful_outputs':len(rows)-errors,'errors_or_invalid':errors,'exact_decision_accuracy':correct/max(1,len(rows)),'mapping_precision':precision,'mapping_recall':recall,'mapping_f1':2*precision*recall/(precision+recall) if precision+recall else 0.,'tp':tp,'fp':fp,'fn':fn}

def main():
    p=argparse.ArgumentParser();p.add_argument('--execute-api',action='store_true');p.add_argument('--max-questions',type=int,default=5);p.add_argument('--max-requests',type=int,default=24);p.add_argument('--max-output-tokens',type=int,default=2200);p.add_argument('--out',default='results/model_ab')
    a=p.parse_args()
    if min(a.max_questions,a.max_requests,a.max_output_tokens)<=0:p.error('Limits must be positive')
    out=HERE/a.out;out.mkdir(parents=True,exist_ok=True)
    profiles=json.loads((HERE/'data'/'phase2_profiles.json').read_text(encoding='utf-8'))
    data=json.loads((HERE/'data'/'snapshot.json').read_text(encoding='utf-8'))
    catalog=TargetCatalog(HERE/'phase2_bundle'/'자료'/'2_타겟_정의'/'2_타겟_물리모델_v1.0.csv')
    gold={(q['system'],q['table'].lower(),q['column']):q for q in data['queries']}
    available=[]
    for row in profiles:
        q=gold.get((row['channel'],row['source_table'].lower(),row['source_column']))
        if q is not None and (not q['gold'] or set(q['gold'])&catalog.all_ids):available.append((row,sorted(set(q['gold'])&catalog.all_ids)))
    # Round-robin systems for a small smoke run; use 93 for the complete scope.
    groups={s:[r for r in available if r[0]['channel']==s] for s in sorted({r[0]['channel'] for r in available})}
    selected=[]
    while any(groups.values()) and len(selected)<a.max_questions:
        for group in groups.values():
            if group and len(selected)<a.max_questions:selected.append(group.pop(0))
    config={'mode':'PAID_API' if a.execute_api else 'DRY_RUN_NO_API','available_questions':len(available),'selected_query_ids':[r['query_id'] for r,_ in selected],'selected_questions':len(selected),'max_actual_http_attempts':a.max_requests,'per_attempt_output_token_limit':a.max_output_tokens,'embedding_api_calls':0,'databricks_writes':0,'comparison':'Original recommend_v2 vs strict recommend_v2; same corpus, cached embeddings, weighted fusion and deployment.','sampling_note':'A small round-robin run is a smoke test; full-scope results and independent validation are required.'}
    if not a.execute_api:
        (out/'model_ab_plan.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(config,ensure_ascii=False,indent=2));return
    names=['MAPS_AZURE_ENDPOINT','MAPS_AZURE_KEY','MAPS_CHAT_DEPLOYMENT']
    if any(not os.environ.get(name) for name in names):p.error('Set MAPS_AZURE_ENDPOINT, MAPS_AZURE_KEY and MAPS_CHAT_DEPLOYMENT in the local environment; no requests were made')
    chunks=kn.load_chunks(HERE/'phase2_bundle'/'자료'/'4_지식조각_RAG용'/'지식조각');visible=kn.searchable(chunks);retr=kn.retrievable(chunks)
    store=VectorStore.load(HERE/'phase2_original'/'data'/'data'/'임베딩'/'embeddings.npz');lookups=Lookups(visible)
    budget={'used':0,'max_requests':a.max_requests,'max_output_tokens':a.max_output_tokens};clients={};recommenders={}
    for name,module,retriever in [('original',original,OriginalRetriever(retr,store.chunk_vectors(retr))),('upgraded',upgraded,ImprovedRetriever(retr,store.chunk_vectors(retr)))]:
        client=BoundedAzureClient(os.environ[names[0]],os.environ[names[1]],os.environ[names[2]],budget);clients[name]=client
        recommenders[name]=module.Recommender(catalog,lookups,retriever,client,query_vectors=store.vecs,embedder=None,mode='hybrid',k=5)
    rows=[];raw=[]
    for i,(profile,g) in enumerate(selected):
        for name in (['original','upgraded'] if i%2==0 else ['upgraded','original']):
            status='OK';target=None;flags='';error=None;result={}
            try:
                result,evidence=recommenders[name].recommend_v2(profile)
                target=result.get('ai_target');flags=result.get('flags') or ''
                if result.get('confidence_level') in ['INVALID_CANDIDATE','ERROR'] or not target:status='INVALID_OR_REVIEW'
                raw.append({'method':name,'query_id':profile['query_id'],'result':result,'evidence':evidence})
            except BudgetReached:error='REQUEST_BUDGET_REACHED';status='ERROR'
            except Exception as exc:error=type(exc).__name__;status='ERROR'
            pred=[] if status!='OK' or not target or str(target).upper()=='EXCLUDE' else [target]
            rows.append({'method':name,'query_id':profile['query_id'],'system':profile['channel'],'column':profile['source_column'],'gold':g,'predicted':pred,'status':status,'flags':flags,'error':error,'prompt_tokens':result.get('prompt_tokens'),'completion_tokens':result.get('completion_tokens')})
            # Save after every question; interruption preserves completed outputs.
            (out/'model_ab_predictions.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            (out/'model_ab_raw.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=[{'method':name,**metrics([r for r in rows if r['method']==name])} for name in recommenders]
    write_csv(out/'model_ab_metrics.csv',summary)
    config.update(actual_http_attempts=budget['used'],deployment=os.environ[names[2]],summary=summary,calls={name:client.calls for name,client in clients.items()},pricing='Not estimated; report actual usage tokens and apply deployment prices separately.')
    (out/'model_ab_execution.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
    if any(r['status']=='ERROR' for r in rows):sys.exit(1)

if __name__=='__main__':main()
