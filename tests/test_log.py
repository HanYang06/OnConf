# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""日志：一份记录流、两个出口、三个口子。

这一层是**体验层**，所以测的是用户真正看得见的东西：终端上那几行长什么样、审计
文件里能不能无损地查回来、失败有没有留痕、以及「哪个出口能关、哪个口子说了算」。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from typing import TYPE_CHECKING

import pytest

from onconf import Engine, _log, _reset
from onconf._core import MISSING, NO_VALUE
from onconf._log import Log, Record, cell_len, error_kind, strip_ansi
from onconf.errors import (
    ConfError,
    KeyHasNoValueError,
    KeyNotRegisteredError,
)


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


#: ``from onconf import _engine`` 拿到的是**单例变量**（``__init__._engine``），不是模块 ——
#: 模块与那个变量同名，包属性被变量遮住了。所以这里显式走 importlib。
_engine = import_module("onconf._engine")


#: 审计文件里的完整时间戳：审计要跨天查
_FULL_DATE = re.compile(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\]")
#: 这个测试文件自己的调用点
_HERE = re.compile(r"at=.*test_log\.py:\d+")


@pytest.fixture(autouse=True)
def _isolate() -> Iterator[None]:
    _reset()
    yield
    _reset()


def _lines(text: str) -> list[str]:
    """只留记录行（``[Read]`` / ``[Write]`` / ``[Change]`` / ``[Error]`` 开头）。"""
    return [line for line in text.splitlines() if line.startswith("[")]


def _first(text: str, level: str) -> str:
    return next(line for line in _lines(text) if line.startswith(f"[{level}]"))


def _file(home: Path) -> str:
    """审计文件那一份（缺省落点）。"""
    return (home / "audit.log").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 四个级别：写全量、读去重
# --------------------------------------------------------------------------- #


class TestWriteRecords:
    def test_a_declaration_logs_a_write_and_a_change(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``fill`` 写一条 ``[Write]``，值真的变了再写一条 ``[Change] old → new``。"""
        engine = Engine(tmp_path)
        engine("app.server.port", 512)

        err = capsys.readouterr().err
        write = _first(err, "Write")
        assert "item=app.server.port" in write
        assert "file=settings.json" in write
        assert "op=fill" in write
        assert "data=512" in write

        change = _first(err, "Change")
        assert "old=-" in change, "新建的键要从「没有」变成有"
        assert "new=512" in change
        assert _HERE.search(change), "变更行必须带调用点"

    def test_a_satisfied_declaration_is_logged_as_noop(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """声明跑了但文件已经是对的 ⇒ ``op=noop``。"""
        engine = Engine(tmp_path)
        engine("k", 1)
        capsys.readouterr()

        engine("k", 1)

        assert "op=noop" in capsys.readouterr().err

    def test_a_respected_file_is_logged_as_skip(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """值不一致但尊重文件 ⇒ ``op=skip`` 且 old / new 都在。"""
        engine = Engine(tmp_path)
        engine("k", 1)
        capsys.readouterr()

        engine("k", 2)

        err = capsys.readouterr().err
        skip = _first(err, "Write")
        assert "op=skip" in skip
        assert "old=1" in skip
        assert "new=2" in skip
        assert "reason=尊重文件" in skip

    def test_a_differing_value_is_never_logged_as_a_change(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """运行期没有覆盖出口：值不一致只记 ``op=skip``，**没有** ``[Change]``。"""
        engine = Engine(tmp_path)
        engine("k", 1)
        capsys.readouterr()

        engine("k", 2)

        err = capsys.readouterr().err
        assert "op=skip" in err
        assert "[Change]" not in err

    def test_sync_never_removes_undeclared_keys(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """运行期**没有删除动作**：``sync()`` 只是把待提交的交出去。

        删除只在命令行的收敛路径上（那条路径的声明集是完整的）。运行期拿不到完整
        声明集，删谁都是猜 —— 所以这里连一条 ``op=clean`` 记录都不该出现。
        """
        engine = Engine(tmp_path)
        engine("k", 1)
        data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        data["ghost"] = 7
        (tmp_path / "settings.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        capsys.readouterr()

        engine.sync()

        assert "op=clean" not in capsys.readouterr().err
        assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["ghost"] == 7


class TestReadRecords:
    def test_a_read_carries_origin_and_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        engine = Engine(tmp_path)
        engine("k", 512)
        capsys.readouterr()

        engine("k")
        engine.flush()

        read = _first(capsys.readouterr().err, "Read")
        assert "item=k" in read
        assert "origin=file" in read
        assert "data=512" in read
        assert "n=1" in read

    def test_a_value_that_only_lives_in_the_vocabulary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """事实里没有、词表里有默认值 ⇒ ``origin=vocab``。"""
        home = tmp_path / "conf"
        seed = Engine(home)
        seed("k", 512)
        seed.close()
        (home / "settings.json").write_text(
            json.dumps({"$schema": "schema/settings.json"}, indent=2) + "\n", encoding="utf-8"
        )

        fresh = Engine(home)
        fresh("k")
        fresh.flush()

        assert "origin=vocab" in capsys.readouterr().err

    def test_repeated_reads_are_aggregated(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """**同事务同键去重**：循环里读一万次只留一行 ``n=10000``。"""
        engine = Engine(tmp_path)
        engine("k", 1)
        capsys.readouterr()

        for _ in range(10_000):
            engine("k")
        engine.flush()

        reads = [line for line in _lines(capsys.readouterr().err) if line.startswith("[Read]")]
        assert len(reads) == 1, "读没有去重聚合"
        assert "n=10000" in reads[0]


# --------------------------------------------------------------------------- #
# 失败必须留痕
# --------------------------------------------------------------------------- #


class TestErrorRecords:
    def test_an_unregistered_key_is_logged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        engine = Engine(tmp_path)
        with pytest.raises(KeyNotRegisteredError):
            engine("nope")

        err = capsys.readouterr().err
        assert "err=key-not-registered" in err

    def test_a_registered_key_without_a_value_is_logged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        engine = Engine(tmp_path)
        with pytest.raises(KeyHasNoValueError):
            engine("required", doc="必填")

        assert "err=key-has-no-value" in capsys.readouterr().err

    def test_a_backend_rejection_is_logged_before_it_raises(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """后端拒收一个值（TOML 没有 null）也要先留痕，再原样抛。"""
        (tmp_path / "settings.toml").write_text("a = 1\n", encoding="utf-8")
        engine = Engine(tmp_path, file_type="toml")
        with pytest.raises(TypeError):
            engine("port", None)

        err = capsys.readouterr().err
        assert "err=type-error" in err


# --------------------------------------------------------------------------- #
# 两种渲染：终端对齐 / 文件无损
# --------------------------------------------------------------------------- #


class TestRendering:
    def test_display_width_counts_cjk_as_two(self) -> None:
        """``len("配置")`` 是 2，显示宽度是 4。"""
        assert cell_len("配置") == 4
        assert cell_len("ab") == 2
        assert cell_len("e\u0301") == 1, "组合字符不占列"
        assert strip_ansi("\x1b[31m红\x1b[0m") == "红"
        assert cell_len("\x1b[31m红\x1b[0m") == 2, "ANSI 颜色码是零宽的"

    def test_truncation_respects_display_width(self) -> None:
        clipped = _log._truncate("配" * 40, 10)
        assert clipped.endswith("…")
        assert cell_len(clipped) <= 10

    def test_columns_are_aligned_within_a_batch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """弹性制表位：同一批里 ``file=`` 落在同一个显示列上。"""
        engine = Engine(tmp_path, flush_window=60.0)
        engine("a.very.long.key.name", 1)
        engine("b", 2)
        engine.flush()

        writes = [line for line in _lines(capsys.readouterr().err) if line.startswith("[Write]")]
        assert len(writes) == 4, "两个键各两条：fill / update_meta"
        columns = {cell_len(line[: line.index("file=")]) for line in writes}
        assert len(columns) == 1, f"列没有对齐：{writes}"

    def test_long_values_are_clipped_on_the_terminal_but_never_in_the_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """截断只发生在终端渲染层，文件那一份必须无损。"""
        home = tmp_path / "conf"
        long_value = "x" * 300
        engine = Engine(home)
        engine("k", long_value)
        engine.close()

        assert "…" in capsys.readouterr().err
        assert long_value in _file(home)

    def test_values_are_rendered_compactly(self) -> None:
        assert _log._fmt(MISSING) == "-"
        assert _log._fmt(NO_VALUE) == "-"
        assert _log._fmt(None) == "null"
        assert _log._fmt(True) == "true"  # noqa: FBT003 - 这里布尔字面量就是要测的值
        assert _log._fmt(False) == "false"  # noqa: FBT003 - 同上
        assert _log._fmt("plain") == "plain"
        assert _log._fmt("two words") == '"two words"'
        assert _log._fmt(512) == "512"

    def test_error_kinds_are_kebab_case(self) -> None:
        assert error_kind(KeyNotRegisteredError("x")) == "key-not-registered"
        assert error_kind(ConfError("x")) == "conf"
        assert error_kind(TypeError("x")) == "type-error", "内建异常去掉 Error 后太含糊"
        assert error_kind(json.JSONDecodeError("x", "", 0)) == "json-decode", "连续大写算一个词"

    def test_a_backend_rejection_is_logged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """写不进去的值（TOML 没有 null）也要留痕 —— 它抛的是 TypeError，不是 ConfError。"""
        (tmp_path / "settings.toml").write_text("", encoding="utf-8")
        engine = Engine(tmp_path, file_type="toml")
        with pytest.raises(TypeError):
            engine("k", None)

        err = capsys.readouterr().err
        assert "err=type-error" in err
        assert "item=-" in err, "整批被后端拒了，归属不到某个键"

    def test_a_broken_values_file_is_logged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """文件坏了（TOML 表数组是 v1 明确拒绝的构造）也要留痕，异常照原样抛。"""
        (tmp_path / "settings.toml").write_text("[[servers]]\nport = 1\n", encoding="utf-8")
        engine = Engine(tmp_path, file_type="toml")
        with pytest.raises(ValueError, match="表数组"):
            engine("app.port")

        assert "err=toml-flat-required" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# 文件出口：恒写、只追加、落点可改、不造目录
# --------------------------------------------------------------------------- #


class TestFileSink:
    def test_the_file_sink_is_always_written(self, tmp_path: Path) -> None:
        """文件出口**没有开关**：引擎跑起来就写，缺省落在配置目录里。"""
        home = tmp_path / "conf"
        engine = Engine(home)
        engine("k", 1)
        engine.close()

        assert "item=k" in _file(home)
        assert _FULL_DATE.search(_file(home)), "文件形态带完整日期"

    def test_a_read_only_run_still_lands_in_the_file(self, tmp_path: Path) -> None:
        """恒写对只读也成立：一次纯读会往同一份文件里追加一行 ``[Read]``。"""
        home = tmp_path / "conf"
        seed = Engine(home)
        seed("k", 1)
        seed.close()
        before = (home / "audit.log").stat().st_size

        fresh = Engine(home)
        assert fresh("k") == 1
        fresh.flush()

        assert "[Read]" in _file(home)
        assert (home / "audit.log").stat().st_size > before, "只读也留痕"

    def test_the_audit_file_is_append_only(self, tmp_path: Path) -> None:
        home = tmp_path / "conf"
        first = Engine(home)
        first("a", 1)
        first.close()
        second = Engine(home)
        second("b", 2)
        second.close()

        lines = _lines(_file(home))
        assert any("item=a" in line for line in lines)
        assert any("item=b" in line for line in lines), "第二次运行必须追加，不是重写"

    def test_a_relative_log_path_is_resolved_against_home(self, tmp_path: Path) -> None:
        home = tmp_path / "conf"
        (home / "logs").mkdir(parents=True)
        engine = Engine(home, log_path="logs/run.log")
        engine("k", 1)
        engine.close()

        assert "item=k" in (home / "logs" / "run.log").read_text(encoding="utf-8")
        assert not (home / "audit.log").exists(), "改了落点就不该再写缺省那一份"

    def test_an_absolute_log_path_is_used_as_given(self, tmp_path: Path) -> None:
        """落点可以在配置目录之外 —— 它是调用方直接给的参数，不参与键名那套校验。"""
        target = tmp_path / "elsewhere" / "run.log"
        target.parent.mkdir()
        engine = Engine(tmp_path / "conf", log_path=target)
        engine("k", 1)
        engine.close()

        assert "item=k" in target.read_text(encoding="utf-8")

    def test_the_file_sink_never_creates_its_parent(self, tmp_path: Path) -> None:
        """**建目录不是审计的事**：父目录不存在就写不出去、就报错。"""
        target = tmp_path / "missing" / "audit.log"
        log = Log(path=target, console=False)
        log.wrote(item="k", file="settings.json", op="fill", data=1)

        with pytest.raises(ConfError, match="审计文件写入失败"):
            log.close_txn()

        assert not target.parent.exists(), "审计凭空造出了一棵目录树"

    def test_a_log_path_under_a_missing_directory_is_loud(self, tmp_path: Path) -> None:
        """同一个口径在引擎这一层：`home` 打错要当场看得见。"""
        engine = Engine(tmp_path / "conf", log_path=tmp_path / "missing" / "audit.log")

        with pytest.raises(ConfError, match="审计文件写入失败"):
            engine("k", 1)
        assert not (tmp_path / "missing").exists()

    @pytest.mark.skipif(os.name == "nt", reason="Windows 上 chmod 只切换只读位")
    def test_the_audit_file_is_private(self, tmp_path: Path) -> None:
        """审计里写着配置值，所以文件必须是 0600（T12）。"""
        engine = Engine(tmp_path)
        engine("k", 1)

        assert (tmp_path / "audit.log").stat().st_mode & 0o777 == 0o600

    def test_a_broken_audit_sink_is_loud(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """审计缺席不是「少看几行」，所以它的失败要抛出来。"""

        def boom(_path: Path, _data: bytes) -> None:
            raise OSError("磁盘满了")

        engine = Engine(tmp_path)
        monkeypatch.setattr(_log, "_append_file", boom)

        with pytest.raises(ConfError, match="审计文件写入失败"):
            engine("k", 1)

    def test_key_names_never_become_audit_paths(self, tmp_path: Path) -> None:
        """审计文件名是固定的，不参与键名拼接（T1）。"""
        home = tmp_path / "conf"
        engine = Engine(home)
        engine("../../escape", 1)
        engine.close()

        written = {path.name for path in home.rglob("*") if path.is_file()}
        assert written <= {"settings.json", "settings.lock", "settings.key", "audit.log"}
        assert not (tmp_path / "escape.json").exists()


# --------------------------------------------------------------------------- #
# 三个口子：默认全空，塞什么就按什么来
# --------------------------------------------------------------------------- #


class TestHooks:
    def test_there_is_no_rotation_unless_a_hook_says_so(self, tmp_path: Path) -> None:
        """默认不轮转：一个文件一直长。"""
        home = tmp_path / "conf"
        engine = Engine(home)
        for index in range(20):
            engine(f"k{index}", "x" * 120)
        engine.close()

        assert [path.name for path in home.glob("audit*.log")] == ["audit.log"], "默认轮转了"

    def test_a_rotate_hook_switches_the_sink_without_moving_anything(
        self, tmp_path: Path
    ) -> None:
        """轮转是**换落点**：旧文件原地不动，绝不 rename。"""
        home = tmp_path / "conf"
        seen: list[int] = []

        def rotate(path: Path, size: int) -> Path:
            seen.append(size)
            return path if size == 0 else path.with_name("audit-part2.log")

        engine = Engine(home, log_rotate=rotate)
        engine("a", 1)
        engine("b", 2)
        engine.close()

        assert seen, "轮转钩子必须被调用"
        assert (home / "audit.log").exists(), "旧文件被搬走了 —— 轮转只能是换落点"
        assert (home / "audit-part2.log").exists(), "钩子给了新落点就得换过去"
        assert "item=a" in _file(home), "已经写下的审计不许被动过"

    def test_a_rotate_hook_may_keep_the_same_path(self, tmp_path: Path) -> None:
        """返回同一个落点就是「不轮转」，这是钩子的正常返回。"""
        home = tmp_path / "conf"
        engine = Engine(home, log_rotate=lambda path, _size: path)
        engine("a", 1)
        engine.close()

        assert [path.name for path in home.glob("audit*.log")] == ["audit.log"]

    def test_a_scrub_hook_runs_before_anything_lands(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """脱敏钩子在落盘前生效，而且**两个出口都看同一份**已脱敏的记录。"""

        def scrub(record: Record) -> Record:
            return replace(record, data=MISSING, old=MISSING, new=MISSING)

        home = tmp_path / "conf"
        engine = Engine(home, log_scrub=scrub)
        engine("k", "secret")
        engine.close()

        text = _file(home)
        assert "secret" not in text
        assert "old=-" in text, "脱敏后的变更行只剩两个缺席标记"
        assert "new=-" in text
        assert "data=secret" not in text
        assert "secret" not in capsys.readouterr().err

    def test_an_encode_hook_decides_the_final_bytes(self, tmp_path: Path) -> None:
        """编码钩子定的是**落盘字节**：加密 / 压缩都挂在这里。"""
        home = tmp_path / "conf"
        engine = Engine(home, log_encode=lambda data: b"<enc>" + data)
        engine("k", 1)
        engine.close()

        raw = (home / "audit.log").read_bytes()
        assert raw.startswith(b"<enc>")
        assert b"item=k" in raw

    def test_values_land_verbatim_by_default(self, tmp_path: Path) -> None:
        """默认既不脱敏也不编码：`data=` / `old=` / `new=` 里就是真实值。"""
        home = tmp_path / "conf"
        engine = Engine(home)
        engine("k", "plain-value")
        engine.close()

        assert "data=plain-value" in _file(home)


# --------------------------------------------------------------------------- #
# 控制台出口：能关、不占 stdout、非 TTY 无色、TTY 才碰 rich
# --------------------------------------------------------------------------- #


class TestConsoleSink:
    def test_the_console_can_be_closed_but_the_file_is_still_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "conf"
        engine = Engine(home, log_console=False)
        engine("k", 1)
        engine.close()

        captured = capsys.readouterr()
        assert captured.err == "", "控制台关掉了还写终端"
        assert captured.out == ""
        assert "item=k" in _file(home), "关控制台不该关掉文件那一份"

    def test_the_library_never_writes_to_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``stdout`` 是调用方的数据通道，库日志只走 ``stderr``。"""
        engine = Engine(tmp_path)
        engine("k", 1)

        assert capsys.readouterr().out == ""

    def test_non_tty_output_has_no_ansi(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        engine = Engine(tmp_path)
        engine("k", 1)

        assert "\x1b[" not in capsys.readouterr().err, "管道与 CI 日志里不许出现 ANSI"

    def test_a_tty_gets_coloured_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY 上才走 rich 着色，而且行内容与纯文本那份一致。"""
        monkeypatch.setattr(_log, "_is_tty", lambda _stream: True)
        engine = Engine(tmp_path)
        engine("k", 1)

        err = capsys.readouterr().err
        assert "\x1b[" in err, "TTY 上应当着色"
        assert "item=k" in strip_ansi(err)
        assert "rich" in sys.modules, "着色分支必须真的用上 rich"

    def test_importing_onconf_does_not_import_rich(self) -> None:
        """强制路径不许多付 rich 的导入成本：`import onconf` 不得触碰它。"""
        code = "import sys, onconf; print('rich' in sys.modules)"
        done = subprocess.run(  # noqa: S603 - 参数全是本测试写死的，没有外部输入
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )

        assert done.stdout.strip() == "False"

    def test_both_sinks_carry_the_same_facts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """两个出口同源：文件里查得到的字段，终端上也查得到。"""
        home = tmp_path / "conf"
        engine = Engine(home)
        engine("app.port", 512)
        engine.close()

        err = strip_ansi(capsys.readouterr().err)
        text = _file(home)
        for field in ("item=app.port", "op=fill", "data=512"):
            assert field in err, field
            assert field in text, field


# --------------------------------------------------------------------------- #
# 谁记账：收口时返回的就是真正输出出去的那一批
# --------------------------------------------------------------------------- #


class TestAccounting:
    def test_close_txn_returns_what_was_emitted(self, tmp_path: Path) -> None:
        log = Log(path=tmp_path / "audit.log", console=False)
        record = log.wrote(item="a", file="settings.json", op="fill", data=1)

        assert log.close_txn() == (record,)
        assert log.close_txn() == (), "缓冲清空了，第二次没有产出"


# --------------------------------------------------------------------------- #
# 日志自己坏掉时：不盖住真正的异常，也不毁掉另一半
# --------------------------------------------------------------------------- #


class TestBrokenSinks:
    def test_a_broken_audit_sink_does_not_mask_the_real_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """审计写不出去时，抛出来的必须是**原来那个异常**（类型都不能变）。"""

        def boom(_path: Path, _data: bytes) -> None:
            raise OSError("磁盘满了")

        engine = Engine(tmp_path, file_type="toml")
        monkeypatch.setattr(_log, "_append_file", boom)

        with pytest.raises(TypeError):
            engine("port", None)
        with pytest.raises(KeyNotRegisteredError):
            engine("nope")

    def test_a_broken_console_renderer_does_not_destroy_the_audit_batch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """控制台那一路坏掉不该顺手把审计那一批也带走。"""

        def boom(*_args: object, **_kwargs: object) -> str:
            raise RuntimeError("渲染炸了")

        home = tmp_path / "conf"
        engine = Engine(home)
        monkeypatch.setattr(_log, "_render_terminal", boom)
        engine("k", 1)
        engine.close()

        assert "item=k" in _file(home)

    def test_a_disk_error_is_logged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """盘满 / 没权限是 ``OSError``，不是 ConfError —— 一样要留痕。"""

        def boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("磁盘满了")

        engine = Engine(tmp_path)
        monkeypatch.setattr(_engine, "_atomic_write_text", boom)
        with pytest.raises(OSError):
            engine("k", 1)

        assert "err=os-error" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# 身份与行完整性
# --------------------------------------------------------------------------- #


class TestIdentityIntegrity:
    def test_identity_lands_on_every_line(self, tmp_path: Path) -> None:
        home = tmp_path / "conf"
        engine = Engine(home, identity="order-svc@host-3")
        engine("k", 1)
        engine.close()

        assert "id=order-svc@host-3" in _file(home)

    def test_a_newline_in_a_key_cannot_forge_a_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """键名里的换行不许伪造出额外的审计行。"""
        engine = Engine(tmp_path)
        forged = "k\n[Write]-[1970-01-01T00:00:00.000]-[txn=1 pid=1] item=FAKE"
        engine(forged, 1)

        lines = _lines(capsys.readouterr().err)
        # ``[Start]`` 那一行随环境而变（值文件名、pid），所以这里只钉**伪造**这一件事。
        writes = [line for line in lines if line.startswith("[Write]")]
        assert len(writes) == 2, f"[Write] 行数不对：{lines}"
        assert all("\\n" in line for line in writes), "换行应当被折成可见转义"
        assert not any(line.startswith("[Write]-[1970-01-01T00:00:00.000]") for line in lines), (
            "键名里的换行伪造出了一条独立的审计行"
        )


# --------------------------------------------------------------------------- #
# 生命周期：引擎起来时留一行
# --------------------------------------------------------------------------- #


class TestLifecycle:
    def test_start_is_logged_once_before_any_fact(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """先说自己起来了，然后才是配置事实；而且只说一次。"""
        engine = Engine(tmp_path)
        engine("k", 1)

        lines = _lines(capsys.readouterr().err)
        assert lines[0].startswith("[Start]"), lines
        assert len([line for line in lines if line.startswith("[Start]")]) == 1, "记了两次"
        assert "txn=0" in lines[0], "生命周期记录不属于任何配置事务"
