"""YAML 值后端：读出 + **外科手术式回写**。

YAML 比 JSON 更要紧，因为**注释只活在 YAML 里**（§27.3）。
``safe_load`` + ``safe_dump`` 会毁掉：注释、锚点 / 别名、多文档、标签、键序——
所以这里**没有「全量重 dump」这个选项**，只有文本级替换。

## v1 的契约：扁平映射

.. code-block:: yaml

    # 值文件：改值请直接编辑本文件
    pack.max.byte: 2147483648   # 封口线
    slot.max.byte.b: 512

顶层键**不缩进**，值写在同行的标量。

## 明确拒绝的构造

嵌套块映射、块标量（``|`` / ``>``）、跨行的流式集合、多文档（``---``）——
**v1 报错，不猜、不静默搞坏**。理由：这些构造下「这个键的值占哪几个字节」
不是一个确定的答案，而猜错的代价是毁掉用户的文件。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import yaml

_WS = " \t"
_DOC_MARKERS = ("---", "...")
_PLAIN_KEY_OK = re.compile(r"^[A-Za-z0-9_.\-]+$")


class YamlFlatRequired(ValueError):
    """值文件里出现了 v1 不支持的构造（嵌套 / 块标量 / 跨行集合）。"""


# --------------------------------------------------------------------------- #
# 行级扫描
# --------------------------------------------------------------------------- #


def _comment_index(s: str) -> int:
    """返回行内注释 ``#`` 的下标；没有则返回 ``len(s)``。

    ``#`` 只有位于行首或前面是空白时才是注释（YAML 规则），
    且引号里的 ``#`` 不算。
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


def _key_and_colon(s: str) -> tuple[str, int]:
    """从一个顶层行的开头解析出键，返回 ``(key, 冒号下标)``。"""
    if s[0] in "\"'":
        quote = s[0]
        i = 1
        while i < len(s):
            if quote == '"' and s[i] == "\\":
                i += 2
                continue
            if s[i] == quote:
                break
            i += 1
        else:
            raise YamlFlatRequired(f"未闭合的键：{s!r}")
        key = yaml.safe_load(s[: i + 1])
        rest = s[i + 1 :]
        offset = i + 1 + (len(rest) - len(rest.lstrip(_WS)))
        if offset >= len(s) or s[offset] != ":":
            raise YamlFlatRequired(f"键后面不是冒号：{s!r}")
        return str(key), offset

    colon = s.find(":")
    if colon <= 0:
        raise YamlFlatRequired(f"顶层行不是 `键: 值`：{s!r}")
    return s[:colon].strip(), colon


@dataclass(frozen=True)
class Member:
    """一个顶层键在原文里的位置。"""

    key: str
    line_start: int
    line_end: int  # 含行尾换行
    value_start: int
    value_end: int

    @property
    def span(self) -> tuple[int, int]:
        return (self.value_start, self.value_end)


def iter_members(text: str) -> Iterator[Member]:
    """按原文顺序产出顶层成员，遇到不支持的构造就报错。"""
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        body = raw_line.rstrip("\r\n")
        line_start, line_end = offset, offset + len(raw_line)
        offset = line_end

        stripped = body.strip()
        if not stripped or stripped.startswith("#") or body.strip() in _DOC_MARKERS:
            continue

        indent = body[: len(body) - len(body.lstrip(_WS))]
        if indent:
            raise YamlFlatRequired(
                f"第 {text.count(chr(10), 0, line_start) + 1} 行有缩进，v1 只支持扁平映射：{body!r}"
            )

        key, colon = _key_and_colon(body)
        rest = body[colon + 1 :]
        lead = len(rest) - len(rest.lstrip(_WS))
        value_start = line_start + colon + 1 + lead
        value_text = body[colon + 1 + lead :]

        if not value_text.strip():
            raise YamlFlatRequired(f"键 {key!r} 的值在下一行（嵌套或块标量），v1 不支持")
        if value_text.lstrip().startswith(("|", ">")):
            raise YamlFlatRequired(f"键 {key!r} 用了块标量，v1 不支持")
        if not _is_balanced(value_text):
            raise YamlFlatRequired(f"键 {key!r} 的值跨了多行，v1 不支持")

        value_end = value_start + len(value_text[: _comment_index(value_text)].rstrip(_WS))
        yield Member(key, line_start, line_end, value_start, value_end)


def _is_balanced(s: str) -> bool:
    """流式集合必须在同一行闭合（引号内的括号不算）。"""
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


def find(text: str, key: str) -> Member | None:
    for member in iter_members(text):
        if member.key == key:
            return member
    return None


# --------------------------------------------------------------------------- #
# 读 / 渲染
# --------------------------------------------------------------------------- #


def loads(text: str) -> dict[str, Any]:
    """读出值文件。拒绝多文档；不做任何类型加工（透明原则）。"""
    documents = list(yaml.safe_load_all(text))
    if len(documents) > 1:
        raise YamlFlatRequired("多文档 YAML 不支持（v1 一份文件 = 一个顶层对象）")
    data = documents[0] if documents else None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TypeError("值文件的顶层必须是一个 YAML 映射")
    return data


def render(value: Any) -> str:
    """把一个值渲染成**单行** YAML 标量。

    落不成单行就当场拒绝——写出去一个坏值文件的代价远高于一次报错。
    """
    if value is None:
        return "null"
    if isinstance(value, (str, int, float, bool, list, dict)):
        try:
            dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True)
        except yaml.YAMLError as exc:  # pragma: no cover - 防御性
            raise TypeError(f"值无法落成 YAML：{value!r}") from exc
        body = dumped.removesuffix("\n...\n").removesuffix("\n")
        if "\n" in body:
            raise TypeError(f"值落成 YAML 后跨了多行，v1 不支持：{value!r}")
        return body
    raise TypeError(f"值无法落成 YAML：{value!r}")


def render_key(key: str) -> str:
    """需要时给键加引号。我们的键是点分小写，通常不用。

    注意：PyYAML 给**裸标量文档**会补一个 ``...`` 结束标记，
    必须像 :func:`render` 那样剥掉，否则键里会混进一个换行。
    """
    if _PLAIN_KEY_OK.match(key):
        return key
    dumped = yaml.safe_dump(key, allow_unicode=True)
    return dumped.removesuffix("\n...\n").removesuffix("\n")


def render_pair(key: str, value: Any) -> str:
    return f"{render_key(key)}: {render(value)}"


# --------------------------------------------------------------------------- #
# 外科手术式回写
# --------------------------------------------------------------------------- #


def set_value(text: str, key: str, value: Any) -> str:
    """替换一个**已存在**键的值，其余字节逐字保留（含行尾注释）。"""
    member = find(text, key)
    if member is None:
        raise KeyError(key)
    return text[: member.value_start] + render(value) + text[member.value_end:]


def append_key(text: str, key: str, value: Any) -> str:
    """在最后一个顶层成员之后新起一行。"""
    line = render_pair(key, value) + "\n"
    members = list(iter_members(text))
    if not members:
        prefix = text if text == "" or text.endswith("\n") else text + "\n"
        return prefix + line
    at = members[-1].line_end
    # 末行可能没有行尾换行——不补一个的话会和新键拼成同一行
    separator = "" if text[:at].endswith(("\n", "\r")) else "\n"
    return text[:at] + separator + line + text[at:]


def delete_key(text: str, key: str) -> str:
    """删掉承载该键的**那一行**。

    刻意**不**顺手删掉上方紧邻的注释：注释是用户的字，删多了就是越权。
    代价是可能留下一条孤儿注释——这个取舍选「保守」。
    """
    member = find(text, key)
    if member is None:
        raise KeyError(key)
    return text[: member.line_start] + text[member.line_end:]
