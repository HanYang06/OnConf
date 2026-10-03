# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""词表：**库自己的资产**（§18.6 归属权）。

三条设计约束：

1. **三态**（§17.7）：未登记 / 已登记无值 / 值为 ``None``。
   JSON 里用「`default` 键缺失」表示无值，「`default: null`」表示值就是 ``None``。
   这两者语义完全不同，塌陷掉就是 §17 里那个最阴的 bug。
2. **对齐 JSON Schema**（§12.4）：白拿 IDE 补全与现成工具链。
   Python 独有类型（如 ``tuple``）用 ``x-auto-conf-py`` 扩展无损保留。
3. **顶层带声明集哈希**（§18.7）：脏检查的指纹，对得上就整体跳过写入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ._core import (
    MISSING,
    NO_VALUE,
    Action,
    Decl,
    VocabEntry,
    declaration_hash,
)


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
HASH_KEY = "x-auto-conf-hash"
PY_TYPE_KEY = "x-auto-conf-py"

# bool 必须排在 int 前面（bool 是 int 的子类）
_PY_TO_JSON: tuple[tuple[type, str], ...] = (
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (list, "array"),
    (tuple, "array"),
    (dict, "object"),
    (type(None), "null"),
)

_JSON_TO_PY: dict[str, type] = {
    "boolean": bool,
    "integer": int,
    "number": float,
    "string": str,
    "array": list,
    "object": dict,
    "null": type(None),
}

_BY_NAME: dict[str, type] = {t.__name__: t for t, _ in _PY_TO_JSON}


def type_to_json(t: type | None) -> str | None:
    """Python 类型 → JSON Schema 的 ``type`` 名。"""
    if t is None:
        return None
    for py, js in _PY_TO_JSON:
        if t is py:
            return js
    return "string"  # 未知类型降级成 string，并靠 x-auto-conf-py 保住原样


def type_from_json(name: str | None, py_hint: str | None = None) -> type | None:
    """JSON Schema 的 ``type`` 名 → Python 类型，优先采信 ``x-auto-conf-py``。"""
    if py_hint and py_hint in _BY_NAME:
        return _BY_NAME[py_hint]
    if name is None:
        return None
    return _JSON_TO_PY.get(name)


@dataclass
class Vocabulary:
    """键 → 登记项的登记册。"""

    entries: dict[str, VocabEntry] = field(default_factory=dict)
    hash: str | None = None

    # ---------------------------------------------------------------- 查询

    def __contains__(self, key: object) -> bool:
        return key in self.entries

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def get(self, key: str) -> VocabEntry | None:
        return self.entries.get(key)

    def keys(self) -> list[str]:
        return sorted(self.entries)

    def as_dict(self) -> dict[str, VocabEntry]:
        """给 :func:`auto_conf._core.read_value` 用的只读视图。"""
        return self.entries

    # ---------------------------------------------------------------- 变更

    def register(self, decl: Decl) -> VocabEntry:
        """把一次声明写进词表。``decl.value is MISSING`` ⇒ 记 ``NO_VALUE``。"""
        entry = VocabEntry(
            key=decl.key,
            type=decl.type,
            doc=decl.doc,
            default=NO_VALUE if decl.value is MISSING else decl.value,
        )
        self.entries[decl.key] = entry
        return entry

    def drop(self, key: str) -> None:
        self.entries.pop(key, None)

    def apply(self, actions: Iterable[Action], decls: list[Decl]) -> None:
        """把对账动作落到词表上，并刷新哈希 —— 这是「提交」的落点。

        注意：``skip`` / ``overwrite`` 只影响**配置文件**，词表侧的更新由
        独立的 ``update_meta`` 动作承担（§18.5 结论 1：动词表，不动文件）。
        """
        by_key = {d.key: d for d in decls}
        for action in actions:
            if action.kind == "clean":
                self.drop(action.key)
                continue
            if action.kind in ("update_meta", "register", "fill"):
                decl = by_key.get(action.key)
                if decl is not None:
                    self.register(decl)
        self.hash = declaration_hash(decls)

    # ------------------------------------------------------------ 脏检查

    def matches(self, decls: list[Decl]) -> bool:
        """声明集指纹对得上 ⇒ 写入阶段整体跳过，一个字节都不写。"""
        return self.hash is not None and self.hash == declaration_hash(decls)

    # ------------------------------------------------------------ 序列化

    def to_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for key in self.keys():
            entry = self.entries[key]
            node: dict[str, Any] = {}
            js_type = type_to_json(entry.type)
            if js_type is not None:
                node["type"] = js_type
                if _JSON_TO_PY.get(js_type) is not entry.type and entry.type is not None:
                    node[PY_TYPE_KEY] = entry.type.__name__
            if entry.doc is not None:
                node["description"] = entry.doc
            if entry.default is not NO_VALUE:
                node["default"] = entry.default  # 注意：None 会被写成 "default": null
            properties[key] = node

        schema: dict[str, Any] = {
            "$schema": SCHEMA_URI,
            "type": "object",
            "properties": properties,
        }
        if self.hash is not None:
            schema[HASH_KEY] = self.hash
        return schema

    @classmethod
    def from_schema(cls, data: dict[str, Any]) -> Vocabulary:
        entries: dict[str, VocabEntry] = {}
        for key, node in (data.get("properties") or {}).items():
            entries[key] = VocabEntry(
                key=key,
                type=type_from_json(node.get("type"), node.get(PY_TYPE_KEY)),
                doc=node.get("description"),
                # 关键：键「缺失」⇒ NO_VALUE；键在（哪怕值是 null）⇒ 就是那个值。
                # dict.get 的哨兵默认值正好给出这个语义。
                default=node.get("default", NO_VALUE),
            )
        return cls(entries=entries, hash=data.get(HASH_KEY))
