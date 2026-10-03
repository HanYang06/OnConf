# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""JSON 后端：外科手术式回写的**不变量**测试。

核心不变量只有一条：

    set_value(text, k, v) 与 text 的差异，必须只落在 k 的值的字节区间内。

下面每个改写测试都直接断言这一条，而不是断言"结果能解析"——
能解析还不够，用户没让我们动的字节必须逐字不动。
"""

from __future__ import annotations

import json

import pytest

from auto_conf._json_backend import (
    append_key,
    delete_key,
    find,
    iter_members,
    loads,
    render,
    set_value,
)


REAL = (
    "{\n"
    '  "$schema": "schema/settings.json",\n'
    '  "body.history.depth": 1,\n'
    '  "core.log.level": "WARNING",\n'
    '  "gc.auto.byte": 0,\n'
    '  "hub.default": "main",\n'
    '  "index.max.byte": 67108864,\n'
    '  "pack.max.byte": 2147483648,\n'
    '  "slot.max.byte.b": 512,\n'
    '  "slot.max.byte.kb": 0\n'
    "}\n"
)

TRICKY = (
    "{\n"
    '  "s": "a, b: c } { \\"q\\"",\n'
    '  "arr": [1, 2, {"k": "v"}],\n'
    '  "obj": {"x": [1]},\n'
    '  "n": null,\n'
    '  "t": true\n'
    "}\n"
)


def assert_only_span_changed(old: str, new: str, start: int, end: int, replacement: str) -> None:
    """最强形式的断言：新的文本 == 旧文本，**只有** [start, end) 被换掉。"""
    assert new == old[:start] + replacement + old[end:]


# --------------------------------------------------------------------------- #
# 读
# --------------------------------------------------------------------------- #


class TestLoads:
    def test_real_artifact(self) -> None:
        data = loads(REAL)
        assert data["$schema"] == "schema/settings.json"
        assert data["pack.max.byte"] == 2147483648
        assert len(data) == 9

    def test_order_is_preserved(self) -> None:
        assert next(iter(loads(REAL))) == "$schema"

    def test_values_are_not_processed(self) -> None:
        """透明原则：读回来的是 JSON 原本的类型，不提升、不转换。"""
        data = loads('{"i": 1, "f": 1.5, "s": "1", "b": true, "n": null}')
        assert data == {"i": 1, "f": 1.5, "s": "1", "b": True, "n": None}
        assert isinstance(data["i"], int)
        assert not isinstance(data["i"], bool)

    def test_top_level_must_be_object(self) -> None:
        with pytest.raises(TypeError, match="顶层"):
            loads("[1, 2]")


class TestRender:
    def test_scalars(self) -> None:
        assert render(1) == "1"
        assert render(True) == "true"  # noqa: FBT003 - 被测的就是布尔标量
        assert render(None) == "null"
        assert render("main") == '"main"'

    def test_non_ascii_is_kept_readable(self) -> None:
        assert render("格长") == '"格长"'

    def test_unserialisable_is_rejected_loudly(self) -> None:
        """落不成的当场拒绝 —— 写出去的值文件是坏的，代价远高于一次报错。"""
        with pytest.raises(TypeError, match="无法落成 JSON"):
            render(object())


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #


class TestScan:
    def test_members_in_order(self) -> None:
        assert [m.key for m in iter_members(REAL)] == [
            "$schema",
            "body.history.depth",
            "core.log.level",
            "gc.auto.byte",
            "hub.default",
            "index.max.byte",
            "pack.max.byte",
            "slot.max.byte.b",
            "slot.max.byte.kb",
        ]

    def test_find_missing(self) -> None:
        assert find(REAL, "nope") is None

    @pytest.mark.parametrize("key", ["s", "arr", "obj", "n", "t"])
    def test_tricky_keys_are_found(self, key: str) -> None:
        """值里有逗号 / 冒号 / 花括号 / 转义引号，不许把扫描带偏。"""
        member = find(TRICKY, key)
        assert member is not None
        assert json.loads(TRICKY[member.value_start : member.value_end]) == loads(TRICKY)[key]

    def test_nested_value_span_is_exact(self) -> None:
        member = find(TRICKY, "arr")
        assert member is not None
        assert TRICKY[member.value_start : member.value_end] == '[1, 2, {"k": "v"}]'


# --------------------------------------------------------------------------- #
# 外科手术式回写 —— 不变量
# --------------------------------------------------------------------------- #


class TestSetValue:
    def test_only_the_value_span_changes(self) -> None:
        member = find(REAL, "pack.max.byte")
        assert member is not None
        new = set_value(REAL, "pack.max.byte", 1024)
        assert_only_span_changed(REAL, new, member.value_start, member.value_end, "1024")

    def test_schema_directive_is_untouched(self) -> None:
        new = set_value(REAL, "hub.default", "other")
        assert '"$schema": "schema/settings.json"' in new
        assert new.index("$schema") < new.index("hub.default")

    def test_type_change_is_allowed(self) -> None:
        new = set_value(REAL, "slot.max.byte.b", "512")
        assert loads(new)["slot.max.byte.b"] == "512"
        assert '"slot.max.byte.b": "512"' in new

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            set_value(REAL, "nope", 1)

    def test_repeated_writes_stay_byte_stable(self) -> None:
        """写回自己（幂等）时，整篇文本逐字不变。"""
        assert set_value(REAL, "gc.auto.byte", 0) == REAL


class TestAppendKey:
    def test_only_insertion_happens(self) -> None:
        close = REAL.rindex("}")
        new = append_key(REAL, "new.key", 7)
        assert new.startswith(REAL[:close].rstrip())
        assert new.endswith("}\n")

    def test_parses_and_keeps_schema_first(self) -> None:
        new = append_key(REAL, "new.key", 7)
        data = loads(new)
        assert data["new.key"] == 7
        assert next(iter(data)) == "$schema"
        assert list(data)[-1] == "new.key"

    def test_indentation_matches_the_file(self) -> None:
        new = append_key(REAL, "new.key", 7)
        assert '\n  "new.key": 7\n}' in new

    def test_into_empty_object(self) -> None:
        new = append_key("{}\n", "a.b", 1)
        assert loads(new) == {"a.b": 1}

    def test_appended_value_is_not_processed(self) -> None:
        new = append_key(REAL, "s", "512")
        assert '"s": "512"' in new


class TestDeleteKey:
    def test_delete_middle_member(self) -> None:
        new = delete_key(REAL, "hub.default")
        data = loads(new)
        assert "hub.default" not in data
        assert data["$schema"] == "schema/settings.json"
        assert data["index.max.byte"] == 67108864

    def test_delete_last_member(self) -> None:
        new = delete_key(REAL, "slot.max.byte.kb")
        data = loads(new)
        assert list(data)[-1] == "slot.max.byte.b"
        assert "$schema" in data

    def test_delete_first_member_keeps_the_rest_intact(self) -> None:
        new = delete_key(REAL, "$schema")
        data = loads(new)
        assert "$schema" not in data
        assert next(iter(data)) == "body.history.depth"

    def test_everything_else_is_byte_identical(self) -> None:
        new = delete_key(REAL, "hub.default")
        surviving = [line for line in REAL.splitlines() if "hub.default" not in line]
        for line in surviving:
            assert line in new

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            delete_key(REAL, "nope")


class TestRoundTripOnRealArtifact:
    """一组端到端改写，最后必须仍是一个完好的值文件。"""

    def test_edit_append_delete_cycle(self) -> None:
        text = REAL
        text = set_value(text, "pack.max.byte", 1024)
        text = append_key(text, "core.storage.new", True)  # noqa: FBT003 - 被测的就是布尔值
        text = delete_key(text, "gc.auto.byte")

        data = loads(text)
        assert data["pack.max.byte"] == 1024
        assert data["core.storage.new"] is True
        assert "gc.auto.byte" not in data
        assert data["$schema"] == "schema/settings.json"
        assert set(data) == (
            set(loads(REAL)) - {"gc.auto.byte"} | {"core.storage.new"}
        )

    def test_untouched_keys_are_byte_identical(self) -> None:
        new = set_value(REAL, "gc.auto.byte", 4096)
        for key in ("$schema", "hub.default", "index.max.byte", "slot.max.byte.b"):
            old_member = find(REAL, key)
            new_member = find(new, key)
            assert old_member is not None
            assert new_member is not None
            old_text = REAL[old_member.span[0] : old_member.span[1]]
            new_text = new[new_member.span[0] : new_member.span[1]]
            assert old_text == new_text
