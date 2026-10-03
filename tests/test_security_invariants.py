# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""安全不变量的回归测试。

这里守护的是 ``docs/security/threat-model.md`` 中声明为「不变量」的性质。
它们**不是功能测试**：失败意味着一条安全性质被破坏了，而不是某个功能坏了。

对应的不变量：

* 默认路径不开网络端口、不 spawn 子进程
* 只用 ``yaml.safe_load``，绝不 ``yaml.load``
* 不对配置内容做 ``eval`` / ``exec`` / ``pickle``
* 键名永不参与文件路径拼接
* 值文件路径只来自固定白名单
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import auto_conf
from auto_conf import AutoConf, Engine, conf
from auto_conf._engine import default_home


if TYPE_CHECKING:
    import pytest


_SRC = Path(auto_conf.__file__).parent

#: 源码中不得出现的模块（一旦出现即网络 / 反序列化 / 子进程面被打开）
_FORBIDDEN_MODULES = frozenset(
    {"socket", "socketserver", "pickle", "cPickle", "shelve", "marshal", "subprocess", "ctypes"}
)
#: 不得使用的 yaml 入口（``safe_load`` / ``safe_load_all`` 是允许的）
_FORBIDDEN_YAML_ATTRS = frozenset({"load", "load_all", "FullLoader", "UnsafeLoader", "CLoader"})
#: 不得出现的内建调用
_FORBIDDEN_BUILTINS = frozenset({"eval", "exec", "compile", "__import__"})
#: 值文件名的固定白名单（来自 ``_engine._VALUES_CANDIDATES``）
_VALUES_WHITELIST = frozenset({"settings.json", "settings.yaml", "settings.yml", "settings.env"})


def _module_asts() -> list[tuple[Path, ast.Module]]:
    """解析 ``src/auto_conf/`` 下每个模块的语法树（只读，不导入）。"""
    sources = sorted(_SRC.glob("*.py"))
    assert sources, f"没在 {_SRC} 下找到任何模块，测试本身失效了"
    return [(p, ast.parse(p.read_text(encoding="utf-8"))) for p in sources]


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_forbidden_modules_are_imported() -> None:
    """不开网络 / 不反序列化 / 不起子进程 —— 这三条是身份问题（DESIGN §26.3）。"""
    offenders: list[str] = []
    for path, tree in _module_asts():
        bad = _imported_roots(tree) & _FORBIDDEN_MODULES
        if bad:
            offenders.append(f"{path.name}: {sorted(bad)}")
    assert not offenders, "源码引入了被禁模块：\n" + "\n".join(offenders)


def test_yaml_is_only_ever_loaded_safely() -> None:
    """配置文件是不可信输入，反序列化不能变成任意对象构造。

    同时挡住 ``import yaml`` 之后的 ``yaml.load(...)`` 与 ``from yaml import load``。
    """
    offenders: list[str] = []
    for path, tree in _module_asts():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in _FORBIDDEN_YAML_ATTRS
                and isinstance(node.value, ast.Name)
                and node.value.id == "yaml"
            ):
                offenders.append(f"{path.name}:{node.lineno} yaml.{node.attr}")
            elif isinstance(node, ast.ImportFrom) and node.module == "yaml":
                offenders.extend(
                    f"{path.name}:{node.lineno} from yaml import {alias.name}"
                    for alias in node.names
                    if alias.name in _FORBIDDEN_YAML_ATTRS
                )
    assert not offenders, "出现了不安全的 YAML 入口：\n" + "\n".join(offenders)


def test_config_content_is_never_dynamically_executed() -> None:
    """不对配置内容做 eval / exec / compile / import。"""
    offenders: list[str] = []
    for path, tree in _module_asts():
        offenders.extend(
            f"{path.name}:{node.lineno} {node.func.id}()"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FORBIDDEN_BUILTINS
        )
    assert not offenders, "出现了动态执行调用：\n" + "\n".join(offenders)


def test_values_path_always_comes_from_the_whitelist(tmp_path: Path) -> None:
    """值文件与 schema 的路径由固定白名单推导，不由任何外部字符串拼接。"""
    engine = Engine(home=str(tmp_path))
    assert engine.values_path.name in _VALUES_WHITELIST
    assert engine.values_path.parent == tmp_path.resolve()
    assert engine.schema_path.parent.name == "schema"
    assert engine.schema_path.name in {f"{n.rsplit('.', 1)[0]}.json" for n in _VALUES_WHITELIST}


def test_key_name_cannot_escape_the_config_home(tmp_path: Path) -> None:
    """键名里塞 ``../`` 不得写出配置目录之外（T1）。

    这是行为级验证：即使将来重构了寻址逻辑，也必须保持成立。
    """
    home = tmp_path / "conf"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    auto_conf._reset()
    AutoConf(home=str(home))
    conf("../../outside/escaped", 1)
    conf("..\\..\\outside\\escaped_win", 2)  # Windows 分隔符同样不得生效

    # 写出来的东西**全都在 home 里面**，一个都不许落到外面。
    # 用相对路径的 parts 比用文件名强：文件名相同不代表路径安全
    #（schema/settings.json 与 settings.json 同名），而且 parts 不看平台分隔符。
    written = sorted(p.relative_to(home) for p in home.rglob("*") if p.is_file())
    assert Path("settings.json") in written
    assert all(p.parts[0] in {"settings.json", "schema"} for p in written)
    assert all(".." not in p.parts for p in written)

    # 配置目录之外不得出现任何新文件
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "escaped.json").exists()
    assert not (tmp_path / "escaped_win.json").exists()

    auto_conf._reset()


def test_home_env_is_only_a_trusted_bootstrap_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``AUTO_CONF_HOME`` 决定配置目录，且会被规范化（T2）。

    这条**不是**安全保证 —— 它只是把「环境变量是可信输入」这个前提固定下来：
    库不做目录包含性校验，所以调用方不得让不可信来源控制它。
    """
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.setenv("AUTO_CONF_HOME", str(nested / ".." / "b"))

    resolved = default_home()
    assert resolved == nested.resolve()
    assert ".." not in str(resolved)
