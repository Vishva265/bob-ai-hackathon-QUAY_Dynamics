"""Read a persisted publication and verify all three exports over live HTTP."""
import argparse
import csv
import io
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--output',type=Path,default=Path('artifacts/plans/api-smoke-sqlite.json'))
    args=parser.parse_args()
    def get(path):
        with urlopen(args.base_url+path,timeout=60) as response:
            return response.read(),{k.lower():v for k,v in response.headers.items()}
    ready=json.loads(get('/ready')[0])
    assert ready['migration_revision']=='0010',ready
    plan=json.loads(get('/plans/72-hour')[0])
    path='/plans/'+plan['id']
    assert json.loads(get(path)[0])==plan and len(plan['shifts'])==9
    content,headers=get(path+'/export?format=json')
    assert json.loads(content)==plan and 'attachment;' in headers['content-disposition']
    content,_=get(path+'/export?format=csv')
    rows=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
    assert sum(r['row_type']=='SHIFT_SUMMARY' for r in rows)==9
    content,_=get(path+'/export?format=html')
    assert b'@media print' in content and plan['id'].encode() in content
    assert isinstance(json.loads(get(path+'/history')[0])['items'],list)
    try:
        get(path+'/export?format=pdf')
        raise AssertionError('Unsupported format accepted')
    except HTTPError as error:
        assert error.code==422
    result=dict(validation_passed=True,checks=8,ready=ready,plan_id=plan['id'],
        status=plan['status'],shifts=9,csv_rows=len(rows),formats=['json','csv','html'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
