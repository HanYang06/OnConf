# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""TOML 后端：表头归一成点分键 + 外科手术式回写的不变量。"""

from __future__ import annotations

import datetime as dt

import pytest

from auto_conf._toml_backend import (
    TomlFlatRequiredError,
    append_key,
    delete_key,
    find,
    iter_members,
    loads,
    render,
    render_pair,
    set_value,
)


REAL = (
    "# 值文件：改值请直接编辑本文件\n"
    "\n"
    "pack.max.byte = 2147483648   # 封口线\n"
    'hub.default = "main"          # 默认 hub 名\n'
    "\n"
    "[gc]\n"
    "auto.byte = 0                 # 0 即不自动回收\n"
)


def assert_only_span_changed(old: str, new: str, start: int, end: int, replacement: str) -> None:
    assert new == old[:start] + replacement + old[end:]


# --------------------------------------------------------------------------- #
# 读：表头归一成点分键
# --------------------------------------------------------------------------- #


class TestLoads:
    def test_table_header_becomes_a_dotted_key(self) -> None:
        """``[gc]`` + ``auto.byte = 0`` ⇒ 键 ``gc.auto.byte``（§28.4）。"""
        data = loads(REAL)
        assert data["gc.auto.byte"] == 0
        assert "gc" not in data

    def test_flat_dotted_keys_work(self) -> None:
        data = loads(REAL)
        assert data["pack.max.byte"] == 2147483648
        assert data["hub.default"] == "main"

    def test_values_keep_their_toml_types(self) -> None:
        data = loads('i = 1\nf = 1.5\nb = true\ns = "1"\narr = [1, 2]\n')
        assert data == {"i": 1, "f": 1.5, "b": True, "s": "1", "arr": [1, 2]}
        assert isinstance(data["i"], int)
        assert not isinstance(data["i"], bool)

    def test_datetime_stays_a_datetime(self) -> None:
        data = loads("when = 1979-05-27T07:32:00Z\n")
        assert isinstance(data["when"], dt.datetime)

    def test_quoted_string_with_hash_is_not_a_comment(self) -> None:
        assert loads('a.b = "x # y"   # 真注释\n') == {"a.b": "x # y"}

    def test_empty_file(self) -> None:
        assert loads("") == {}
        assert loads("# 只有注释\n") == {}


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #


class TestRender:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (512, "512"),
            (True, "true"),
            (False, "false"),
            (1.5, "1.5"),
            ("main", '"main"'),
        ],
    )
    def test_scalars(self, value: object, expected: str) -> None:
        assert render(value) == expected

    def test_unicode_is_kept_readable(self) -> None:
        assert render("格长") == '"格长"'
        assert loads(f"a = {render('格长')}")["a"] == "格长"

    def test_escaping_round_trips(self) -> None:
        for value in ['say "hi"', "a\\b", "a\nb", "a\tb"]:
            assert loads(f"a = {render(value)}")["a"] == value

    def test_array_and_inline_table(self) -> None:
        assert loads(f"a = {render([1, 2])}")["a"] == [1, 2]
        assert loads(f"a = {render({'k': 'v'})}")["a"] == {"k": "v"}

    def test_none_is_refused_loudly(self) -> None:
        """TOML 没有 null —— 写不进去就是写不进去。"""
        with pytest.raises(TypeError, match="没有 null"):
            render(None)

    def test_unrepresentable_is_refused(self) -> None:
        with pytest.raises(TypeError, match="无法落成 TOML"):
            render(object())

    def test_render_pair(self) -> None:
        assert render_pair("a.b", 1) == "a.b = 1"


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #


class TestScan:
    def test_keys_and_sections(self) -> None:
        members = list(iter_members(REAL))
        assert [m.key for m in members] == ["pack.max.byte", "hub.default", "gc.auto.byte"]
        assert [m.section for m in members] == [(), (), ("gc",)]

    def test_value_span_excludes_comment_and_padding(self) -> None:
        member = find(REAL, "hub.default")
        assert member is not None
        assert REAL[member.value_start : member.value_end] == '"main"'

    def test_find_missing(self) -> None:
        assert find(REAL, "nope") is None


class TestRefusals:
    def test_array_of_tables(self) -> None:
        with pytest.raises(TomlFlatRequiredError, match="表数组"):
            loads("[[a]]\nb = 1\n")

    def test_multiline_value(self) -> None:
        with pytest.raises(TomlFlatRequiredError, match="跨了多行"):
            loads("a = [1,\n  2]\n")

    def test_value_on_next_line(self) -> None:
        with pytest.raises(TomlFlatRequiredError):
            loads("a =\n")

    def test_garbage_line(self) -> None:
        with pytest.raises(TomlFlatRequiredError, match="不是 `键 = 值`"):
            loads("a = 1\n这行没有等号\n")


# --------------------------------------------------------------------------- #
# 外科手术式回写 —— 不变量
# --------------------------------------------------------------------------- #


class TestSetValue:
    def test_only_the_value_span_changes(self) -> None:
        member = find(REAL, "gc.auto.byte")
        assert member is not None
        new = set_value(REAL, "gc.auto.byte", 4096)
        assert_only_span_changed(REAL, new, member.value_start, member.value_end, "4096")

    def test_comments_and_headers_survive(self) -> None:
        new = set_value(REAL, "pack.max.byte", 1024)
        assert "# 值文件：改值请直接编辑本文件" in new
        assert "pack.max.byte = 1024   # 封口线" in new
        assert "[gc]" in new

    def test_all_other_lines_are_byte_identical(self) -> None:
        new = set_value(REAL, "hub.default", '"other"')
        for old_line in REAL.splitlines():
            if "hub" not in old_line:
                assert old_line in new

    def test_writing_the_same_value_is_byte_stable(self) -> None:
        assert set_value(REAL, "hub.default", "main") == REAL

    def test_a_table_key_is_editable_in_place(self) -> None:
        new = set_value(REAL, "gc.auto.byte", 1)
        assert loads(new)["gc.auto.byte"] == 1
        assert "[gc]" in new

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            set_value(REAL, "nope", 1)


class TestAppendKey:
    def test_into_an_existing_section(self) -> None:
        new = append_key(REAL, "gc.manual", 1)
        assert loads(new) == {**loads(REAL), "gc.manual": 1}
        assert new.startswith(REAL)

    def test_creates_a_new_section(self) -> None:
        new = append_key(REAL, "index.max.byte", 67108864)
        assert loads(new)["index.max.byte"] == 67108864
        assert "[index.max]" in new

    def test_top_level_key_goes_before_the_first_header(self) -> None:
        """TOML 的语法要求：裸键必须排在第一个表头之前。"""
        new = append_key(REAL, "version", 1)
        assert loads(new)["version"] == 1
        assert new.index("version = 1") < new.index("[gc]")

    def test_top_level_key_into_a_headerless_file(self) -> None:
        new = append_key("a = 1\n", "b", 2)
        assert loads(new) == {"a": 1, "b": 2}

    def test_into_an_empty_file(self) -> None:
        assert loads(append_key("", "a.b", 1)) == {"a.b": 1}


class TestDeleteKey:
    def test_delete_a_table_key(self) -> None:
        new = delete_key(REAL, "gc.auto.byte")
        assert "gc.auto.byte" not in loads(new)
        assert "[gc]" in new  # 表头本身留着

    def test_delete_a_top_level_key(self) -> None:
        new = delete_key(REAL, "hub.default")
        assert "hub.default" not in loads(new)
        assert "# 值文件：改值请直接编辑本文件" in new
        assert loads(new)["pack.max.byte"] == 2147483648

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            delete_key(REAL, "nope")


class TestEditCycle:
    def test_edit_append_delete_stays_sane(self) -> None:
        text = REAL
        text = set_value(text, "gc.auto.byte", 4096)
        text = append_key(text, "index.max.byte", 67108864)
        text = delete_key(text, "hub.default")

        data = loads(text)
        assert data["gc.auto.byte"] == 4096
        assert data["index.max.byte"] == 67108864
        assert "hub.default" not in data
        assert data["pack.max.byte"] == 2147483648
