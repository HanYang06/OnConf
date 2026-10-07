# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""命令行：``onconf build`` / ``onconf sync``。

## 声明从哪里来：**找 ``conf`` 这个函数，分析它的参数构成**

这个库的公开 API 只有一个使用口 ``conf(key, value=…, doc=…)``，参数结构与三种模式
一一对应。所以命令行不需要「加载并执行用户代码」这套新机制，也不需要约定
声明文件的格式：**在项目里找 ``conf(...)`` 调用，按参数形态解读**。

无歧义、可以直接对号入座的形态：

===============  ==========================  ====================
写法              解读                        进不进期望集
===============  ==========================  ====================
``conf(key)``     读                          否
``conf(key, v)``  声明 + 值                   是
``conf(key, v, d)``声明 + 值 + 说明           是
``conf(key, doc=…)`` 只登记（value 位空着）    是（无值）
``conf(key, value=…)`` 声明 + 值               是
===============  ==========================  ====================

``doc=`` 与第二个位置参数的区别，判据与使用口完全一致：**写没写 ``doc=``**。

**声明形态**里只有字面量能解读：``ast.literal_eval`` 求不出来的实参（变量、表达式、
循环里拼出来的键）**无法进入期望集**，会被逐条列出来。这不是缺陷，是静态扫描的边界，
摆清楚即可。**读取不受这条限制**：读取不产生任何持久状态，``conf(变量)`` 不进问题清单
（``docs/design/init_config.md`` §8）。

## 期望集不完整时怎么办

* ``sync``（**会删键**）：期望集不完整就**不清理**，直接以非 0 退出 —— 这是引擎
  「规则 1 只在期望集完整时才允许执行」那条正确性前提在命令行的落地。
  加 ``--no-clean`` 时只补缺、不删键，因此期望集不完整也不再危险，照常执行。
* ``build``（**重建值文件**）：重建本来就是「以声明为准」，所以照常执行、把读不懂的
  调用逐条打出来；先用 ``--dry-run`` 看一眼再决定。

## 默认范围：当前项目

不要求调用方告诉命令行「声明代码在哪」：既然在这个项目里，就默认整个项目都是候选。
``pyproject.toml`` / ``.gitignore`` 的收敛留给后续版本（见 ``docs/roadmap/2.x.md`` 的 2-056）；
现在只有一份固定的跳过名单（``.git`` / ``.venv`` / 缓存目录……），免得扫进依赖树。
这**不是**执行用户代码：只做 ``ast.parse``，不 import、不 eval。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _paths
from ._core import MISSING, NO_VALUE, Action, Decl, declaration_hash, undeclared
from ._engine import (
    _BACKENDS,
    _POINTER_CAPABLE,
    DEFAULT_FILE_NAME,
    DEFAULT_FILE_TYPE,
    OWNER_ENV,
    SCHEMA_DIR,
    Engine,
    _atomic_write_text,
    _detect_newline,
    _file_suffix,
    _schema_pointer,
    _values_path,
    default_home,
)
from ._vocab import Vocabulary
from .errors import ConfError


if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence


#: 扫描时永远跳过的目录名（依赖树、缓存、站点产物）。这不是「忽略规则」，
#: 只是免得把 ``.venv`` 里几十万个文件读一遍 —— 真正的收敛规则后续版本再谈。
_SKIP_DIRS = frozenset(
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

#: ``conf(...)`` 能认的参数名
_CONF_KEYWORDS = frozenset({"key", "value", "doc"})

#: 三个位置参数的下标（与使用口的签名一一对应）
_VALUE_POSITION = 1
_DOC_POSITION = 2
_MAX_POSITIONAL = 3

#: 一条 ``sync`` 计划里的动作类型 → 人类可读的动词
_ACTION_LABEL = {
    "clean": "delete",
    "fill": "fill",
    "register": "register",
    "update_meta": "update-meta",
    "skip": "keep",
}


@dataclass(frozen=True)
class Finding:
    """扫描到的一次声明。``value is MISSING`` ⇒ 只登记不给值。"""

    key: str
    value: Any = MISSING
    doc: str | None = None
    where: str = ""


@dataclass
class Scan:
    """一次项目扫描的结果。

    ``decls`` 是按扫描顺序去重后的期望集（同一个键后者覆盖前者）；
    ``problems`` 是读不懂的调用（会让期望集不完整）；``notes`` 是重复声明之类的提醒。
    """

    decls: list[Finding] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #


def _python_files(root: Path) -> Iterator[Path]:
    """项目里的 ``*.py``：目录与文件都按字典序，跳过 :data:`_SKIP_DIRS`。"""
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(current) / name


def _conf_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    """这个模块怎么拿到 ``conf``：``(直接别名集合, 模块别名集合)``。

    ``from onconf import conf`` / ``from onconf import conf as c`` ⇒ 直接别名；
    ``import onconf`` / ``import onconf as oc`` ⇒ 模块别名（``oc.conf(...)``）。
    """
    direct: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "onconf":
            direct.update(
                alias.asname or alias.name for alias in node.names if alias.name == "conf"
            )
        elif isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name for alias in node.names if alias.name == "onconf"
            )
    return direct, modules


def _is_conf_call(func: ast.expr, direct: set[str], modules: set[str]) -> bool:
    """这个被调用的名字是不是 ``onconf.conf``。"""
    if isinstance(func, ast.Name):
        return func.id in direct
    if isinstance(func, ast.Attribute) and func.attr == "conf":
        return isinstance(func.value, ast.Name) and func.value.id in modules
    return False


def _literal(node: ast.expr) -> tuple[bool, Any]:
    """能不能静态求值；求不出来**不报错**，交给调用方记成问题。"""
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _is_declaration(value_node: ast.expr | None, doc_node: ast.expr | None) -> bool:
    """这次调用是不是**声明形态** —— 与运行期的判据同源。

    运行期只看 ``value`` 位填没填（``value is MISSING and doc is None`` ⇒ 读，见
    ``docs/design/init_config.md`` §4）。这里在求值之前先做同一个判断：``value``
    有实参就是声明；``doc`` 有实参且不是字面 ``None`` 也算 —— ``doc=None`` 与没写
    ``doc`` 等价。
    """
    if value_node is not None:
        return True
    if doc_node is None:
        return False
    ok, raw = _literal(doc_node)
    return not (ok and raw is None)


def _read_call(node: ast.Call, where: str) -> Finding | str | None:
    """解读一次 ``conf(...)``：声明 / 读 / 一句问题。

    返回 ``None`` 表示这是**读**。读取不产生任何持久状态，因此**不受「声明处必须
    字面量」约束**，也不进期望集 —— 只有声明形态才需要那串键在声明点看得见
    （``docs/design/init_config.md`` §8）。
    """
    shape = _call_nodes(node)
    if isinstance(shape, str):
        return shape
    key_node, value_node, doc_node = shape

    if not _is_declaration(value_node, doc_node):
        return None  # 读：不进期望集，也不要求字面量

    ok, key = _literal(key_node)
    if not ok:
        return f"key is not a literal (line {key_node.lineno})"
    if not isinstance(key, str):
        return f"key is not a string (line {key_node.lineno}: got {type(key).__name__})"

    value: Any = MISSING
    if value_node is not None:
        ok, value = _literal(value_node)
        if not ok:
            return f"value of {key!r} is not a literal (line {value_node.lineno})"

    doc: str | None = None
    if doc_node is not None:
        ok, raw_doc = _literal(doc_node)
        if not ok:
            return f"doc of {key!r} is not a literal (line {doc_node.lineno})"
        if raw_doc is not None and not isinstance(raw_doc, str):
            return f"doc of {key!r} is not a string (got {type(raw_doc).__name__})"
        doc = raw_doc

    return Finding(key=key, value=value, doc=doc, where=where)


def _call_nodes(node: ast.Call) -> tuple[ast.expr, ast.expr | None, ast.expr | None] | str:
    """把一次 ``conf(...)`` 的三个位置摊开；形状不对就给一句问题。

    判据与使用口完全一致：第 2 位置是 ``value``，第 3 位置是 ``doc``；
    关键字写法只在**没写位置参数**时才顶上来（两者同时给就是写法冲突）。
    """
    if any(kw.arg is None for kw in node.keywords):
        return "a call with `**kwargs` cannot be read statically"
    keyword: dict[str, ast.expr] = {}
    for kw in node.keywords:
        if kw.arg is None:  # pragma: no cover - 上面那行已经挡了
            return "a call with `**kwargs` cannot be read statically"
        keyword[kw.arg] = kw.value
    unknown = set(keyword) - _CONF_KEYWORDS
    if unknown:
        return f"unknown parameter(s) {sorted(unknown)}"
    if len(node.args) > _MAX_POSITIONAL:
        return f"more than {_MAX_POSITIONAL} positional arguments ({len(node.args)} given)"
    if "value" in keyword and len(node.args) > _VALUE_POSITION:
        return "value given both positionally and as a keyword"

    key_node = node.args[0] if node.args else keyword.get("key")
    if key_node is None:
        return "no key"
    value_node = keyword.get("value")
    if value_node is None and len(node.args) > _VALUE_POSITION:
        value_node = node.args[_VALUE_POSITION]
    doc_node = keyword.get("doc")
    if doc_node is None and len(node.args) > _DOC_POSITION:
        doc_node = node.args[_DOC_POSITION]
    return key_node, value_node, doc_node


def scan_project(root: Path) -> Scan:
    """扫描项目里的 ``conf(...)`` 调用，得到期望集与读不懂的调用清单。"""
    scan = Scan()
    merged: dict[str, Finding] = {}
    for path in _python_files(root):
        try:
            # ``utf-8-sig``：带 BOM 的源文件在 CPython 里是合法的（tokenizer 会剥掉），
            # 而 ``ast.parse`` 收到带 BOM 的**字符串**会直接报语法错误 —— 这里对齐前者。
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            scan.problems.append(f"{_relative(path, root)}: cannot be read ({exc})")
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            scan.problems.append(
                f"{_relative(path, root)}:{exc.lineno}: syntax error, cannot be scanned"
            )
            continue

        direct, modules = _conf_aliases(tree)
        if not direct and not modules:
            continue

        calls = sorted(
            (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
            key=lambda node: (node.lineno, node.col_offset),
        )
        for node in calls:
            if not _is_conf_call(node.func, direct, modules):
                continue
            where = f"{_relative(path, root)}:{node.lineno}"
            outcome = _read_call(node, where)
            if outcome is None:
                continue
            if isinstance(outcome, str):
                scan.problems.append(f"{where}: {outcome}")
                continue
            previous = merged.get(outcome.key)
            if previous is None:
                merged[outcome.key] = outcome
                continue
            if previous.value != outcome.value:
                scan.notes.append(
                    f"{outcome.key!r} is declared more than once; {where} wins "
                    f"(previous: {previous.where})"
                )
            merged[outcome.key] = outcome

    scan.decls = list(merged.values())
    return scan


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - 扫描到的路径都来自 root 之下
        return path.as_posix()


# --------------------------------------------------------------------------- #
# 期望集 → 声明 / 动作
# --------------------------------------------------------------------------- #


def _split(key: str, *, multi: bool) -> tuple[str, str]:
    """与 :meth:`onconf._engine.Engine._address` 同一套寻址规则。"""
    if multi and ":" in key:
        path_part, inner = key.split(":", 1)
        return path_part, inner
    return "", key


def _to_decls(scan: Scan, *, multi: bool) -> list[Decl]:
    """扫描结果 → ``Decl``。非法路径段在这里就报错，不等到落盘那一刻。"""
    decls: list[Decl] = []
    for finding in scan.decls:
        path_part, _ = _split(finding.key, multi=multi)
        if path_part:
            _paths.relative_parts(path_part)
        decls.append(
            Decl(key=finding.key, value=finding.value, doc=finding.doc, at=finding.where)
        )
    return decls


def _show(one: Any) -> Any:
    """哨兵不进 JSON：``MISSING`` / ``NO_VALUE`` 都写成 ``null``。"""
    return None if one is MISSING or one is NO_VALUE else one


def _finding_json(finding: Finding) -> dict[str, Any]:
    return {
        "key": finding.key,
        "value": _show(finding.value),
        "has_value": finding.value is not MISSING,
        "doc": finding.doc,
        "where": finding.where,
    }


def _action_json(action: Action) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "key": action.key,
        "value": _show(action.value),
        "old": _show(action.old),
        "reason": action.reason,
    }


# --------------------------------------------------------------------------- #
# build：完整重建
# --------------------------------------------------------------------------- #


def _build(
    out: Path,
    *,
    file_name: str,
    file_type: str,
    multi: bool,
    decls: Sequence[Decl],
    dry_run: bool,
) -> list[dict[str, Any]]:
    """把声明集**完整重建**成值文件 + 词表，返回这次写下的计划。

    「完整重建」= 产物里只有声明集：值文件从后端种子起步逐键追加，词表整篇重写。
    这与运行期的「只补缺」是两件事，所以它落在命令行、由人发起。
    """
    suffix = _file_suffix(file_type)
    backend = _BACKENDS[suffix]
    schema_target = _schema_path(out, file_name)

    groups: dict[str, list[Decl]] = {}
    for decl in decls:
        groups.setdefault(_split(decl.key, multi=multi)[0], []).append(decl)

    plan: list[dict[str, Any]] = []
    for path_part, group in sorted(groups.items()):
        name = path_part or file_name
        target = _values_path(out, name, suffix)
        text = backend.EMPTY_TEXT
        if suffix in _POINTER_CAPABLE:
            text = backend.append_key(text, "$schema", _schema_pointer(target, schema_target))
        written = 0
        for decl in group:
            if decl.value is MISSING:
                continue
            text = backend.append_key(text, _split(decl.key, multi=multi)[1], decl.value)
            written += 1
        plan.append({"kind": "rebuild", "file": _relative(target, out), "keys": written})
        if not dry_run:
            newline = _detect_newline(target.read_bytes()) if target.exists() else "\n"
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(target, text, newline=newline)

    vocab = Vocabulary()
    for decl in decls:
        vocab.register(decl)
    vocab.hash = declaration_hash(list(decls))
    plan.append({"kind": "vocabulary", "file": _relative(schema_target, out), "keys": len(vocab)})
    if not dry_run:
        schema_target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            schema_target,
            json.dumps(vocab.to_schema(), indent=2, ensure_ascii=False) + "\n",
            newline="\n",
        )
    return plan


def _schema_path(home: Path, file_name: str) -> Path:
    """词表路径：``<home>/schema/<file_name>.json``（与引擎同一套命名）。"""
    return home / SCHEMA_DIR / f"{file_name}.json"


# --------------------------------------------------------------------------- #
# sync：温和收敛
# --------------------------------------------------------------------------- #


def _sync_plan(engine: Engine, decls: Sequence[Decl], *, clean: bool) -> list[Action]:
    """**不写一个字节**地算出这次 ``sync`` 会做什么（``--dry-run`` 与预览共用）。

    收敛 = 运行期那套对账（补缺 / 补元数据）**加上**删除未声明的键。删除只在命令行
    这条路径上发生：它的判据是「事实里有、声明集里没有」，而这里的声明集是**完整**的
    —— 静态扫描整个项目的产物。运行期永远拿不到完整声明集，所以运行期不删
    （见 ``docs/design/concurrency.md``）。
    """
    engine._ensure_loaded()  # noqa: SLF001 - 同包内部：只借用「把事实读进内存」这一步
    actions = engine._reconcile_all(list(decls))  # noqa: SLF001
    if clean:
        actions.extend(undeclared(engine._facts_view(), {d.key for d in decls}))  # noqa: SLF001
    return actions


def _run_sync(
    engine: Engine,
    decls: Sequence[Decl],
    *,
    clean: bool,
    dry_run: bool,
) -> list[Action]:
    """先算计划、再执行；返回的是**执行前算出来的**那份计划。"""
    plan = _sync_plan(engine, decls, clean=clean)
    if dry_run:
        return plan
    for decl in decls:
        engine.declare(decl.key, decl.value, decl.doc)
    engine.flush()
    if clean:
        engine._remove_undeclared()  # noqa: SLF001 - 删除只挂在命令行这条路径上
    return plan


# --------------------------------------------------------------------------- #
# 输出与入口
# --------------------------------------------------------------------------- #


def _print_human(payload: dict[str, Any]) -> None:
    print(f"onconf {payload['command']}")  # noqa: T201 - 命令行的输出就是它的职责
    print(f"  home        : {payload['home']}")  # noqa: T201
    print(f"  values      : {payload['file_name']}{payload['file_suffix']}")  # noqa: T201
    if payload["multi_file"]:
        print("  multi-file  : on (the `<path>:` prefix in a key decides the file)")  # noqa: T201
    if payload.get("output"):
        print(f"  output      : {payload['output']}")  # noqa: T201
    for item in payload["declarations"]:
        value = repr(item["value"]) if item["has_value"] else "(registered, no value)"
        print(f"  declared    : {item['key']} = {value}   [{item['where']}]")  # noqa: T201
    for item in payload["plan"]:
        if "key" in item:
            label = _ACTION_LABEL.get(item["kind"], item["kind"])
            print(f"  {label:<12}: {item['key']}  {item.get('reason', '')}".rstrip())  # noqa: T201
        else:
            print(f"  {item['kind']:<12}: {item['file']}  ({item['keys']} keys)")  # noqa: T201
    for problem in payload["problems"]:
        print(f"  ! unreadable: {problem}")  # noqa: T201
    for note in payload["notes"]:
        print(f"  · note      : {note}")  # noqa: T201
    if payload["dry_run"]:
        print("  (--dry-run: nothing was written)")  # noqa: T201
    print(f"  total       : {payload['summary']}")  # noqa: T201


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))  # noqa: T201
    else:
        _print_human(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """``onconf`` 的入口：目前只有 ``build`` / ``sync``（其余命令尚未实现）。

    命令行是**人 / CI 发起的配置管理者**，所以它清掉 ``ONCONF_OWNER_PID``：被一个属主
    进程 shell 出来跑的时候，它不该被当成那个属主的派生进程而只读 —— 「想更新，拿命令行去」
    这句话得成立。命令行不跟运行中的进程协调（那是调用方的部署责任）。
    """
    os.environ.pop(OWNER_ENV, None)
    args = _parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except ConfError as exc:
        print(f"onconf: {exc}", file=sys.stderr)  # noqa: T201
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onconf", description="the OnConf command line")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--home", default=None, help="config directory (default ./conf or ONCONF_HOME)"
        )
        target.add_argument("--file-name", default=DEFAULT_FILE_NAME, help="value file name stem")
        target.add_argument("--file-type", default=DEFAULT_FILE_TYPE, help="value file type")
        target.add_argument(
            "--no-one-file", action="store_true", help="multi-file: a key carries its path"
        )
        target.add_argument(
            "--dry-run", action="store_true", help="print what would happen; write nothing"
        )
        target.add_argument("--json", action="store_true", help="machine-readable output")

    build = sub.add_parser("build", help="rebuild the value file(s) and the vocabulary")
    common(build)
    build.add_argument(
        "--path", default=None, help="write the rebuild here; the original stays untouched"
    )
    build.set_defaults(handler=_cmd_build)

    sync = sub.add_parser(
        "sync", help="converge to the declarations: fill, and delete undeclared keys"
    )
    common(sync)
    sync.add_argument("--no-clean", action="store_true", help="fill only; delete nothing")
    sync.set_defaults(handler=_cmd_sync)
    return parser


def _base_payload(args: argparse.Namespace) -> dict[str, Any]:
    home = Path(args.home).resolve() if args.home else default_home()
    return {
        "command": args.command,
        "home": str(home),
        "file_name": args.file_name,
        "file_type": args.file_type,
        "file_suffix": _file_suffix(args.file_type),
        "multi_file": bool(args.no_one_file),
        "dry_run": bool(args.dry_run),
        "declarations": [],
        "plan": [],
        "problems": [],
        "notes": [],
        "summary": "",
    }


def _scan_payload(payload: dict[str, Any]) -> Scan:
    scan = scan_project(Path.cwd())
    payload["declarations"] = [_finding_json(item) for item in scan.decls]
    payload["problems"] = scan.problems
    payload["notes"] = scan.notes
    return scan


def _cmd_build(args: argparse.Namespace) -> int:
    payload = _base_payload(args)
    scan = _scan_payload(payload)
    decls = _to_decls(scan, multi=args.no_one_file)

    out = Path(args.path).resolve() if args.path else Path(payload["home"])
    payload["output"] = str(out)
    payload["plan"] = _build(
        out,
        file_name=args.file_name,
        file_type=args.file_type,
        multi=args.no_one_file,
        decls=decls,
        dry_run=args.dry_run,
    )
    files = sum(1 for item in payload["plan"] if item["kind"] == "rebuild")
    payload["summary"] = (
        f"rebuilt {len(decls)} declaration(s) into {files} value file(s) -> {out}"
        + (" (--dry-run preview)" if args.dry_run else "")
    )
    _emit(payload, as_json=args.json)
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    payload = _base_payload(args)
    scan = _scan_payload(payload)
    decls = _to_decls(scan, multi=args.no_one_file)
    clean = not args.no_clean

    if clean and scan.problems:
        payload["summary"] = (
            f"incomplete declaration set ({len(scan.problems)} unreadable call(s)): "
            "refusing to delete any key; add --no-clean, or make those calls literal"
        )
        _emit(payload, as_json=args.json)
        return 1

    engine = Engine(
        payload["home"],
        file_name=args.file_name,
        file_type=args.file_type,
        no_one_file=args.no_one_file,
    )
    try:
        actions = _run_sync(engine, decls, clean=clean, dry_run=args.dry_run)
    finally:
        engine.close()

    payload["plan"] = [_action_json(action) for action in actions]
    payload["clean"] = clean
    payload["summary"] = (
        f"{_count_kinds(actions)}; "
        + ("deleted undeclared keys" if clean else "deleted nothing (--no-clean)")
        + (" (--dry-run preview)" if args.dry_run else "")
    )
    _emit(payload, as_json=args.json)
    return 0


def _count_kinds(actions: Sequence[Action]) -> str:
    if not actions:
        return "nothing to do"
    counts: dict[str, int] = {}
    for action in actions:
        counts[action.kind] = counts.get(action.kind, 0) + 1
    return ", ".join(f"{kind} x{count}" for kind, count in sorted(counts.items()))


if __name__ == "__main__":  # pragma: no cover - 控制台脚本走 entry point
    raise SystemExit(main())
