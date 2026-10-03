"""引擎装配的端到端测试：声明 → 对账 → 落盘 → 读回。

这里测的是**用户真正看得见的行为**，不是内部函数。
每个测试都在 tmp_path 里造一个全新的配置世界。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_conf import (
    AutoConf,
    ConfError,
    KeyHasNoValue,
    KeyNotRegistered,
    TypeConflict,
    conf,
)
from auto_conf._engine import SCHEMA_POINTER, Engine


@pytest.fixture(autouse=True)
def _isolate() -> None:
    from auto_conf import _reset

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
        with pytest.raises(KeyNotRegistered):
            engine("nope")

    def test_metadata_only_call_registers_then_reads(self, engine: Engine) -> None:
        """``conf(key, doc=…)`` = 登记 + 立刻取值 ⇒ 没配就报错。

        这正是「启动即校验必填项」：键进了词表，但事实里没有值。
        """
        with pytest.raises(KeyHasNoValue):
            engine("probe.doc", doc="这是个必填键")

        # 登记是**发生了**的：再读一次，错的是「没有值」而不是「没登记」
        with pytest.raises(KeyHasNoValue):
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

    def test_force_overwrites_that_one_key(self, engine: Engine) -> None:
        engine("a.b", 1)
        engine.values_path.write_text(
            json.dumps({"$schema": SCHEMA_POINTER, "a.b": 42}, indent=2) + "\n",
            encoding="utf-8",
        )
        fresh = Engine(engine.home)
        assert fresh("a.b", 1, force=True) == 1


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

    def test_user_comments_in_yaml_survive_a_rewrite(self, tmp_path: Path) -> None:
        """YAML 值文件：改一个键，用户手写的注释逐字保留（§27.3）。"""
        values = tmp_path / "settings.yaml"
        values.write_text(
            "# 我手写的注释\n"
            "a.b: 1   # 行尾注释\n"
            "c.d: 2\n",
            encoding="utf-8",
        )
        engine = Engine(tmp_path)
        engine("a.b", 99, force=True)

        text = values.read_text(encoding="utf-8")
        assert "# 我手写的注释" in text
        assert "a.b: 99   # 行尾注释" in text
        assert "c.d: 2" in text

    def test_appending_a_key_keeps_existing_comments(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.yaml"
        values.write_text("# 头注释\na.b: 1   # 行尾\n", encoding="utf-8")
        Engine(tmp_path)("c.d", 2)

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

    def test_existing_user_keys_survive_incremental_declares(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.yaml"
        values.write_text("# 我手写的\na.b: 1   # 行尾注释\nc.d: 2\n", encoding="utf-8")
        Engine(tmp_path)("a.b", 99, force=True)

        text = values.read_text(encoding="utf-8")
        assert "# 我手写的" in text
        assert "a.b: 99   # 行尾注释" in text
        assert "c.d: 2" in text

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
# type= 只做声明期校验
# --------------------------------------------------------------------------- #


class TestDeclaredType:
    def test_mismatched_default_is_rejected_at_declare_time(self, engine: Engine) -> None:
        with pytest.raises(TypeConflict, match="不符合声明的类型"):
            engine("a.b", "512", type=int)

    def test_bool_is_not_accepted_as_int(self, engine: Engine) -> None:
        with pytest.raises(TypeConflict):
            engine("a.b", True, type=int)

    def test_type_is_not_used_to_convert_on_read(self, engine: Engine) -> None:
        """透明原则：值原样进出，引擎不做读取期转换。"""
        engine("a.b", 512, type=int)
        assert engine("a.b") == 512
        assert isinstance(engine("a.b"), int)

    def test_type_lands_in_the_vocabulary(self, engine: Engine) -> None:
        engine("a.b", 512, type=int)
        schema = json.loads(engine.schema_path.read_text(encoding="utf-8"))
        assert schema["properties"]["a.b"]["type"] == "integer"


# --------------------------------------------------------------------------- #
# 模块级单例：两个面
# --------------------------------------------------------------------------- #


class TestModuleLevelFaces:
    def test_auto_conf_then_conf(self, tmp_path: Path) -> None:
        AutoConf(home=str(tmp_path))
        assert conf("a.b", 1) == 1
        assert conf("a.b") == 1

    def test_zero_bootstrap_uses_the_home_env(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AUTO_CONF_HOME", str(tmp_path))
        assert conf("a.b", 1) == 1
        assert (tmp_path / "settings.json").exists()

    def test_repeated_auto_conf_without_params_is_fine(self, tmp_path: Path) -> None:
        first = AutoConf(home=str(tmp_path))
        assert AutoConf() is first

    def test_reconfiguring_a_live_engine_is_refused_loudly(self, tmp_path: Path) -> None:
        AutoConf(home=str(tmp_path))
        with pytest.raises(ConfError, match="已经启动"):
            AutoConf(home=str(tmp_path / "other"))

    def test_unknown_engine_param_is_not_swallowed(self, tmp_path: Path) -> None:
        """开放 kwargs 的默认行为是静默吞掉拼写错误 —— 必须堵死（§15.4）。"""
        with pytest.raises(TypeError, match="未知的引擎参数"):
            AutoConf(hme=str(tmp_path))
