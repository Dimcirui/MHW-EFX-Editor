# -*- coding: utf-8 -*-
"""tests/test_invariants.py  —  三条架构不变量的机械守卫

这三条以前只靠 CLAUDE.md 和散落的注释提醒。共同点是**违反后在 Blender 里看不出来**：
插件照常工作、byte-perfect 照常通过，坏的是 CLI 工具链、旧版本兼容、或发布包。
所以必须机械守着。

    python tests/test_invariants.py
"""
import ast
import glob
import os
import re
import sys
import unittest

try:                                    # Windows 控制台默认 cp936 编不出 ✓/框线
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 纯 Python 层——不许出现 bpy
PURE_DIRS = ("efx_format", "epv_format")
#: 随包分发的全部第一方源码（= 打包清单覆盖的范围）
SHIPPED_DIRS = ("efx_format", "epv_format", "blender_efx", "blender_epv")

#: 3.11+ 才有的标准库名字。`feature_version` 只管语法，管不到这些。
_NEW_STDLIB = {
    "tomllib": (3, 11),                 # 顶层模块
    "typing.Self": (3, 11), "typing.LiteralString": (3, 11), "typing.Never": (3, 11),
    "typing.assert_never": (3, 11), "typing.TypeVarTuple": (3, 11), "typing.Unpack": (3, 11),
    "enum.StrEnum": (3, 11), "asyncio.TaskGroup": (3, 11),
    "datetime.UTC": (3, 11), "itertools.batched": (3, 12),
}


def _sources(dirs):
    out = []
    for d in dirs:
        out += glob.glob(os.path.join(ROOT, d, "**", "*.py"), recursive=True)
    return [p for p in out if "__pycache__" not in p]


def _rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _tree(path):
    return ast.parse(_read(path), filename=path)


class TestPureLayerHasNoBpy(unittest.TestCase):
    """`efx_format/` 与 `epv_format/` 必须零 `bpy` 依赖（CLAUDE.md §1）。

    违反的后果是**静默的**：Blender 里一切照常，只有 62 个 tools 脚本里
    import 了 efx_format 的那 56 个会炸，而它们不是每次都跑。
    """

    def test_no_bpy_import(self):
        bad = []
        for path in _sources(PURE_DIRS):
            tree = _tree(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.split(".")[0] == "bpy":
                            bad.append("%s:%d  import %s" % (_rel(path), node.lineno, a.name))
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").split(".")[0] == "bpy":
                        bad.append("%s:%d  from %s" % (_rel(path), node.lineno, node.module))
        self.assertEqual(bad, [], "纯 Python 层混入了 bpy：\n  " + "\n  ".join(bad))

    def test_pure_layer_does_not_import_glue(self):
        """反向依赖同样禁止：胶水层可以用核心层，核心层不许回头用胶水层。"""
        bad = []
        for path in _sources(PURE_DIRS):
            tree = _tree(path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for n in names:
                    if n.split(".")[0] in ("blender_efx", "blender_epv"):
                        bad.append("%s:%d  %s" % (_rel(path), node.lineno, n))
        self.assertEqual(bad, [], "核心层反向依赖了胶水层：\n  " + "\n  ".join(bad))


class TestPython310Compatible(unittest.TestCase):
    """全部随包源码必须是 Python 3.10 语法（Blender 3.6 带的就是 3.10）。

    本机跑的是新版 Python，3.11+ 语法在这里能过、到 3.6 上才炸——所以得显式降级解析。
    """

    def test_syntax_parses_as_310(self):
        bad = []
        for path in _sources(SHIPPED_DIRS):
            src = _read(path)
            try:
                ast.parse(src, filename=path, feature_version=(3, 10))
            except SyntaxError as e:
                bad.append("%s:%s  %s" % (_rel(path), e.lineno, e.msg))
        self.assertEqual(bad, [], "用到了 3.10 之后才有的语法：\n  " + "\n  ".join(bad))

    def test_no_newer_stdlib(self):
        """`feature_version` 管语法不管标准库，这些名字得单独拦。"""
        bad = []
        for path in _sources(SHIPPED_DIRS):
            tree = _tree(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name in _NEW_STDLIB:
                            bad.append("%s:%d  import %s（需 %s）"
                                       % (_rel(path), node.lineno, a.name,
                                          "%d.%d" % _NEW_STDLIB[a.name]))
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    for a in node.names:
                        key = "%s.%s" % (node.module or "", a.name)
                        if key in _NEW_STDLIB:
                            bad.append("%s:%d  from %s import %s（需 %s）"
                                       % (_rel(path), node.lineno, node.module, a.name,
                                          "%d.%d" % _NEW_STDLIB[key]))
        self.assertEqual(bad, [], "用到了 3.10 之后才有的标准库：\n  " + "\n  ".join(bad))


class TestPackagingComplete(unittest.TestCase):
    """新增顶层模块/资源后，两个发布包都得带上它（CLAUDE.md §1「不要破坏双打包」）。

    扩展包和 legacy 包共用 `tools/build_extension.py` 的同一份清单，
    所以查一份就够；漏了的后果是装上去 ImportError。
    """

    def setUp(self):
        spec = os.path.join(ROOT, "tools", "build_extension.py")
        if not os.path.isfile(spec):
            self.skipTest("tools/build_extension.py 不在（发布包里本就不含 tools/）")
        import importlib.util
        s = importlib.util.spec_from_file_location("_build", spec)
        self.build = importlib.util.module_from_spec(s)
        s.loader.exec_module(self.build)

    def test_all_toplevel_packages_are_shipped(self):
        covered = set(self.build.INCLUDE_FILES) | set(self.build.INCLUDE_DIRS)
        missing = []
        for name in os.listdir(ROOT):
            full = os.path.join(ROOT, name)
            if os.path.isdir(full) and os.path.isfile(os.path.join(full, "__init__.py")):
                if name not in covered:
                    missing.append(name + "/")
            elif name.endswith(".py") and name not in covered:
                missing.append(name)
        self.assertEqual(missing, [],
                         "顶层模块没进打包清单（tools/build_extension.py 的 "
                         "INCLUDE_FILES / INCLUDE_DIRS）：\n  " + "\n  ".join(missing))

    def test_shipped_code_imports_nothing_unpackaged(self):
        """随包代码不许 import 没被打包的第一方顶层模块。"""
        covered = {c.rstrip("/").split("/")[0] for c in
                   set(self.build.INCLUDE_FILES) | set(self.build.INCLUDE_DIRS)}
        covered |= {c[:-3] for c in self.build.INCLUDE_FILES if c.endswith(".py")}
        firstparty = {n for n in os.listdir(ROOT)
                      if os.path.isdir(os.path.join(ROOT, n))
                      and os.path.isfile(os.path.join(ROOT, n, "__init__.py"))}
        firstparty |= {n[:-3] for n in os.listdir(ROOT) if n.endswith(".py")}
        bad = []
        for path in _sources(SHIPPED_DIRS) + [os.path.join(ROOT, "__init__.py")]:
            tree = _tree(path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for n in names:
                    top = n.split(".")[0]
                    if top in firstparty and top not in covered:
                        bad.append("%s:%d  %s" % (_rel(path), node.lineno, n))
        self.assertEqual(bad, [], "随包代码引用了不在打包清单里的模块：\n  " + "\n  ".join(bad))

    def test_version_is_in_sync(self):
        """`blender_manifest.toml`（4.2+ 扩展读）与根 `__init__.py` 的 `_VERSION`
        （旧式 addon 的 bl_info 读）必须一致——两处分别服务两个安装路径。"""
        mf = _read(os.path.join(ROOT, "blender_manifest.toml"))
        m = re.search(r'^\s*version\s*=\s*["\']([\d.]+)["\']', mf, re.M)
        self.assertIsNotNone(m, "blender_manifest.toml 里找不到 version")
        manifest_ver = m.group(1)

        init = _read(os.path.join(ROOT, "__init__.py"))
        m2 = re.search(r'^_VERSION\s*=\s*\(([^)]+)\)', init, re.M)
        self.assertIsNotNone(m2, "__init__.py 里找不到 _VERSION")
        init_ver = ".".join(x.strip() for x in m2.group(1).split(","))

        self.assertEqual(manifest_ver, init_ver,
                         "版本号两处不一致：blender_manifest.toml=%s，__init__.py::_VERSION=%s"
                         % (manifest_ver, init_ver))


class TestHashHexCommentsAgree(unittest.TestCase):
    """`hashes/__init__.py` 里 `NAME = <十进制>  # 0xHEX` 的两种写法必须一致。

    十进制是代码实际用的值，十六进制只是给人对照 .bt 模板用的——**手抄的**，会错。
    2026-09-20 首次全量核对：93 条里 7 条对不上（7.5%），全是错位/多打一位；
    其中两条还带着 "(actually 0x…)" 的二次订正，**而二次订正也是错的**。
    这类错误肉眼极难发现，但机械一比就出来。
    """

    _DECL = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(\d+)\s*#(.*)$')
    _HEX = re.compile(r'0x([0-9A-Fa-f]+)')

    def test_hex_matches_decimal(self):
        path = os.path.join(ROOT, "efx_format", "hashes", "__init__.py")
        bad, checked = [], 0
        for lineno, line in enumerate(_read(path).splitlines(), 1):
            m = self._DECL.match(line)
            if not m:
                continue
            dec, comment = int(m.group(2)), m.group(3)
            hexes = self._HEX.findall(comment)
            if not hexes:
                continue
            checked += 1
            if not any(int(h, 16) == dec for h in hexes):
                bad.append("hashes/__init__.py:%d  %s = %d  注释写 %s，应为 0x%08X"
                           % (lineno, m.group(1), dec,
                              " / ".join("0x" + h for h in hexes), dec))
        self.assertGreater(checked, 50, "解析到的带十六进制注释常量太少，正则可能失配了")
        self.assertEqual(bad, [], "十六进制注释与十进制值对不上：\n  " + "\n  ".join(bad))


if __name__ == "__main__":
    unittest.main(verbosity=2)
