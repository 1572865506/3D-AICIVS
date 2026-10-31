"""InputNormalizer.normalize_box_dim 尺寸字段解析回归测试。

用途：守护 API 输入的三种尺寸写法（嵌套 dimensions / 平铺短键 / 平铺全名），
防止平铺全名字段再次被静默忽略并回退 0.1m 默认值。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import pytest

from backend.solver_v2.api.adapter import InputNormalizer
from backend.solver_v2.domain.models import BoxDim


class TestNormalizeBoxDim:
    def test_nested_dimensions_layout(self):
        """推荐写法：嵌套 dimensions 结构。"""
        dim = InputNormalizer.normalize_box_dim(
            {"dimensions": {"length": 1.2, "width": 1.0, "height": 0.8}}
        )
        assert (dim.x, dim.y, dim.z) == (1.2, 1.0, 0.8)

    def test_flat_short_keys_layout(self):
        """legacy test_suite 写法：平铺短键 w/x、d/y、h/z。"""
        dim = InputNormalizer.normalize_box_dim({"w": 0.9, "d": 0.5, "h": 0.4})
        assert (dim.x, dim.y, dim.z) == (0.9, 0.5, 0.4)

    def test_flat_fullname_keys_layout(self):
        """第三方直连常见写法：平铺全名 length/width/height，此前被静默忽略。"""
        dim = InputNormalizer.normalize_box_dim({"length": 1.2, "width": 1.0, "height": 1.0})
        assert (dim.x, dim.y, dim.z) == (1.2, 1.0, 1.0)

    def test_canonical_axes_x_ge_y(self):
        """长宽互换时归一化为 x >= y。"""
        dim = InputNormalizer.normalize_box_dim({"length": 0.8, "width": 1.2, "height": 0.5})
        assert dim.x == 1.2 and dim.y == 0.8 and dim.z == 0.5

    def test_missing_dimensions_fall_back_to_default(self):
        """完全缺失尺寸字段时保持 0.1m 默认值（不抛异常）。"""
        dim = InputNormalizer.normalize_box_dim({"sku": "X"})
        assert (dim.x, dim.y, dim.z) == (0.1, 0.1, 0.1)

    def test_short_keys_take_precedence_over_fullname(self):
        """同一 item 同时携带短键与全名键时，保持既有短键优先级不变。"""
        dim = InputNormalizer.normalize_box_dim({"w": 0.9, "length": 9.9, "d": 0.5, "width": 5.5, "h": 0.4})
        assert (dim.x, dim.y, dim.z) == (0.9, 0.5, 0.4)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
