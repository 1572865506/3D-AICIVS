"""有界进程任务执行：提交 JSON，返回可轮询/取消的任务；终态记录定时回收。

工作线程仅监督隔离子进程，硬超时与取消会终止子进程。输出在子进程内完成验证。
"""
import copy
import multiprocessing as mp
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from backend.solver_v2.solver.options import SolverOptions

TERMINAL = {'COMPLETED','FAILED','CANCELLED','TIMED_OUT'}


def solve_payload(payload):
    from backend.solver_v2.api.adapter import InputAdapter, OutputAdapter
    from backend.solver_v2.solver.unified_solver import UnifiedSolver
    from backend.api.service import LoadingAPIService
    container=InputAdapter.parse_container(payload.get('container') or payload.get('containerSpec',{}))
    cargo=InputAdapter.parse_cargo_list(payload.get('manifest') or payload.get('cargo') or payload.get('sku',[]))
    options=SolverOptions.parse(mode=payload.get('mode','BALANCED'), seed=payload.get('randomSeed',42),
                                time_budget=payload.get('timeBudgetSec',20.0))
    start=time.monotonic()
    solution=UnifiedSolver(container).solve(cargo,mode=options.mode,seed=options.seed,
                                            time_budget=options.time_budget*.8)
    loading=LoadingAPIService().register_solver_output(payload['_job_id'],solution,container,cargo)
    legacy=OutputAdapter.to_legacy_response(solution,container,cargo,elapsed_ms=(time.monotonic()-start)*1000)
    legacy.update(solutionId=payload['_job_id'],loadingJobId=payload['_job_id'],
                  sequenceFeasible=loading['sequence']['feasible'])
    return {'loading':loading,'legacy':legacy}


def _worker(connection, payload, worker):
    try:
        connection.send(('ok',worker(payload)))
    except Exception as exc:
        from backend.api.error_response import classify_api_exception
        status,error=classify_api_exception(exc)
        if status >= 500:
            error={'error':'内部计算失败','code':'INTERNAL_ERROR'}
        connection.send(('error',{'http_status':status,**error}))
    finally:
        connection.close()


class JobManager:
    def __init__(self, workers=2, capacity=8, max_records=128, ttl=600, worker=solve_payload):
        self.lock=threading.RLock()
        self.records={}
        self.pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='packing-job')
        self.capacity=capacity
        self.max_records=max_records
        self.ttl=ttl
        self.worker=worker
        self.context=mp.get_context('spawn')

    def _prune(self):
        now=time.monotonic()
        for key,record in list(self.records.items()):
            if record['status'] in TERMINAL and now-record['updated'] >= self.ttl:
                del self.records[key]

    def submit(self,payload):
        options=SolverOptions.parse(mode=payload.get('mode','BALANCED'),seed=payload.get('randomSeed',42),
                                    time_budget=payload.get('timeBudgetSec',20.0))
        manifest=payload.get('manifest') or payload.get('cargo') or payload.get('sku',[])
        if not isinstance(manifest,list) or len(manifest)>500:
            raise ValueError('货单必须为数组且不能超过 500 种 SKU')
        total=0
        for item in manifest:
            source=item.get('source',item)
            total+=int(source.get('quantity',source.get('qty',1)))
        if total>100000:
            raise ValueError('货单不能超过 100000 箱')
        with self.lock:
            self._prune()
            if sum(r['status'] not in TERMINAL for r in self.records.values()) >= self.capacity:
                raise OverflowError('任务队列已满')
            if len(self.records) >= self.max_records:
                completed=[k for k,r in self.records.items() if r['status'] in TERMINAL]
                if not completed:
                    raise OverflowError('任务记录已满')
                del self.records[completed[0]]
            key=uuid.uuid4().hex
            data=copy.deepcopy(payload);data['_job_id']=key
            self.records[key]={'job_id':key,'status':'QUEUED','updated':time.monotonic(),
                               'cancel':threading.Event(),'result':None,'error':None}
            self.pool.submit(self._run,key,data,options.time_budget)
            return key

    def _run(self,key,payload,budget):
        with self.lock:
            record=self.records[key]
            if record['cancel'].is_set():
                record.update(status='CANCELLED',updated=time.monotonic());return
            record.update(status='RUNNING',updated=time.monotonic())
        receive,send=self.context.Pipe(duplex=False)
        process=self.context.Process(target=_worker,args=(send,payload,self.worker),daemon=True)
        status='FAILED';result=None;error=None
        try:
            deadline=time.monotonic()+budget
            process.start();send.close()
            while True:
                if record['cancel'].is_set():
                    status='CANCELLED';break
                if time.monotonic() >= deadline:
                    status='TIMED_OUT';break
                if receive.poll(.02):
                    kind,value=receive.recv()
                    if kind=='ok':
                        result=value;status='COMPLETED'
                        if value.get('loading',{}).get('solution_status') == 'TIMED_OUT':
                            status='TIMED_OUT'
                    else:
                        error=value
                    break
                if not process.is_alive():
                    error={'error':'工作进程提前退出'};break
        except Exception:
            error={'error':'任务执行失败'}
        finally:
            if process.pid is not None:
                if process.is_alive():process.terminate()
                process.join(timeout=1)
                if process.is_alive():process.kill();process.join(timeout=1)
            receive.close();send.close()
            with self.lock:
                # 取消与完成同时发生时，以已接受的取消请求为准。
                if record['cancel'].is_set():status='CANCELLED';result=None
                record.update(status=status,result=result,error=error,updated=time.monotonic())

    def get(self,key):
        with self.lock:
            self._prune()
            r=self.records.get(key)
            if r is None:return None
            return {k:copy.deepcopy(v) for k,v in r.items() if k not in {'cancel','updated'}}

    def cancel(self,key):
        with self.lock:
            r=self.records.get(key)
            if r is None:return False
            if r['status'] not in TERMINAL:r['cancel'].set()
            return True

    def close(self):
        with self.lock:
            for r in self.records.values():r['cancel'].set()
        self.pool.shutdown(wait=True)
