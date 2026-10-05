# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""JSON 值后端：读出 + **外科手术式回写**。

## 为什么不是 ``json.dumps`` 整篇重写

值文件的主人是**用户**（归属权见 ``docs/design/file_support.md``），他们会手改它。整篇重写会顺手改掉
用户没让我们动的东西：缩进风格、键序、``$schema`` 指令、以及我们这轮不该碰的键。

所以回写走**文本级替换**：只把目标键的**值区间**换掉，区间之外的字节一个不动。
本模块的不变量是可测的：

    set_value(text, k, v) 与 text 的差异，必须只落在 k 的值的字节区间内。

## 值文件是**扁平**对象

``Cairn/config/settings.json`` 的真实形态::

    {"$schema": "schema/settings.json", "pack.max.byte": 2147483648, "slot.max.byte.b": 512}

键是点分**字面量**，不做嵌套。所以这里只需要扫**顶层**成员，不需要路径栈。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Iterator


_WS = " \t\r\n"

#: 新建值文件时的**种子文本**：``append_key`` 需要在一个合法骨架里插第一个键。
#: JSON 的空骨架必须是一个空对象 —— 空文本连 ``{`` 都没有，插不进去。
EMPTY_TEXT = "{}"


# --------------------------------------------------------------------------- #
# 词法跳跃
# --------------------------------------------------------------------------- #


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in _WS:
        i += 1
    return i


def _skip_string(text: str, i: int) -> int:
    """``text[i]`` 必须是 ``"``，返回闭合引号**之后**的位置。"""
    i += 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        i += 1
    raise ValueError("未闭合的字符串")


def _skip_value(text: str, i: int) -> int:
    """``text[i]`` 是值的首字符，返回值**之后**的位置。"""
    c = text[i]
    if c == '"':
        return _skip_string(text, i)
    if c in "{[":
        depth = 0
        while i < len(text):
            ch = text[i]
            if ch == '"':
                i = _skip_string(text, i)
                continue
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise ValueError("未闭合的容器")
    while i < len(text) and text[i] not in ",}]":
        i += 1
    return i


# --------------------------------------------------------------------------- #
# 顶层成员扫描
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Member:
    """顶层对象的一个成员在原文里的位置。"""

    key: str
    key_start: int  # 键的起始引号
    value_start: int
    value_end: int  # 值的结尾（已去掉尾随空白）

    @property
    def span(self) -> tuple[int, int]:
        return (self.value_start, self.value_end)


def _open_brace(text: str) -> int:
    i = _skip_ws(text, 0)
    if i >= len(text) or text[i] != "{":
        raise TypeError("值文件的顶层必须是一个 JSON 对象")
    return i


def _close_brace(text: str) -> int:
    i = _open_brace(text)
    depth = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("未闭合的顶层对象")


def iter_members(text: str) -> Iterator[Member]:
    """按原文顺序产出顶层成员。"""
    i = _skip_ws(text, _open_brace(text) + 1)
    while i < len(text) and text[i] != "}":
        if text[i] != '"':
            raise ValueError(f"偏移 {i} 处期望键字符串")
        key_start = i
        key_end = _skip_string(text, i)
        key = json.loads(text[key_start:key_end])
        i = _skip_ws(text, key_end)
        if i >= len(text) or text[i] != ":":
            raise ValueError(f"偏移 {i} 处期望冒号")
        i = _skip_ws(text, i + 1)
        value_start = i
        value_end = _skip_value(text, i)
        while value_end > value_start and text[value_end - 1] in _WS:
            value_end -= 1
        yield Member(key, key_start, value_start, value_end)
        i = _skip_ws(text, value_end)
        if i < len(text) and text[i] == ",":
            i = _skip_ws(text, i + 1)
        elif i >= len(text) or text[i] != "}":
            raise ValueError(f"偏移 {i} 处期望逗号或右花括号")


def find(text: str, key: str) -> Member | None:
    for member in iter_members(text):
        if member.key == key:
            return member
    return None


# --------------------------------------------------------------------------- #
# 读 / 渲染
# --------------------------------------------------------------------------- #


def loads(text: str) -> dict[str, Any]:
    """读出值文件。``dict`` 保序，且**不做任何类型加工**（透明原则）。"""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("值文件的顶层必须是一个 JSON 对象")
    return data


def render(value: Any) -> str:
    """把一个值渲染成 JSON 字面量。

    落不成 JSON 的当场拒绝——否则写出去的值文件是坏的，
    而坏文件的代价远高于一次报错。
    """
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"值无法落成 JSON：{value!r}") from exc


# --------------------------------------------------------------------------- #
# 外科手术式回写
# --------------------------------------------------------------------------- #


def set_value(text: str, key: str, value: Any) -> str:
    """替换一个**已存在**键的值，其余字节逐字保留。"""
    member = find(text, key)
    if member is None:
        raise KeyError(key)
    return text[: member.value_start] + render(value) + text[member.value_end :]


def append_key(text: str, key: str, value: Any, *, indent: str | None = None) -> str:
    """新增一个键，插在末尾（``$schema`` 因此仍在最前）。"""
    members = list(iter_members(text))
    close = _close_brace(text)

    if not members:
        pad = indent or "  "
        head = text[: _open_brace(text) + 1]
        return f"{head}\n{pad}{render_pair(key, value)}\n{text[close:]}"

    if indent is None:
        head = text[_open_brace(text) + 1 : members[0].key_start]
        nl = head.rfind("\n")
        indent = head[nl + 1 :] if nl >= 0 else "  "

    body = text[:close].rstrip()
    return f"{body},\n{indent}{render_pair(key, value)}\n" + text[close:]


def render_pair(key: str, value: Any) -> str:
    return f"{json.dumps(key, ensure_ascii=False)}: {render(value)}"


def delete_key(text: str, key: str) -> str:
    """删掉一个顶层成员，连同它该带走的那一个逗号。"""
    members = list(iter_members(text))
    index = next((n for n, m in enumerate(members) if m.key == key), None)
    if index is None:
        raise KeyError(key)

    member = members[index]
    start, end = member.key_start, member.value_end

    before = start - 1
    while before >= 0 and text[before] in _WS:
        before -= 1
    if text[before] == ",":
        # 不是首个成员：把它前面那个逗号一起带走
        start = before
    elif index + 1 < len(members):
        # 首个成员且后面还有人：把尾随逗号与到下一个键之间的空白一起带走
        end = members[index + 1].key_start
        return text[:start] + text[end:]
    return text[:start] + text[end:]
