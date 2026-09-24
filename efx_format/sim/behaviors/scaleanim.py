# -*- coding: utf-8 -*-
"""SCALEANIM —— 逐帧缩放动画。

两组相互独立的缩放，均为**加法累积 + 逐帧乘法衰减**：

    整体（三轴同步）  sizeScalarAdd(+Jitter)        每帧加到三个轴上的增量
                      sizeScalarAddCoef(+Jitter)    该增量每帧乘以此值；1 为匀速，小于 1 逐渐减慢
    逐轴              size{X,Y,Z}Add(+Jitter) / size{X,Y,Z}AddCoef(+Jitter)
    两组共用        animUpdateStart(+Jitter)      起始延迟帧数，延迟结束前两组都不生效

缩放为加法而非乘法：官方 TimelineParam 的通道名为 SizeScalarAdd / SizeXAdd / SizeYAdd /
SizeZAdd。SizeScalarAdd 加在渲染体的 `scale` 字段上；逐轴一组加在从 1 起的倍率上，与宽高
无关：-1/60 在 60 帧内缩到 0。

维护约束：
- 必须同时写入两种结果：`p.scale`（从 1 起的归一化倍率）与 `p.rolled["sa_scalar"]` /
  `["sa_axis"]`（绝对增量）。BILLBOARD3D / PLANE 读取绝对增量（`_common.quad_size`），
  MESH / RIBBON 读取 `p.scale`。
- TIML（A1）：两组速度每帧取「曲线值 + 出生时抽取的抖动偏移」为基准，再乘以各自 Accel 按帧
  累积的衰减；没有轨道时与逐帧递推完全一致。两组的衰减都从 animUpdateStart 起才开始累积。
"""

from ...hashes import SCALEANIM
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import XFORM


@register(SCALEANIM)
class ScaleAnim(Behavior):
    """XFORM 阶段写入 p.scale 与绝对增量。"""

    STAGE = XFORM
    ORDER = 100

    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(SCALEANIM)
        if f is not None:
            self._has_tracks = f.has_tracks

    def on_particle_spawn(self, p, em, rng):
        f = em.f(SCALEANIM, p)
        if f is None:
            return
        mode = em.config.jitter_mode

        uniform_v = jitter(f.get("sizeScalarAdd"), f.get("sizeScalarAddJitter"),
                           rng, mode)
        uniform_a = jitter(f.get("sizeScalarAddCoef", 1.0),
                           f.get("sizeScalarAddCoefJitter"), rng, mode)

        axis_v = []
        axis_a = []
        for ax in ("X", "Y", "Z"):
            axis_v.append(jitter(f.get("size" + ax + "Add"),
                                 f.get("size" + ax + "AddJitter"), rng, mode))
            axis_a.append(jitter(f.get("size" + ax + "AddCoef", 1.0),
                                 f.get("size" + ax + "AddCoefJitter"), rng, mode))

        delay = max(0, jitter_int(f.get("animUpdateStart"),
                                  f.get("animUpdateStartJitter"), rng, mode))

        st = {
            "uv": uniform_v, "ua": uniform_a,
            "av": axis_v, "aa": axis_a,
            "delay": delay,
        }
        if self._has_tracks:
            # TIML 基准 = 曲线值 + 偏移；衰减为 Accel 的累积乘积
            st["u_off"] = uniform_v - f.get("sizeScalarAdd")
            st["a_off"] = [axis_v[i] - f.get("size" + ax + "Add")
                           for i, ax in enumerate(("X", "Y", "Z"))]
            st["u_decay"] = 1.0
            st["a_decay"] = [1.0, 1.0, 1.0]
        p.user[ScaleAnim] = st
        p.rolled["sa_scalar"] = 0.0
        p.rolled["sa_axis"] = [0.0, 0.0, 0.0]

    def on_particle_step(self, p, em):
        st = p.user.get(ScaleAnim)
        if st is None or p.age < st["delay"]:
            return
        f = em.f(SCALEANIM, p) if "u_off" in st else None

        if f is not None:
            st["uv"] = (f.get("sizeScalarAdd") + st["u_off"]) * st["u_decay"]
            st["u_decay"] *= st["ua"]
        uv = st["uv"]
        if uv:
            p.scale.x += uv
            p.scale.y += uv
            p.scale.z += uv
            p.rolled["sa_scalar"] += uv
        st["uv"] = uv * st["ua"]

        av, aa = st["av"], st["aa"]
        if f is not None:
            dec = st["a_decay"]
            for i, name in enumerate(("sizeXAdd", "sizeYAdd", "sizeZAdd")):
                av[i] = (f.get(name) + st["a_off"][i]) * dec[i]
                dec[i] *= aa[i]
        ax = p.rolled["sa_axis"]
        if av[0]:
            p.scale.x += av[0]
            ax[0] += av[0]
        if av[1]:
            p.scale.y += av[1]
            ax[1] += av[1]
        if av[2]:
            p.scale.z += av[2]
            ax[2] += av[2]
        av[0] *= aa[0]
        av[1] *= aa[1]
        av[2] *= aa[2]
