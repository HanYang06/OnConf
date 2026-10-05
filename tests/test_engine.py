# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引擎装配的端到端测试：声明 → 对账 → 落盘 → 读回。

这里测的是**用户真正看得见的行为**，不是内部函数。
每个测试都在 tmp_path 里造一个全新的配置世界。
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from onconf import (
    AutoConf,
    ConfError,
    EngineParams,
    KeyHasNoValueError,
    KeyNotRegisteredError,
    _reset,
    conf,
)
from onconf._engine import SCHEMA_POINTER, Engine, default_home
from onconf._lock import LockTimeoutError, exclusive


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate() -> Iterator[None]:
    _reset()
    yield
    _reset()


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return Engine(tmp_path)


# --------------------------------------------------------------------------- #
# 声明 / 读
# --------------------------------------------------------------------------- #


class TestDeclareAndRead:
    def test_declare_returns_the_effective_value(self, engine: Engine) -> None:
        """返回的是当前生效值，不是声明处的默认值（§17.9 / 缺陷 D5）。"""
        assert engine("pack.max.byte", 2147483648) == 2147483648

    def test_read_after_declare_comes_from_the_file(self, engine: Engine) -> None:
        engine("hub.default", "main")
        assert engine("hub.default") == "main"

    def test_values_land_in_the_file(self, engine: Engine) -> None:
        engine("hub.default", "main")
        data = json.loads(engine.values_path.read_text(encoding="utf-8"))
        assert data["hub.default"] == "main"

    def test_plain_call_is_a_read_not_a_register(self, engine: Engine) -> None:
        with pytest.raises(KeyNotRegisteredError):
            engine("nope")

    def test_metadata_only_call_registers_then_reads(self, engine: Engine) -> None:
        """``conf(key, doc=…)`` = 登记 + 立刻取值 ⇒ 没配就报错。

        这正是「启动即校验必填项」：键进了词表，但事实里没有值。
        """
        with pytest.raises(KeyHasNoValueError):
            engine("probe.doc", doc="这是个必填键")

        # 登记是**发生了**的：再读一次，错的是「没有值」而不是「没登记」
        with pytest.raises(KeyHasNoValueError):
            engine("probe.doc")
        assert "probe.doc" in engine._vocab

    def test_none_is_a_legal_value(self, engine: Engine) -> None:
        engine("a.b", None)
        assert engine("a.b") is None

    def test_declaring_does_not_touch_an_edited_value(self, engine: Engine) -> None:
        """文件是权威：用户改过的值，声明不会把它冲掉。"""
        engine("a.b", 1)
        engine.values_path.write_text(
            json.dumps({"$schema": SCHEMA_POINTER, "a.b": 42}, indent=2) + "\n",
            encoding="utf-8",
        )
        fresh = Engine(engine.home)
        assert fresh("a.b", 1) == 42

    def test_a_differing_value_is_never_overwritten(self, engine: Engine) -> None:
        """运行期**没有覆盖出口**：值不一致 ⇒ 值文件逐字不动。

        覆盖既存值是人主动发起的事（命令行的 ``build`` / ``sync``），
        不属于代码的写路径。
        """
        engine("a.b", 1)
        before = engine.values_path.read_bytes()

        fresh = Engine(engine.home)
        assert fresh("a.b", 42) == 1
        assert engine.values_path.read_bytes() == before


# --------------------------------------------------------------------------- #
# 值文件 / 词表
# --------------------------------------------------------------------------- #


class TestArtifacts:
    def test_values_file_gets_a_schema_pointer(self, engine: Engine) -> None:
        """新建值文件时写下 $schema，编辑器立刻有补全（§27.3）。"""
        engine("a.b", 1)
        assert json.loads(engine.values_path.read_text(encoding="utf-8"))["$schema"] == (
            SCHEMA_POINTER
        )

    def test_schema_file_is_written(self, engine: Engine) -> None:
        engine("a.b", 1, doc="说明")
        schema = json.loads(engine.schema_path.read_text(encoding="utf-8"))
        assert schema["properties"]["a.b"]["default"] == 1
        assert schema["properties"]["a.b"]["description"] == "说明"

    def test_schema_lives_next_to_the_values_file(self, engine: Engine) -> None:
        assert engine.schema_path.parent.name == "schema"
        assert engine.schema_path.name == "settings.json"

    def test_user_comments_survive_a_new_key(self, tmp_path: Path) -> None:
        """YAML 值文件：补一个新键，用户手写的注释逐字保留（§27.3）。"""
        values = tmp_path / "settings.yaml"
        values.write_text(
            "# 我手写的注释\na.b: 1   # 行尾注释\nc.d: 2\n",
            encoding="utf-8",
        )
        Engine(tmp_path, file_type="yaml")("e.f", 99)

        text = values.read_text(encoding="utf-8")
        assert "# 我手写的注释" in text
        assert "a.b: 1   # 行尾注释" in text
        assert "c.d: 2" in text
        assert "e.f: 99" in text

    def test_appending_a_key_keeps_existing_comments(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.yaml"
        values.write_text("# 头注释\na.b: 1   # 行尾\n", encoding="utf-8")
        Engine(tmp_path, file_type="yaml")("c.d", 2)

        text = values.read_text(encoding="utf-8")
        assert "# 头注释" in text
        assert "a.b: 1   # 行尾" in text
        assert "c.d: 2" in text

    def test_repeat_run_writes_nothing(self, engine: Engine) -> None:
        """声明集没变 ⇒ 哈希短路 ⇒ 一个字节都不写（§18.7）。"""
        engine("a.b", 1)
        stamp = engine.values_path.stat().st_mtime_ns
        schema_stamp = engine.schema_path.stat().st_mtime_ns

        fresh = Engine(engine.home)
        assert fresh("a.b", 1) == 1
        assert engine.values_path.stat().st_mtime_ns == stamp
        assert engine.schema_path.stat().st_mtime_ns == schema_stamp


class TestIndirection:
    """值代表另一个配置项 —— 引擎不设限（§28.3）。

    ``conf(conf("alias"))`` 的**第一实参仍是字面量**，静态扫描看得见 ``alias`` 这一层；
    看不见的只有它解出来的那一层，这是明示的代价，不是禁令。
    """

    def test_value_can_be_another_key(self, engine: Engine) -> None:
        engine("real.key", 512)
        engine("alias.key", "real.key")
        assert engine(engine("alias.key")) == 512

    def test_direct_and_indirect_agree(self, engine: Engine) -> None:
        engine("real.key", 512)
        engine("alias.key", "real.key")
        assert engine(engine("alias.key")) == engine("real.key")

    def test_chain_of_three(self, engine: Engine) -> None:
        engine("third", "second")
        engine("second", "first")
        engine("first", "终点")
        assert engine(engine(engine("third"))) == "终点"

    def test_non_string_key_names_the_real_problem(self, engine: Engine) -> None:
        engine("a.number", 512)
        with pytest.raises(TypeError, match="键必须是字符串"):
            engine(engine("a.number"))


class TestSchemaPointer:
    def test_pointer_is_added_to_an_existing_file(self, tmp_path: Path) -> None:
        """老文件缺指针也要补 —— 没有它编辑器不知道词表在哪（§28.6）。"""
        values = tmp_path / "settings.yaml"
        values.write_text("# 注释\npack.max.byte: 1\n", encoding="utf-8")

        Engine(tmp_path, file_type="yaml")("hub.default", "main")

        text = values.read_text(encoding="utf-8")
        assert "$schema" in text
        assert SCHEMA_POINTER in text
        assert "# 注释" in text
        assert "pack.max.byte: 1" in text

    def test_pointer_is_idempotent(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.yaml"
        values.write_text("# 注释\npack.max.byte: 1\n", encoding="utf-8")

        Engine(tmp_path, file_type="yaml")("hub.default", "main")
        once = values.read_text(encoding="utf-8")
        Engine(tmp_path, file_type="yaml")("index.max.byte", 2)
        twice = values.read_text(encoding="utf-8")

        assert twice.count("$schema") == 1
        assert twice.startswith(once.splitlines()[0])


class TestCleanIsDeferredToTheCommitPoint:
    """规则 1（清理未知数据）只有在**期望集完整**时才允许跑。

    这条是回归测试：增量声明若顺手清理，会把文件里「还没声明到」的键全删掉。
    """

    def test_incremental_declare_does_not_delete_unseen_keys(self, engine: Engine) -> None:
        engine("a.b", 1)
        engine("c.d", 2)
        data = json.loads(engine.values_path.read_text(encoding="utf-8"))
        assert data["a.b"] == 1
        assert data["c.d"] == 2

    def test_existing_user_values_are_never_rewritten(self, tmp_path: Path) -> None:
        """值不一致 ⇒ 尊重文件：整篇值文件逐字不变（含注释、键序、行尾）。"""
        values = tmp_path / "settings.yaml"
        original = "$schema: schema/settings.json\n# 我手写的\na.b: 1   # 行尾注释\nc.d: 2\n"
        values.write_text(original, encoding="utf-8")

        Engine(tmp_path, file_type="yaml")("a.b", 99)

        assert values.read_text(encoding="utf-8") == original

    def test_sync_cleans_what_the_declaration_set_does_not_know(self, engine: Engine) -> None:
        engine("a.b", 1)
        engine.values_path.write_text(
            json.dumps({"$schema": SCHEMA_POINTER, "a.b": 1, "ghost": 9}, indent=2) + "\n",
            encoding="utf-8",
        )
        fresh = Engine(engine.home)
        fresh("a.b", 1)
        fresh.sync()

        data = json.loads(engine.values_path.read_text(encoding="utf-8"))
        assert "ghost" not in data
        assert data["a.b"] == 1

    def test_sync_keeps_the_schema_pointer(self, engine: Engine) -> None:
        engine("a.b", 1)
        engine.sync()
        assert json.loads(engine.values_path.read_text(encoding="utf-8"))["$schema"] == (
            SCHEMA_POINTER
        )


# --------------------------------------------------------------------------- #
# 已摘除的参数：``type=`` / ``force=`` / ``**engine``
# --------------------------------------------------------------------------- #


class TestRemovedParameters:
    """参数面收敛的回归：摘掉的参数传进来必须当场 ``TypeError``，不许静默降级。

    旧行为里 ``conf(key, force=True)`` 会被当成**读** —— 调用方以为在覆盖，
    实际什么都没发生。``**engine`` 同理，让使用口也能配置引擎。
    """

    def test_type_is_gone(self, engine: Engine) -> None:
        with pytest.raises(TypeError, match="type"):
            engine("a.b", 512, type=int)  # type: ignore[call-arg]

    def test_force_is_gone(self, engine: Engine) -> None:
        with pytest.raises(TypeError, match="force"):
            engine("a.b", 512, force=True)  # type: ignore[call-arg]

    def test_engine_params_are_gone_from_the_usage_face(self, tmp_path: Path) -> None:
        """使用口不得配置引擎：``conf(…, home=…)`` 是 ``TypeError``。"""
        AutoConf(home=str(tmp_path))
        with pytest.raises(TypeError, match="home"):
            conf("a.b", 1, home=str(tmp_path / "other"))  # type: ignore[call-arg]

    def test_values_are_not_converted_on_read(self, engine: Engine) -> None:
        """透明原则：写进去什么类型，读回来还是什么类型。"""
        engine("a.b", 512)
        engine("c.d", "512")
        assert isinstance(engine("a.b"), int)
        assert isinstance(engine("c.d"), str)

    def test_engine_params_match_the_constructor(self) -> None:
        """``EngineParams`` 的注解与 ``Engine.__init__`` 的形参逐一对应。"""
        ctor = set(inspect.signature(Engine.__init__).parameters) - {"self"}
        assert set(EngineParams.__annotations__) == ctor

    def test_lock_timeout_is_reachable_from_the_public_surface(self, tmp_path: Path) -> None:
        """``lock_timeout`` 以前对公开 API 完全不可达（``EngineParams`` 里没有它）。"""
        engine = AutoConf(home=str(tmp_path), lock_timeout=30.0)
        assert engine.lock_timeout == 30.0


# --------------------------------------------------------------------------- #
# 值文件的选定：``file_type`` 显式声明，不再按存在性挑
# --------------------------------------------------------------------------- #


class TestValueFileSelection:
    def test_default_is_json(self, tmp_path: Path) -> None:
        """默认就是**字面** ``"json"`` —— 「本质上以 JSON 为主」这条定位的落点。"""
        assert Engine(tmp_path).values_path.name == "settings.json"

    def test_empty_string_is_no_longer_a_type(self, tmp_path: Path) -> None:
        """缺省值是**字面** ``"json"``：空串不再是「等价于 json」的暗号（D01 §5）。"""
        with pytest.raises(ConfError, match="不认识的 file_type"):
            Engine(tmp_path, file_type="")

    def test_file_type_decides_the_suffix(self, tmp_path: Path) -> None:
        for file_type, name in (
            ("json", "settings.json"),
            ("yaml", "settings.yaml"),
            ("yml", "settings.yml"),
            ("toml", "settings.toml"),
            ("env", "settings.env"),
        ):
            assert Engine(tmp_path, file_type=file_type).values_path.name == name

    def test_a_brand_new_file_uses_the_backend_seed(self, tmp_path: Path) -> None:
        """新建值文件必须从**后端给的种子**起步，四种后端都要能落第一个键。

        这条是回归：种子以前写死成 ``"{}"``，TOML / YAML 后端会把它当内容解析而炸掉。
        以前「用哪个文件」按存在性挑，非 JSON 文件必然已经存在，所以那条路踩不到。
        """
        for file_type, key, value in (
            ("json", "a.b", 1),
            ("yaml", "a.b", 1),
            ("toml", "a.b", 1),
            ("env", "A_B", "1"),
        ):
            home = tmp_path / file_type
            Engine(home, file_type=file_type)(key, value)
            assert (home / f"settings.{file_type}").exists()
            assert Engine(home, file_type=file_type)(key) == value

    def test_unknown_file_type_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfError, match="不认识的 file_type"):
            Engine(tmp_path, file_type="ini")

    def test_existence_no_longer_decides(self, tmp_path: Path) -> None:
        """目录里只有 ``settings.yaml`` 也**不会**被自动选中 —— 选定是显式的。"""
        (tmp_path / "settings.yaml").write_text("a.b: 1\n", encoding="utf-8")
        engine = Engine(tmp_path)
        assert engine.values_path.name == "settings.json"
        with pytest.raises(KeyNotRegisteredError):
            engine("a.b")


class TestCrossBackendTypes:
    """同一个键，不同后端读回不同类型 —— **不承诺可移植**（D01 §2.3）。

    这条差异刻意不进词表（词表只有一份 JSON Schema），只写进 README 与设计页。
    """

    def test_the_same_key_reads_differently_per_backend(self, tmp_path: Path) -> None:
        json_home = tmp_path / "json"
        json_home.mkdir()
        (json_home / "settings.json").write_text(
            '{\n  "app.tags": ["a", "b"]\n}\n', encoding="utf-8"
        )
        from_json = Engine(json_home)("app.tags")
        assert from_json == ["a", "b"]
        assert isinstance(from_json, list)

        env_home = tmp_path / "env"
        env_home.mkdir()
        (env_home / "settings.env").write_text("app.tags=['a', 'b']\n", encoding="utf-8")
        from_env = Engine(env_home, file_type="env")("app.tags")
        assert from_env == "['a', 'b']"
        assert isinstance(from_env, str)


# --------------------------------------------------------------------------- #
# 值文件名：``file_name``（缺省 settings，可显式指定）
# --------------------------------------------------------------------------- #


class TestFileName:
    def test_default_name_is_settings(self, tmp_path: Path) -> None:
        assert Engine(tmp_path).values_path.name == "settings.json"

    def test_a_custom_name_pairs_with_the_type(self, tmp_path: Path) -> None:
        engine = Engine(tmp_path, file_name="app", file_type="toml")
        assert engine.values_path.name == "app.toml"
        assert engine("a.b", 1) == 1
        assert (tmp_path / "app.toml").exists()

    def test_the_bookkeeping_follows_the_name(self, tmp_path: Path) -> None:
        """词表与锁都按同一个名字派生 —— 改了名字就是另一套文件。"""
        engine = Engine(tmp_path, file_name="app")
        engine("a.b", 1, doc="说明")
        assert engine.schema_path == tmp_path / "schema" / "app.json"
        assert engine.lock_path.name == "app.lock"

    @pytest.mark.parametrize("bad", ["a/b", "..", "", "C:x", "a\\b"])
    def test_a_name_that_could_escape_is_refused(self, tmp_path: Path, bad: str) -> None:
        with pytest.raises(ConfError, match="不合法"):
            Engine(tmp_path, file_name=bad)

    def test_two_names_in_one_directory_do_not_share_bookkeeping(self, tmp_path: Path) -> None:
        """同一个目录、不同文件名的两个引擎互不相干（端点也按名字分开）。"""
        first = Engine(tmp_path, file_name="one")
        second = Engine(tmp_path, file_name="two")
        first("a", 1)
        second("a", 2)
        assert first("a") == 1
        assert second("a") == 2
        assert first.schema_path != second.schema_path
        assert first.lock_path != second.lock_path


# --------------------------------------------------------------------------- #
# 多文件：键里内嵌路径（``no_one_file``）
# --------------------------------------------------------------------------- #


class TestMultiFile:
    @pytest.fixture
    def multi(self, tmp_path: Path) -> Engine:
        return Engine(tmp_path, no_one_file=True)

    def test_off_means_the_colon_is_just_a_key(self, tmp_path: Path) -> None:
        """多文件关闭时 ``:`` 不参与解析 —— 整个字符串就是一个普通键（D02 §1 验收）。"""
        engine = Engine(tmp_path)
        engine("app/conf/net:net.id.post", 1)
        data = json.loads(engine.values_path.read_text(encoding="utf-8"))
        assert data["app/conf/net:net.id.post"] == 1
        assert not (tmp_path / "app").exists()

    def test_on_routes_the_key_into_its_file(self, multi: Engine, tmp_path: Path) -> None:
        assert multi("app/conf/net:net.id.post", 8080) == 8080
        sub = tmp_path / "app" / "conf" / "net.json"
        assert json.loads(sub.read_text(encoding="utf-8"))["net.id.post"] == 8080

    def test_round_trip_through_a_new_engine(self, multi: Engine, tmp_path: Path) -> None:
        multi("app/conf/net:net.id.post", 8080)
        fresh = Engine(tmp_path, no_one_file=True)
        assert fresh("app/conf/net:net.id.post") == 8080

    def test_a_key_without_a_path_lands_in_the_default_file(self, multi: Engine) -> None:
        multi("plain.key", "x")
        assert json.loads(multi.values_path.read_text(encoding="utf-8"))["plain.key"] == "x"

    def test_one_vocabulary_for_every_file(self, multi: Engine) -> None:
        """词表只有一份，键是全键（含路径段）—— 多文件不搞多份词表（D02 未决 3 的裁定）。"""
        multi("app/conf/net:net.id.post", 1)
        multi("plain.key", 2)
        props = json.loads(multi.schema_path.read_text(encoding="utf-8"))["properties"]
        assert set(props) == {"app/conf/net:net.id.post", "plain.key"}

    def test_the_pointer_is_relative_to_each_file(self, multi: Engine, tmp_path: Path) -> None:
        multi("app/conf/net:net.id.post", 1)
        multi("plain.key", 2)

        node = json.loads((tmp_path / "app" / "conf" / "net.json").read_text(encoding="utf-8"))
        assert node["$schema"] == "../../schema/settings.json"
        assert (
            json.loads(multi.values_path.read_text(encoding="utf-8"))["$schema"]
            == SCHEMA_POINTER
        )

    def test_untouched_bytes_survive_in_a_sub_file(self, tmp_path: Path) -> None:
        sub = tmp_path / "app" / "net.yaml"
        sub.parent.mkdir(parents=True)
        sub.write_text("# 我手写的注释\nkept: 2   # 行尾\n", encoding="utf-8")

        Engine(tmp_path, file_type="yaml", no_one_file=True)("app/net:added", 1)

        text = sub.read_text(encoding="utf-8")
        assert "# 我手写的注释" in text
        assert "kept: 2   # 行尾" in text
        assert "added: 1" in text

    @pytest.mark.parametrize("bad", ["../x:k", "/abs/x:k", "a/../../x:k", "a\\b:k"])
    def test_traversal_is_refused(self, multi: Engine, tmp_path: Path, bad: str) -> None:
        with pytest.raises(ConfError, match="不合法"):
            multi(bad, 1)
        # 一个值文件都没写出来（``schema/`` 下只有锁的握手点）
        assert list(tmp_path.glob("**/*.json")) == []

    def test_sync_cleans_only_the_files_it_manages(self, tmp_path: Path) -> None:
        """未被声明引用的值文件不归这个引擎管，``sync`` 一个字节都不动它。"""
        engine = Engine(tmp_path, no_one_file=True)
        engine("app/net:kept", 1)

        sub = tmp_path / "app" / "net.json"
        data = json.loads(sub.read_text(encoding="utf-8"))
        data["ghost"] = 9
        sub.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        untouched = tmp_path / "untouched.json"
        untouched.write_text('{"someone.elses": 1}\n', encoding="utf-8")

        fresh = Engine(tmp_path, no_one_file=True)
        fresh("app/net:kept", 1)
        fresh.sync()

        assert "ghost" not in json.loads(sub.read_text(encoding="utf-8"))
        assert untouched.read_text(encoding="utf-8") == '{"someone.elses": 1}\n'

    def test_env_backend_works_in_multi_file(self, tmp_path: Path) -> None:
        """D02 §1 验收：``.env`` 后端在多文件开启时可用。"""
        engine = Engine(tmp_path, file_type="env", no_one_file=True)
        assert engine("app/net:NET_PORT", "8080") == "8080"
        assert (tmp_path / "app" / "net.env").read_text(encoding="utf-8") == "NET_PORT=8080\n"
        assert engine("app/net:NET_PORT") == "8080"


# --------------------------------------------------------------------------- #
# 使用口的三种模式：五种写法逐个对应
# --------------------------------------------------------------------------- #


class TestThreeModes:
    """ISSUE-001 的验收：五种写法与模式一一对应，一个都不能走岔。"""

    @pytest.fixture(autouse=True)
    def _home(self, tmp_path: Path) -> None:
        AutoConf(home=str(tmp_path))

    def test_mode3_read(self) -> None:
        conf("a.b", 1)
        assert conf("a.b") == 1

    def test_mode1_declare_and_write(self) -> None:
        assert conf("a.b", 1) == 1

    def test_mode1_with_positional_doc(self, tmp_path: Path) -> None:
        """第三个位置参数就是 ``doc`` —— 写法贴合矩阵，且说明进了词表。"""
        assert conf("a.b", 1, "服务端口") == 1
        schema = json.loads((tmp_path / "schema" / "settings.json").read_text(encoding="utf-8"))
        assert schema["properties"]["a.b"]["description"] == "服务端口"

    def test_mode1_with_keyword_doc(self) -> None:
        assert conf("a.b", 1, doc="服务端口") == 1

    def test_mode2_register_only(self) -> None:
        """``conf(key, doc=…)`` 的 value 位是空的 ⇒ 只登记，随即取值 ⇒ 没配就报错。"""
        with pytest.raises(KeyHasNoValueError):
            conf("a.required", doc="必填键")

    def test_mode2_returns_the_value_when_the_file_has_one(self) -> None:
        conf("a.b", 1)
        assert conf("a.b", doc="说明") == 1

    def test_mode1_returns_the_file_value_not_the_default(self) -> None:
        """值文件优先：声明 1 但文件里是 42 ⇒ 返回 42。"""
        conf("a.b", 1)
        engine = AutoConf()
        engine.values_path.write_text(
            json.dumps({"$schema": SCHEMA_POINTER, "a.b": 42}, indent=2) + "\n",
            encoding="utf-8",
        )
        assert conf("a.b", 1) == 42


# --------------------------------------------------------------------------- #
# ``home`` 的缺省：``./conf``
# --------------------------------------------------------------------------- #


class TestHomeDefault:
    def test_default_home_is_conf_under_the_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONCONF_HOME", raising=False)
        monkeypatch.chdir(tmp_path)
        assert default_home() == (tmp_path / "conf").resolve()

    def test_home_env_wins_over_the_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONCONF_HOME", str(tmp_path / "elsewhere"))
        assert default_home() == (tmp_path / "elsewhere").resolve()

    def test_engine_without_home_lands_in_dot_conf(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONCONF_HOME", raising=False)
        monkeypatch.chdir(tmp_path)
        Engine()("a.b", 1)
        assert (tmp_path / "conf" / "settings.json").exists()


# --------------------------------------------------------------------------- #
# 模块级单例：两个面
# --------------------------------------------------------------------------- #


class TestModuleLevelFaces:
    def test_onconf_then_conf(self, tmp_path: Path) -> None:
        AutoConf(home=str(tmp_path))
        assert conf("a.b", 1) == 1
        assert conf("a.b") == 1

    def test_zero_bootstrap_uses_the_home_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONCONF_HOME", str(tmp_path))
        assert conf("a.b", 1) == 1
        assert (tmp_path / "settings.json").exists()

    def test_repeated_onconf_without_params_is_fine(self, tmp_path: Path) -> None:
        first = AutoConf(home=str(tmp_path))
        assert AutoConf() is first

    def test_reconfiguring_a_live_engine_is_refused_loudly(self, tmp_path: Path) -> None:
        AutoConf(home=str(tmp_path))
        with pytest.raises(ConfError, match="已经启动"):
            AutoConf(home=str(tmp_path / "other"))

    def test_unknown_engine_param_is_not_swallowed(self, tmp_path: Path) -> None:
        """开放 kwargs 的默认行为是静默吞掉拼写错误 —— 必须堵死（§15.4）。"""
        with pytest.raises(TypeError, match="未知的引擎参数"):
            # 就是要传一个拼错的参数，看它会不会被静默吞掉
            AutoConf(hme=str(tmp_path))  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# .env 值文件
# --------------------------------------------------------------------------- #


class TestEnvValuesFile:
    def test_env_file_is_used_when_declared(self, tmp_path: Path) -> None:
        (tmp_path / "settings.env").write_text(
            "# 手写注释\nexport A_B=1\nC_D=two\n", encoding="utf-8"
        )
        engine = Engine(tmp_path, file_type="env")
        assert engine.values_path.name == "settings.env"
        assert engine("C_D") == "two"

    def test_string_backend_refuses_non_string_values(self, tmp_path: Path) -> None:
        (tmp_path / "settings.env").write_text("A_B=1\n", encoding="utf-8")
        engine = Engine(tmp_path, file_type="env")
        with pytest.raises(TypeError, match="只能存字符串"):
            engine("PORT", 8080)

    def test_string_values_round_trip(self, tmp_path: Path) -> None:
        (tmp_path / "settings.env").write_text("A_B=1\n", encoding="utf-8")
        engine = Engine(tmp_path, file_type="env")
        assert engine("PORT", "8080") == "8080"
        assert isinstance(engine("PORT"), str)

    def test_no_schema_pointer_is_forced_into_an_env_file(self, tmp_path: Path) -> None:
        """``.env`` 放不下成员，硬塞只会让文件变成语法错误。"""
        values = tmp_path / "settings.env"
        values.write_text("A_B=1\n", encoding="utf-8")
        Engine(tmp_path, file_type="env")("C_D", "two")

        text = values.read_text(encoding="utf-8")
        assert "$schema" not in text
        assert "A_B=1" in text
        assert "C_D=two" in text

    def test_comments_survive_a_new_key(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.env"
        values.write_text("# 头注释\nexport A_B=1\nC_D=two\n", encoding="utf-8")
        Engine(tmp_path, file_type="env")("E_F", "9")

        text = values.read_text(encoding="utf-8")
        assert "# 头注释" in text
        assert "export A_B=1" in text
        assert "C_D=two" in text
        assert "E_F=9" in text


# --------------------------------------------------------------------------- #
# TOML 值文件
# --------------------------------------------------------------------------- #


class TestTomlValuesFile:
    def test_toml_file_is_used_when_declared(self, tmp_path: Path) -> None:
        (tmp_path / "settings.toml").write_text(
            "# 手写注释\n\n[gc]\nauto.byte = 0   # 行尾注释\n", encoding="utf-8"
        )
        engine = Engine(tmp_path, file_type="toml")
        assert engine.values_path.name == "settings.toml"
        assert engine("gc.auto.byte") == 0

    def test_table_header_is_normalised_to_a_dotted_key(self, tmp_path: Path) -> None:
        """对上层完全透明：它只看得见点分键（§28.4）。"""
        (tmp_path / "settings.toml").write_text("[pack.max]\nbyte = 512\n", encoding="utf-8")
        assert Engine(tmp_path, file_type="toml")("pack.max.byte") == 512

    def test_new_key_lands_in_the_matching_section(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.toml"
        values.write_text("[gc]\nauto.byte = 0\n", encoding="utf-8")
        Engine(tmp_path, file_type="toml")("gc.threshold", 1024)

        text = values.read_text(encoding="utf-8")
        assert text.index("[gc]") < text.index("threshold = 1024")
        assert "threshold = 1024" in text

    def test_comments_survive_a_new_key(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.toml"
        values.write_text("# 头注释\n\ngc.auto.byte = 0   # 行尾注释\n", encoding="utf-8")
        Engine(tmp_path, file_type="toml")("gc.manual", 4096)

        text = values.read_text(encoding="utf-8")
        assert "# 头注释" in text
        assert "gc.auto.byte = 0   # 行尾注释" in text
        assert "manual = 4096" in text

    def test_none_cannot_be_written(self, tmp_path: Path) -> None:
        """TOML 没有 null。"""
        (tmp_path / "settings.toml").write_text("a = 1\n", encoding="utf-8")
        engine = Engine(tmp_path, file_type="toml")
        with pytest.raises(TypeError, match="没有 null"):
            engine("b", None)

    def test_no_schema_pointer_is_forced_into_a_toml_file(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.toml"
        values.write_text("a = 1\n", encoding="utf-8")
        Engine(tmp_path, file_type="toml")("b", 2)

        text = values.read_text(encoding="utf-8")
        assert "$schema" not in text
        assert "a = 1" in text
        assert "b = 2" in text


# --------------------------------------------------------------------------- #
# 攒批窗口（**按需开**；默认是当场落盘）
# --------------------------------------------------------------------------- #


class TestFlushWindow:
    def test_immediate_by_default(self, tmp_path: Path) -> None:
        Engine(tmp_path)("a.b", 1)
        assert (tmp_path / "settings.json").exists()

    def test_window_batches_instead_of_writing_each_time(self, tmp_path: Path) -> None:
        engine = Engine(tmp_path, flush_window=60.0)
        engine("a.one", 1)
        engine("a.two", 2)
        engine("a.three", 3)
        assert not engine.values_path.exists()  # 窗口没到，一次都没写

        engine.flush()
        data = json.loads(engine.values_path.read_text(encoding="utf-8"))
        assert [data["a.one"], data["a.two"], data["a.three"]] == [1, 2, 3]

    def test_a_read_flushes_first(self, tmp_path: Path) -> None:
        """R3/R5：读之前必须先把自己的待写落盘，否则读不到自己刚声明的事实。"""
        engine = Engine(tmp_path, flush_window=60.0)
        assert engine("a.b", 1) == 1
        assert not engine.values_path.exists()

        assert engine("a.b") == 1  # 这一次读强制提交
        assert engine.values_path.exists()

    def test_window_expiry_commits_on_the_next_call(self, tmp_path: Path) -> None:
        engine = Engine(tmp_path, flush_window=0.05)
        engine("a.b", 1)
        assert not engine.values_path.exists()

        time.sleep(0.08)
        engine("c.d", 2)  # 机会式检查：窗口到期 ⇒ 先把攒着的落了

        data = json.loads(engine.values_path.read_text(encoding="utf-8"))
        assert data["a.b"] == 1
        assert data["c.d"] == 2

    def test_sync_commits_the_whole_batch(self, tmp_path: Path) -> None:
        engine = Engine(tmp_path, flush_window=60.0)
        engine("a.b", 1)
        engine("c.d", 2)
        engine.sync()
        assert json.loads(engine.values_path.read_text(encoding="utf-8"))["c.d"] == 2

    def test_window_defers_but_never_loses(self, tmp_path: Path) -> None:
        """窗口只改「什么时候写」，不改「写什么」。"""
        deferred = Engine(tmp_path, flush_window=60.0)
        deferred("a.b", 1)
        deferred("c.d", 2)
        deferred.sync()

        immediate = Engine(tmp_path)
        immediate("a.b", 1)
        immediate("c.d", 2)

        assert json.loads(deferred.values_path.read_text(encoding="utf-8")) == json.loads(
            immediate.values_path.read_text(encoding="utf-8")
        )


# --------------------------------------------------------------------------- #
# 提交期的并发：锁 + 锁内重读
# --------------------------------------------------------------------------- #


class TestCommitReReadsUnderTheLock:
    def test_another_process_s_update_is_not_clobbered(self, tmp_path: Path) -> None:
        """锁内重读：别人在这期间写的键，不许被我们整篇盖掉。"""
        engine = Engine(tmp_path, flush_window=60.0)
        engine("mine", 1)  # 进缓冲，还没落盘

        # 模拟另一个进程：它已经往值文件里写了一个键
        (tmp_path / "settings.json").write_text(
            json.dumps({"$schema": SCHEMA_POINTER, "theirs": 2}, indent=2) + "\n",
            encoding="utf-8",
        )

        engine.flush()  # 锁内重读 ⇒ 看得见 theirs

        data = json.loads(engine.values_path.read_text(encoding="utf-8"))
        assert data["theirs"] == 2
        assert data["mine"] == 1

    def test_vocabulary_entries_from_another_process_are_kept(self, tmp_path: Path) -> None:
        """只动词表的提交也要能看见 —— 所以指纹得同时看值文件和词表。"""
        engine = Engine(tmp_path, flush_window=60.0)
        engine("mine", 1)

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir(exist_ok=True)
        (schema_dir / "settings.json").write_text(
            json.dumps(
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {"theirs": {"default": 2}},
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        engine("mine", 1)  # 再声明一次，触发一次提交
        engine.flush()

        props = json.loads(engine.schema_path.read_text(encoding="utf-8"))["properties"]
        assert "theirs" in props
        assert "mine" in props


class TestRealProcesses:
    """真开进程：多个进程各写各的键，一个都不许丢。"""

    _WORKER = (
        "import sys\n"
        "from onconf import Engine\n"
        "eng = Engine(sys.argv[1], flush_window=0.0)\n"
        "for key in sys.argv[2:]:\n"
        "    eng(key, key)\n"
        "eng.flush()\n"
    )

    def test_four_processes_do_not_lose_each_others_keys(self, tmp_path: Path) -> None:
        keys = [f"key.of.proc{n}" for n in range(4)]
        procs = [
            subprocess.Popen(  # noqa: S603 - 参数全是本测试自己造的，没有外部输入
                [sys.executable, "-c", self._WORKER, str(tmp_path), *keys[n::4]],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for n in range(4)
        ]
        for proc in procs:
            _, stderr = proc.communicate(timeout=120)
            assert proc.returncode == 0, stderr.decode("utf-8", "replace")

        data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        for key in keys:
            assert key in data, f"{key} 被别的进程盖掉了"

    _SYNCER = (
        "import sys\n"
        "from onconf import Engine\n"
        "eng = Engine(sys.argv[1], flush_window=0.0)\n"
        "eng(sys.argv[2], sys.argv[2])\n"
        "eng.sync()\n"  # 完整提交点 ⇒ 规则 1 允许执行
        "eng.close()\n"
    )

    _KEEPER = (
        "import sys\n"
        "from onconf import Engine\n"
        "eng = Engine(sys.argv[1], flush_window=0.0)\n"
        "eng('keeper.alive', 1)\n"
        "print('ready', flush=True)\n"
        "sys.stdin.readline()\n"
        "eng.close()\n"
    )

    def test_rule_one_uses_every_process_declaration_set(self, tmp_path: Path) -> None:
        """**写者活着的时候**，规则 1 的基准才是所有进程的声明并集。

        规则 1（清理未知数据）必须拿**完整**声明集当基准。硬锁那条路做不到 —— 每个
        进程只知道自己那份，于是后 ``sync()`` 的进程会把先写的键当「未知数据」删掉
        （§18.4 记着的那个洞）。写者是唯一收口点，它的声明集是并集，所以一个键都不
        该少。

        **但这条有个前提：写者得活着。** 声明集**不是**持久状态 —— 写者一换人，
        并集就跟着没了，接着上来的新写者会拿自己那一份去清理。进程起一个就退一个
        的用法（下面 :meth:`test_four_processes_do_not_lose_each_others_keys` 那种）
        正好踩在这个前提之外。所以这里先起一个守着的写者，再串行跑三个客户端。
        """
        keys = [f"key.of.sync{n}" for n in range(3)]
        keeper = subprocess.Popen(  # noqa: S603 - 参数全是本测试自己造的，没有外部输入
            [sys.executable, "-c", self._KEEPER, str(tmp_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert keeper.stdout is not None
            assert keeper.stdout.readline().strip() == "ready", "守着的写者没起来"
            for key in keys:
                proc = subprocess.run(  # noqa: S603 - 同上
                    [sys.executable, "-c", self._SYNCER, str(tmp_path), key],
                    capture_output=True,
                    check=False,  # 返回值自己判，好把 stderr 一起报出来
                    timeout=120,
                )
                assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        finally:
            if keeper.stdin is not None:
                keeper.stdin.close()
            keeper.wait(timeout=120)
            # 显式关掉，别留给 GC：本仓库 filterwarnings=error，
            # 一个 ResourceWarning 就是一条失败的测试。
            for stream in (keeper.stdout, keeper.stderr):
                if stream is not None:
                    stream.close()

        data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        for key in keys:
            assert key in data, f"{key} 被后来者的规则 1 当成未知数据清掉了"


# --------------------------------------------------------------------------- #
# 锁本身
# --------------------------------------------------------------------------- #


class TestLockPrimitive:
    def test_second_acquire_in_the_same_process_times_out(self, tmp_path: Path) -> None:
        """互斥是真的 —— 同一进程里换个句柄也拿不到。"""
        target = tmp_path / "x.lock"
        with exclusive(target, timeout=1.0):  # noqa: SIM117 - 外层得先进去，内层才拿不到
            with pytest.raises(LockTimeoutError), exclusive(target, timeout=0.05):
                pass

    def test_lock_is_released_after_the_context(self, tmp_path: Path) -> None:
        target = tmp_path / "x.lock"
        with exclusive(target, timeout=1.0):
            pass
        with exclusive(target, timeout=1.0):  # 不该超时
            pass

    def test_lock_file_is_just_a_handshake_point(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "x.lock"
        with exclusive(target, timeout=1.0):
            pass
        assert target.exists()
