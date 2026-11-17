"""形状 xfrm → 变换矩阵的单元测试。

重点是两条容易写错的规矩：
* 旋转/翻转都绕形状**自身中心**，形状框必须待在原位
* 翻转只影响几何，文字不跟着镜像（见 render/html.py 的 mirror 参数）
"""

from __future__ import annotations

import unittest

from ppt2web.parse.shapes import ShapeCollector


def xfrm(**kw):
    base = {
        "x": 1000.0,
        "y": 2000.0,
        "cx": 400.0,
        "cy": 200.0,
        "rot": 0.0,
        "flip_h": False,
        "flip_v": False,
    }
    base.update(kw)
    return base


def corners(matrix, cx, cy):
    return [matrix.apply(x, y) for x, y in
            ((0, 0), (cx, 0), (cx, cy), (0, cy))]


class TestOwnMatrix(unittest.TestCase):
    def test_不平移时形状框待在原位(self):
        m = ShapeCollector._own_matrix(xfrm())
        pts = corners(m, 400, 200)
        self.assertEqual(sorted({round(p[0], 3) for p in pts}), [1000.0, 1400.0])
        self.assertEqual(sorted({round(p[1], 3) for p in pts}), [2000.0, 2200.0])

    def test_水平翻转后形状框仍在原位(self):
        m = ShapeCollector._own_matrix(xfrm(flip_h=True))
        pts = corners(m, 400, 200)
        self.assertEqual(sorted({round(p[0], 3) for p in pts}), [1000.0, 1400.0])
        self.assertEqual(sorted({round(p[1], 3) for p in pts}), [2000.0, 2200.0])
        # 局部 x=0 的点落到右边界（内容左右翻转了）
        self.assertAlmostEqual(m.apply(0, 0)[0], 1400.0, places=3)

    def test_垂直翻转后形状框仍在原位(self):
        m = ShapeCollector._own_matrix(xfrm(flip_v=True))
        pts = corners(m, 400, 200)
        self.assertEqual(sorted({round(p[0], 3) for p in pts}), [1000.0, 1400.0])
        self.assertEqual(sorted({round(p[1], 3) for p in pts}), [2000.0, 2200.0])
        self.assertAlmostEqual(m.apply(0, 0)[1], 2200.0, places=3)

    def test_旋转绕形状中心(self):
        m = ShapeCollector._own_matrix(xfrm(rot=90.0))
        cx, cy = 1200.0, 2100.0  # 形状中心
        # 中心点不动
        self.assertAlmostEqual(m.apply(200, 100)[0], cx, places=3)
        self.assertAlmostEqual(m.apply(200, 100)[1], cy, places=3)
        # 左上角绕中心顺时针转 90° → 落到右上角
        x, y = m.apply(0, 0)
        self.assertAlmostEqual(x, cx + 100.0, places=3)
        self.assertAlmostEqual(y, cy - 200.0, places=3)

    def test_旋转加翻转(self):
        m = ShapeCollector._own_matrix(xfrm(rot=90.0, flip_h=True))
        cx, cy = 1200.0, 2100.0
        self.assertAlmostEqual(m.apply(200, 100)[0], cx, places=3)
        self.assertAlmostEqual(m.apply(200, 100)[1], cy, places=3)


if __name__ == "__main__":
    unittest.main()
