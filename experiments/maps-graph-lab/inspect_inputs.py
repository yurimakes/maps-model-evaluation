import sys, json, zipfile, io, csv
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'maps-local-lab'/'.packages'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'maps-local-lab'))
from prepare_data import csv_rows
d=json.loads((Path(__file__).resolve().parents[1]/'maps-local-lab/data/snapshot.json').read_text(encoding='utf8'))
with zipfile.ZipFile(d['manifest'][0]['path']) as z:
    for n in z.namelist():
        if n.startswith('3.') and n.endswith('.csv'):
            rows=csv_rows(z.read(n))
            print(json.dumps({'file':n,'rows':len(rows),'sample':rows[:1]},ensure_ascii=False))
    for n in z.namelist():
        if n.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(z.read(n))) as zz:
                print('nested',len(zz.namelist()),sum(x.file_size for x in zz.infolist()))
