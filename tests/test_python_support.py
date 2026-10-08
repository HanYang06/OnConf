# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""Python 支持范围的契约：声明、工具链目标与 CI 矩阵必须是同一件事。

支持范围是公开契约（[路线图 2-080]），它在四个地方各落一次，任何一处单独漂移都会
造出「声明支持 3.11、实际只在 3.14 上验过」这种假承诺：

- ``pyproject.toml`` 的 ``requires-python``：安装期闸门；
- ``pyproject.toml`` 的 classifiers：PyPI 页面上对外的声明；
- ``pyproject.toml`` 的 ``ruff target-version`` 与 ``mypy python_version``：静态检查按哪个
  版本判定可用性；
- ``.github/workflows/ci.yml`` 的 test 矩阵：真的在哪些解释器上跑过。

这个文件只管上面四处**口径**是否一致。语法下界另有一道更锐的闸门：``ruff check`` 会把
PEP 695 / 701 / 758 这类新语法直接判成 ``invalid-syntax``（见 2-080），此处不重复造。

[路线图 2-080]: ../docs/roadmap/2.x.md
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent

#: 受支持的解释器，从下界到上界。这是一条**决定**，不是推导结果：
#: 公开契约变了才动它，并且必须与路线图 2-080 的记载一起改。
SUPPORTED = ("3.11", "3.12", "3.13", "3.14")

_PLATFORMS = ("ubuntu-latest", "windows-latest", "macos-latest")


def _pyproject() -> dict[str, Any]:
    """读一遍 ``pyproject.toml``（唯一事实源）。"""
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_declared_floor_is_the_lowest_supported_version() -> None:
    """``requires-python`` 只能是下界，不能偷偷抬高。"""
    assert _pyproject()["project"]["requires-python"] == f">={SUPPORTED[0]}"


def test_the_toolchain_targets_the_floor() -> None:
    """Ruff 与 mypy 按**下界**判定：写上界会放过只在 3.14 上成立的写法。"""
    config = _pyproject()
    floor = SUPPORTED[0]
    assert config["tool"]["ruff"]["target-version"] == f"py{floor.replace('.', '')}"
    assert config["tool"]["mypy"]["python_version"] == floor


def test_classifiers_declare_every_supported_version() -> None:
    """PyPI 上的声明要与支持范围逐条对上，不多也不少。"""
    classifiers = _pyproject()["project"]["classifiers"]
    declared = {
        classifier.rsplit(" ", 1)[-1]
        for classifier in classifiers
        if classifier.startswith("Programming Language :: Python :: 3.")
    }
    assert declared == set(SUPPORTED)


def test_ci_runs_the_suite_on_every_supported_version() -> None:
    """受支持的版本必须在三个平台上真的跑过，不能只声明。"""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    matrix = yaml.safe_load(text)["jobs"]["test"]["strategy"]["matrix"]
    assert set(matrix["python-version"]) == set(SUPPORTED)
    assert set(_PLATFORMS) <= set(matrix["os"])


def test_the_dev_pin_stays_inside_the_supported_range() -> None:
    """``.python-version`` 钉的是本地开发解释器，它本身也得是被支持的一个。"""
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() in SUPPORTED
