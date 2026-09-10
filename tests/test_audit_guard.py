"""给门禁注入坏报告，验证门禁本身不会虚假通过。"""
import copy
import pytest
from tests.regression_guard import assert_reports


def report():
    return {'is_valid':True,'violations':0,'overlap_pair_count':0,'utilization':80,
            'sku_fulfillment':{'starved_skus':[], 'priority_inversion':False,'rigid_completion_pct':100}}


@pytest.mark.parametrize('field,value',[('is_valid',False),('violations',1),('overlap_pair_count',1)])
def test_reject_invalid(field,value):
    bad=report();bad[field]=value
    with pytest.raises(AssertionError):
        assert_reports({'A':bad},{'A':report()})


@pytest.mark.parametrize('field,value',[('starved_skus',['X']),('priority_inversion',True)])
def test_reject_bad_fulfillment(field,value):
    bad=report();bad['sku_fulfillment'][field]=value
    with pytest.raises(AssertionError):
        assert_reports({'A':bad},{'A':report()})


def test_clean_report_passes():
    assert_reports({'A':report()},{'A':report()})


def test_nested_benchmark_report():
    assert_reports({'suite_name':'suite','results':{'A':report()}},{'results':{'A':report()}})
