"""Run the pinned synthetic ko-pii experiment into a new repository results folder."""
from pathlib import Path
import argparse, hashlib, json, sys

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path.insert(0,str(HERE/'runtime'))
import ko_pii
from probe import run as run_text
from structured import run as run_structured

def scores(cases):
    totals=dict(tp=0,fp=0,fn=0,gold=0,literal_remaining=0,uncovered=0)
    for case in cases:
        gold={(s['label'],s['start'],s['end']) for s in case['gold']}
        pred={(s['label'],s['start'],s['end']) for s in case['predictions']}
        for key,value in [('tp',len(gold&pred)),('fp',len(pred-gold)),('fn',len(gold-pred)),
          ('gold',len(gold)),('literal_remaining',len(case['literal_remaining_labels'])),('uncovered',len(case['uncovered_labels']))]:
            totals[key]+=value
    return totals

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,help='New folder below repository results/ko-pii; refuses overwrites')
    args=parser.parse_args()
    output=(REPO/args.out).resolve()
    allowed=(REPO/'results/ko-pii').resolve()
    if output==allowed or not output.is_relative_to(allowed):
        parser.error('Output must be a new subdirectory of results/ko-pii')
    if ko_pii.__version__!='1.22.17':parser.error('This protocol requires ko-pii==1.22.17')
    output.mkdir(parents=True,exist_ok=False)
    text=run_text(output,HERE/'fixtures/text_cases.jsonl')
    structured=run_structured(output,HERE/'fixtures')
    summary={
      'all_text':{mode:scores(run['cases']) for mode,run in text['runs'].items()},
      'dialogue':{mode:scores([c for c in run['cases'] if c['group']=='dialogue']) for mode,run in text['runs'].items()},
      'structured':{k:structured[k] for k in ['csv_auto','csv_explicit','json_auto','json_explicit']}}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    provenance={
      'protocol_id':'ko-pii-synthetic-v1', 'action':'actual local rule-library execution on synthetic fixtures',
      'synthetic_only':True,'raw_maps_data_used':False,'model_or_api_calls':False,
      'code_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'run.py',HERE/'probe.py',HERE/'structured.py']},
      'fixture_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((HERE/'fixtures').iterdir())},
      'limits':'No independent holdout, no MAPS production accuracy or pipeline integration claim. Partial masking and literal residual counts differ.'}
    (output/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':output.relative_to(REPO).as_posix(),
      'text_strict':summary['all_text']['STRICT'],
      'structured_remaining_cells':{name:value['original_value_remaining_cells'] for name,value in summary['structured'].items()}},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
