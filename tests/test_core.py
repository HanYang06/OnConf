# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""纯内存核心的语义测试。

这些测试就是「API 契约」本身：设计文档里的每一条规则，
在这里都必须有一个能跑的反例。
"""

from __future__ import annotations

import inspect

import pytest

from onconf._core import (
    NO_VALUE,
    Action,
    Decl,
    VocabEntry,
    declaration_hash,
    read_value,
    reconcile,
    undeclared,
)
from onconf.errors import KeyHasNoValueError, KeyNotRegisteredError


# --------------------------------------------------------------------------- #
# 读取 —— 引擎对值是**透明**的
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
        vocab = {"a.b": VocabEntry("a.b", default=8080)}
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
# 写入对账四条规则
# --------------------------------------------------------------------------- #


def _kinds(actions: list[Action]) -> list[tuple[str, str]]:
    return [(a.kind, a.key) for a in actions]


class TestReconcile:
    def test_reconcile_never_cleans(self) -> None:
        """事实有、期望没有 ⇒ **运行期什么都不做**。

        删除的判据「事实里有、期望集里没有」只有在期望集完整时才成立，而运行期的期望集
        永远只是「这个进程到目前为止声明过的」。所以 ``reconcile`` 连一条 ``clean``
        都不产出 —— 删除只走 ``undeclared`` 那条命令行专用的路。
        """
        actions = reconcile([], {"ghost": 1}, {})
        assert actions == []

    def test_rule2_fill_missing_with_default(self) -> None:
        actions = reconcile([Decl("a.b", 512)], {}, {})
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
        assert not [a for a in actions if a.kind == "fill"]

    def test_rule4_has_no_overwrite_escape(self) -> None:
        """运行期**没有**覆盖出口：值不一致永远只产出一条 ``skip``。

        覆盖既存值是**人主动发起**的事（命令行的 ``build`` / ``sync``），
        不属于代码的写路径 —— 代码只能补它没有的，不能改它已经有的。
        """
        actions = reconcile([Decl("a.b", 512), Decl("c.d", 1)], {"a.b": 1024, "c.d": 2}, {})
        assert [k for k in _kinds(actions) if k[0] == "skip"] == [("skip", "a.b"), ("skip", "c.d")]
        assert "overwrite" not in {a.kind for a in actions}

    def test_reconcile_has_no_force_knob(self) -> None:
        """``force_keys`` 已随 ``force`` 一起移除：这条路径上没有「点名覆盖」。"""
        assert "force_keys" not in inspect.signature(reconcile).parameters

    def test_rule4_skip_still_updates_vocab_fingerprint(self) -> None:
        """值不动，但词表里的默认值指纹要更新（只动词表、不动文件）。"""
        vocab = {"a.b": VocabEntry("a.b", default=512)}
        actions = reconcile([Decl("a.b", 2048)], {"a.b": 1024}, vocab)
        assert ("skip", "a.b") in _kinds(actions)
        meta = next(a for a in actions if a.kind == "update_meta")
        assert meta.value == 2048

    def test_rule3_update_meta_when_vocab_missing(self) -> None:
        actions = reconcile([Decl("a.b", 512, doc="端口")], {"a.b": 512}, {})
        assert _kinds(actions) == [("update_meta", "a.b")]

    def test_no_action_when_everything_matches(self) -> None:
        """全量对账的稳态：什么都不做，这是「写放大归零」的前提。"""
        vocab = {"a.b": VocabEntry("a.b", doc="端口", default=512)}
        actions = reconcile([Decl("a.b", 512, doc="端口")], {"a.b": 512}, vocab)
        assert actions == []

    def test_fill_and_removal_are_two_different_paths(self) -> None:
        """补缺走 ``reconcile``，删除走 ``undeclared`` —— 两条路互不越界。"""
        assert _kinds(reconcile([Decl("new", 1)], {"old": 2}, {})) == [
            ("fill", "new"),
            ("update_meta", "new"),
        ]
        assert _kinds(undeclared({"old": 2}, {"new"})) == [("clean", "old")]


class TestDirectiveKeys:
    """``$`` 开头的是**指令**，不是配置项：不许被删除，也不许被声明。

    这条来自真实产物 ``Cairn/config/settings.json``：

        {"$schema": "schema/settings.json", "pack.max.byte": 2147483648}

    删除若不豁免它，第一次收敛就会把 ``$schema`` 删掉 —— 那等于删掉用户的编辑器工具链。
    """

    def test_schema_directive_is_not_removed(self) -> None:
        facts = {"$schema": "schema/settings.json", "a.b": 1}
        assert _kinds(undeclared(facts, {"a.b"})) == []

    def test_unknown_directives_are_kept(self) -> None:
        assert undeclared({"$id": "x", "$comment": "y"}, set()) == []

    def test_real_cairn_payload_shape(self) -> None:
        facts = {
            "$schema": "schema/settings.json",
            "slot.max.byte.b": 512,
            "pack.max.byte": 2147483648,
            "hub.default": "main",
        }
        decls = [
            Decl("slot.max.byte.b", 512),
            Decl("pack.max.byte", 2 * 1024**3),
            Decl("hub.default", "main"),
        ]
        actions = reconcile(decls, facts, {})
        # 稳态下只该产出元数据登记
        assert {a.kind for a in actions} <= {"update_meta"}
        # 收敛也不会碰任何一条指令
        assert undeclared(facts, {d.key for d in decls}) == []


# --------------------------------------------------------------------------- #
# 声明集哈希
# --------------------------------------------------------------------------- #


class TestDeclarationHash:
    def test_stable(self) -> None:
        decls = [Decl("a.b", 512, doc="x")]
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
