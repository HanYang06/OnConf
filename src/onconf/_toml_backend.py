# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""TOML 值后端：读出 + **外科手术式回写**。

## 表头归一成点分键（§28.4）

TOML 的物理形态带表头，但键空间仍是**扁平点分**：

.. code-block:: toml

    [pack.max]
    byte = 2147483648        # ⇒ 键 "pack.max.byte"

所以读的时候把「当前表头路径 + 本行键」拼成完整键，写的时候再落回对应的表头段里。
对上层完全透明：它只看得见点分键。

## ``tomllib`` 只用来解**值**

结构（哪个键在哪一段、值的字节区间）由本模块的**行扫描**给出；
每个值的**类型**交给 ``tomllib`` 解析（``tomllib.loads("x = " + text)``），
这样整数、浮点、布尔、日期时间都按 TOML 规范解析，不用自己写第二遍。

## 明确拒绝

* 表数组 ``[[…]]``；
* 跨行的值（多行数组、``\"\"\"`` / ``'''`` 多行字符串）；
* ``None`` —— **TOML 没有 null**，写不进去就是写不进去，当场报错。

v1 一律**报错**，不猜、不静默搞坏。
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

from ._textscan import balanced_on_one_line, value_span


if TYPE_CHECKING:
    from collections.abc import Iterator

#: 新建值文件时的**种子文本**：TOML 的空文件本身就是合法骨架。
EMPTY_TEXT = ""

#: 可打印字符的下界（0x20 是空格）；小于它的控制字符要转义
_PRINTABLE_FROM = 0x20

_HEADER = re.compile(r"^\[(?P<path>[^\[\]]+)\]$")
_LINE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*)"
    r"[ \t]*=[ \t]*(?P<value>.*)$"
)


class TomlFlatRequiredError(ValueError):
    """值文件里出现了 v1 不支持的构造（表数组 / 跨行值）。"""


@dataclass(frozen=True)
class Member:
    """一个键在原文里的位置。"""

    key: str  # 完整点分路径
    section: tuple[str, ...]  # 所在的表头路径（顶层为空元组）
    line_start: int
    line_end: int
    value_start: int
    value_end: int

    @property
    def span(self) -> tuple[int, int]:
        return (self.value_start, self.value_end)


def _split_path(path: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in path.split(".") if part.strip())


def _line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #


def iter_members(text: str) -> Iterator[Member]:
    """按原文顺序产出成员，键已归一成完整点分路径。"""
    section: tuple[str, ...] = ()
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        body = raw_line.rstrip("\r\n")
        line_start, line_end = offset, offset + len(raw_line)
        offset = line_end

        stripped = body.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("[["):
            raise TomlFlatRequiredError(
                f"第 {_line_no(text, line_start)} 行是表数组 [[…]]，v1 不支持"
            )
        if stripped.startswith("["):
            header = _HEADER.match(stripped)
            if header is None:
                raise TomlFlatRequiredError(
                    f"第 {_line_no(text, line_start)} 行的表头无法解析：{body!r}"
                )
            section = _split_path(header["path"])
            continue

        match = _LINE.match(body)
        if match is None:
            raise TomlFlatRequiredError(
                f"第 {_line_no(text, line_start)} 行不是 `键 = 值`：{body!r}"
            )

        value_start = line_start + match.start("value")
        raw_value = body[match.start("value") :]
        if not raw_value.strip():
            raise TomlFlatRequiredError(
                f"第 {_line_no(text, line_start)} 行的值在下一行，v1 不支持"
            )
        if not balanced_on_one_line(raw_value):
            raise TomlFlatRequiredError(
                f"第 {_line_no(text, line_start)} 行的值跨了多行，v1 不支持"
            )
        value_end = line_start + value_span(body, match.start("value"))

        key = ".".join((*section, *match["key"].split(".")))
        yield Member(key, section, line_start, line_end, value_start, value_end)


def find(text: str, key: str) -> Member | None:
    for member in iter_members(text):
        if member.key == key:
            return member
    return None


# --------------------------------------------------------------------------- #
# 读 / 渲染
# --------------------------------------------------------------------------- #


def _parse_value(raw: str) -> Any:
    try:
        return tomllib.loads(f"x = {raw}")["x"]
    except (tomllib.TOMLDecodeError, KeyError) as exc:
        raise TomlFlatRequiredError(f"值无法按 TOML 解析：{raw!r}") from exc


def loads(text: str) -> dict[str, Any]:
    """读出值文件，键是扁平点分路径。**不做任何类型加工**（透明原则）。"""
    data: dict[str, Any] = {}
    for member in iter_members(text):
        data[member.key] = _parse_value(text[member.value_start : member.value_end])
    return data


def _render_string(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < _PRINTABLE_FROM:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def render(value: Any) -> str:
    """把一个值渲染成**单行** TOML 字面量。

    ``None`` 没有对应的 TOML 字面量，当场拒绝并指路。
    """
    if value is None:
        raise TypeError("TOML 没有 null，写不进 None；要存空值请改用 JSON / YAML 值文件")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _render_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(render(item) for item in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{k} = {render(v)}" for k, v in value.items())
        return "{ " + inner + " }"
    raise TypeError(f"值无法落成 TOML：{value!r}")


def render_pair(key: str, value: Any) -> str:
    return f"{key} = {render(value)}"


# --------------------------------------------------------------------------- #
# 外科手术式回写
# --------------------------------------------------------------------------- #


def set_value(text: str, key: str, value: Any) -> str:
    """替换一个**已存在**键的值，其余字节逐字保留（含行尾注释）。"""
    member = find(text, key)
    if member is None:
        raise KeyError(key)
    return text[: member.value_start] + render(value) + text[member.value_end :]


def delete_key(text: str, key: str) -> str:
    """删掉承载该键的**那一行**（上方紧邻的注释刻意保留）。"""
    member = find(text, key)
    if member is None:
        raise KeyError(key)
    return text[: member.line_start] + text[member.line_end :]


def _section_spans(text: str) -> dict[tuple[str, ...], int]:
    """表头路径 → 该段最后一行**之后**的位置（含表头行本身）。

    段里一个成员都没有时，值就是表头行的结尾 —— 往那里插正好落在段内。
    """
    spans: dict[tuple[str, ...], int] = {}
    current: tuple[str, ...] = ()
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        body = raw_line.rstrip("\r\n")
        line_end = offset + len(raw_line)
        stripped = body.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            header = _HEADER.match(stripped)
            if header is not None:
                current = _split_path(header["path"])
                spans[current] = line_end
        elif stripped and not stripped.startswith("#") and _LINE.match(body):
            spans[current] = line_end
        offset = line_end
    return spans


def append_key(text: str, key: str, value: Any) -> str:
    """新增一个键。

    * 父段（``key`` 去掉最后一段）已存在 ⇒ 插在该段末尾；
    * 父段不存在 ⇒ 新起一个 ``[父段]`` 块；
    * 顶层键（没有父段）⇒ 必须排在**第一个表头之前**（TOML 的语法要求）。
    """
    leaf = key.rsplit(".", 1)[-1]
    line = render_pair(leaf, value) + "\n"
    parent = key.rpartition(".")[0]

    if not parent:
        headers = [
            offset
            for offset, raw in _iter_lines(text)
            if raw.strip().startswith("[") and not raw.strip().startswith("[[")
        ]
        if headers:
            return text[: headers[0]] + line + text[headers[0] :]
        return _append_block(text, line)

    spans = _section_spans(text)
    at = spans.get(tuple(parent.split(".")))
    if at is not None:
        return text[:at] + line + text[at:]
    return _append_block(text, f"[{parent}]\n{line}")


def _iter_lines(text: str) -> Iterator[tuple[int, str]]:
    offset = 0
    for raw in text.splitlines(keepends=True):
        yield offset, raw.rstrip("\r\n")
        offset += len(raw)


def _append_block(text: str, block: str) -> str:
    body = text if text == "" or text.endswith("\n") else text + "\n"
    if body and not body.endswith("\n\n"):
        body += "\n"
    return body + block
