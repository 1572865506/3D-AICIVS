"""Stable HTTP classification for solver failures exposed by the loading API."""

INPUT_CONSTRAINT_ERRORS = {
    "NO_VALID_DOOR_WALL": (
        "门墙安全配置未满足。请在 SKU 参数中明确配置至少一种“封柜门”货物，"
        "并检查其尺寸、数量、单件重量及合法方向。"
    ),
}


def classify_api_exception(exc):
    message = str(exc)
    code = message.split(":", 1)[0].strip()
    if code in INPUT_CONSTRAINT_ERRORS:
        return 422, {
            "success": False,
            "error": message,
            "code": code,
            "category": "INPUT_CONSTRAINT",
            "action": INPUT_CONSTRAINT_ERRORS[code],
            "retryable": False,
        }
    return 500, {
        "success": False,
        "error": message,
        "code": code or "INTERNAL_ERROR",
        "category": "INTERNAL_ERROR",
        "retryable": True,
    }
