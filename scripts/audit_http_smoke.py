"""仅访问本机修复服务，验证公开资源、真实任务、超时与取消。"""
import json
import time
import urllib.request
import urllib.error

BASE='http://127.0.0.1:18080'


def request(path,payload=None):
    req=urllib.request.Request(BASE+path,data=None if payload is None else json.dumps(payload).encode(),
                               headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=10) as response:
            body=response.read();status=response.status
    except urllib.error.HTTPError as error:
        status=error.code;body=error.read()
    try:body=json.loads(body)
    except (ValueError,UnicodeDecodeError):body=None
    return status,body


def wait(key):
    for _ in range(150):
        status,job=request('/api/v1/loading/'+key+'/status')
        if job['status'] in {'COMPLETED','FAILED','CANCELLED','TIMED_OUT'}:return job
        time.sleep(.05)
    raise AssertionError('任务没有按时结束')


if __name__=='__main__':
    result={}
    for path in ['/','.env','/.env','/.git/config','/backend/server.py','/frontend/src/inputSafety.js']:
        if not path.startswith('/'):continue
        status,_=request(path);result[path]=status
        assert status == (200 if path in ['/','/frontend/src/inputSafety.js'] else 404)
    status,_=request('/api/v1/pack',{})
    assert status==410
    result['legacy_disabled']=status
    payload={'container':{'L':2.1,'W':1.1,'H':1.1},
             'manifest':[{'sku':'A','w':1,'d':1,'h':1,'weight':10,'quantity':2}],
             'timeBudgetSec':5,'mode':'FAST'}
    status,job=request('/api/v1/loading/jobs',payload)
    assert status==202
    key=job['job_id'];finished=wait(key)
    assert finished['status']=='COMPLETED',finished
    status,layout=request('/api/v1/loading/'+key)
    assert status==200 and layout['layout_status']=='VALID' and len(layout['cargo'])==2
    assert layout['sequence_status']=='FEASIBLE',layout['sequence']
    result['normal']={'job_status':finished['status'],'layout':layout['layout_status'],'sequence':layout['sequence_status']}
    status,job=request('/api/v1/loading/jobs',{**payload,'timeBudgetSec':.001})
    result['timeout']=wait(job['job_id'])['status'];assert result['timeout']=='TIMED_OUT'
    status,job=request('/api/v1/loading/jobs',payload)
    request('/api/v1/loading/'+job['job_id']+'/cancel',{})
    result['cancel']=wait(job['job_id'])['status'];assert result['cancel']=='CANCELLED'
    print(json.dumps(result,ensure_ascii=False,indent=2))
