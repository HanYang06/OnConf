# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""YAML 后端：外科手术式回写的**不变量**测试。

核心不变量（比 JSON 那条更要紧，因为注释只活在 YAML 里）：

    改一个键的值，用户手写的注释 / 缩进 / 键序 / 其余行，逐字不动。

以及一组**拒绝**测试：v1 遇到嵌套、块标量、跨行集合、多文档必须报错，
不许猜、不许静默搞坏。
"""

from __future__ import annotations

import pytest
import yaml

from onconf._yaml_backend import (
    YamlFlatRequiredError,
    append_key,
    delete_key,
    find,
    iter_members,
    loads,
    render,
    render_key,
    set_value,
)


REAL = (
    "# Cairn 配置值文件\n"
    "# 改值请直接编辑本文件；改默认值请改声明的那个 conf(...) 调用点\n"
    "\n"
    "pack.max.byte: 2147483648   # 封口线：单个载体写满这个数就换新的一份\n"
    "hub.default: main           # 默认 hub 名：写入不点名时进这一个\n"
    "slot.max.byte.b: 512        # 格长档位之一（字节）\n"
    "index.max.byte: 67108864    # 一个索引块的体积上限（字节）\n"
)


def assert_only_span_changed(old: str, new: str, start: int, end: int, replacement: str) -> None:
    assert new == old[:start] + replacement + old[end:]


# --------------------------------------------------------------------------- #
# 读
# --------------------------------------------------------------------------- #


class TestLoads:
    def test_reads_flat_mapping(self) -> None:
        data = loads(REAL)
        assert data["pack.max.byte"] == 2147483648
        assert data["hub.default"] == "main"

    def test_order_is_preserved(self) -> None:
        assert list(loads(REAL)) == [
            "pack.max.byte",
            "hub.default",
            "slot.max.byte.b",
            "index.max.byte",
        ]

    def test_values_are_not_processed(self) -> None:
        assert loads('i: 1\ns: "1"\nb: true\nn: null\n') == {
            "i": 1,
            "s": "1",
            "b": True,
            "n": None,
        }

    def test_an_explicit_tag_is_respected(self) -> None:
        """``!!str "8080"`` 读回**字符串**：载体明说了类型，引擎原样交出。"""
        assert loads('port: !!str "8080"\n') == {"port": "8080"}

    def test_empty_file(self) -> None:
        assert loads("") == {}
        assert loads("# 只有注释\n") == {}

    def test_multi_document_is_rejected(self) -> None:
        with pytest.raises(YamlFlatRequiredError, match="多文档"):
            loads("a: 1\n---\nb: 2\n")

    def test_top_level_must_be_mapping(self) -> None:
        with pytest.raises(TypeError, match="顶层"):
            loads("- 1\n- 2\n")


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
            (None, "null"),
            (1.5, "1.5"),
            ("main", "main"),
        ],
    )
    def test_simple_scalars(self, value: object, expected: str) -> None:
        assert render(value) == expected

    def test_unicode_is_kept_readable(self) -> None:
        assert render("格长") == "格长"

    def test_string_needing_quotes_gets_quoted(self) -> None:
        assert yaml.safe_load(render("a: b")) == "a: b"
        assert render("a: b").startswith(("'", '"'))

    def test_collections_are_flow_style(self) -> None:
        assert yaml.safe_load(render([1, 2])) == [1, 2]
        assert yaml.safe_load(render({"k": "v"})) == {"k": "v"}

    def test_multiline_value_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="跨了多行"):
            render("a\nb")

    def test_unrepresentable_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="无法落成 YAML"):
            render(object())

    def test_key_quoting(self) -> None:
        assert render_key("pack.max.byte") == "pack.max.byte"
        assert yaml.safe_load(render_key("a: b") + ": 1") == {"a: b": 1}


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #


class TestScan:
    def test_members_skip_comments_and_blanks(self) -> None:
        assert [m.key for m in iter_members(REAL)] == [
            "pack.max.byte",
            "hub.default",
            "slot.max.byte.b",
            "index.max.byte",
        ]

    def test_value_span_excludes_comment_and_padding(self) -> None:
        member = find(REAL, "hub.default")
        assert member is not None
        assert REAL[member.value_start : member.value_end] == "main"

    def test_hash_without_leading_space_is_not_a_comment(self) -> None:
        text = "a.b: x#y\n"
        member = find(text, "a.b")
        assert member is not None
        assert text[member.value_start : member.value_end] == "x#y"

    def test_hash_inside_quotes_is_not_a_comment(self) -> None:
        text = 'a.b: "x # y"   # 真注释\n'
        member = find(text, "a.b")
        assert member is not None
        assert text[member.value_start : member.value_end] == '"x # y"'

    def test_find_missing(self) -> None:
        assert find(REAL, "nope") is None

    def test_quoted_key_is_found(self) -> None:
        text = '"a.b": 1\n'
        member = find(text, "a.b")
        assert member is not None
        assert text[member.value_start : member.value_end] == "1"


class TestRefusals:
    """v1 只支持扁平映射。不支持的构造必须**报错**，不能猜。"""

    def test_nested_block_mapping(self) -> None:
        with pytest.raises(YamlFlatRequiredError, match=r"下一行|缩进"):
            list(iter_members("pack:\n  max: 1\n"))

    def test_key_with_value_on_next_line(self) -> None:
        with pytest.raises(YamlFlatRequiredError):
            list(iter_members("pack:   # 注释\n  max: 1\n"))

    def test_block_scalar(self) -> None:
        with pytest.raises(YamlFlatRequiredError, match="块标量"):
            list(iter_members("note: |\n  hello\n"))

    def test_multiline_flow_collection(self) -> None:
        with pytest.raises(YamlFlatRequiredError, match="跨了多行"):
            list(iter_members("a.b: [1,\n  2]\n"))

    def test_stray_indented_line_names_the_line(self) -> None:
        with pytest.raises(YamlFlatRequiredError, match="第 2 行"):
            list(iter_members("a: 1\n  b: 2\n"))


# --------------------------------------------------------------------------- #
# 外科手术式回写 —— 不变量
# --------------------------------------------------------------------------- #


class TestSetValue:
    def test_only_the_value_span_changes(self) -> None:
        member = find(REAL, "slot.max.byte.b")
        assert member is not None
        new = set_value(REAL, "slot.max.byte.b", 1024)
        assert_only_span_changed(REAL, new, member.value_start, member.value_end, "1024")

    def test_trailing_comment_survives(self) -> None:
        new = set_value(REAL, "hub.default", "other")
        assert "# 默认 hub 名：写入不点名时进这一个" in new

    def test_header_comments_survive(self) -> None:
        new = set_value(REAL, "hub.default", "other")
        assert new.startswith("# Cairn 配置值文件\n# 改值请直接编辑本文件")

    def test_all_other_lines_are_byte_identical(self) -> None:
        new = set_value(REAL, "hub.default", "other")
        old_lines = REAL.splitlines()
        new_lines = new.splitlines()
        assert len(old_lines) == len(new_lines)
        for old_line, new_line in zip(old_lines, new_lines, strict=False):
            if "hub.default" not in old_line:
                assert old_line == new_line

    def test_writing_the_same_value_is_byte_stable(self) -> None:
        assert set_value(REAL, "hub.default", "main") == REAL

    def test_type_change_is_allowed(self) -> None:
        new = set_value(REAL, "slot.max.byte.b", "512")
        assert loads(new)["slot.max.byte.b"] == "512"
        assert "slot.max.byte.b: '512'" in new

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            set_value(REAL, "nope", 1)

    def test_refuses_on_unparsable_file(self) -> None:
        with pytest.raises(YamlFlatRequiredError):
            set_value("a:\n  b: 1\n", "a", 2)


class TestAppendKey:
    def test_appends_after_last_member(self) -> None:
        new = append_key(REAL, "gc.auto.byte", 0)
        assert loads(new)["gc.auto.byte"] == 0
        assert list(loads(new))[-1] == "gc.auto.byte"

    def test_existing_bytes_are_preserved(self) -> None:
        new = append_key(REAL, "gc.auto.byte", 0)
        assert new.startswith(REAL)

    def test_into_empty_file(self) -> None:
        assert loads(append_key("", "a.b", 1)) == {"a.b": 1}

    def test_into_file_without_trailing_newline(self) -> None:
        new = append_key("a.b: 1", "c.d", 2)
        assert loads(new) == {"a.b": 1, "c.d": 2}


class TestDeleteKey:
    def test_deletes_only_that_line(self) -> None:
        new = delete_key(REAL, "hub.default")
        assert "hub.default" not in new
        assert "# Cairn 配置值文件" in new
        assert "pack.max.byte: 2147483648   # 封口线：单个载体写满这个数就换新的一份" in new

    def test_remaining_parses(self) -> None:
        new = delete_key(REAL, "hub.default")
        assert list(loads(new)) == ["pack.max.byte", "slot.max.byte.b", "index.max.byte"]

    def test_comment_above_is_deliberately_kept(self) -> None:
        """保守取舍：宁可留孤儿注释，也不删用户没让我们删的字。"""
        text = "# 这一行是 hub 的说明\nhub.default: main\n"
        new = delete_key(text, "hub.default")
        assert "# 这一行是 hub 的说明" in new

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            delete_key(REAL, "nope")


class TestEditCycle:
    def test_edit_append_delete_keeps_the_file_sane(self) -> None:
        text = REAL
        text = set_value(text, "index.max.byte", 33554432)
        text = append_key(text, "gc.auto.byte", 0)
        text = delete_key(text, "hub.default")

        data = loads(text)
        assert data["index.max.byte"] == 33554432
        assert data["gc.auto.byte"] == 0
        assert "hub.default" not in data
        assert set(data) == set(loads(REAL)) - {"hub.default"} | {"gc.auto.byte"}
