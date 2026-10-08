# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""着色闸门的回归：判定顺序、非终端的逐字稳定、以及「关」永远排在「开」前面。

闸门本身只有两条职责 —— **能不能上色**与**怎么把一段文本套上语义**。所以这里不测具体
命令的输出形态（那是 ``test_cli.py`` 的活），只测判定表本身。
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

import pytest

from onconf import _style


if TYPE_CHECKING:
    from collections.abc import Iterator


ANSI = "\x1b["

#: 判定表要看的三个环境变量：每个用例都从「一个都没设」起步
_ENV_KNOBS = ("NO_COLOR", "FORCE_COLOR", "TERM")


class _FakeTty:
    """只回答一个问题：我是不是终端。"""

    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_slate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """每个用例都从「没设环境变量、``--color`` 缺省」起步。"""
    for name in _ENV_KNOBS:
        monkeypatch.delenv(name, raising=False)
    _style.configure(_style.COLOR_AUTO)
    yield
    _style.configure(_style.COLOR_AUTO)


def _on_a_tty(monkeypatch: pytest.MonkeyPatch, *, vt: bool = True) -> None:
    """把 ``stdout`` 伪装成终端，并替 Windows 回答「控制台支不支持 VT」。"""
    monkeypatch.setattr(sys, "stdout", _FakeTty())
    monkeypatch.setattr(_style, "_supports_virtual_terminal", lambda: vt)


class TestGate:
    def test_auto_on_a_pipe_stays_plain(self) -> None:
        assert _style.wants_color() is False

    def test_auto_on_a_tty_turns_colour_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _on_a_tty(monkeypatch)
        assert _style.wants_color() is True

    def test_auto_on_a_tty_without_vt_stays_plain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """老 conhost：宁可不上色，也不灌裸转义序列。"""
        _on_a_tty(monkeypatch, vt=False)
        assert _style.wants_color() is False

    def test_always_beats_a_pipe(self) -> None:
        _style.configure(_style.COLOR_ALWAYS)
        assert _style.wants_color() is True

    def test_never_beats_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _on_a_tty(monkeypatch)
        monkeypatch.setenv("FORCE_COLOR", "1")
        _style.configure(_style.COLOR_NEVER)
        assert _style.wants_color() is False

    def test_force_color_beats_a_pipe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert _style.wants_color() is True

    def test_no_color_is_read_before_force_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """两个都设时以「关」为准 —— 这是 ``NO_COLOR`` 的约定，也是更安全的一侧。"""
        _on_a_tty(monkeypatch)
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert _style.wants_color() is False

    def test_term_dumb_turns_it_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _on_a_tty(monkeypatch)
        monkeypatch.setenv("TERM", "dumb")
        assert _style.wants_color() is False

    def test_the_three_modes_are_the_public_surface(self) -> None:
        assert set(_style.COLOR_MODES) == {"auto", "always", "never"}


class TestPaint:
    def test_off_returns_the_text_unchanged(self) -> None:
        assert _style.paint("OK", _style.STYLE_OK) == "OK"

    def test_on_wraps_the_text_in_sgr(self) -> None:
        _style.configure(_style.COLOR_ALWAYS)
        painted = _style.paint("OK", _style.STYLE_OK)
        assert painted.startswith(ANSI)
        assert painted.endswith("\x1b[0m")
        assert _style.paint("OK", _style.STYLE_OK).count("OK") == 1

    def test_an_unknown_style_is_a_no_op(self) -> None:
        _style.configure(_style.COLOR_ALWAYS)
        assert _style.paint("x", "no-such-style") == "x"

    def test_empty_text_is_a_no_op(self) -> None:
        _style.configure(_style.COLOR_ALWAYS)
        assert _style.paint("", _style.STYLE_ERROR) == ""

    def test_the_stream_decides_in_auto_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺省看 ``stdout``，但也可以问另一个流（错误行走 ``stderr``）。"""
        _on_a_tty(monkeypatch)
        assert _style.paint("x", _style.STYLE_OK, stream=sys.stderr) == "x"


class TestVirtualTerminalProbe:
    def test_posix_always_supports_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_style, "_PLATFORM", "linux")
        assert _style._supports_virtual_terminal() is True

    def test_windows_reports_what_the_console_says(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_style, "_PLATFORM", "win32")
        monkeypatch.setitem(
            sys.modules, "nt", types.SimpleNamespace(_supports_virtual_terminal=lambda: True)
        )
        assert _style._supports_virtual_terminal() is True

    def test_windows_without_the_private_api_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``nt`` 里没有那个私有 C API 时按「不支持」办，不许猜。"""
        monkeypatch.setattr(_style, "_PLATFORM", "win32")
        monkeypatch.setitem(sys.modules, "nt", types.SimpleNamespace())
        assert _style._supports_virtual_terminal() is False

    def test_windows_with_a_non_callable_probe_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_style, "_PLATFORM", "win32")
        monkeypatch.setitem(
            sys.modules, "nt", types.SimpleNamespace(_supports_virtual_terminal=False)
        )
        assert _style._supports_virtual_terminal() is False
