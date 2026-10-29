"""Add review suggestions to phase-2 output; never write approval or migration state."""
from __future__ import annotations
import copy,csv,json
from functools import lru_cache
import numpy as np
from run_experiments import HERE,Features,tune_threshold,summarize
from prepare_data import write_csv

EXCLUDE={'','EXCLUDE','NONE','NULL','NO_MATCH'}

def combine(legacy_target,candidate,candidate_score,threshold,permitted=True):
    """No labels are accepted by this function. Legacy positive output is preserved."""
    legacy_target=str(legacy_target or '').strip()
    if legacy_target.upper() not in EXCLUDE:
        return legacy_target,'LEGACY_PRESERVED' if permitted else 'REVIEW_LEGACY_CONFLICT'
    if candidate_score>=threshold and candidate_score>0:
        return candidate,'REVIEW_NEW_CANDIDATE'
    return 'EXCLUDE','LEGACY_EXCLUDE_PRESERVED'

class UpgradeEngine:
    def __init__(self,data=None):
        self.data=data or json.loads((HERE/'data'/'snapshot.json').read_text(encoding='utf-8'))
        self.features=Features(self.data)
        self.known={(q['system'],q['table'].lower(),q['column']):i for i,q in enumerate(self.features.q)}
        self.target={t['id']:t for t in self.features.t}
        self.policy_version=self.features.policy['version']

    @lru_cache(maxsize=16)
    def context(self,heldout_system):
        train=[i for i,q in enumerate(self.features.q) if q['system']!=heldout_system]
        # Keep the stricter threshold from before and after policy filtering.
        # Both are chosen on other systems, never on the current system's labels.
        threshold=max(tune_threshold(self.features,'hybrid_transfer',train),tune_threshold(self.features,'maps_v3_candidate',train))
        scores=self.features.scores('maps_v3_candidate',train)
        return threshold,scores

    def recommend(self,source,legacy_target):
        system=source['system'];key=(system,source['table'].lower(),source['column'])
        if key in self.known and all(source.get(k,self.features.q[self.known[key]][k])==self.features.q[self.known[key]][k] for k in ['description','dtype']):
            f=self.features;i=self.known[key];threshold,scores=self.context(system);row=scores[i]
        else:
            # A new schema column can be scored without supplying a ground-truth label.
            data=copy.deepcopy(self.data)
            query={**source,'description':source.get('description',''),'dtype':source.get('dtype',''),'id':'|'.join(key),'gold':[],'mapping_ids':[]}
            data['queries'].append(query);f=Features(data);i=len(f.q)-1
            train=[j for j,q in enumerate(f.q) if q['system']!=system]
            threshold=max(tune_threshold(f,'hybrid_transfer',train),tune_threshold(f,'maps_v3_candidate',train))
            row=f.scores('maps_v3_candidate',train)[i]
        q=f.q[i];order=np.argsort(-row,kind='stable');best=int(order[0]);candidate=f.tids[best]
        legacy=str(legacy_target or '').strip()
        permitted=legacy not in self.target or f.permitted(q,self.target[legacy])
        if legacy.upper() not in EXCLUDE and legacy not in self.target:permitted=False
        proposed,status=combine(legacy,candidate,float(row[best]),threshold,permitted)
        flags=[]
        if not q['description']:flags.append('MISSING_SOURCE_DESCRIPTION')
        if not q['dtype']:flags.append('MISSING_SOURCE_DATATYPE')
        if status=='REVIEW_LEGACY_CONFLICT':flags.append('BUSINESS_RELATIONSHIP_CONFLICT')
        return {'source_system':system,'source_table':q['table'],'source_column':q['column'],'legacy_target_original':legacy,'v3_target_proposal':proposed,'v3_status':status,'retrieval_score':float(row[best]),'retrieval_threshold':threshold,'top5_candidates':[{'target':f.tids[int(j)],'score':float(row[j])} for j in order[:5] if row[j]>0],'flags':flags,'policy_version':self.policy_version,'requires_human_review':True,'execution_allowed':False}

def replay(out):
    out.mkdir(parents=True,exist_ok=True);engine=UpgradeEngine();f=engine.features
    index={}
    for q in f.q:index.setdefault((q['system'],q['column'].lower()),[]).append(q)
    results=[];summaries=[]
    for log,raw in engine.data['old_runs'].items():
        before=[];after=[];new=0;corrected=0;regressed=0
        for r in raw:
            qs=index.get((r['채널'],r['원천컬럼'].lower()),[])
            if len(qs)!=1:continue
            q=qs[0];source={k:q[k] for k in ['system','table','column','description','dtype']}
            suggestion=engine.recommend(source,r['target'])
            def score_row(target):
                pred=[] if target.upper() in EXCLUDE else [target]
                return {'gold':q['gold'],'predicted':pred,'ranked':pred}
            a=score_row(r['target']);b=score_row(suggestion['v3_target_proposal'])
            before.append(a);after.append(b)
            a_correct=set(a['gold'])==set(a['predicted']);b_correct=set(b['gold'])==set(b['predicted'])
            new+=suggestion['v3_status']=='REVIEW_NEW_CANDIDATE';corrected+=not a_correct and b_correct;regressed+=a_correct and not b_correct
            results.append({'log':log,'query_id':r['query_id'],'rep':r['rep'],'gold':' ; '.join(q['gold']),**{k:v for k,v in suggestion.items() if k not in ['top5_candidates','flags']},'flags':','.join(suggestion['flags']),'before_correct':a_correct,'after_correct':b_correct})
        a=summarize(before);b=summarize(after)
        for stage,m in [('phase2_logged_output',a),('phase2_plus_review_suggestions',b)]:
            summaries.append({'log':log,'stage':stage,'distinct_queries':len({(r['query_id']) for r in raw}),'repeated_outputs':len(before),'mapping_precision':m['mapping_precision'],'mapping_recall':m['mapping_recall'],'mapping_f1':m['mapping_f1'],'decision_accuracy':m['decision_accuracy'],'new_review_suggestions':new if stage.endswith('suggestions') else 0,'corrected_outputs':corrected if stage.endswith('suggestions') else 0,'regressed_outputs':regressed if stage.endswith('suggestions') else 0})
    write_csv(out/'replay_predictions.csv',results);write_csv(out/'replay_metrics.csv',summaries)
    (out/'replay_notes.json').write_text(json.dumps({'purpose':'Phase-2 output replay with an additive Human Review suggestion module','validation_status':'EXPLORATORY_NOT_BLINDED','limitations':['Only 18 existing HOMEPAGE questions are available; repetitions are not independent examples.','Business policies and method design were informed by inspecting existing project artifacts and errors.','This is a replay of saved outputs, not a rerun of the original RAG or evidence that production migration accuracy improved.','New suggestions require human review; no approval or migration rule is automatically written.'],'scores':summaries},ensure_ascii=False,indent=2),encoding='utf-8')
    report=out/'report.html'
    if report.exists():
        import html
        table=''.join('<tr><td>'+html.escape(r['log']+' · '+r['stage'])+'</td>'+''.join('<td>'+f'{r[k]*100:.1f}%'+'</td>' for k in ['mapping_precision','mapping_recall','mapping_f1','decision_accuracy'])+'</tr>' for r in summaries)
        section='<section class="card"><h2>2차 출력 + 재검토 후보 추가 · 로그 재생</h2><p>기존 2차의 매핑 출력은 보존하고, EXCLUDE일 때만 업무관계 검사와 다른 원천의 승인 이력을 이용해 후보를 추가했습니다. 추가 후보는 모두 Human Review 대상입니다.</p><div class="notice"><b>18개 기존 질문에 대한 탐색 재생입니다.</b> 개선 방안 설계에 참고한 동일 질문을 다시 평가했으므로 독립 성능으로 해석할 수 없습니다. 새로운 문항과 실제 2차 RAG 재실행으로 검증하기 전에는 운영 성능 상승을 주장하지 않습니다. 기존 정밀도가 100%인 로그에서는 정밀도 상승 여지도 없습니다.</div><div class="scroll"><table><thead><tr><th>방법</th><th>정밀도</th><th>재현율</th><th>F1</th><th>추천·제외 정확도</th></tr></thead><tbody>'+table+'</tbody></table></div><p><a href="replay_predictions.csv">변경된 후보 전체</a> · <a href="replay_metrics.csv">재생 성능표</a> · <a href="replay_notes.json">평가 한계</a></p></section>'
        text=report.read_text(encoding='utf-8').replace('<section class="card"><h2>실측 비교</h2>',section+'<section class="card"><h2>검색·규칙 모듈별 비교</h2>',1)
        report.write_text(text,encoding='utf-8')
    print(json.dumps(summaries,ensure_ascii=False,indent=2))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/latest');a=p.parse_args();replay(HERE/a.out)
