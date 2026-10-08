# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引导层发现：命令行怎么知道项目把引擎配在了哪儿。

命令行有三条路知道引导层（``home`` / ``file_name`` / ``file_type`` / ``no_one_file`` /
``log_path``），优先级从高到低：

1. **显式参数** —— 人说的一定算；
2. **项目代码** —— 静态扫 ``AutoConf(...)`` 的**字面量**关键字；算不出来的表达式
   （``home=config_root()`` 这种"配置之前得先算"的）在一处**一次性子进程**里求值；
3. **派生快照** —— ``<home>/.onconf.json``，引擎装配时落下的那一次事实；
4. **约定** —— ``ONCONF_HOME`` / ``./conf`` / 各参数自己的缺省值。

``home`` 是例外：快照就住在 ``<home>`` 里，所以它**不可能**是 home 的来源 —— 自举只走
1 / 2 / 4，表里那个 ``home`` 字段只做**自检**：表里写的地址与它所在的目录对不上，就当
这张表是搬过来的，整张不采信。

## 求值：白名单摘取 + 一次性子进程

命令行的办法不是去解释 ``config_root()``，而是**把它搬进一个一次性进程里跑**：

* 从源码里**按白名单摘**出那个表达式与它依赖的模块级语句（常量、``import os`` /
  ``from pathlib import Path``、它调用的那些函数），白名单之外一律**拒绝**；
* 把摘出来的片段拼成一个脚本交给 ``python -I -S -B -c``：``__file__`` 绑定到被扫的
  **那个文件**、``stdin`` 关掉、超时、只回一行 JSON。**库进程里不做任何动态执行** ——
  编译是子解释器自己干的，所以 ``src/`` 里没有 ``eval`` / ``exec`` / ``compile`` /
  ``__import__``；
* 子进程是**副作用与稳定性边界**，不是安全沙箱：那道门是白名单（能走进子进程的只有
  路径与环境计算），隔离负责的是"别把主进程搞脏、别让死循环挂住命令行"；
* 引擎的默认路径**不起子进程** —— 这条能力属于命令行这个"人发起的工具进程"。
  ``import onconf`` 那条路碰不到它：本模块只被 ``_cli`` 导入，``_engine`` 不导入它。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._engine import (
    DEFAULT_FILE_NAME,
    DEFAULT_FILE_TYPE,
    HOME_ENV,
    SNAPSHOT_NAME,
    SNAPSHOT_VERSION,
    _log_path,
    default_home,
)


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


#: 扫描时永远跳过的目录名（声明扫描与引导层扫描**共用这一份**跳过名单）。
SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".eggs",
        "node_modules",
        "site",
        "build",
        "dist",
    }
)

#: 命令行认的引导层参数。日志钩子（``log_rotate`` 之类）**不可记录**，不在这里。
BOOT_PARAMS = ("home", "file_name", "file_type", "no_one_file", "log_path")

#: 求值子进程的超时（秒）。解析一个路径不该要几秒。
_EVAL_TIMEOUT = 5.0

#: 摘取值时最多搬多少条模块级语句（挡住病态引用图把脚本撑爆）。
_MAX_EXTRACTED = 64

#: 摘出来的代码里允许出现的模块。
_ALLOWED_MODULES = frozenset({"os", "os.path", "pathlib"})

#: ``from pathlib import ...`` 允许的名字。
_ALLOWED_PATHLIB_NAMES = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "PosixPath", "WindowsPath"}
)

#: ``from os import ...`` 允许的名字。
_ALLOWED_OS_NAMES = frozenset({"environ", "getenv", "path", "sep", "name", "linesep", "curdir"})

#: 允许直接出现（以及被调用）的"环境名"：内建与 pathlib 的入口。
_ALLOWED_BUILTINS = frozenset({"str", "int", "float", "len"})
_ALLOWED_ROOTS = frozenset({"os", "pathlib"}) | _ALLOWED_PATHLIB_NAMES
_AMBIENT_NAMES = _ALLOWED_BUILTINS | _ALLOWED_ROOTS | {"__file__"}

#: ``os`` 上允许出现的属性路径。**`os.system` 这类一律不在表里**。
_ALLOWED_OS = frozenset(
    {
        "os.environ",
        "os.environ.get",
        "os.getenv",
        "os.path",
        "os.path.join",
        "os.path.abspath",
        "os.path.normpath",
        "os.path.expanduser",
        "os.path.expandvars",
        "os.path.dirname",
        "os.path.basename",
        "os.path.isabs",
        "os.path.realpath",
        "os.path.sep",
        "os.path.pardir",
        "os.sep",
        "os.name",
        "os.linesep",
        "os.curdir",
        "os.pardir",
    }
)

#: 允许出现在摘出来的片段里的节点类型。**不在表里的一律拒绝**（含循环、推导式、
#: ``lambda``、``try`` / ``with``、属性名以下划线开头的访问）。
_ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset(
    {
        ast.FunctionDef,
        ast.arguments,
        ast.arg,
        ast.Return,
        ast.If,
        ast.Pass,
        ast.Assign,
        ast.AnnAssign,
        ast.Import,
        ast.ImportFrom,
        ast.alias,
        ast.Constant,
        ast.Name,
        ast.Attribute,
        ast.Call,
        ast.keyword,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.IfExp,
        ast.Subscript,
        ast.Tuple,
        ast.List,
        ast.Slice,
        ast.JoinedStr,
        ast.FormattedValue,
        ast.Load,
        ast.Store,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Is,
        ast.IsNot,
    }
)


# --------------------------------------------------------------------------- #
# 扫描底座：与声明扫描共用
# --------------------------------------------------------------------------- #


def python_files(root: Path) -> Iterator[Path]:
    """项目里的 ``*.py``：目录与文件都按字典序，跳过 :data:`SKIP_DIRS`。"""
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(current) / name


def relative(path: Path, root: Path) -> str:
    """显示用路径：能相对就相对，不能就原样。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - 扫描到的路径都来自 root 之下
        return path.as_posix()


def read_module(path: Path, root: Path) -> tuple[ast.Module | None, str]:
    """读 + 解析一个源文件；读不动就回 ``(None, 一句问题)``。

    ``utf-8-sig``：带 BOM 的源文件在 CPython 里合法（tokenizer 会剥掉），而
    ``ast.parse`` 收到带 BOM 的**字符串**会直接报语法错误 —— 这里对齐前者。
    """
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{relative(path, root)}: cannot be read ({exc})"
    try:
        return ast.parse(source, filename=str(path)), ""
    except SyntaxError as exc:
        return None, f"{relative(path, root)}:{exc.lineno}: syntax error, cannot be scanned"


# --------------------------------------------------------------------------- #
# 扫描：项目里的 AutoConf(...)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BootDecl:
    """一次 ``AutoConf(...)`` 声明：字面量直接取到值，其余留节点待求值。"""

    where: str
    values: dict[str, Any]
    nodes: dict[str, ast.expr]
    path: Path
    tree: ast.Module


@dataclass
class BootScan:
    """一次引导层扫描：读到的声明，以及读不懂的地方。"""

    decls: list[BootDecl] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _auto_conf_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    """这个模块怎么拿到 ``AutoConf``：``(直接别名集合, 模块别名集合)``。"""
    direct: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "onconf":
            direct.update(
                alias.asname or alias.name for alias in node.names if alias.name == "AutoConf"
            )
        elif isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name for alias in node.names if alias.name == "onconf"
            )
    return direct, modules


def _is_auto_conf_call(func: ast.expr, direct: set[str], modules: set[str]) -> bool:
    """这个被调用的名字是不是 ``onconf.AutoConf``。"""
    if isinstance(func, ast.Name):
        return func.id in direct
    if isinstance(func, ast.Attribute) and func.attr == "AutoConf":
        return isinstance(func.value, ast.Name) and func.value.id in modules
    return False


def _literal(node: ast.expr) -> tuple[bool, Any]:
    """能不能静态求值；求不出来**不报错**，交给调用方去子进程里问。"""
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _read_boot_call(
    node: ast.Call, *, path: Path, tree: ast.Module, where: str
) -> BootDecl | str | None:
    """解读一次 ``AutoConf(...)``：只有引导层关键字进表，返回 ``None`` 表示没话可说。"""
    values: dict[str, Any] = {}
    nodes: dict[str, ast.expr] = {}
    for keyword in node.keywords:
        if keyword.arg is None:
            return "a call with `**kwargs` cannot be read statically"
        if keyword.arg not in BOOT_PARAMS:
            continue
        ok, value = _literal(keyword.value)
        if ok:
            values[keyword.arg] = value
        else:
            nodes[keyword.arg] = keyword.value
    if not values and not nodes:
        return None
    return BootDecl(where=where, values=values, nodes=nodes, path=path, tree=tree)


def scan_boot(root: Path) -> BootScan:
    """扫项目里的 ``AutoConf(...)``：只读参数结构，**不 import、不执行**。"""
    scan = BootScan()
    for path in python_files(root):
        tree, problem = read_module(path, root)
        if tree is None:
            scan.problems.append(problem)
            continue
        direct, modules = _auto_conf_aliases(tree)
        if not direct and not modules:
            continue
        calls = sorted(
            (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
            key=lambda node: (node.lineno, node.col_offset),
        )
        for node in calls:
            if not _is_auto_conf_call(node.func, direct, modules):
                continue
            where = f"{relative(path, root)}:{node.lineno}"
            decl = _read_boot_call(node, path=path, tree=tree, where=where)
            if decl is None:
                continue
            if isinstance(decl, str):
                scan.problems.append(f"{where}: {decl}")
                continue
            scan.decls.append(decl)
    return scan


# --------------------------------------------------------------------------- #
# 白名单：摘出来的片段里允许出现什么
# --------------------------------------------------------------------------- #


def _defined_names(node: ast.stmt) -> list[str]:
    """一条模块级语句定义了哪些名字。"""
    if isinstance(node, ast.Import):
        return [alias.asname or alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [alias.asname or alias.name for alias in node.names]
    if isinstance(node, ast.Assign):
        return [target.id for target in node.targets if isinstance(target, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    if isinstance(node, ast.FunctionDef):
        return [node.name]
    return []


def _os_dotted(node: ast.Attribute) -> str | None:
    """属性链从 ``os`` 起头时给出它的点分路径，否则 ``None``。"""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not (isinstance(current, ast.Name) and current.id == "os"):
        return None
    return "os." + ".".join(reversed(parts))


def _check_import(node: ast.Import | ast.ImportFrom) -> str:
    """只允许 ``os`` / ``os.path`` / ``pathlib`` 的读侧入口。"""
    if isinstance(node, ast.Import):
        bad = [alias.name for alias in node.names if alias.name not in _ALLOWED_MODULES]
        return f"import {bad[0]!r} is not allowed in a boot resolver" if bad else ""
    if node.level or node.module not in _ALLOWED_MODULES:
        return f"import from {node.module!r} is not allowed in a boot resolver"
    allowed = _ALLOWED_PATHLIB_NAMES if node.module == "pathlib" else _ALLOWED_OS_NAMES
    bad = [alias.name for alias in node.names if alias.name not in allowed]
    return f"import {bad[0]!r} is not allowed in a boot resolver" if bad else ""


def _check_attribute(node: ast.Attribute) -> str:
    """属性访问：**下划线开头的一律拒绝**，``os`` 起头的还得在白名单里。"""
    if node.attr.startswith("_"):
        return f"attribute {node.attr!r} is not allowed in a boot resolver"
    dotted = _os_dotted(node)
    if dotted is not None and dotted not in _ALLOWED_OS:
        return f"{dotted} is not allowed in a boot resolver"
    return ""


def _check_node(node: ast.AST, names: set[str]) -> str:
    """单个节点的一票否决；放行就给空串。"""
    if type(node) not in _ALLOWED_NODES:
        return f"{type(node).__name__} is not allowed in a boot resolver"
    if isinstance(node, ast.Import | ast.ImportFrom):
        return _check_import(node)
    if isinstance(node, ast.Attribute):
        return _check_attribute(node)
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id not in names:
            return f"name {node.id!r} is not available to a boot resolver"
        return ""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in names:
        return f"call to {node.func.id!r} is not allowed in a boot resolver"
    return ""


def _check(nodes: Sequence[ast.AST], names: set[str]) -> str:
    """整段片段过一遍白名单；**不认识的一律拒绝**。"""
    for node in nodes:
        for sub in ast.walk(node):
            problem = _check_node(sub, names)
            if problem:
                return problem
    return ""


def _available_names(chosen: Sequence[ast.stmt]) -> set[str]:
    """摘出来的片段里，哪些名字是可以读的。"""
    names: set[str] = set(_AMBIENT_NAMES)
    for stmt in chosen:
        names.update(_defined_names(stmt))
    return names | _local_names(chosen)


# --------------------------------------------------------------------------- #
# 摘取 + 求值
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Module:
    """一个模块里可摘的东西：按原顺序的模块级语句 + 名字 → 定义它的语句。"""

    path: Path
    order: list[ast.stmt]
    defines: dict[str, ast.stmt]


def _index_module(path: Path, tree: ast.Module) -> _Module:
    order: list[ast.stmt] = []
    defines: dict[str, ast.stmt] = {}
    for node in tree.body:
        order.append(node)
        for name in _defined_names(node):
            defines.setdefault(name, node)
    return _Module(path=path, order=order, defines=defines)


def _local_names(nodes: Sequence[ast.stmt]) -> set[str]:
    """摘出来的函数里**自己绑定**的名字：参数 + 赋值目标。

    它们是局部变量，不该再去模块级找定义（``from_env = os.environ.get(...)``）。
    """
    names: set[str] = set()
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                names.add(sub.id)
            elif isinstance(sub, ast.arg):
                names.add(sub.arg)
    return names


def _extract(module: _Module, expr: ast.expr) -> tuple[list[ast.stmt], str]:
    """表达式 → 要一起搬进子进程的模块级语句（按原顺序）。**缺东西就拒绝。**"""
    wanted: set[str] = set()
    pending: list[ast.AST] = [expr]
    while pending:
        node = pending.pop()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id not in wanted:
                wanted.add(sub.id)
                definition = module.defines.get(sub.id)
                if definition is not None:
                    pending.append(definition)
    chosen = [stmt for stmt in module.order if set(_defined_names(stmt)) & wanted]
    if len(chosen) > _MAX_EXTRACTED:
        return [], "too many module-level statements to extract"
    local = _local_names(chosen)
    missing = sorted(
        name
        for name in wanted
        if name not in module.defines and name not in _AMBIENT_NAMES and name not in local
    )
    if missing:
        return [], f"not defined in {module.path.name}: {missing}"
    return chosen, ""


def _build_script(module: _Module, expr: ast.expr, chosen: Sequence[ast.stmt], *, want: str) -> str:
    """拼出交给子解释器的脚本：``__file__`` 绑在被扫的那个文件上。"""
    body = "\n".join(ast.unparse(stmt) for stmt in chosen)
    return (
        "from __future__ import annotations\n"
        "import json\n"
        f"__file__ = {str(module.path)!r}\n"
        f"{body}\n"
        f"print(json.dumps({{'value': {want}({ast.unparse(expr)})}}))\n"
    )


def _run_child(script: str) -> tuple[bool, Any, str]:
    """把脚本交给一次性子解释器，回 ``(成功?, 值, 一句问题)``。"""
    if not sys.executable:  # pragma: no cover - 正常解释器一定有
        return False, None, "no interpreter is available to run the resolver"
    try:
        done = subprocess.run(  # noqa: S603 - 参数是列表，shell 不参与
            [sys.executable, "-I", "-S", "-B", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=_EVAL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, None, f"the resolver did not finish within {_EVAL_TIMEOUT:g}s"
    except OSError as exc:
        return False, None, f"cannot start the resolver process ({exc})"
    if done.returncode != 0:
        lines = (done.stderr or "").strip().splitlines()
        detail = lines[-1] if lines else f"exit code {done.returncode}"
        return False, None, f"the resolver failed: {detail}"
    try:
        value = json.loads(done.stdout.strip().splitlines()[-1])["value"]
    except (ValueError, KeyError, IndexError):
        return False, None, "the resolver did not return a value"
    return True, value, ""


def evaluate(
    expr: ast.expr, *, path: Path, tree: ast.Module, want: str = "str"
) -> tuple[bool, Any, str]:
    """求一个引导层表达式的值：**白名单摘取 + 一次性子进程**。"""
    module = _index_module(path, tree)
    chosen, problem = _extract(module, expr)
    if problem:
        return False, None, problem
    problem = _check([*chosen, expr], _available_names(chosen))
    if problem:
        return False, None, problem
    return _run_child(_build_script(module, expr, chosen, want=want))


# --------------------------------------------------------------------------- #
# 派生快照
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Snapshot:
    """``<home>/.onconf.json`` 读出来的一张表（已经过自检）。"""

    file_name: str
    file_type: str
    no_one_file: bool
    log_path: str
    declared_at: str
    recorded_at: str


def _same_path(left: str, right: Path) -> bool:
    """两个路径是不是同一个位置（Windows 上大小写不敏感）。"""
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(right.resolve()))


def _text(raw: dict[str, Any], name: str) -> str:
    """表里的一格字符串：不是字符串就当空串。"""
    value = raw.get(name)
    return value if isinstance(value, str) else ""


def read_snapshot(home: Path) -> Snapshot | None:
    """读 ``<home>/.onconf.json``；**坏表、旧版本、地址对不上，都当没有这张表**。"""
    try:
        raw = json.loads((home / SNAPSHOT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != SNAPSHOT_VERSION:
        return None
    recorded_home = raw.get("home")
    if not isinstance(recorded_home, str) or not _same_path(recorded_home, home):
        return None
    file_name = raw.get("file_name")
    file_type = raw.get("file_type")
    log_path = raw.get("log_path")
    no_one_file = raw.get("no_one_file")
    if not isinstance(file_name, str) or not isinstance(file_type, str):
        return None
    if not isinstance(log_path, str) or not isinstance(no_one_file, bool):
        return None
    return Snapshot(
        file_name=file_name,
        file_type=file_type,
        no_one_file=no_one_file,
        log_path=log_path,
        declared_at=_text(raw, "declared_at"),
        recorded_at=_text(raw, "recorded_at"),
    )


# --------------------------------------------------------------------------- #
# 解析：优先级与出处
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BootLayer:
    """这一次命令行实际采用的引导层，以及每个值的**出处**。

    ``durable`` 是「**该落表的值**」：只看代码 / 表 / 缺省三者，**显式参数不进表** ——
    否则一次 shell 调用就会改写下一次命令的缺省（见 ``docs/design/cli.md`` §1.2）。
    """

    home: Path
    file_name: str
    file_type: str
    no_one_file: bool
    log_path: str
    sources: dict[str, str]
    origin: str
    notes: list[str]
    problems: list[str]
    durable: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        """机器的形状：与 ``--json`` 的其余字段同源。"""
        return {
            "home": str(self.home),
            "file_name": self.file_name,
            "file_type": self.file_type,
            "no_one_file": self.no_one_file,
            "log_path": self.log_path,
            "sources": dict(self.sources),
            "origin": self.origin,
            "notes": list(self.notes),
            "problems": list(self.problems),
        }


def _usable(name: str, value: Any) -> Any:
    """类型不对的取值当没有 —— 与引擎构造时的判据同源，不在命令行这边放宽。"""
    if name == "no_one_file":
        return value if isinstance(value, bool) else None
    return value if isinstance(value, str) else None


def _declared(scan: BootScan) -> tuple[dict[str, Any], str, list[str]]:
    """把项目里的声明合并成一张取值表；说法不一致就出问题（不猜谁先执行）。"""
    values: dict[str, Any] = {}
    problems: list[str] = list(scan.problems)
    origin = ""
    for decl in scan.decls:
        local = dict(decl.values)
        for name, node in sorted(decl.nodes.items()):
            want = "bool" if name == "no_one_file" else "str"
            ok, value, problem = evaluate(node, path=decl.path, tree=decl.tree, want=want)
            if not ok:
                problems.append(f"{decl.where}: cannot resolve `{name}=` ({problem})")
                continue
            local[name] = value
        for name, value in sorted(local.items()):
            checked = _usable(name, value)
            if checked is None:
                problems.append(f"{decl.where}: `{name}=` is not usable ({value!r})")
                continue
            if name in values and values[name] != checked:
                problems.append(
                    f"`{name}=` is declared differently in more than one AutoConf(...) call"
                    f" ({decl.where})"
                )
                continue
            values[name] = checked
            origin = origin or decl.where
    return values, origin, problems


def _home_of(home: str | os.PathLike[str] | None, code: dict[str, Any]) -> tuple[Path, str]:
    """``home`` 的自举：显式参数 → 代码 → 环境变量 → 约定。**表帮不上忙。**"""
    if home is not None:
        return Path(home).resolve(), "flag"
    if "home" in code:
        return Path(code["home"]).resolve(), "code"
    if os.environ.get(HOME_ENV):
        return default_home(), "env"
    return default_home(), "default"


def _comparable(name: str, value: Any, home: Path) -> Any:
    """比较用的规范形态：``log_path`` 一律化成**绝对落点**。

    表里存的是引擎解析后的 ``self.log_path``，而代码里写的是 ``"logs/audit.log"`` 这种
    相对值 —— 直接比会永远"过期"。这不是放宽判据，是把两边放到同一个刻度上。
    """
    if name == "log_path" and isinstance(value, str):
        return str(_log_path(home, value))
    return value


def _pick(
    name: str,
    flag: Any,
    code: dict[str, Any],
    snapshot: Snapshot | None,
    default: Any,
    home: Path,
) -> tuple[Any, str, str, Any]:
    """一个引导层参数 → ``(取值, 出处, 一句"表过期了", 该落表的值)``。

    落表的值**不看显式参数**：命令行是管理者，一次 `--file-name` 是这一趟的意图，
    不该改写下一次命令的缺省。代码说了就记代码的，代码没说就沿用表里那份，再没有才是缺省。
    """
    if name in code:
        durable = code[name]
    elif snapshot is not None:
        durable = getattr(snapshot, name)
    else:
        durable = default
    if flag is not None:
        return flag, "flag", "", durable
    if name in code:
        note = ""
        if snapshot is not None and getattr(snapshot, name) != _comparable(name, code[name], home):
            note = (
                f"the boot snapshot is stale: the code says {name}={code[name]!r}, "
                f"the table says {getattr(snapshot, name)!r} — run the app once to refresh it"
            )
        return code[name], "code", note, durable
    if snapshot is not None:
        return getattr(snapshot, name), "snapshot", "", durable
    return default, "default", "", durable


def resolve_boot(
    root: Path,
    *,
    home: str | os.PathLike[str] | None = None,
    file_name: str | None = None,
    file_type: str | None = None,
    no_one_file: bool | None = None,
    log_path: str | None = None,
) -> BootLayer:
    """把三条路合成这一次实际采用的引导层（优先级见模块文档）。"""
    scan = scan_boot(root)
    code, origin, problems = _declared(scan)
    resolved_home, home_source = _home_of(home, code)
    unresolved_home = any("home" in decl.nodes for decl in scan.decls)
    if unresolved_home and home is None and "home" not in code:
        problems.append(
            f"cannot resolve `home=` statically: pass --home (falling back to {resolved_home})"
        )
    snapshot = read_snapshot(resolved_home)

    sources: dict[str, str] = {"home": home_source}
    notes: list[str] = []
    flags: dict[str, Any] = {
        "file_name": file_name,
        "file_type": file_type,
        "no_one_file": no_one_file,
        "log_path": log_path,
    }
    defaults: dict[str, Any] = {
        "file_name": DEFAULT_FILE_NAME,
        "file_type": DEFAULT_FILE_TYPE,
        "no_one_file": False,
        "log_path": "",
    }
    picked: dict[str, Any] = {}
    durable: dict[str, Any] = {"home": resolved_home}
    for name in ("file_name", "file_type", "no_one_file", "log_path"):
        value, source, note, kept = _pick(
            name, flags[name], code, snapshot, defaults[name], resolved_home
        )
        picked[name] = value
        durable[name] = kept
        sources[name] = source
        if note:
            notes.append(note)

    return BootLayer(
        home=resolved_home,
        file_name=picked["file_name"],
        file_type=picked["file_type"],
        no_one_file=picked["no_one_file"],
        log_path=picked["log_path"],
        sources=sources,
        origin=origin,
        notes=notes,
        problems=problems,
        durable=durable,
    )
