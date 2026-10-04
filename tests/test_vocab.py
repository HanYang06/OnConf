# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""词表的三态、JSON Schema 往返、以及哈希短路。"""

from __future__ import annotations

import json

import pytest

from onconf._core import NO_VALUE, Decl, declaration_hash, read_value, reconcile
from onconf._vocab import Vocabulary, type_from_json, type_to_json
from onconf.errors import KeyHasNoValueError


class TestTypeMapping:
    @pytest.mark.parametrize(
        ("py", "js"),
        [
            (bool, "boolean"),
            (int, "integer"),
            (float, "number"),
            (str, "string"),
            (list, "array"),
            (tuple, "array"),
            (dict, "object"),
            (type(None), "null"),
            (None, None),
        ],
    )
    def test_py_to_json(self, py: type | None, js: str | None) -> None:
        assert type_to_json(py) == js

    def test_bool_is_not_int(self) -> None:
        """Bool 是 int 的子类，映射顺序错了会把 bool 写成 integer。"""
        assert type_to_json(bool) == "boolean"

    def test_json_to_py(self) -> None:
        assert type_from_json("integer") is int
        assert type_from_json("boolean") is bool
        assert type_from_json(None) is None


class TestTriState:
    """§17.7：未登记 / 已登记无值 / 值为 None —— 三态不许塌陷。"""

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
        vocab.register(Decl("has.default", 512, type=int, doc="端口"))

        restored = Vocabulary.from_schema(vocab.to_schema())

        assert restored.get("only.registered").default is NO_VALUE  # type: ignore[union-attr]
        assert restored.get("is.none").default is None  # type: ignore[union-attr]
        assert restored.get("has.default").default == 512  # type: ignore[union-attr]
        assert restored.get("has.default").type is int  # type: ignore[union-attr]

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

    def test_tuple_type_is_preserved_via_extension(self) -> None:
        """JSON Schema 没有 tuple，靠 x-onconf-py 无损保留。"""
        vocab = Vocabulary()
        vocab.register(Decl("a.b", (1, 2), type=tuple))
        schema = vocab.to_schema()["properties"]["a.b"]
        assert schema["type"] == "array"
        assert schema["x-onconf-py"] == "tuple"
        assert Vocabulary.from_schema(vocab.to_schema()).get("a.b").type is tuple  # type: ignore[union-attr]

    def test_schema_is_json_serialisable(self) -> None:
        vocab = Vocabulary()
        vocab.register(Decl("a.b", 512, type=int, doc="端口"))
        restored = Vocabulary.from_schema(json.loads(json.dumps(vocab.to_schema())))
        assert restored.get("a.b").doc == "端口"  # type: ignore[union-attr]
        assert restored.get("a.b").default == 512  # type: ignore[union-attr]

    def test_hash_survives_round_trip(self) -> None:
        decls = [Decl("a.b", 512, type=int)]
        vocab = Vocabulary()
        vocab.apply(reconcile(decls, {}, {}), decls)
        restored = Vocabulary.from_schema(vocab.to_schema())
        assert restored.hash == vocab.hash


class TestHashShortCircuit:
    """§18.7：对得上 ⇒ 整体跳过；对不上 ⇒ 走完整对账（不是报错）。"""

    def test_first_run_is_dirty(self) -> None:
        assert not Vocabulary().matches([Decl("a.b", 512)])

    def test_after_commit_it_matches(self) -> None:
        decls = [Decl("a.b", 512, type=int)]
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
        decls = [Decl("a.b", 512, type=int, doc="端口")]
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
        """§18.5 结论 1：尊重文件，但词表里的默认值指纹要更新。"""
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
