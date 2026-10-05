# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""安全不变量的回归测试。

这里守护的是 ``docs/security/threat-model.md`` 中声明为「不变量」的性质。
它们**不是功能测试**：失败意味着一条安全性质被破坏了，而不是某个功能坏了。

对应的不变量：

* 默认路径不开网络端口、不 spawn 子进程
* 只用 ``yaml.safe_load``，绝不 ``yaml.load``
* 不对配置内容做 ``eval`` / ``exec`` / ``pickle``
* **外部字符串（值文件名、键内嵌路径）到路径只经包含性校验**（D01 §3.5 / D02 §2）
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import onconf
from onconf import AutoConf, Engine, conf
from onconf._engine import default_home


_SRC_DIR = Path(onconf.__file__).parent

#: 源码中不得出现的模块（一旦出现即网络 / 反序列化 / 子进程面被打开）
_FORBIDDEN_MODULES = frozenset(
    {"socket", "socketserver", "pickle", "cPickle", "shelve", "marshal", "subprocess", "ctypes"}
)
#: 不得使用的 yaml 入口（``safe_load`` / ``safe_load_all`` 是允许的）
_FORBIDDEN_YAML_ATTRS = frozenset({"load", "load_all", "FullLoader", "UnsafeLoader", "CLoader"})
#: 不得出现的内建调用
_FORBIDDEN_BUILTINS = frozenset({"eval", "exec", "compile", "__import__"})

#: 文件名的非法形态：逐个都必须被包含性校验拒绝（D02 §2 验收）
_BAD_FILE_NAMES = ("..", ".", "a/b", "a\\b", "C:evil", "", "\x00")


def _module_asts() -> list[tuple[Path, ast.Module]]:
    """解析 ``src/onconf/`` 下每个模块的语法树（只读，不导入）。"""
    sources = sorted(_SRC_DIR.glob("*.py"))
    assert sources, f"没在 {_SRC_DIR} 下找到任何模块，测试本身失效了"
    return [(p, ast.parse(p.read_text(encoding="utf-8"))) for p in sources]


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


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


def test_values_path_is_derived_from_a_validated_name(tmp_path: Path) -> None:
    """值文件与 schema 的路径由**校验过的名字**派生，不由任何外部字符串直接拼接。"""
    engine = Engine(home=str(tmp_path), file_name="custom")
    assert engine.values_path.name == "custom.json"
    assert engine.values_path.parent == tmp_path.resolve()
    assert engine.schema_path.parent.name == "schema"
    assert engine.schema_path.name == "custom.json"


@pytest.mark.parametrize("bad", _BAD_FILE_NAMES)
def test_a_file_name_that_could_escape_the_home_is_refused(tmp_path: Path, bad: str) -> None:
    """包含性校验的第一道：``file_name`` 只能是纯文件名（D02 §2）。"""
    home = tmp_path / "conf"
    home.mkdir()
    with pytest.raises(onconf.ConfError, match="不合法"):
        Engine(home=home, file_name=bad)
    assert _files_under(home) == []


def test_key_name_cannot_escape_the_config_home(tmp_path: Path) -> None:
    """键名里塞 ``../`` 不得写出配置目录之外（T1）。

    多文件**关闭**时 ``:`` 根本不参与解析，整个字符串就是一个普通键 ——
    这是行为级验证：即使将来重构了寻址逻辑，也必须保持成立。
    """
    home = tmp_path / "conf"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    onconf._reset()
    AutoConf(home=str(home))
    conf("../../outside/escaped", 1)
    conf("..\\..\\outside\\escaped_win", 2)  # Windows 分隔符同样不得生效

    # 写出来的东西**全都在 home 里面**，一个都不许落到外面。
    # 用相对路径的 parts 比用文件名强：文件名相同不代表路径安全
    # （schema/settings.json 与 settings.json 同名），而且 parts 不看平台分隔符。
    written = sorted(p.relative_to(home) for p in home.rglob("*") if p.is_file())
    assert Path("settings.json") in written
    assert all(p.parts[0] in {"settings.json", "schema"} for p in written)
    assert all(".." not in p.parts for p in written)

    # 配置目录之外不得出现任何新文件
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "escaped.json").exists()
    assert not (tmp_path / "escaped_win.json").exists()

    onconf._reset()


@pytest.mark.parametrize("bad", ["../x:k", "/abs/x:k", "a/../../x:k", "a\\b:k"])
def test_multi_file_path_cannot_escape_the_config_home(tmp_path: Path, bad: str) -> None:
    """多文件**开启**时路径来自键字符串，必须整条被包含性校验挡住（T1 + D02 §1 验收）。"""
    home = tmp_path / "conf"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    onconf._reset()
    AutoConf(home=str(home), no_one_file=True)
    with pytest.raises(onconf.ConfError, match="不合法"):
        conf(bad, 1)

    assert _files_under(outside) == []
    assert list(home.glob("**/*.json")) == []
    onconf._reset()


def test_a_drive_letter_looking_key_stays_inside_the_home(tmp_path: Path) -> None:
    """``C:/x:k`` 按**第一个** ``:`` 切分：路径段是 ``C``、文件内键是 ``/x:k``。

    也就是说 Windows 盘符形态根本进不了路径层 —— 它会被当成一个普通文件名，
    文件落在 ``<home>/C.json``。这条用例把这个语义固定下来：不报错，但**也不越界**。
    """
    home = tmp_path / "conf"
    home.mkdir()

    onconf._reset()
    AutoConf(home=str(home), no_one_file=True)
    conf("C:/x:k", 1)

    written = _files_under(home)
    assert [p.name for p in written if p.suffix == ".json" and p.parent == home] == ["C.json"]
    assert all(p.resolve().is_relative_to(home.resolve()) for p in written)
    onconf._reset()


def test_home_env_is_only_a_trusted_bootstrap_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ONCONF_HOME`` 决定配置目录，且会被规范化（T2）。

    这条**不是**安全保证 —— 它只是把「环境变量是可信输入」这个前提固定下来：
    库不做目录包含性校验，所以调用方不得让不可信来源控制它。
    """
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.setenv("ONCONF_HOME", str(nested / ".." / "b"))

    resolved = default_home()
    assert resolved == nested.resolve()
    assert ".." not in str(resolved)
