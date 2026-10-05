# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""包含性校验的回归。

这些用例守护的是**唯一入口**：外部字符串（文件名、键里内嵌的路径）到路径的转换
只能经过 :mod:`onconf._paths`，五条规则逐条有一个反例。规则本身很短，漏一条的
后果是写入落到配置目录之外 —— 那是安全性质，不是功能缺陷。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from onconf._paths import file_name_stem, relative_parts, values_path
from onconf.errors import ConfError


if TYPE_CHECKING:
    from pathlib import Path


class TestFileName:
    def test_a_plain_name_passes_through(self, tmp_path: Path) -> None:
        assert file_name_stem("settings") == "settings"
        assert values_path(tmp_path, "settings", ".json") == tmp_path / "settings.json"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            ".",
            "..",
            "a/b",
            "a\\b",
            "C:x",
            "x\x00y",
        ],
    )
    def test_every_shape_is_rejected(self, bad: str) -> None:
        with pytest.raises(ConfError, match="不合法"):
            file_name_stem(bad)


class TestRelativeParts:
    def test_a_relative_path_is_split(self) -> None:
        assert relative_parts("app/conf/net") == ("app", "conf", "net")

    def test_a_single_segment_is_a_relative_path_too(self) -> None:
        assert relative_parts("net") == ("net",)

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "/etc/passwd",
            "a/../../x",
            "a//b",
            "./a",
            "a/",
            "a\\b",
            "C:/x",
            "a\x00b",
            "..",
        ],
    )
    def test_every_shape_is_rejected(self, bad: str) -> None:
        with pytest.raises(ConfError, match="不合法"):
            relative_parts(bad)


class TestValuesPath:
    def test_the_suffix_lands_on_the_last_segment(self, tmp_path: Path) -> None:
        assert values_path(tmp_path, "app/conf/net", ".toml") == tmp_path / "app/conf/net.toml"

    def test_no_file_lands_outside_the_home(self, tmp_path: Path) -> None:
        home = tmp_path / "conf"
        home.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        for bad in ("../outside/x", "a/../../outside/x", "/etc/passwd"):
            with pytest.raises(ConfError, match="不合法"):
                values_path(home, bad, ".json")
        assert list(outside.iterdir()) == []

    def test_a_symlink_pointing_outside_is_refused(self, tmp_path: Path) -> None:
        """解析之后越界同样拒绝：既有的符号链接会被 ``resolve()`` 展开。"""
        home = tmp_path / "conf"
        home.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = home / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):  # pragma: no cover - 平台/权限不给建链
            pytest.skip("本机无法创建目录符号链接")

        with pytest.raises(ConfError, match="越出配置目录"):
            values_path(home, "link/x", ".json")
