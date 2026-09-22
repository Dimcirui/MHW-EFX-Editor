# -*- coding: utf-8 -*-
"""序列帧矩形表与模拟所需的外部资源容器。

维护约束：
- 本模块不打开文件，只接收字节。路径解析属于宿主，核心因此可脱离 Blender 单测。
- 帧矩形沿用 .uvs 的存法：uv0 为左上、uv1 为右下，v 轴向下。到 Blender/GPU 的 v
  翻转在绘制层做，此处不得预先翻转。
"""

# 与 blender_efx/uvs_io.py::_gen_frames_grid 必须给出同一套帧序，否则预览与编辑器对不上。
_SCANS = ("LR_TB", "LR_BT", "RL_TB", "RL_BT", "TB_LR", "BT_LR", "TB_RL", "BT_RL")


def _grid_pairs(h, v, scan):
    """(列, 行) 的播放顺序；行号越大 v 越大，即越靠贴图底部。"""
    if scan == "LR_TB":
        return [(i, v - 1 - j) for j in range(v) for i in range(h)]
    if scan == "LR_BT":
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
    """一组序列帧矩形；source 区分真读出来的表和网格兜底出来的表。

    兜底表不得当作真表呈现给用户，UI 须按 source 如实标注。
    """

    __slots__ = ("rects", "source", "tex_paths", "grid")

    SRC_UVS = "uvs"
    SRC_GRID = "grid"

    def __init__(self, rects, source=SRC_UVS, tex_paths=(), grid=None):
        #: [(u0, v0, u1, v1), ...]，v 向下
        self.rects = list(rects)
        self.source = source
        #: group 引用的贴图路径，最多 4 条
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
        """一帧的四个角 UV，序为 BL, BR, TR, TL，与 sim_preview.py::_quad_verts 对齐。

        flip_u / flip_v 对应 loopingMode 的水平/垂直翻转，turns 对应 loopingOrientation
        的 90° 旋转，单位为四分之一圈。

        ⚠ 旋转方向的正负未经验证，订正时只需把这里的移位方向取反。
        """
        u0, v0, u1, v1 = self.rect(i, wrap)
        if flip_u:
            u0, u1 = u1, u0
        if flip_v:
            v0, v1 = v1, v0
        # v 向下，故下沿两角取 v1
        out = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
        turns = int(turns) % 4
        if turns:
            out = out[turns:] + out[:turns]
        return tuple(out)


def from_uvs_bytes(data, group=0):
    """`.uvs` 字节 + group 下标 → FrameTable；group 即 UVSEQUENCE.sequenceNo。

    下标越界、解析失败或该 group 无帧时返回 None，由调用方决定是否退网格。
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
    """没有 .uvs 时的兜底帧表：把整张图当 H×V 等分网格。默认 8×8 是推定值。"""
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
    """宿主注入的外部资源。只收字节，不收路径。"""

    __slots__ = ("uvs_bytes", "_cache")

    def __init__(self, uvs_bytes=None):
        #: UVSEQUENCE 属性上载入的 .uvs 原始字节，没有则为空
        self.uvs_bytes = bytes(uvs_bytes) if uvs_bytes else b""
        self._cache = {}

    def uvs_table(self, sequence_no, config=None):
        """取某个 group 的帧表，拿不到则按 config 的网格兜底。

        返回 (table, fell_back)；fell_back 为真表示这是兜底表，调用方须如实提示。
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
