"""Re-score saved predictions. No inference, credentials, source writes or Git mutations."""
import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .contract import cohort, comparison_key, input_fingerprint, query_key, validate
from .metrics import summarize

ROOT = Path(__file__).resolve().parents[1]

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def targets(text):
    return [s.strip() for s in text.split(';') if s.strip()]

def load_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def run(out):
    registry = read_json(ROOT / 'configs/suites.json')
    metrics, normalized, provenance, parity = [], [], [], []
    for suite in registry['suites']:
        snapshot_path = ROOT / suite['snapshot']
        snapshot = read_json(snapshot_path)
        expected, allowed = cohort(snapshot, suite['scope'])
        if len(expected) != suite['expected_questions']:
            raise ValueError('Unexpected cohort size: ' + suite['id'])
        key = comparison_key(expected, allowed, suite['protocol'],input_fingerprint(snapshot))
        for source in suite['prediction_sources']:
            path = ROOT / source['path']
            rows = load_csv(path)
            if 'expected_file_methods' in source and {r[source['method_field']] for r in rows} != set(source['expected_file_methods']):
                raise ValueError('Prediction file methods changed; review registry')
            groups = defaultdict(list)
            for row in rows:
                method = row[source['method_field']]
                if 'models' in source and method not in source['models']:
                    continue
                if suite['scope']=='homepage' and row['system']!='HOMEPAGE':
                    continue
                if source.get('fold_mode')=='historical':
                    system,table,column=row['id'].split('|')
                    if row['system']!=system or row['column']!=column or row['table'] not in ('',table):
                        raise ValueError('Historical identity disagrees with canonical source key')
                    row={**row,'table':table,'fold':'historical'}
                groups[method].append(dict(query_key=query_key(row), system=row['system'], fold=row['fold'],
                    gold=targets(row['gold']), predicted=targets(row['predicted']), ranked=targets(row[source['rank_field']])))
            historical = {r[source['summary_method_field']]: r for r in load_csv(ROOT / source['summary'])}
            if 'models' in source:
                historical={k:v for k,v in historical.items() if k in source['models']}
            if set(groups) != set(historical):
                raise ValueError('Prediction/summary method sets differ')
            provenance.append(dict(suite=suite['id'], origin=source['origin'], prediction_path=source['path'],
                prediction_sha256=file_sha(path), snapshot_sha256=file_sha(snapshot_path),
                summary_sha256=file_sha(ROOT/source['summary']), protocol=suite['protocol'], comparison_key=key))
            for method, records in sorted(groups.items()):
                validate(records, expected, allowed,source.get('fold_mode','source'))
                m = summarize(records)
                for canonical, old in source['parity_fields'].items():
                    if abs(m[canonical] - float(historical[method][old])) > 1e-12:
                        raise ValueError(f'Historical metric mismatch: {source["origin"]}/{method}/{canonical}')
                parity.append(dict(suite=suite['id'], origin=source['origin'], method=method, fields_checked=list(source['parity_fields']), passed=True))
                metrics.append(dict(suite=suite['id'], origin=source['origin'], method=method, comparison_key=key, **m))
                normalized.extend(dict(suite=suite['id'], origin=source['origin'], method=method, **r) for r in records)
    # Construct all results first. Refuse overwriting any previous run or imported artifact.
    out.mkdir(parents=True, exist_ok=False)
    with (out/'metrics.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(metrics[0]));w.writeheader();w.writerows(metrics)
    for name,value in [('normalized_predictions.json',normalized),('provenance.json',provenance),('historical_parity.json',parity)]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    manifest=dict(created_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        action='offline rescoring of preserved predictions; models and APIs not executed',
        registry_sha256=file_sha(ROOT/'configs/suites.json'),
        evaluator_sha256={str(p.relative_to(ROOT)):file_sha(p) for p in sorted((ROOT/'evaluation').glob('*.py'))},
        method_count=len(metrics),prediction_count=len(normalized),historical_parity_passed=len(parity),
        comparability='Compare only equal comparison_key; protocol, gold, query scope and candidates must match.',
        limits=['Does not independently prove training/threshold isolation; legacy leakage tests cover implementations.',
          'Replayed RAG, cached retrieval diagnostics and scripted tests are indexed separately; no new end-to-end model accuracy claim.'])
    (out/'run.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(out),**{k:manifest[k] for k in ['method_count','prediction_count','historical_parity_passed']}),indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', help='New folder under results/common; must not exist')
    a=p.parse_args()
    name=a.out or 'results/common/'+datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%dT%H%M%S%z')
    out=(ROOT/name).resolve()
    if not out.is_relative_to((ROOT/'results/common').resolve()) or out==(ROOT/'results/common').resolve():
        p.error('Output must be a new subdirectory of results/common')
    run(out)

if __name__=='__main__':main()
