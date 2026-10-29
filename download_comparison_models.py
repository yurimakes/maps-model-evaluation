"""Download public pretrained weights, pin their revisions and hash each file."""
import argparse,hashlib,json,time
from pathlib import Path
import requests

MODEL_IDS={'mpnet':'sentence-transformers/all-mpnet-base-v2','e5_multilingual':'intfloat/multilingual-e5-small','ko_sroberta':'jhgan/ko-sroberta-multitask'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();root=Path(a.root);root.mkdir(parents=True,exist_ok=True)
    registry={};registry_path=root/'registry.json'
    if registry_path.exists():registry=json.loads(registry_path.read_text(encoding='utf-8'))
    for key,repo in MODEL_IDS.items():
        start=time.perf_counter();meta=requests.get('https://huggingface.co/api/models/'+repo,timeout=45);meta.raise_for_status();meta=meta.json()
        revision=registry.get(key,{}).get('revision') or meta['sha'];destination=root/key
        file_meta=requests.get('https://huggingface.co/api/models/'+repo+'/revision/'+revision,timeout=45);file_meta.raise_for_status();file_meta=file_meta.json()
        names=[f['rfilename'] for f in file_meta['siblings']]
        weight='model.safetensors' if 'model.safetensors' in names else 'pytorch_model.bin'
        if weight not in names:raise RuntimeError('No supported root model weights in '+repo)
        keep=[n for n in names if n==weight or (not n.startswith(('onnx/','openvino/')) and (n.endswith(('.json','.txt','.model')) or n in ['sentencepiece.bpe.model','README.md','LICENSE']))]
        files=[];print('DOWNLOAD_MODEL',key,repo,revision,flush=True)
        for name in keep:
            rel=Path(name)
            if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe model filename')
            path=destination/rel;path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():
                response=requests.get('https://huggingface.co/'+repo+'/resolve/'+revision+'/'+name,stream=True,timeout=(30,90));response.raise_for_status()
                temporary=path.with_name(path.name+'.partial')
                with temporary.open('wb') as f:
                    for chunk in response.iter_content(1024*1024):
                        if chunk:f.write(chunk)
                temporary.replace(path)
                print('DOWNLOADED',key,name,path.stat().st_size,flush=True)
            h=hashlib.sha256()
            with path.open('rb') as f:
                for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
            files.append({'path':name,'bytes':path.stat().st_size,'sha256':h.hexdigest()})
        registry[key]={'repository':repo,'revision':revision,'path':str(destination.resolve()),'license':file_meta.get('cardData',{}).get('license'),'download_seconds':time.perf_counter()-start,'weight_file':weight,'files':files}
        registry_path.write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8')
        print('MODEL_READY',key,flush=True)
    print('REGISTRY',registry_path,flush=True)

if __name__=='__main__':main()
