# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引擎装配的端到端测试：声明 → 对账 → 落盘 → 读回。

这里测的是**用户真正看得见的行为**，不是内部函数。
每个测试都在 tmp_path 里造一个全新的配置世界。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from onconf import (
    AutoConf,
    ConfError,
    KeyHasNoValueError,
    KeyNotRegisteredError,
    TypeConflictError,
    _reset,
    conf,
)
from onconf._engine import SCHEMA_POINTER, Engine
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
            "# 我手写的注释\na.b: 1   # 行尾注释\nc.d: 2\n",
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

        Engine(tmp_path)("hub.default", "main")

        text = values.read_text(encoding="utf-8")
        assert "$schema" in text
        assert SCHEMA_POINTER in text
        assert "# 注释" in text
        assert "pack.max.byte: 1" in text

    def test_pointer_is_idempotent(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.yaml"
        values.write_text("# 注释\npack.max.byte: 1\n", encoding="utf-8")

        Engine(tmp_path)("hub.default", "main")
        once = values.read_text(encoding="utf-8")
        Engine(tmp_path)("index.max.byte", 2)
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
# ``type=`` 的职责：只做声明期校验
# --------------------------------------------------------------------------- #


class TestDeclaredType:
    def test_mismatched_default_is_rejected_at_declare_time(self, engine: Engine) -> None:
        with pytest.raises(TypeConflictError, match="不符合声明的类型"):
            engine("a.b", "512", type=int)

    def test_bool_is_not_accepted_as_int(self, engine: Engine) -> None:
        with pytest.raises(TypeConflictError):
            engine("a.b", True, type=int)  # noqa: FBT003 - 被测的就是「布尔当真值传」

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
    def test_env_file_is_picked_up(self, tmp_path: Path) -> None:
        (tmp_path / "settings.env").write_text(
            "# 手写注释\nexport A_B=1\nC_D=two\n", encoding="utf-8"
        )
        engine = Engine(tmp_path)
        assert engine.values_path.name == "settings.env"
        assert engine("C_D") == "two"

    def test_string_backend_refuses_non_string_values(self, tmp_path: Path) -> None:
        (tmp_path / "settings.env").write_text("A_B=1\n", encoding="utf-8")
        engine = Engine(tmp_path)
        with pytest.raises(TypeError, match="只能存字符串"):
            engine("PORT", 8080)

    def test_string_values_round_trip(self, tmp_path: Path) -> None:
        (tmp_path / "settings.env").write_text("A_B=1\n", encoding="utf-8")
        engine = Engine(tmp_path)
        assert engine("PORT", "8080") == "8080"
        assert isinstance(engine("PORT"), str)

    def test_no_schema_pointer_is_forced_into_an_env_file(self, tmp_path: Path) -> None:
        """``.env`` 放不下成员，硬塞只会让文件变成语法错误。"""
        values = tmp_path / "settings.env"
        values.write_text("A_B=1\n", encoding="utf-8")
        Engine(tmp_path)("C_D", "two")

        text = values.read_text(encoding="utf-8")
        assert "$schema" not in text
        assert "A_B=1" in text
        assert "C_D=two" in text

    def test_comments_survive_a_rewrite(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.env"
        values.write_text("# 头注释\nexport A_B=1\nC_D=two\n", encoding="utf-8")
        Engine(tmp_path)("A_B", "9", force=True)

        text = values.read_text(encoding="utf-8")
        assert "# 头注释" in text
        assert "export A_B=9" in text
        assert "C_D=two" in text


# --------------------------------------------------------------------------- #
# TOML 值文件
# --------------------------------------------------------------------------- #


class TestTomlValuesFile:
    def test_toml_file_is_picked_up(self, tmp_path: Path) -> None:
        (tmp_path / "settings.toml").write_text(
            "# 手写注释\n\n[gc]\nauto.byte = 0   # 行尾注释\n", encoding="utf-8"
        )
        engine = Engine(tmp_path)
        assert engine.values_path.name == "settings.toml"
        assert engine("gc.auto.byte") == 0

    def test_table_header_is_normalised_to_a_dotted_key(self, tmp_path: Path) -> None:
        """对上层完全透明：它只看得见点分键（§28.4）。"""
        (tmp_path / "settings.toml").write_text("[pack.max]\nbyte = 512\n", encoding="utf-8")
        assert Engine(tmp_path)("pack.max.byte") == 512

    def test_new_key_lands_in_the_matching_section(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.toml"
        values.write_text("[gc]\nauto.byte = 0\n", encoding="utf-8")
        Engine(tmp_path)("gc.threshold", 1024)

        text = values.read_text(encoding="utf-8")
        assert text.index("[gc]") < text.index("threshold = 1024")
        assert "threshold = 1024" in text

    def test_comments_survive_a_rewrite(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.toml"
        values.write_text("# 头注释\n\ngc.auto.byte = 0   # 行尾注释\n", encoding="utf-8")
        Engine(tmp_path)("gc.auto.byte", 4096, force=True)

        text = values.read_text(encoding="utf-8")
        assert "# 头注释" in text
        assert "gc.auto.byte = 4096   # 行尾注释" in text

    def test_none_cannot_be_written(self, tmp_path: Path) -> None:
        """TOML 没有 null。"""
        (tmp_path / "settings.toml").write_text("a = 1\n", encoding="utf-8")
        engine = Engine(tmp_path)
        with pytest.raises(TypeError, match="没有 null"):
            engine("b", None)

    def test_no_schema_pointer_is_forced_into_a_toml_file(self, tmp_path: Path) -> None:
        values = tmp_path / "settings.toml"
        values.write_text("a = 1\n", encoding="utf-8")
        Engine(tmp_path)("b", 2)

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
