"""CLI：训练策略选择器（影子模式）。

等价于：
  python -m backend.solver_v2.learning.train --dataset ... --model ... --report ...

被谁调用：人工/CI；dashboard 只读模型状态，不触发训练。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.learning.train import main  # noqa: E402

if __name__ == "__main__":
    main()
