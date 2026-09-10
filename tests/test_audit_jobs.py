"""隔离进程的硬超时、显式取消、队列上限与结果回收。"""
import time
import pytest
from backend.api.jobs import JobManager, TERMINAL


def slow_worker(payload):
    time.sleep(3)
    return {'loading':{},'legacy':{}}


def quick_worker(payload):
    return {'loading':{'solution_status':'SUCCESS'},'legacy':{}}


def wait(manager,key):
    end=time.monotonic()+5
    while time.monotonic()<end:
        job=manager.get(key)
        if job['status'] in TERMINAL:return job
        time.sleep(.02)
    raise AssertionError('进程未按时结束')


def test_hard_timeout():
    manager=JobManager(worker=slow_worker)
    try:
        key=manager.submit({'timeBudgetSec':.1})
        assert wait(manager,key)['status']=='TIMED_OUT'
    finally:manager.close()


def test_cancel_and_capacity():
    manager=JobManager(worker=slow_worker,capacity=1)
    try:
        key=manager.submit({'timeBudgetSec':5})
        with pytest.raises(OverflowError):manager.submit({})
        assert manager.cancel(key)
        assert wait(manager,key)['status']=='CANCELLED'
    finally:manager.close()


def test_complete_and_expire():
    manager=JobManager(worker=quick_worker,ttl=.1)
    try:
        key=manager.submit({'timeBudgetSec':3})
        assert wait(manager,key)['status']=='COMPLETED'
        time.sleep(.15)
        assert manager.get(key) is None
    finally:manager.close()
