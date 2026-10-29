"""Save immutable test/run logs; optionally commit and push the complete snapshot."""
import argparse,hashlib,json,shutil,subprocess,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--label',default='local');p.add_argument('--commit',action='store_true');p.add_argument('--push',action='store_true');p.add_argument('--model-ab-api',action='store_true');p.add_argument('--model-ab-questions',type=int,default=5);p.add_argument('--model-ab-max-requests',type=int,default=24);p.add_argument('--local-models',action='store_true');p.add_argument('--analyze-models',action='store_true');a=p.parse_args()
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',a.label):p.error('Use letters, numbers, underscores or hyphens in label')
    stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%dT%H%M%S%z');relative='experiments/'+stamp+'-'+a.label
    out=HERE/relative;out.mkdir(parents=True,exist_ok=False)
    logs=[]
    steps=[]
    if (HERE/'build_phase2_upgrade.py').exists():steps.append(('phase2_build',[sys.executable,'-X','utf8','build_phase2_upgrade.py']))
    steps.extend([('tests',[sys.executable,'-X','utf8','-m','unittest','discover','-v','-p','test_*.py']),('benchmark',[sys.executable,'-X','utf8','run_experiments.py','--out',relative]),('phase2_replay',[sys.executable,'-X','utf8','upgrade_adapter.py','--out',relative])])
    if (HERE/'run_phase2_rag.py').exists():steps.append(('phase2_actual_cached_retrieval',[sys.executable,'-X','utf8','run_phase2_rag.py','--out',relative]))
    if (HERE/'run_phase2_model_ab.py').exists():
        command=[sys.executable,'-X','utf8','run_phase2_model_ab.py','--out',relative,'--max-questions',str(a.model_ab_questions),'--max-requests',str(a.model_ab_max_requests)]
        if a.model_ab_api:command.append('--execute-api')
        steps.append(('phase2_model_ab_paid' if a.model_ab_api else 'phase2_model_ab_dry_run',command))
    if a.local_models:
        model_runtime=json.loads((HERE/'model_runtime.local.json').read_text(encoding='utf-8'))['python']
        steps.append(('actual_neural_model_comparison',[model_runtime,'-X','utf8','run_neural_model_comparison.py','--out',relative]))
    if a.local_models or a.analyze_models:
        analysis_input=relative if a.local_models else 'results/latest'
        steps.append(('neural_model_findings',[sys.executable,'-X','utf8','analyze_neural_results.py','--input',analysis_input,'--out',relative]))
    for name,command in steps:
        import os
        environment=dict(os.environ);environment['PYTHONHASHSEED']='42'
        with (out/(name+'.log')).open('w',encoding='utf-8') as log_file:
            proc=subprocess.run(command,cwd=HERE,stdout=log_file,stderr=subprocess.STDOUT,env=environment)
        logs.append({'name':name,'command':command,'exit_code':proc.returncode});print(name,'exit',proc.returncode,flush=True)
        if proc.returncode:break
    source_files=list(HERE.glob('*.py'))+[HERE/'maps_policy.json',HERE/'requirements.txt']
    for folder in ['phase2_original','phase2_upgrade','third_party/magneto_full']:source_files.extend((HERE/folder).rglob('*.py'))
    sources={str(path.relative_to(HERE)):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    (out/'execution.json').write_text(json.dumps({'timestamp':stamp,'steps':logs,'source_sha256':sources,'parent_commit':subprocess.run(['git','rev-parse','HEAD'],cwd=HERE,capture_output=True,text=True).stdout.strip()},ensure_ascii=False,indent=2),encoding='utf-8')
    if all(x['exit_code']==0 for x in logs):
        latest=HERE/'results'/'latest';latest.mkdir(parents=True,exist_ok=True)
        for path in out.iterdir():
            if path.is_file():shutil.copy2(path,latest/path.name)
    if a.commit or a.push:
        subprocess.run(['git','add','--all','--','.'],cwd=HERE,check=True)
        subprocess.run(['git','commit','-m','snapshot: '+a.label+' '+stamp],cwd=HERE,check=True)
    if a.push:
        remote=subprocess.check_output(['git','remote','get-url','origin'],cwd=HERE,text=True).strip()
        if remote!='https://github.com/yurimakes/maps-local-model-benchmark.git':raise RuntimeError('Unexpected remote; refusing snapshot upload')
        info=json.loads(subprocess.check_output(['gh','repo','view','yurimakes/maps-local-model-benchmark','--json','visibility'],cwd=HERE,text=True))
        if info['visibility']!='PRIVATE':raise RuntimeError('Remote must be private before pushing')
        subprocess.run(['git','-c','credential.helper=','-c','credential.helper=!gh auth git-credential','push','origin','HEAD'],cwd=HERE,check=True)
    if any(x['exit_code'] for x in logs):sys.exit(1)
    print('SNAPSHOT',out)

if __name__=='__main__':main()
