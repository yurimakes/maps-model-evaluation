"""Save immutable test/run logs; optionally commit and push the complete snapshot."""
import argparse,hashlib,json,shutil,subprocess,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--label',default='local');p.add_argument('--commit',action='store_true');p.add_argument('--push',action='store_true');a=p.parse_args()
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',a.label):p.error('Use letters, numbers, underscores or hyphens in label')
    stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%dT%H%M%S%z');relative='experiments/'+stamp+'-'+a.label
    out=HERE/relative;out.mkdir(parents=True,exist_ok=False)
    logs=[]
    for name,command in [('tests',[sys.executable,'-X','utf8','test_evaluation.py']),('benchmark',[sys.executable,'-X','utf8','run_experiments.py','--out',relative]),('phase2_replay',[sys.executable,'-X','utf8','upgrade_adapter.py','--out',relative])]:
        proc=subprocess.run(command,cwd=HERE,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (out/(name+'.log')).write_text(proc.stdout+'\n'+proc.stderr,encoding='utf-8')
        logs.append({'name':name,'command':command,'exit_code':proc.returncode});print(name,'exit',proc.returncode,flush=True)
        if proc.returncode:break
    sources={str(path.relative_to(HERE)):hashlib.sha256(path.read_bytes()).hexdigest() for path in list(HERE.glob('*.py'))+[HERE/'maps_policy.json',HERE/'requirements.txt']}
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
