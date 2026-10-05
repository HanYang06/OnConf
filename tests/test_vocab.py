# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""词表的三态、JSON Schema 往返、以及哈希短路。"""

from __future__ import annotations

import json

import pytest

from onconf._core import NO_VALUE, Decl, declaration_hash, read_value, reconcile
from onconf._vocab import Vocabulary
from onconf.errors import KeyHasNoValueError


class TestTriState:
    """未登记 / 已登记无值 / 值为 None —— 三态不许塌陷。"""

    def test_no_value_is_not_none(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("a.b", doc="只登记"))
        assert vocab.get("a.b").default is NO_VALUE  # type: ignore[union-attr]

    def test_explicit_none_is_a_value(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("a.b", None))
        assert vocab.get("a.b").default is None  # type: ignore[union-attr]

    def test_read_after_register_only_raises(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("a.b", doc="只登记"))
        with pytest.raises(KeyHasNoValueError):
            read_value("a.b", {}, vocab.as_dict())

    def test_read_explicit_none_returns_none(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("a.b", None))
        assert read_value("a.b", {}, vocab.as_dict()).value is None


class TestSchemaRoundTrip:
    def test_three_states_survive_round_trip(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("only.registered", doc="只登记"))
        vocab.register(Decl("is.none", None))
        vocab.register(Decl("has.default", 512, doc="端口"))

        restored = Vocabulary.from_schema(vocab.to_schema())

        assert restored.get("only.registered").default is NO_VALUE  # type: ignore[union-attr]
        assert restored.get("is.none").default is None  # type: ignore[union-attr]
        assert restored.get("has.default").default == 512  # type: ignore[union-attr]

    def test_absent_default_key_vs_null_default(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("no.value"))
        vocab.register(Decl("null.value", None))
        props = vocab.to_schema()["properties"]
        assert "default" not in props["no.value"]
        assert "default" in props["null.value"]
        assert props["null.value"]["default"] is None

    def test_doc_becomes_description(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("a.b", 1, doc="格长档位之一"))
        assert vocab.to_schema()["properties"]["a.b"]["description"] == "格长档位之一"

    def test_schema_carries_no_type_field(self) -> None:
        """类型声明已移除：Schema 节点只剩 ``default`` / ``description``。"""
        vocab = Vocabulary()
        vocab.register(Decl("a.b", 512, doc="端口"))
        node = vocab.to_schema()["properties"]["a.b"]
        assert set(node) == {"description", "default"}

    def test_legacy_type_fields_are_ignored(self) -> None:
        """旧词表里残留的 ``type`` / ``x-onconf-py`` 直接忽略，落盘时自然清掉。"""
        legacy = {
            "properties": {"a.b": {"type": "integer", "x-onconf-py": "int", "default": 512}}
        }
        vocab = Vocabulary.from_schema(legacy)
        assert vocab.get("a.b").default == 512  # type: ignore[union-attr]
        assert set(vocab.to_schema()["properties"]["a.b"]) == {"default"}

    def test_schema_is_json_serialisable(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("a.b", 512, doc="端口"))
        restored = Vocabulary.from_schema(json.loads(json.dumps(vocab.to_schema())))
        assert restored.get("a.b").doc == "端口"  # type: ignore[union-attr]
        assert restored.get("a.b").default == 512  # type: ignore[union-attr]

    def test_hash_survives_round_trip(self) -> None:
        decls = [Decl("a.b", 512)]
        vocab = Vocabulary()
        vocab.apply(reconcile(decls, {}, {}), decls)
        restored = Vocabulary.from_schema(vocab.to_schema())
        assert restored.hash == vocab.hash


class TestHashShortCircuit:
    """声明集哈希：对得上 ⇒ 整体跳过；对不上 ⇒ 走完整对账（不是报错）。"""

    def test_first_run_is_dirty(self) -> None:
        assert not Vocabulary().matches([Decl("a.b", 512)])

    def test_after_commit_it_matches(self) -> None:
        decls = [Decl("a.b", 512)]
        vocab = Vocabulary()
        vocab.apply(reconcile(decls, {}, {}), decls)
        assert vocab.matches(decls)

    def test_changed_default_flips_to_dirty(self) -> None:
        vocab = Vocabulary()
        vocab.apply(reconcile([Decl("a.b", 512)], {}, {}), [Decl("a.b", 512)])
        assert not vocab.matches([Decl("a.b", 2048)])

    def test_matches_is_pure_dirty_check_not_a_lock(self) -> None:
        """对不上只意味着短路不成立 —— 开发者永远能改自己的代码。"""
        decls = [Decl("a.b", 2048)]
        vocab = Vocabulary()
        vocab.apply(reconcile([Decl("a.b", 512)], {}, {}), [Decl("a.b", 512)])
        assert not vocab.matches(decls)
        assert reconcile(decls, {"a.b": 512}, vocab.as_dict())  # 照常产出动作


class TestApply:
    def test_apply_registers_and_sets_hash(self) -> None:
        decls = [Decl("a.b", 512, doc="端口")]
        vocab = Vocabulary()
        vocab.apply(reconcile(decls, {}, {}), decls)
        assert vocab.get("a.b").default == 512  # type: ignore[union-attr]
        assert vocab.hash == declaration_hash(decls)

    def test_clean_drops_from_vocab(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("ghost", 1))
        vocab.apply(reconcile([], {"ghost": 1}, vocab.as_dict()), [])
        assert "ghost" not in vocab

    def test_skip_does_not_touch_file_but_meta_is_updated(self) -> None:
        """尊重文件，但词表里的默认值指纹要更新（只动词表、不动文件）。"""
        vocab = Vocabulary()
        vocab.register(Decl("a.b", 512))
        actions = reconcile([Decl("a.b", 2048)], {"a.b": 1024}, vocab.as_dict())
        vocab.apply(actions, [Decl("a.b", 2048)])
        assert vocab.get("a.b").default == 2048  # type: ignore[union-attr]
        assert facts_untouched() is True


def facts_untouched() -> bool:
    """这个测试里「事实」是调用方传进去的 dict，reconcile 从不改它。"""
    facts = {"a.b": 1024}
    reconcile([Decl("a.b", 2048)], facts, {})
    return facts == {"a.b": 1024}
