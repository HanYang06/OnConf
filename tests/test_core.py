# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""纯内存核心的语义测试。

这些测试就是「API 契约」本身：设计文档 §17 / §18 的每一条规则，
在这里都必须有一个能跑的反例。
"""

from __future__ import annotations

import pytest

from auto_conf._core import (
    NO_VALUE,
    Action,
    Decl,
    VocabEntry,
    declaration_hash,
    read_value,
    reconcile,
)
from auto_conf.errors import KeyHasNoValueError, KeyNotRegisteredError


# --------------------------------------------------------------------------- #
# §18.2 读取 —— 引擎对值是**透明**的
# --------------------------------------------------------------------------- #


class TestRead:
    def test_fact_hit(self) -> None:
        got = read_value("a.b", {"a.b": 512}, {})
        assert (got.value, got.origin) == (512, "file")

    def test_none_is_a_legal_value(self) -> None:
        """`None` 是值，不是「没有值」。"""
        got = read_value("a.b", {"a.b": None}, {"a.b": VocabEntry("a.b")})
        assert got.value is None
        assert got.origin == "file"

    def test_string_stays_a_string(self) -> None:
        """透明原则：文件里是 `"512"`，读回来就是字符串，不许变成 512。

        这条是回归测试 —— 早先这里挂着一层类型推断，于是 JSON 里的字符串值
        会莫名其妙变成数字。要数字请在取用处显式 `int(…)`。
        """
        got = read_value("a.b", {"a.b": "512"}, {})
        assert got.value == "512"
        assert isinstance(got.value, str)

    def test_vocab_default_is_returned_verbatim(self) -> None:
        vocab = {"a.b": VocabEntry("a.b", type=int, default=8080)}
        got = read_value("a.b", {}, vocab)
        assert (got.value, got.origin) == (8080, "vocab")

    def test_unknown_key_raises_key_not_registered(self) -> None:
        with pytest.raises(KeyNotRegisteredError):
            read_value("nope", {}, {})

    def test_registered_without_value_raises_key_has_no_value(self) -> None:
        """「配置不存在」和「配置不合理」是两类错误，责任方不同。"""
        with pytest.raises(KeyHasNoValueError):
            read_value("a.b", {}, {"a.b": VocabEntry("a.b", default=NO_VALUE)})


# --------------------------------------------------------------------------- #
# §18.1 写入对账四条规则
# --------------------------------------------------------------------------- #


def _kinds(actions: list[Action]) -> list[tuple[str, str]]:
    return [(a.kind, a.key) for a in actions]


class TestReconcile:
    def test_rule1_clean_unknown_fact(self) -> None:
        """事实有、期望没有 ⇒ 清理。"""
        actions = reconcile([], {"ghost": 1}, {})
        assert _kinds(actions) == [("clean", "ghost")]

    def test_rule2_fill_missing_with_default(self) -> None:
        actions = reconcile([Decl("a.b", 512, type=int)], {}, {})
        assert ("fill", "a.b") in _kinds(actions)
        assert ("register", "a.b") not in _kinds(actions)

    def test_rule2_register_only_when_no_default(self) -> None:
        """没有默认值 ⇒ 完全不碰配置文件，只登记进词表。"""
        actions = reconcile([Decl("a.b", doc="说明")], {}, {})
        kinds = _kinds(actions)
        assert ("register", "a.b") in kinds
        assert ("fill", "a.b") not in kinds
        meta = next(a for a in actions if a.kind == "update_meta")
        assert meta.value is NO_VALUE

    def test_rule4_skip_when_value_differs(self) -> None:
        """两边都有、值不一致 ⇒ 尊重文件，一个字都不改。"""
        actions = reconcile([Decl("a.b", 512)], {"a.b": 1024}, {})
        skip = next(a for a in actions if a.kind == "skip")
        assert skip.old == 1024
        assert skip.value == 512
        assert not [a for a in actions if a.kind in ("fill", "overwrite")]

    def test_rule4_force_overwrites(self) -> None:
        actions = reconcile([Decl("a.b", 512)], {"a.b": 1024}, {}, force_keys={"a.b"})
        over = next(a for a in actions if a.kind == "overwrite")
        assert over.old == 1024
        assert over.value == 512

    def test_force_is_per_key_not_a_global_switch(self) -> None:
        """Force 逐项生效：同一次对账里，没点名的键仍然尊重文件（§18.6）。"""
        decls = [Decl("a.b", 512), Decl("c.d", 1)]
        facts = {"a.b": 1024, "c.d": 2}
        actions = reconcile(decls, facts, {}, force_keys={"a.b"})
        assert ("overwrite", "a.b") in _kinds(actions)
        assert ("skip", "c.d") in _kinds(actions)

    def test_rule4_skip_still_updates_vocab_fingerprint(self) -> None:
        """值不动，但词表里的默认值指纹要更新（§18.5 结论 1，归属权）。"""
        vocab = {"a.b": VocabEntry("a.b", default=512)}
        actions = reconcile([Decl("a.b", 2048)], {"a.b": 1024}, vocab)
        assert ("skip", "a.b") in _kinds(actions)
        meta = next(a for a in actions if a.kind == "update_meta")
        assert meta.value == 2048

    def test_rule3_update_meta_when_vocab_missing(self) -> None:
        actions = reconcile([Decl("a.b", 512, type=int, doc="端口")], {"a.b": 512}, {})
        assert _kinds(actions) == [("update_meta", "a.b")]

    def test_no_action_when_everything_matches(self) -> None:
        """全量对账的稳态：什么都不做，这是「写放大归零」的前提。"""
        vocab = {"a.b": VocabEntry("a.b", type=int, doc="端口", default=512)}
        actions = reconcile([Decl("a.b", 512, type=int, doc="端口")], {"a.b": 512}, vocab)
        assert actions == []

    def test_clean_and_fill_together(self) -> None:
        actions = reconcile([Decl("new", 1)], {"old": 2}, {})
        assert set(_kinds(actions)) >= {("clean", "old"), ("fill", "new")}


class TestDirectiveKeys:
    """``$`` 开头的是**指令**，不是配置项：不许被清理，也不许被声明。

    这条来自真实产物 ``Cairn/config/settings.json``：

        {"$schema": "schema/settings.json", "pack.max.byte": 2147483648}

    规则 1 若不给它豁免，第一次运行就会把 ``$schema`` 删掉。
    """

    def test_schema_directive_is_not_cleaned(self) -> None:
        facts = {"$schema": "schema/settings.json", "a.b": 1}
        actions = reconcile([Decl("a.b", 1)], facts, {})
        assert ("clean", "$schema") not in _kinds(actions)

    def test_unknown_directives_are_kept(self) -> None:
        assert reconcile([], {"$id": "x", "$comment": "y"}, {}) == []

    def test_real_cairn_payload_shape(self) -> None:
        facts = {
            "$schema": "schema/settings.json",
            "slot.max.byte.b": 512,
            "pack.max.byte": 2147483648,
            "hub.default": "main",
        }
        decls = [
            Decl("slot.max.byte.b", 512, type=int),
            Decl("pack.max.byte", 2 * 1024**3, type=int),
            Decl("hub.default", "main", type=str),
        ]
        actions = reconcile(decls, facts, {})
        assert [a for a in actions if a.kind == "clean"] == []
        # 稳态下只该产出元数据登记
        assert {a.kind for a in actions} <= {"update_meta"}


# --------------------------------------------------------------------------- #
# §18.7 声明集哈希
# --------------------------------------------------------------------------- #


class TestDeclarationHash:
    def test_stable(self) -> None:
        decls = [Decl("a.b", 512, type=int, doc="x")]
        assert declaration_hash(decls) == declaration_hash(list(decls))

    def test_order_independent(self) -> None:
        a = [Decl("a", 1), Decl("b", 2)]
        b = [Decl("b", 2), Decl("a", 1)]
        assert declaration_hash(a) == declaration_hash(b)

    def test_default_change_flips_hash(self) -> None:
        """指纹变了 ⇒ 短路不成立 ⇒ 走完整对账。"""
        assert declaration_hash([Decl("a", 1)]) != declaration_hash([Decl("a", 2)])

    def test_doc_change_flips_hash(self) -> None:
        assert declaration_hash([Decl("a", 1, doc="x")]) != declaration_hash(
            [Decl("a", 1, doc="y")]
        )

    def test_missing_value_distinct_from_none(self) -> None:
        """「只登记」和「值就是 None」必须算出不同的指纹。"""
        assert declaration_hash([Decl("a")]) != declaration_hash([Decl("a", None)])
