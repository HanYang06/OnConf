# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""命令行人读渲染的**着色闸门**：判定在一处，样式在一处。

三条边界，别越过：

* **只给语义上色** —— 状态、问题类别、破坏性动词。键名、路径、值与列宽一个都不动；
  颜色是给人读的那条路的装饰，``--json`` 与一切落盘字节**永不经过这里**；
* **非 TTY 一个 ANSI 都不许漏**（与日志的控制台出口同一条口径，见
  ``docs/design/log.md`` §4）：管道、CI 日志、测试捕获里必须是逐字稳定的纯文本；
* **判定与标准库自己的 ``--help`` 着色同源** —— 都认 ``NO_COLOR`` / ``FORCE_COLOR`` /
  ``TERM=dumb``。差别只在闸门：``--color`` 是我们自己的开关，管的是**命令输出**；
  ``--help`` 的渲染归 ``argparse``，不归这里。

``--color=auto`` 的判定顺序：``NO_COLOR`` → ``TERM=dumb`` → ``FORCE_COLOR`` →
是不是终端 → Windows 上控制台支不支持 VT。**「关」排在「开」前面**：宁可不上色，
也不往老 conhost 里灌裸转义序列。
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from typing import TextIO


#: ``--color`` 的三个取值：``auto`` 看终端，``always`` / ``never`` 说了算。
COLOR_AUTO = "auto"
COLOR_ALWAYS = "always"
COLOR_NEVER = "never"

#: 合法取值（``argparse`` 的 ``choices`` 直接用它）
COLOR_MODES = (COLOR_AUTO, COLOR_ALWAYS, COLOR_NEVER)

#: 语义名 —— 调用方只说「这是什么」，不说「用什么颜色」。
STYLE_OK = "ok"
STYLE_ERROR = "error"
STYLE_WARNING = "warning"
STYLE_NOTE = "note"

#: 语义 → SGR 码。**只给语义上色**，不给「好看」上色。
_SGR: dict[str, str] = {
    STYLE_OK: "32",  # 绿：写下去了、一切正常
    STYLE_ERROR: "1;31",  # 粗红：失败、破坏性
    STYLE_WARNING: "33",  # 黄：对不上，但还没动字节
    STYLE_NOTE: "2",  # 暗：说明、跳过
}

_RESET = "\x1b[0m"

_mode = COLOR_AUTO

#: 运行期平台。**显式标成 ``str``**：mypy 会把 ``sys.platform`` 当字面量、按目标平台收窄，
#: 于是另一侧的分支被判成「不可达」（CI 在 Linux 上跑，Windows 那一段就红）。这个判定两边
#: 都要留活口；真机行为由 ``tests/test_style.py`` 的平台用例守着。
_PLATFORM: str = sys.platform


def configure(mode: str) -> None:
    """记下这一次调用的 ``--color``（``main`` 解析完参数后调一次）。"""
    global _mode  # noqa: PLW0603 - 一个进程一次调用，存的就这一次的取值
    _mode = mode


def wants_color(stream: TextIO | None = None) -> bool:
    """这次输出到底上不上色。``stream`` 缺省是 ``stdout``。"""
    if _mode == COLOR_NEVER:
        return False
    if _mode == COLOR_ALWAYS:
        return True
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    target = sys.stdout if stream is None else stream
    # 先问 isatty（便宜），再问 VT（Windows 上要碰一次控制台句柄）
    if not (getattr(target, "isatty", None) and target.isatty()):
        return False
    return _supports_virtual_terminal()


def paint(text: str, style: str, *, stream: TextIO | None = None) -> str:
    """给一段文本套上语义样式；不上色（或样式不认识）时**原样返回**。

    原样返回是关键：非 TTY 那条路与上色前**逐字相同**，所以每种渲染只需要写一遍 ——
    纯文本那份不用另开一条分支。
    """
    sgr = _SGR.get(style)
    if sgr is None or not text or not wants_color(stream):
        return text
    return f"\x1b[{sgr}m{text}{_RESET}"


def _supports_virtual_terminal() -> bool:
    """Windows：问一次控制台支不支持 VT 序列（顺带把它打开）。

    与标准库 ``_colorize.can_colorize`` 同一套判定，用的是 ``nt`` 里那个私有 C API
    —— typeshed 还没给它名字，所以按名字取；取不到就当**不支持**。
    宁可不上色，也不往老 conhost 里灌裸转义序列。
    """
    if _PLATFORM != "win32":
        return True
    import nt  # noqa: PLC0415 - 只在 Windows 的终端判定里问一次，不进 import 图

    probe = getattr(nt, "_supports_virtual_terminal", None)
    if not callable(probe):
        return False
    return bool(probe())
