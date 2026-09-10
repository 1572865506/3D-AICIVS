"""公开资源允许列表：输入 URL，返回限定在项目内的静态文件或拒绝。"""
from pathlib import Path
from urllib.parse import unquote, urlsplit


def public_file(root, url):
    path = unquote(urlsplit(url).path)
    if path == '/':
        path = '/index.html'
    relative = path.lstrip('/')
    parts = Path(relative).parts
    if any(p.startswith('.') for p in parts):
        return None
    allowed = relative in {'index.html','algorithm_space.html','config.baseline.json','frontend/mock/demo_loading_result.json'}
    allowed = allowed or (relative.startswith('frontend/src/') and Path(relative).suffix == '.js')
    if not allowed:
        return None
    base = Path(root).resolve()
    resolved = (base/relative).resolve()
    if resolved != base/relative or not resolved.is_relative_to(base) or not resolved.is_file():
        return None
    return str(resolved)
