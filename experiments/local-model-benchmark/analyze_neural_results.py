"""Analyze frozen actual model outputs without re-running or tuning a model."""
from pathlib import Path
import argparse,csv,hashlib,html,json,random,re,shutil
from model_comparison_utils import metrics
HERE=Path(__file__).resolve().parent

def read_csv(path):return list(csv.DictReader(path.open(encoding='utf-8-sig')))
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='results/latest');p.add_argument('--out',required=True);a=p.parse_args()
    source=HERE/a.input;out=HERE/a.out;out.mkdir(parents=True,exist_ok=True)
    for pattern in ['neural_*','embeddings_*.npz','raw_scores_*.json','requirements-models.lock.txt','actual_neural_model_comparison.log']:
        for path in source.glob(pattern):
            if path.is_file() and path.resolve()!=(out/path.name).resolve():shutil.copy2(path,out/path.name)
    rows=read_csv(out/'neural_predictions.csv')
    for r in rows:
        for key in ['gold','predicted','ranked']:r[key]=[s for s in r[key].split(' ; ') if s]
    baseline='2차 저장 출력 · self_consistency_raw_fixed.csv · first_rep';candidate='magneto_e5_multilingual_metadata'
    old={r['id']:r for r in rows if r['model']==baseline};new={r['id']:r for r in rows if r['model']==candidate}
    ids=sorted(set(old)&set(new));a_metrics=metrics([old[k] for k in ids]);b_metrics=metrics([new[k] for k in ids])
    rng=random.Random(42);deltas=[]
    for _ in range(2000):
        sample=rng.choices(ids,k=len(ids));deltas.append(metrics([new[k] for k in sample])['f1']-metrics([old[k] for k in sample])['f1'])
    deltas.sort()
    def quantile(p):
        x=(len(deltas)-1)*p;i=int(x);j=min(i+1,len(deltas)-1);return deltas[i]*(j-x)+deltas[j]*(x-i) if j!=i else deltas[i]
    changes=[]
    for key in ids:
        if old[key]['predicted']!=new[key]['predicted']:changes.append({'id':key,'column':old[key]['column'],'gold':old[key]['gold'],'baseline':old[key]['predicted'],'e5':new[key]['predicted']})
    findings={'baseline':baseline,'candidate':candidate,'common_questions':len(ids),'baseline_metrics':a_metrics,'candidate_metrics':b_metrics,'f1_delta':b_metrics['f1']-a_metrics['f1'],'precision_delta':b_metrics['precision']-a_metrics['precision'],'recall_delta':b_metrics['recall']-a_metrics['recall'],'paired_question_bootstrap_95_interval':[quantile(.025),quantile(.975)],'bootstrap_seed':42,'bootstrap_resamples':2000,'limitations':'Descriptive question bootstrap on the same 18 development questions in one source system; does not establish external generalization.','changes':changes,'decision':'Prioritize clear source/target metadata and multilingual E5 candidate support; retain phase-2 final validation/HITL; do not claim a wholesale model replacement improves precision.','input_sha256':{name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in ['neural_predictions.csv','neural_model_metrics.csv','neural_common18_metrics.csv','neural_execution.json']}}
    (out/'neural_findings.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2),encoding='utf-8')
    pct=lambda x:f'{100*x:.1f}%'
    lines=['# 실제 모델 비교 · 판단', '', '우선 방향은 **메타데이터 보강 + 다국어 E5 후보 보완 + 기존 2차 최종 검증 유지**다.', '', '## 동일한 홈페이지 18질문', '', '| 방법 | 정밀도 | 재현율 | F1 | 정확도 |','|---|---:|---:|---:|---:|', '| 2차 저장 출력 · 고정 설정 rep=1 | '+' | '.join(pct(a_metrics[k]) for k in ['precision','recall','f1','accuracy'])+' |','| Magneto + 다국어 E5 + 메타데이터 | '+' | '.join(pct(b_metrics[k]) for k in ['precision','recall','f1','accuracy'])+' |','',f"F1 차이는 {(b_metrics['f1']-a_metrics['f1'])*100:.2f}%p이며 정밀도는 {(b_metrics['precision']-a_metrics['precision'])*100:.2f}%p다. 문항 단위 부트스트랩의 F1 차이 95% 구간은 {quantile(.025)*100:.2f}~{quantile(.975)*100:.2f}%p다. 같은 개발 문항의 참고 분석이고 새로운 원천에 대한 통계 검증이 아니다.",'','## 달라진 두 판단','']
    for r in changes:lines.append('- '+r['column']+': 정답 '+(' / '.join(r['gold']) or '제외')+', 기존 '+(' / '.join(r['baseline']) or '제외')+' → E5 '+(' / '.join(r['e5']) or '제외'))
    lines+=['','## 전체 93질문에서의 방향','', '- 공식 Magneto MPNet은 컬럼명만 쓸 때 F1 43.2%, 설명·자료형을 추가하면 65.2%였다. 먼저 메타데이터를 제대로 활용할 필요가 있다.','- 같은 메타데이터 조건의 다국어 E5는 F1 65.9%로 MPNet 65.2%와 차이가 작았다. CPU 매핑 단계 시간은 E5 약 3.1초, MPNet 약 17.2초였다. 다운로드·로드·별도 공통입력 벡터 비교는 제외한 관측 시간이다.','- 한국어 SRoBERTa의 Magneto 메타데이터 조건 F1은 40.9%였다. 한국어 문장 유사도 모델이라는 이유만으로 스키마 매핑 모델로 선택할 근거는 없다.','- E5가 COMPLAINT_TP의 누락을 보완했지만 PRODUCT_GB를 PRD_ID로 잘못 제안했다. 상담 분류·상품 구분·식별자 간 코드/업무관계 검증과 HITL을 유지해야 한다.','- 기존 2차 전체 93질문의 최종 출력은 없고, 새 Azure LLM 추론도 하지 않았다. 93질문에서의 로컬 점수를 기존 2차 전체 성능과 직접 비교하지 않는다.','','실제 세 모델 추론, 공식 Magneto 기본 비LLM 모드, 실패·성공 로그와 모델 리비전·해시를 비공개 저장소에 보존했다.']
    markdown='\n'.join(lines)+'\n';(out/'neural_findings.md').write_text(markdown,encoding='utf-8');(HERE/'MODEL_FINDINGS.md').write_text(markdown,encoding='utf-8')
    report=out/'neural_model_report.html';content=report.read_text(encoding='utf-8')
    section='<section class="card" id="model-findings"><h2>이번 비교에서 정한 고도화 방향</h2><p><b>메타데이터 보강 + 다국어 E5 후보 보완 + 기존 2차 최종 검증 유지</b>를 우선합니다.</p><p>같은 18문항에서 기존 고정 설정 저장 출력의 F1은 '+pct(a_metrics['f1'])+', E5 방식은 '+pct(b_metrics['f1'])+'였습니다. 정밀도는 '+pct(a_metrics['precision'])+'에서 '+pct(b_metrics['precision'])+'로 낮아졌고, 정확도는 둘 다 '+pct(a_metrics['accuracy'])+'입니다.</p><p>E5는 COMPLAINT_TP의 매핑을 추가로 맞혔지만, 제외해야 할 PRODUCT_GB를 PRD_ID로 제안했습니다. 전면 교체보다 후보 보완으로 검증할 근거입니다.</p><p>같은 개발 문항을 재표본한 F1 차이 95% 참고 구간은 '+f'{quantile(.025)*100:.1f}~{quantile(.975)*100:.1f}%p'+'이며 독립적인 개선 입증이 아닙니다. <a href="neural_findings.md">상세 판단</a> · <a href="neural_findings.json">계산·입력 해시</a></p></section>'
    content=re.sub(r'<section class="card" id="model-findings">.*?</section>','',content,flags=re.S)
    content=content.replace('<section class="card"><h2>1.',section+'<section class="card"><h2>1.',1)
    report.write_text(content,encoding='utf-8');print(json.dumps(findings,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
