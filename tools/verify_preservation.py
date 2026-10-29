"""Read-only verification of imported assets, original checkouts and Git history archives."""
import hashlib, json, os, subprocess
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PRES=ROOT.parent/'maps-integration-preservation-20261029'
ENV=dict(os.environ,GIT_OPTIONAL_LOCKS='0')

def git(repo,*args):
    p=subprocess.run(['git','-c',f'safe.directory={repo.as_posix()}','-C',str(repo),*args],
        check=True,env=ENV,capture_output=True)
    return p.stdout.decode('utf-8',errors='replace').strip()

def verify():
    manifest=json.loads((ROOT/'provenance/import-manifest.json').read_text(encoding='utf-8'))
    for r in manifest:
        b=(ROOT/r['new_path']).read_bytes()
        assert hashlib.sha256(b).hexdigest()==r['sha256'],r['new_path']
        assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==r['git_blob'],r['new_path']
    states=json.loads((ROOT/'provenance/repository-state.json').read_text(encoding='utf-8'))
    original=[]
    for name,s in states.items():
        local=Path(s['local_path']);mirror=PRES/(name+'.git')
        assert git(local,'rev-parse','HEAD')==s['local_head']
        assert git(local,'branch','--show-current')==s['local_branch']
        status=git(local,'status','--porcelain=v1','--untracked-files=all')
        assert status==s['local_status_porcelain']
        assert git(ROOT,'rev-parse','refs/archive/'+name+'/main')==s['remote_head']
        git(mirror,'bundle','verify',str(PRES/(name+'.bundle')))
        git(mirror,'fsck','--full')
        assert hashlib.sha256((PRES/(name+'.bundle')).read_bytes()).hexdigest()==s['bundle_sha256']
        original.append(dict(repository=name,head=s['local_head'],branch=s['local_branch'],status_porcelain=status,bundle_verified=True))
    archive_refs=['refs/archive/'+n+'/main' for n in states]
    assert git(ROOT,'rev-list',*archive_refs,'--count')=='10'
    git(ROOT,'merge-base','--is-ancestor',states['maps-local-model-benchmark']['remote_head'],'HEAD')
    new_commits=int(git(ROOT,'rev-list','HEAD','--not',*archive_refs,'--count'))
    git(ROOT,'diff','--check')
    git(ROOT,'fsck','--full')
    return dict(checked_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        original_files_git_blob_and_sha256_verified=len(manifest),original_checkouts=original,
        reachable_original_commits=10,head_unchanged=git(ROOT,'rev-parse','HEAD')==states['maps-local-model-benchmark']['remote_head'],
        original_history_rewritten=False,new_commits=new_commits,
        remote_state_note='This verifier checks local preservation only; it does not infer push or PR status.',
        remote_heads_last_observed_via_github_connector={n:s['remote_head'] for n,s in states.items()},
        status_summary='Current Git status follows. Historical asset relocations are documented in import-manifest.json.',
        status_porcelain=git(ROOT,'-c','core.quotepath=false','status','--porcelain=v1','--untracked-files=all').splitlines())

if __name__=='__main__':
    result=verify()
    (ROOT/'provenance/final-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='status_porcelain'},ensure_ascii=False,indent=2))
