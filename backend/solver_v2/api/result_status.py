"""由求解报告生成权威结果状态；供 API 适配器使用，缺失验证时拒绝肯定结论。"""


def result_status(solution):
    report = getattr(solution, 'validation_result', None)
    valid = report is not None and report.is_valid is True
    violations = [v.to_dict() for v in report.violations] if report is not None else []
    return {
        'contract_version': 'audit-repair-1',
        'solution_status': getattr(solution, 'status', 'NOT_EVALUATED'),
        'fulfillment_status': 'COMPLETE' if getattr(solution, 'unplaced_count', 1) == 0 else 'PARTIAL',
        'layout_status': ('VALID' if valid else 'INVALID') if report is not None else 'NOT_EVALUATED',
        'validation': {'is_valid': valid, 'violations': violations,
                       'rejection_reasons': list(report.rejection_reasons) if report is not None else ['NOT_EVALUATED']},
        'sequence_status': 'NOT_EVALUATED',
        'executable': False,
    }
