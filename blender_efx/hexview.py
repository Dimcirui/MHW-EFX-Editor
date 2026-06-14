"""
blender_efx/hexview.py  —  只读整块 16 进制查看器

为 opaque / 路径-only / 任意 EFX 块（及 opaque 的 root/unknown body）提供
只读的十六进制 dump 视图，便于检查那些尚未字段化的原始字节
（MATERIAL / PTBEHAVIOR / TIML / 4 个退回路径-only 的 custom 类型 / RootBody 等）。

设计：
  - 面板 EFX_PT_hex_view（挂 EFX_PT_main，DEFAULT_CLOSED）——展开才渲染，避免大块卡顿。
  - 面板内只显示前 _PANEL_MAX_BYTES 字节（截断提示），完整内容用"复制完整 hex"算子
    写入系统剪贴板（context.window_manager.clipboard），供外部 hex 工具粘贴。
  - 纯只读：不参与导出、不改任何字节。

约束（CLAUDE.md）：Python 3.11、bpy 稳定子集、包内相对导入。
"""

import base64
import bpy

from .i18n import T


# 面板内最多显示的字节数（超出截断，完整走剪贴板）。每行 16 字节。
_PANEL_MAX_BYTES = 256
_BYTES_PER_ROW = 16


# ─────────────────────────────────────────────────────────────────────────────
# 取对象的原始字节
# ─────────────────────────────────────────────────────────────────────────────

def _get_object_raw_bytes(obj):
    """
    按 ~TYPE 返回该对象的原始字节（用于 hex 显示），取不到返回 None。

      - EFX_BLOCK            → efx_block.raw_b64（导入时写入的原始 data_bytes）
      - EFX_BODY(root/unknown) → obj["raw"]（opaque body 整段）
      - EFX_PLAY / EFX_EXTERN → obj["raw_b64"]
    """
    if obj is None:
        return None
    t = obj.get("~TYPE")
    try:
        if t == "EFX_BLOCK":
            bp = obj.efx_block
            if bp.raw_b64:
                return base64.b64decode(bp.raw_b64)
            # 回退：自定义属性 data_bytes
            if obj.get("data_bytes"):
                return base64.b64decode(str(obj["data_bytes"]))
        elif t == "EFX_BODY":
            kind = str(obj.get("body_kind", ""))
            if kind in ("root", "unknown") and obj.get("raw"):
                return base64.b64decode(str(obj["raw"]))
        elif t in ("EFX_PLAY", "EFX_EXTERN"):
            if obj.get("raw_b64"):
                return base64.b64decode(str(obj["raw_b64"]))
    except Exception:
        return None
    return None


def _can_show_hex(obj):
    """poll 用：该对象是否有可显示的原始字节。"""
    return _get_object_raw_bytes(obj) is not None


# ─────────────────────────────────────────────────────────────────────────────
# 格式化 hex dump
# ─────────────────────────────────────────────────────────────────────────────

def _format_hex_rows(data: bytes, max_bytes: int = None):
    """
    返回 hex dump 文本行列表，每行：
      OFFSET: HH HH HH ...(16)...  ascii
    max_bytes 为 None 表示全量；否则只取前 max_bytes 字节。
    """
    n = len(data) if max_bytes is None else min(len(data), max_bytes)
    rows = []
    for base in range(0, n, _BYTES_PER_ROW):
        chunk = data[base:base + _BYTES_PER_ROW]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        # ascii 列：可打印字符原样，其余用 '.'
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append(f"{base:04X}: {hex_part:<{_BYTES_PER_ROW * 3 - 1}}  {ascii_part}")
    return rows


def _clipboard_hex_text(data: bytes) -> str:
    """
    剪贴板用纯 hex 文本：空格分隔字节、每 16 字节换行，**无偏移/ascii**。
    既便于阅读分块，又能被 _parse_pure_hex 无歧义解析回字节（用于粘贴回写）。
    """
    lines = []
    for base in range(0, len(data), _BYTES_PER_ROW):
        chunk = data[base:base + _BYTES_PER_ROW]
        lines.append(" ".join(f"{b:02X}" for b in chunk))
    return "\n".join(lines)


def _parse_pure_hex(text: str):
    """
    解析纯 hex 文本（空白分隔的两位十六进制）回字节。
    任一 token 不是恰好两位十六进制 → 返回 None（格式非法）。
    """
    toks = text.split()
    if not toks:
        return None
    out = bytearray()
    for tok in toks:
        if len(tok) != 2 or any(c not in "0123456789abcdefABCDEF" for c in tok):
            return None
        out.append(int(tok, 16))
    return bytes(out)


def _set_object_raw_bytes(obj, new_bytes: bytes) -> bool:
    """
    把 new_bytes 写回对象的原始字节存储（供导出使用）。仅支持安全的目标：
      - EFX_BLOCK            → 写 obj["data_bytes"] + 重跑 init_block_props 重建字段模型，
                               efx_dirty=False（导出走"非 dirty → raw data_bytes"路径）。
      - EFX_BODY(root/unknown) → 写 obj["raw"]。
      - EFX_EXTERN           → 写 obj["raw_b64"]（导出直接用 raw_b64）。
    EFX_PLAY 不支持（结构化导出可能覆盖 raw）→ 返回 False。
    返回是否成功写回。
    """
    t = obj.get("~TYPE")
    b64 = base64.b64encode(new_bytes).decode("ascii")
    try:
        if t == "EFX_BLOCK":
            obj["data_bytes"] = b64
            # 重建字段模型（raw_b64 + field_items + extern_ref），并清 dirty
            from .fields import init_block_props
            from ..efx_format.efxfile import AttrBlock
            th = int(obj.efx_block.type_hash_str)
            init_block_props(obj, AttrBlock(type_hash=th, data_bytes=new_bytes))
            obj.efx_block.efx_dirty = False
            return True
        elif t == "EFX_BODY" and str(obj.get("body_kind", "")) in ("root", "unknown"):
            obj["raw"] = b64
            return True
        elif t == "EFX_EXTERN":
            obj["raw_b64"] = b64
            return True
    except Exception:
        return False
    return False


def _paste_supported(obj) -> bool:
    """该对象是否支持 hex 粘贴回写（见 _set_object_raw_bytes）。"""
    if obj is None:
        return False
    t = obj.get("~TYPE")
    if t == "EFX_BLOCK" or t == "EFX_EXTERN":
        return True
    if t == "EFX_BODY" and str(obj.get("body_kind", "")) in ("root", "unknown"):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# 算子：复制完整 hex 到剪贴板
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_copy_block_hex(bpy.types.Operator):
    """把当前对象的完整原始字节以纯 hex 文本复制到系统剪贴板（可编辑后粘回）"""

    bl_idname      = "efx.copy_block_hex"
    bl_label       = "Copy Hex"
    bl_description = "Copy the full raw bytes of the current EFX block/object (space-separated pure hex) to the clipboard; edit and write back with Paste Hex"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _can_show_hex(context.active_object)

    def execute(self, context):
        data = _get_object_raw_bytes(context.active_object)
        if data is None:
            self.report({"ERROR"}, "Cannot get raw bytes")
            return {"CANCELLED"}
        context.window_manager.clipboard = _clipboard_hex_text(data)
        self.report({"INFO"}, f"Copied {len(data)} bytes of pure hex to clipboard")
        return {"FINISHED"}


class EFX_OT_paste_block_hex(bpy.types.Operator):
    """从剪贴板粘贴纯 hex 写回当前对象的原始字节（同长度覆盖）"""

    bl_idname      = "efx.paste_block_hex"
    bl_label       = "Paste Hex"
    bl_description = (
        "Write the clipboard's pure hex (space-separated two-digit hex) back to the current object's raw bytes. "
        "**Same-length overwrite only** (EFX blocks have no length field; changing the byte count breaks file structure)"
    )
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _paste_supported(context.active_object)

    def invoke(self, context, event):
        # 破坏性操作（覆盖原始字节）：弹确认
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = context.active_object
        cur = _get_object_raw_bytes(obj)
        if cur is None:
            self.report({"ERROR"}, "Cannot get current raw bytes")
            return {"CANCELLED"}

        text = context.window_manager.clipboard or ""
        new_bytes = _parse_pure_hex(text)
        if new_bytes is None:
            self.report({"ERROR"}, "Clipboard content is not valid pure hex (should be space-separated two-digit hex bytes)")
            return {"CANCELLED"}

        if len(new_bytes) != len(cur):
            self.report(
                {"ERROR"},
                f"Length mismatch: current {len(cur)} bytes, pasted {len(new_bytes)} bytes. "
                "Same-length overwrite only.",
            )
            return {"CANCELLED"}

        if new_bytes == cur:
            self.report({"INFO"}, "Content matches current, no change")
            return {"CANCELLED"}

        if not _set_object_raw_bytes(obj, new_bytes):
            self.report({"ERROR"}, "This object type does not support hex write-back")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Wrote back {len(new_bytes)} bytes")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 面板：只读 hex 视图
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_hex_view(bpy.types.Panel):
    """只读十六进制视图（选中任意有原始字节的 EFX 对象时显示）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Hex View (Read-only)"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _can_show_hex(context.active_object)

    def draw(self, context):
        layout = self.layout
        data = _get_object_raw_bytes(context.active_object)
        if data is None:
            layout.label(text=T("hex.no_raw_bytes"), icon="ERROR")
            return

        total = len(data)
        row = layout.row()
        row.label(text=f"{T('hex.total_length')}{total} {T('hex.bytes')}", icon="FILE_BLANK")
        btns = row.row(align=True)
        btns.operator("efx.copy_block_hex", text=T("hex.copy_hex"), icon="COPYDOWN")
        if _paste_supported(context.active_object):
            btns.operator("efx.paste_block_hex", text=T("hex.paste_hex"), icon="PASTEDOWN")

        truncated = total > _PANEL_MAX_BYTES
        rows = _format_hex_rows(data, max_bytes=_PANEL_MAX_BYTES)

        col = layout.column(align=True)
        for line in rows:
            col.label(text=line)

        if truncated:
            layout.label(
                text=f"{T('hex.trunc_prefix')}{_PANEL_MAX_BYTES}{T('hex.trunc_suffix')}",
                icon="INFO",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_copy_block_hex,
    EFX_OT_paste_block_hex,
    EFX_PT_hex_view,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
