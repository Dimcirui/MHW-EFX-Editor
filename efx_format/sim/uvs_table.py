# -*- coding: utf-8 -*-
"""
efx_format/sim/uvs_table.py  —  序列帧表（.uvs 帧矩形 / 网格兜底）+ 资源容器

为什么单独一个模块
------------------
UVSEQUENCE 属性里只有一条 `uvsPath`（游戏相对路径），真正的帧矩形在 `.uvs` 文件
里。模拟核心**不 open() 任何文件**——路径怎么解析（chunk 目录在哪、用户手动载入
的是哪份）是宿主的事，核心只吃字节。这条边界跟 `Simulator(blocks, ...)` 不吃
EntryData 是同一个道理：核心能脱离 Blender 单测。

坐标约定
--------
帧矩形**原样沿用 .uvs 里的存法**：`uv0` = 左上、`uv1` = 右下，v 轴向下
（v 越大越靠贴图底部，见记忆 uvs-top-bottom-label-reversed）。到 Blender/GPU
的 v 翻转是画的时候的事，不在这里做。

`FrameTable.corners()` 输出的四个角按 **BL, BR, TR, TL** 排（左下→右下→右上→左上），
与 `blender_efx/sim_preview.py::_quad_verts` 的顶点序对齐——glue 拿去就能用，
不必再猜谁对谁。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10；零第三方依赖。
"""

# 网格兜底的扫描顺序。**公式逐字照抄** blender_efx/uvs_io.py::_gen_frames_grid，
# 两处必须给出同一套帧序——那边是「生成帧表写进 .uvs」，这边是「没有 .uvs 时假装
# 有一张」，读法不一致会让预览和编辑器对不上。
_SCANS = ("LR_TB", "LR_BT", "RL_TB", "RL_BT", "TB_LR", "BT_LR", "TB_RL", "BT_RL")


def _grid_pairs(h, v, scan):
    """(列, 行) 的播放顺序。行号 ri 大 = v 大 = 靠贴图底部。"""
    if scan == "LR_TB":      # 左→右 上→下
        return [(i, v - 1 - j) for j in range(v) for i in range(h)]
    if scan == "LR_BT":      # 左→右 下→上
        return [(i, j) for j in range(v) for i in range(h)]
    if scan == "RL_TB":
        return [(h - 1 - i, v - 1 - j) for j in range(v) for i in range(h)]
    if scan == "RL_BT":
        return [(h - 1 - i, j) for j in range(v) for i in range(h)]
    if scan == "TB_LR":
        return [(i, v - 1 - j) for i in range(h) for j in range(v)]
    if scan == "BT_LR":
        return [(i, j) for i in range(h) for j in range(v)]
    if scan == "TB_RL":
        return [(h - 1 - i, v - 1 - j) for i in range(h) for j in range(v)]
    return [(h - 1 - i, j) for i in range(h) for j in range(v)]    # BT_RL


# ─────────────────────────────────────────────────────────────────────────────
# FrameTable
# ─────────────────────────────────────────────────────────────────────────────

class FrameTable(object):
    """一组序列帧矩形。`source` 说明它是真读来的还是猜出来的，供 UI 如实标注。"""

    __slots__ = ("rects", "source", "tex_paths", "grid")

    #: 真从 .uvs 的某个 group 读出来的
    SRC_UVS = "uvs"
    #: 没有 .uvs，按 H×V 网格假设的（预览会 note 一条）
    SRC_GRID = "grid"

    def __init__(self, rects, source=SRC_UVS, tex_paths=(), grid=None):
        #: [(u0, v0, u1, v1), ...]，v 向下，与 .uvs 同
        self.rects = list(rects)
        self.source = source
        #: group 引用的贴图路径（最多 4 条）。P0 用不到，P1 贴图要靠它找图。
        self.tex_paths = tuple(tex_paths)
        #: 网格兜底时的 (H, V)；真表为 None
        self.grid = grid

    def __len__(self):
        return len(self.rects)

    def __repr__(self):
        return "<FrameTable %s n=%d>" % (self.source, len(self.rects))

    # ── 取帧 ─────────────────────────────────────────────────────────────────
    def index(self, i, wrap=True):
        """把任意整数收进 [0, n)。`wrap=False` 时改为夹取两端。"""
        n = len(self.rects)
        if n <= 0:
            return 0
        i = int(i)
        if wrap:
            return i % n
        return 0 if i < 0 else (n - 1 if i >= n else i)

    def rect(self, i, wrap=True):
        if not self.rects:
            return (0.0, 0.0, 1.0, 1.0)
        return self.rects[self.index(i, wrap)]

    def corners(self, i, flip_u=False, flip_v=False, turns=0, wrap=True):
        """一帧的四个角 UV，序为 BL, BR, TR, TL（同 `_quad_verts`）。

        `flip_u` / `flip_v`  —— loopingMode 的水平/垂直翻转（语料里「随机翻」是主流）。
        `turns`              —— loopingOrientation 的 90° 旋转，单位是「四分之一圈」。
                                1 = 顺时针 90°，3 = 逆时针 90°（= -1）。
                                ⚠ 旋转**方向**的正负没有实机验证：视觉上就是差一个
                                「转反了」，真要订正只需把这里的 rotate 方向取反。
        """
        u0, v0, u1, v1 = self.rect(i, wrap)
        if flip_u:
            u0, u1 = u1, u0
        if flip_v:
            v0, v1 = v1, v0
        # BL, BR, TR, TL —— v1 是下沿（v 向下），所以下面两角取 v1
        out = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
        turns = int(turns) % 4
        if turns:
            out = out[turns:] + out[:turns]
        return tuple(out)


def from_uvs_bytes(data, group=0):
    """`.uvs` 字节 + group 下标 → FrameTable。

    `group` 就是 UVSEQUENCE.sequenceNo（用户确认：sequenceNo 即 group 下标）。
    下标越界、解析失败、或该 group 没有帧 → 返回 None（调用方决定是否退网格）。
    """
    if not data:
        return None
    try:
        from ..uvs import UVSFile
        uvs = UVSFile.parse(bytes(data))
    except Exception:
        return None

    groups = uvs.groups or []
    g = int(group)
    if g < 0 or g >= len(groups):
        return None
    grp = groups[g]
    if not grp.frames:
        return None

    rects = []
    for fr in grp.frames:
        rects.append((float(fr.uv0[0]), float(fr.uv0[1]),
                      float(fr.uv1[0]), float(fr.uv1[1])))

    paths = []
    for idx in (grp.path_indices or [])[:max(0, int(grp.map_count or 0))]:
        if 0 <= idx < len(uvs.strings):
            paths.append(uvs.strings[idx].path)
    return FrameTable(rects, FrameTable.SRC_UVS, paths)


def grid_table(h=8, v=8, scan="LR_TB", count=None):
    """没有 .uvs 时的兜底帧表：把整张图当 H×V 等分网格。

    默认 8×8 = 64 格，依据是全语料 `patternNoJitter == 63` 占 33.6%
    （28253/84106）——作者自己在按 64 格写起始帧随机范围。
    """
    h = max(1, int(h))
    v = max(1, int(v))
    if scan not in _SCANS:
        scan = "LR_TB"
    w, hh = 1.0 / h, 1.0 / v
    rects = []
    for ci, ri in _grid_pairs(h, v, scan):
        rects.append((ci * w, ri * hh, (ci + 1) * w, (ri + 1) * hh))
    if count and 0 < int(count) < len(rects):
        rects = rects[:int(count)]
    return FrameTable(rects, FrameTable.SRC_GRID, (), (h, v))


# ─────────────────────────────────────────────────────────────────────────────
# SimResources —— 模拟需要但属性块里没有的外部数据
# ─────────────────────────────────────────────────────────────────────────────

class SimResources(object):
    """glue 层塞进来的外部资源。现在只有 .uvs 字节，将来贴图/EPV 也走这里。

    刻意只收**字节**不收路径：核心不 open() 文件（见模块 docstring）。
    """

    __slots__ = ("uvs_bytes", "_cache")

    def __init__(self, uvs_bytes=None):
        #: 用户在 UVSEQUENCE 属性上载入的 .uvs 原始字节（没有则 None/空）
        self.uvs_bytes = bytes(uvs_bytes) if uvs_bytes else b""
        self._cache = {}

    def uvs_table(self, sequence_no, config=None):
        """取某个 group 的帧表；拿不到就按 config 里的网格兜底。

        返回 (table, fell_back)：`fell_back=True` 表示这是猜的，调用方应当 note 一条。
        """
        key = int(sequence_no)
        if key in self._cache:
            return self._cache[key]

        table = from_uvs_bytes(self.uvs_bytes, key)
        fell_back = table is None
        if fell_back:
            h = getattr(config, "uvs_grid_h", 8) if config is not None else 8
            v = getattr(config, "uvs_grid_v", 8) if config is not None else 8
            scan = getattr(config, "uvs_grid_scan", "LR_TB") if config is not None else "LR_TB"
            table = grid_table(h, v, scan)
        out = (table, fell_back)
        self._cache[key] = out
        return out

    def __repr__(self):
        return "<SimResources uvs=%dB>" % len(self.uvs_bytes)
