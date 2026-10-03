# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""文本级扫描的公共小工具。

外科手术式回写要在**原文里定位一个值的字节区间**，而不同格式的注释规则不一样
（YAML / TOML 认行内 ``#``，``.env`` 不认）。这里只放两样共用的东西：
「哪里开始是注释」和「一个引号串到哪结束」。
"""

from __future__ import annotations


_WS = " \t"


def comment_index(s: str) -> int:
    """返回行内注释 ``#`` 的下标；没有则返回 ``len(s)``。

    ``#`` 只有位于行首或前面是空白时才是注释，且引号里的 ``#`` 不算。
    注意这是 **YAML / TOML 的规则**；``.env`` 刻意不认行内注释（密码里带 ``#``
    是常态），所以那边不走这里。
    """
    quote: str | None = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote is not None:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
        elif c == "#" and (i == 0 or s[i - 1] in _WS):
            return i
        i += 1
    return len(s)


def balanced_on_one_line(s: str) -> bool:
    """流式集合（``[…]`` / ``{…}``）与引号必须在同一行内闭合。"""
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote is not None:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0 and quote is None


def value_span(body: str, start: int, *, honor_comments: bool = True) -> int:
    """从 ``body[start:]`` 量出值的结束下标。

    返回值与 ``start`` **同一坐标系**（都是相对 ``body`` 的下标）——
    调用方自己加行首偏移。这一点踩过：混用绝对/相对会算出
    ``end < start`` 的空区间，而且不报错，只是值悄悄变成空字符串。
    """
    tail = body[start:]
    cut = comment_index(tail) if honor_comments else len(tail)
    return start + len(tail[:cut].rstrip(_WS))
