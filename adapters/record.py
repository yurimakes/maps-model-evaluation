"""Record and score saved model predictions in a new immutable run directory."""
import argparse
import json
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from evaluation.contract import cohort, comparison_key, input_fingerprint, validate
from evaluation.metrics import summarize

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_predictions(path):
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    rows = read(path)
    if not isinstance(rows, list):
        raise ValueError('Predictions must be a JSON list or JSONL records')
    return rows

def record(experiment_path, prediction_path, output_root=None):
    config = read(experiment_path)
    model = read(ROOT/config['model_config'])
    registry = read(ROOT/'configs/suites.json')
    suite = next(s for s in registry['suites'] if s['id'] == config['suite'])
    if suite['scope'] not in ('all','phase2','homepage'):
        raise ValueError('Unknown evaluation scope')
    snapshot_path = ROOT/suite['snapshot']
    snapshot = read(snapshot_path)
    expected, allowed = cohort(snapshot, suite['scope'])
    if len(expected) != suite['expected_questions']:
        raise ValueError('Cohort size changed')
    output_root = output_root or ROOT/'runs'
    run_id = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%dT%H%M%S%z')+'-'+uuid.uuid4().hex[:10]
    out = output_root/run_id
    out.mkdir(parents=True, exist_ok=False)
    manifest = dict(run_id=run_id, status='running', action='saved_prediction_rescore',
        model=model, experiment=config, model_inference_executed=False, paid_api_calls=0,
        python=sys.version, platform=platform.platform(), snapshot_sha256=sha(snapshot_path),
        predictions_sha256=sha(prediction_path), experiment_sha256=sha(experiment_path),
        model_config_sha256=sha(ROOT/config['model_config']),
        source_sha256={str(p.relative_to(ROOT)):sha(p) for folder in ['evaluation','adapters'] for p in (ROOT/folder).glob('*.py')},
        comparison_key=comparison_key(expected,allowed,suite['protocol'],input_fingerprint(snapshot)),
        protocol=suite['protocol'])
    for field,args in [('parent_commit',['rev-parse','HEAD']),('working_tree_dirty',['status','--porcelain'])]:
        r=subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        manifest[field]=(bool(r.stdout.strip()) if field=='working_tree_dirty' else r.stdout.strip()) if r.returncode==0 else None
    (out/'config.json').write_text(json.dumps(dict(experiment=config,model=model),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        rows=load_predictions(prediction_path)
        if config.get('saved_method'):
            rows=[r for r in rows if r.get('method')==config['saved_method'] and r.get('suite')==config['suite']]
        # Errors never become correct exclusions. Keep failed runs, without success metrics.
        if any(r.get('status','OK')!='OK' for r in rows):
            raise ValueError('ERROR/INVALID predictions require a separate failure report; they cannot be scored as abstentions')
        validate(rows,expected,allowed)
        (out/'predictions.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
        (out/'metrics.json').write_text(json.dumps(summarize(rows),indent=2)+'\n',encoding='utf-8')
        manifest.update(status='completed',questions=len(rows))
        (out/'execution.log').write_text('Saved predictions validated and re-scored. No model inference performed.\n',encoding='utf-8')
    except Exception as error:
        manifest.update(status='failed',error=str(error))
        (out/'execution.log').write_text(type(error).__name__+': '+str(error)+'\n',encoding='utf-8')
        raise
    finally:
        (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--experiment',required=True,type=Path)
    p.add_argument('--predictions',required=True,type=Path)
    a=p.parse_args()
    print(record(a.experiment.resolve(),a.predictions.resolve()))

if __name__=='__main__':main()
