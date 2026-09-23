# -*- coding: utf-8 -*-
"""BILLBOARD3D —— 朝向相机的面片。

尺寸：`width`(SizeX) 与 `height`(SizeY) 为游戏单位，`scale`(SizeScalar) 为**倍率**而非独立
尺寸；两者相乘后再乘 `p.scale`（SCALEANIM 累积的倍率，出生时为 1）。SCALEANIM 的增量加在
尺寸字段上：SizeScalarAdd 作用于 `scale`，SizeXAdd 作用于 `width`。

颜色：`color` / `colorRange` 为 XYZ type 2（`<4B`）的 0-255 无符号字节，构成 RGBA 四元组的
固定值与随机范围；`useColorRange=1` 时逐通道（含 alpha）在两者之间取值，染色模型见 `_common`。
第四字节在 codec 中名为 pad，此处用作 alpha，乘入 `item.color[3]`，再乘以 LIFE 计算的
`p.alpha`。`brightness`（通道名 ColorRate）作为**乘数**，1.0 为中性值。`blendMode` 的
0=Alpha 混合、1=加法混合，直接写入 `RenderItem.blend`，由 glue 转换为 `gpu.state.blend_set`。

`correctColorNo` / `colorRangeCorrectColorNo` 非 0 时，游戏内颜色取自调用方 .epv 的槽位，本地
`color` 不生效。预览无法读取 .epv，仍使用本地值并记录 note：修改颜色无效是游戏内的实际行为，
而非预览缺陷。

ROTATEANIM 的自旋中，只有绕相机视线方向的分量表现为屏幕上的自转：billboard 每帧朝向相机，
绕画面内两个轴的旋转不可见。`p.rot.z` 已包含供 PLANE / MESH 使用的自旋 Z 分量，因此
`_spin_on_view` 先减去该分量，再按视线方向投影加回。

维护约束：
- 尺寸必须限定为非负：负尺寸在游戏中表现为消失，而非面片翻转。
- `item.extra["base_tint"]` 保存渲染主体自身的颜色，不含 RGBFIRE / RGBWATER 写入 `p.color`
  的代表色。该颜色对贴图与两层染色是**逐通道相乘的滤镜**，而非叠加的底色（红色滤镜下，贴图中
  非红色部分变黑，而不是被红色覆盖）。带 RGBFIRE / RGBWATER 时 `item.color` 已乘入 `p.color`，
  因此 glue 的两层染色分支必须单独乘以该自身颜色。
- `build_render` 是逐粒子逐帧执行的热路径。外观的静态部分在出生时求值并缓存，仅在带 TIML 时
  逐帧重新求值；`_has_tracks` 在 init 时确定，不带 TIML 时无需调用 `em.f()`。
- 本 behavior 不写入任何粒子状态，strict 模式会检查这一点。
"""

import math

from ...hashes import BILLBOARD3D
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from . import _flowmap
from ._common import pick_color, quad_size, roll_rgba

BLEND_ALPHA = 0
BLEND_ADDITIVE = 1


def _rgba(seq):
    """将 XYZ type 2 的四个字节转换为 0-1 浮点四元组。"""
    if not isinstance(seq, (list, tuple)) or len(seq) < 3:
        return (1.0, 1.0, 1.0, 1.0)
    a = float(seq[3]) / 255.0 if len(seq) > 3 else 1.0
    return (float(seq[0]) / 255.0, float(seq[1]) / 255.0, float(seq[2]) / 255.0, a)


@register(BILLBOARD3D)
class Billboard3D(Behavior):
    """RENDER_BODY 阶段产出 RenderItem。"""

    STAGE = RENDER_BODY
    ORDER = 100

    #: 本属性是否带 TIML 曲线；带曲线时在 build_render 中逐帧重新求值。
    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(BILLBOARD3D)
        if f is None:
            return
        self._has_tracks = f.has_tracks
        if f.i("correctColorNo") or f.i("colorRangeCorrectColorNo"):
            em.note("BILLBOARD3D 绑了 EPV 颜色槽位：游戏内颜色来自 .epv，"
                    "本地 color 不生效（预览仍按本地值画）")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(BILLBOARD3D, p)
        if f is None:
            return
        mode = em.config.jitter_mode

        p.rolled["bb_scale"] = jitter(f.get("scale", 1.0), f.get("scaleJitter"), rng, mode)
        p.rolled["bb_width"] = jitter(f.get("width", 1.0), f.get("widthJitter"), rng, mode)
        p.rolled["bb_height"] = jitter(f.get("height", 1.0), f.get("heightJitter"), rng, mode)
        p.rolled["bb_bright"] = jitter(f.get("brightness", 1.0), f.get("brightnessJitter"),
                                       rng, mode)
        p.rolled["bb_rgba"], p.rolled["bb_coff"] = roll_rgba(f, rng, em.config)

        # 初始平面角，ROTATEANIM 的平面旋转在其上累积
        p.rot.z += jitter(f.get("rotation"), f.get("rotationJitter"), rng, mode)

        p.rolled["bb_blend"] = ("ADDITIVE" if f.i("blendMode") == BLEND_ADDITIVE
                                else "ALPHA")

        _flowmap.roll(p, f, rng, mode)

    @staticmethod
    def _size(p, em, scale, width, height):
        """返回本帧的宽高（`Vec3`，z 恒为 1），结果限定为非负。"""
        return quad_size(p, em.config, scale, width, height)

    @staticmethod
    def _spin_on_view(p, em, view):
        """返回 ROTATEANIM 自旋在相机视线方向上的附加屏幕转角；无自旋时返回 0。"""
        ang = p.rolled.get("spin_ang")
        if ang is None:
            return 0.0
        if getattr(em.config, "rotateanim_billboard_axis", "view") != "view":
            return 0.0                      # 'z' 档仅使用 p.rot.z
        n = view.cam_forward
        d = math.sqrt(n.x * n.x + n.y * n.y + n.z * n.z)
        if d < 1e-9:
            return 0.0
        return (ang[0] * n.x + ang[1] * n.y + ang[2] * n.z) / d - ang[2]

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        if "bb_rgba" not in rolled:      # 未经过 spawn，交由下游处理
            return item

        item = RenderItem(kind="BILLBOARD", pos=p.pos.copy())
        item.rot = p.rot.z + self._spin_on_view(p, em, view)

        if self._has_tracks:
            f = em.f(BILLBOARD3D, p)
            s = f.get("scale", 1.0)
            item.size = self._size(p, em, s, f.get("width", 1.0), f.get("height", 1.0))
            r0, g0, b0, a0 = pick_color(f, rolled.get("bb_coff"))
            bright = f.get("brightness", 1.0)
        else:
            s = rolled["bb_scale"]
            item.size = self._size(p, em, s, rolled["bb_width"], rolled["bb_height"])
            r0, g0, b0, a0 = rolled["bb_rgba"]
            bright = rolled["bb_bright"]

        item.color = [r0 * bright * p.color[0],
                      g0 * bright * p.color[1],
                      b0 * bright * p.color[2],
                      a0 * p.alpha]
        item.extra["base_tint"] = (r0 * bright, g0 * bright, b0 * bright)
        item.blend = rolled.get("bb_blend", "ALPHA")
        item.extra["vel"] = p.vel
        item.extra["age"] = p.age
        return _flowmap.apply(p, em, item)
