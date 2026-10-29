"""Verify preserved source bytes and run local contract tests without altering legacy results."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,help='Existing compatible Python 3.13 package folder for legacy tests')
    a=parser.parse_args()
    out=ROOT/'results/validation'/datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%dT%H%M%S%z')
    out.mkdir(parents=True,exist_ok=False)
    imported=json.loads((ROOT/'provenance/import-manifest.json').read_text(encoding='utf-8'))
    for r in imported:
        p=ROOT/r['new_path']
        if hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:
            raise ValueError('Imported asset changed: '+r['new_path'])
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONHASHSEED='42',PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    if a.packages:env['PYTHONPATH']=str(a.packages.resolve())
    checks=[]
    def run(name,args,cwd):
        with (out/(name+'.log')).open('w',encoding='utf-8') as f:
            proc=subprocess.run([sys.executable,'-X','utf8',*args],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
        text=(out/(name+'.log')).read_text(encoding='utf-8',errors='replace')
        counts=re.findall(r'Ran (\d+) tests?',text)
        checks.append(dict(name=name,exit_code=proc.returncode,tests=int(counts[-1]) if counts else None))
        print(name,proc.returncode,flush=True)
    run('common-contract',['-m','unittest','discover','-s','tests','-v'],ROOT)
    if a.packages:
        run('benchmark-contract',['-m','unittest','discover','-p','test_*.py','-v'],ROOT/'experiments/local-model-benchmark')
        run('legacy-local-contract',['test_evaluation.py'],ROOT/'experiments/maps-local-lab')
        # Graph verifier writes verification.json: run on disposable copies, retain its output as new evidence.
        work=Path(tempfile.mkdtemp(prefix='maps_validation_',dir=out))
        for folder in ['maps-graph-lab','maps-local-lab']:
            shutil.copytree(ROOT/'experiments'/folder,work/folder,ignore=shutil.ignore_patterns('__pycache__','.packages'))
        run('graph-isolation-and-integrity',['verify.py'],work/'maps-graph-lab')
        if (work/'maps-graph-lab/results/verification.json').exists():
            shutil.copy2(work/'maps-graph-lab/results/verification.json',out/'graph-verification.json')
        # Keep disposable verification copies in this new run folder for reproducibility.
    else:
        checks.append(dict(name='legacy-runtime-tests',status='not_run',reason='Supply --packages for the separate legacy dependencies'))
    for r in imported:
        assert hashlib.sha256((ROOT/r['new_path']).read_bytes()).hexdigest()==r['sha256'],r['new_path']
    result=dict(imported_files_verified=len(imported),legacy_assets_unchanged=True,checks=checks,
        paid_api_calls=0,model_inference_executed=False,passed=all(c.get('exit_code',0)==0 for c in checks))
    (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(out),**result),indent=2))
    if not result['passed']:sys.exit(1)

if __name__=='__main__':main()
