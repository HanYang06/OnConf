# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
""".env 后端：外科手术式回写 + 「它是字符串后端」这条硬约定。"""

from __future__ import annotations

import pytest

from auto_conf._env_backend import (
    EnvSyntaxError,
    append_key,
    delete_key,
    find,
    iter_members,
    loads,
    render,
    set_value,
)


REAL = (
    "# 值文件：改值请直接编辑本文件\n"
    "\n"
    "export PACK_MAX_BYTE=2147483648\n"
    "HUB_DEFAULT=main\n"
    "\n"
    "# 带引号的\n"
    'DB_URL="sqlite:///data/app.db"\n'
    "PASSWORD=abc#def\n"
)


def assert_only_span_changed(old: str, new: str, start: int, end: int, replacement: str) -> None:
    assert new == old[:start] + replacement + old[end:]


# --------------------------------------------------------------------------- #
# 读
# --------------------------------------------------------------------------- #


class TestLoads:
    def test_keys_and_values(self) -> None:
        assert loads(REAL)["PACK_MAX_BYTE"] == "2147483648"
        assert loads(REAL)["HUB_DEFAULT"] == "main"

    def test_values_are_always_strings(self) -> None:
        """字符串后端：不做类型推断，透明原则。"""
        data = loads("PORT=8080\nFLAG=true\nEMPTY=\n")
        assert data == {"PORT": "8080", "FLAG": "true", "EMPTY": ""}

    def test_export_prefix_is_stripped(self) -> None:
        assert loads("export A_B=1\n") == {"A_B": "1"}

    def test_double_quotes_are_unescaped(self) -> None:
        assert loads('A="a\\nb"\n')["A"] == "a\nb"
        assert loads('A="say \\"hi\\""\n')["A"] == 'say "hi"'

    def test_single_quotes_are_literal(self) -> None:
        assert loads("A='a\\nb'\n")["A"] == "a\\nb"

    def test_hash_inside_a_value_is_kept(self) -> None:
        """密码里带 # 是常态 —— 行内不认注释，这条是刻意的。"""
        assert loads(REAL)["PASSWORD"] == "abc#def"  # noqa: S105 - 这是夹具不是口令

    def test_whole_line_comment_is_skipped(self) -> None:
        assert loads("# 只有注释\n") == {}

    def test_dotted_keys_work(self) -> None:
        assert loads("pack.max.byte=1\n") == {"pack.max.byte": "1"}

    def test_malformed_line_is_rejected(self) -> None:
        with pytest.raises(EnvSyntaxError, match="第 2 行"):
            loads("A=1\n这行没有等号\n")


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #


class TestRender:
    @pytest.mark.parametrize("value", ["main", "2147483648", "sqlite:///x.db", "abc#def"])
    def test_plain_values_are_not_quoted(self, value: str) -> None:
        """``#`` 不触发引号：本后端不认行内注释，``abc#def`` 是合法裸值。"""
        assert render(value) == value

    @pytest.mark.parametrize("value", ["", "a b", "a #b", 'say "hi"', "a\nb", " lead"])
    def test_tricky_values_are_quoted_and_round_trip(self, value: str) -> None:
        rendered = render(value)
        assert rendered.startswith('"')
        assert loads(f"A={rendered}\n")["A"] == value

    @pytest.mark.parametrize("value", [512, 1.5, True, None, ["a"]])
    def test_non_string_values_are_refused_loudly(self, value: object) -> None:
        """与其假装能存，不如当场拒绝并指路。"""
        with pytest.raises(TypeError, match="只能存字符串"):
            render(value)


# --------------------------------------------------------------------------- #
# 外科手术式回写
# --------------------------------------------------------------------------- #


class TestSetValue:
    def test_only_the_value_span_changes(self) -> None:
        member = find(REAL, "HUB_DEFAULT")
        assert member is not None
        new = set_value(REAL, "HUB_DEFAULT", "other")
        assert_only_span_changed(REAL, new, member.value_start, member.value_end, "other")

    def test_export_prefix_and_comment_lines_survive(self) -> None:
        new = set_value(REAL, "PACK_MAX_BYTE", "1024")
        assert "export PACK_MAX_BYTE=1024" in new
        assert "# 值文件：改值请直接编辑本文件" in new
        assert "# 带引号的" in new

    def test_quoted_value_can_become_plain_and_still_round_trips(self) -> None:
        """原来带引号的值，新值不必要时就去掉引号 —— 反过来也一样成立。"""
        new = set_value(REAL, "DB_URL", "sqlite:///other.db")
        assert "DB_URL=sqlite:///other.db" in new
        assert loads(new)["DB_URL"] == "sqlite:///other.db"

    def test_value_needing_quotes_gets_them(self) -> None:
        new = set_value(REAL, "HUB_DEFAULT", "a b")
        assert 'HUB_DEFAULT="a b"' in new
        assert loads(new)["HUB_DEFAULT"] == "a b"

    def test_writing_the_same_value_is_byte_stable(self) -> None:
        assert set_value(REAL, "HUB_DEFAULT", "main") == REAL

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            set_value(REAL, "NOPE", "x")


class TestAppendDelete:
    def test_append_keeps_existing_bytes(self) -> None:
        new = append_key(REAL, "NEW_KEY", "v")
        assert new.startswith(REAL)
        assert loads(new)["NEW_KEY"] == "v"

    def test_append_into_empty_file(self) -> None:
        assert loads(append_key("", "A_B", "1")) == {"A_B": "1"}

    def test_append_without_trailing_newline(self) -> None:
        assert loads(append_key("A=1", "B", "2")) == {"A": "1", "B": "2"}

    def test_delete_removes_only_that_line(self) -> None:
        new = delete_key(REAL, "HUB_DEFAULT")
        assert "HUB_DEFAULT" not in new
        assert "# 值文件：改值请直接编辑本文件" in new
        assert "PACK_MAX_BYTE=2147483648" in new or "export PACK_MAX_BYTE=2147483648" in new

    def test_delete_missing_raises(self) -> None:
        with pytest.raises(KeyError):
            delete_key(REAL, "NOPE")


class TestScan:
    def test_members_in_order(self) -> None:
        assert [m.key for m in iter_members(REAL)] == [
            "PACK_MAX_BYTE",
            "HUB_DEFAULT",
            "DB_URL",
            "PASSWORD",
        ]

    def test_value_span_excludes_surrounding_spaces(self) -> None:
        member = find("A  =  main  \n", "A")
        assert member is not None
        assert "A  =  main  \n"[member.value_start : member.value_end] == "main"

    def test_empty_value_has_an_empty_span(self) -> None:
        member = find("A=\n", "A")
        assert member is not None
        assert member.value_start == member.value_end
        assert set_value("A=\n", "A", "1") == "A=1\n"
