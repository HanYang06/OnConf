# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
""".env / 环境变量风格的值后端：读出 + **外科手术式回写**。

## 它是**字符串后端**，这条必须说在前面

``.env`` 物理上只能存字符串。所以它**不参与**「写出去什么，读回来还是它」这条保证——
与其假装能做到，不如当场拒绝：

* ``render()`` 只接受 ``str``，别的类型直接报错并指路「请用 JSON / YAML 值文件」；
* ``loads()`` 读回来的一律是 ``str``，**不做类型推断**（透明原则：引擎不解释值）。

要整数就自己 ``int(conf("PORT"))`` —— 显式，且一眼看得出在转换。

## 与 YAML 后端的两处刻意的不同

1. **不认行内注释**。``#`` 只在**整行**（前面只有空白）时才是注释。
   理由：``.env`` 里放密码是常态，``PASSWORD=abc#def`` 的 ``#`` 是值的一部分。
   （YAML 那边认行内注释，因为 YAML 规范就是那么定的。）
2. **不做键名转换**。键就是文件里写的那个名字（``pack.max.byte=1`` 或 ``PACK_MAX_BYTE=1``
   都行，**不作映射**）。有损的 ``.`` ↔ ``_`` 映射留给词表的显式映射，不在后端里猜。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Iterator


_WS = " \t"

#: 新建值文件时的**种子文本**：``.env`` 的空文件本身就是合法骨架。
EMPTY_TEXT = ""

#: ``[空白][export ][键][空白]=[空白][值]``
_LINE = re.compile(
    r"^(?P<prefix>[ \t]*(?:export[ \t]+)?)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_.\-]*)"
    r"(?P<sep>[ \t]*=[ \t]*)"
    r"(?P<value>.*)$"
)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}

#: 一对引号最少占两个字符
_MIN_QUOTED = 2

#: 需要加引号的情形：含空白、引号或反斜杠。
#:
#: **刻意不含 ``#``** —— 本后端不认行内注释，``abc#def`` 是合法裸值。
#: 而 ``abc #def`` 因为含空白已经被这条规则盖住了（也顺带兼容
#: python-dotenv 那类会把 `` #`` 当注释的解析器）。
_MUST_QUOTE = re.compile(r"""[\s"'\\]""")


class EnvSyntaxError(ValueError):
    """值文件里有不是 ``KEY=value`` 的行。"""


@dataclass(frozen=True)
class Member:
    """一个顶层键在原文里的位置。"""

    key: str
    line_start: int
    line_end: int
    value_start: int
    value_end: int

    @property
    def span(self) -> tuple[int, int]:
        return (self.value_start, self.value_end)


# --------------------------------------------------------------------------- #
# 值解析 / 渲染
# --------------------------------------------------------------------------- #


def _unescape(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _parse_value(raw: str) -> str:
    s = raw.strip()
    if len(s) >= _MIN_QUOTED and s[0] == '"' and s[-1] == '"':
        return _unescape(s[1:-1])
    if len(s) >= _MIN_QUOTED and s[0] == "'" and s[-1] == "'":
        return s[1:-1]  # 单引号内是字面量，不转义
    return s


def render(value: Any) -> str:
    """把一个值渲染成 ``.env`` 的值片段。**只接受字符串。**"""
    if not isinstance(value, str):
        raise TypeError(
            f".env 只能存字符串，拿到 {value.__class__.__name__}（{value!r}）；"
            "要存非字符串的值，请改用 JSON / YAML 值文件。"
        )
    if value == "" or _MUST_QUOTE.search(value):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\r", "\\r")
        )
        return f'"{escaped}"'
    return value


def render_pair(key: str, value: Any) -> str:
    return f"{key}={render(value)}"


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #


def iter_members(text: str) -> Iterator[Member]:
    """按原文顺序产出顶层成员。``#`` 只有整行才算注释。"""
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        body = raw_line.rstrip("\r\n")
        line_start, line_end = offset, offset + len(raw_line)
        offset = line_end

        stripped = body.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = _LINE.match(body)
        if match is None:
            line_no = text.count(chr(10), 0, line_start) + 1
            raise EnvSyntaxError(f"第 {line_no} 行不是 KEY=value：{body!r}")

        value_start = line_start + match.start("value")
        tail = body[match.start("value") :]
        value_end = value_start + len(tail.rstrip(_WS))
        yield Member(match["key"], line_start, line_end, value_start, value_end)


def find(text: str, key: str) -> Member | None:
    for member in iter_members(text):
        if member.key == key:
            return member
    return None


# --------------------------------------------------------------------------- #
# 读
# --------------------------------------------------------------------------- #


def loads(text: str) -> dict[str, str]:
    """读出值文件。**一律是字符串**，不做类型推断。"""
    data: dict[str, str] = {}
    for member in iter_members(text):
        data[member.key] = _parse_value(text[member.value_start : member.value_end])
    return data


# --------------------------------------------------------------------------- #
# 外科手术式回写
# --------------------------------------------------------------------------- #


def set_value(text: str, key: str, value: Any) -> str:
    """替换一个**已存在**键的值，其余字节逐字保留（含 ``export `` 前缀）。"""
    member = find(text, key)
    if member is None:
        raise KeyError(key)
    return text[: member.value_start] + render(value) + text[member.value_end :]


def append_key(text: str, key: str, value: Any) -> str:
    """在最后一个顶层成员之后新起一行。"""
    line = render_pair(key, value) + "\n"
    members = list(iter_members(text))
    if not members:
        prefix = text if text == "" or text.endswith("\n") else text + "\n"
        return prefix + line
    at = members[-1].line_end
    separator = "" if text[:at].endswith(("\n", "\r")) else "\n"
    return text[:at] + separator + line + text[at:]


def delete_key(text: str, key: str) -> str:
    """删掉承载该键的**那一行**（上方紧邻的注释刻意保留，见 YAML 后端同款取舍）。"""
    member = find(text, key)
    if member is None:
        raise KeyError(key)
    return text[: member.line_start] + text[member.line_end :]
