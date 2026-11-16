"""Stable HTTP classification for solver failures exposed by the loading API."""
import json

INPUT_CONSTRAINT_ERRORS = {
    "CONFIG_UNSATISFIABLE": (
        "货单约束组合无可行解（例如：仅允许平放且限定顶层，但没有可作为底座的货物）。"
        "请调整该 SKU 的朝向/层数/区域规则后重试。"
    ),
    "NO_VALID_DOOR_WALL": (
        "门墙安全配置未满足。请在 SKU 参数中明确配置至少一种“封柜门”货物，"
        "并检查其尺寸、数量、单件重量及合法方向。"
    ),
    "INPUT_INVALID": (
        "请求参数超出允许范围（时间预算/备选数量/货单规模等）。"
        "请检查请求字段后重试。"
    ),
    "MULTISTOP_UNSATISFIABLE": (
        "多点卸货分区容量不足。请减少该站货量、增加卸货站数或更换更大柜型。"
    ),
    "DOOR_SEAL_CAPACITY_UNSATISFIABLE": (
        "封门件在门端安全台阶/门面倾覆约束下放不下。请减少封门件数量、"
        "增加门区纵深、调整封门件朝向，或显式关闭门端台阶安全策略。"
    ),
}


def classify_api_exception(exc):
    if isinstance(exc, json.JSONDecodeError):
        return 400, {
            "success": False,
            "code": "INPUT_VALIDATION_ERROR",
            "error": f"Invalid JSON payload: {exc.msg}",
            "details": {
                "line": exc.lineno,
                "col": exc.colno,
                "pos": exc.pos,
            },
            "category": "INPUT_VALIDATION_ERROR",
            "retryable": False,
        }

    message = str(exc)
    code = message.split(":", 1)[0].strip() if ":" in message else ""

    if code in INPUT_CONSTRAINT_ERRORS:
        return 422, {
            "success": False,
            "code": code,
            "error": message,
            "details": {
                "action": INPUT_CONSTRAINT_ERRORS[code],
            },
            "category": "INPUT_CONSTRAINT",
            "action": INPUT_CONSTRAINT_ERRORS[code],
            "retryable": False,
        }

    if isinstance(exc, (ValueError, KeyError, TypeError)):
        error_code = code if code.isupper() and "_" in code else "INPUT_VALIDATION_ERROR"
        return 400, {
            "success": False,
            "code": error_code,
            "error": message or type(exc).__name__,
            "details": {
                "exception_type": type(exc).__name__,
            },
            "category": "INPUT_VALIDATION_ERROR",
            "retryable": False,
        }

    return 500, {
        "success": False,
        "code": code or "INTERNAL_ERROR",
        "error": message or "Internal server error",
        "details": {
            "exception_type": type(exc).__name__,
        },
        "category": "INTERNAL_ERROR",
        "retryable": True,
    }
