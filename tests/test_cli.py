# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""命令行的回归：静态扫描 + ``build`` / ``sync``。

命令行的行为只有两个来源：**扫描到的期望集**与**引擎的收敛**。所以这里的用例分两组：
一组盯扫描（参数形态、别名、字面量边界），一组盯两条命令对磁盘的实际动作
（重建 / 补缺 / 删除 / ``--dry-run`` 一个字节都不写）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from onconf import _reset
from onconf._cli import main, scan_project
from onconf._log import strip_ansi


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate() -> Iterator[None]:
    _reset()
    yield
    _reset()


def _write(tmp_path: Path, source: str, name: str = "main.py") -> None:
    (tmp_path / name).write_text(source, encoding="utf-8")


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(tmp_path)
    return main(list(argv))


# --------------------------------------------------------------------------- #
# 扫描：参数形态
# --------------------------------------------------------------------------- #


class TestScan:
    def test_the_three_unambiguous_shapes(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "from onconf import conf\n"
            "conf('a.one', 1)\n"
            "conf('a.two', 2, '说明')\n"
            "conf('a.three', doc='只登记')\n",
        )
        scan = scan_project(tmp_path)
        found = {item.key: item for item in scan.decls}
        assert set(found) == {"a.one", "a.two", "a.three"}
        assert found["a.one"].value == 1
        assert found["a.one"].doc is None
        assert found["a.two"].doc == "说明"
        assert found["a.three"].doc == "只登记"
        assert not scan.problems

    def test_a_read_is_not_a_declaration(self, tmp_path: Path) -> None:
        _write(tmp_path, "from onconf import conf\nprint(conf('a.port'))\n")
        assert scan_project(tmp_path).decls == []

    def test_doc_keyword_is_told_apart_from_a_value(self, tmp_path: Path) -> None:
        """``conf(key, doc=…)`` 是登记；``conf(key, value=…)`` 是声明 —— 只看写没写 ``doc=``。"""
        _write(
            tmp_path,
            "from onconf import conf\n"
            "conf('a.required', doc='必填')\n"
            "conf(key='a.port', value=8080)\n",
        )
        found = {item.key: item for item in scan_project(tmp_path).decls}
        assert found["a.required"].doc == "必填"
        assert found["a.required"].value.__class__.__name__ == "_Sentinel"  # MISSING
        assert found["a.port"].value == 8080

    def test_an_alias_is_followed(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "import onconf as oc\nfrom onconf import conf as c\n"
            "oc.conf('a.one', 1)\nc('a.two', 2)\n",
        )
        assert {item.key for item in scan_project(tmp_path).decls} == {"a.one", "a.two"}

    def test_another_librarys_conf_is_ignored(self, tmp_path: Path) -> None:
        _write(tmp_path, "from elsewhere import conf\nconf('not.ours', 1)\n")
        assert scan_project(tmp_path).decls == []

    def test_a_non_literal_is_a_problem_not_a_silent_drop(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "from onconf import conf\n"
            "PORT = 8080\n"
            "conf('a.port', PORT)\n"
            "for name in ('a', 'b'):\n"
            "    conf('loop.' + name, 1)\n",
        )
        scan = scan_project(tmp_path)
        assert scan.decls == []
        assert len(scan.problems) == 2

    def test_a_variable_key_is_out_of_scope(self, tmp_path: Path) -> None:
        """``APP_POST = "app.post"; conf(APP_POST, 8080)`` 会有人这么写 —— 但**不在支持范围内**。

        这条用例把口径钉死：不解读、也不去猜，一律进问题清单。命令行只认字面量，
        因为它的价值来自「扫全部代码 = 与代码天然同步」，而不是来自替表达式求值。
        """
        _write(
            tmp_path,
            'from onconf import conf\nAPP_POST = "app.post"\nconf(APP_POST, 8080)\n',
        )
        scan = scan_project(tmp_path)
        assert scan.decls == []
        assert len(scan.problems) == 1
        assert "is not a literal" in scan.problems[0]

    def test_a_variable_key_read_is_not_a_problem(self, tmp_path: Path) -> None:
        """**读取**不受「声明处必须字面量」约束，``conf(APP)`` 不进问题清单。

        期望集只由声明形态构成，读取不进期望集 —— 因此它的键是不是字面量与
        「期望集完不完整」无关。误报的代价不只是多一行输出：``sync`` 会因为
        问题清单非空而平白拒绝清理。
        """
        _write(tmp_path, 'from onconf import conf\nAPP = "app.post"\nconf(APP)\n')
        scan = scan_project(tmp_path)
        assert scan.decls == []
        assert scan.problems == []

    def test_a_doc_only_declaration_with_a_variable_key_is_a_problem(
        self, tmp_path: Path
    ) -> None:
        """``conf(APP, doc=…)`` 是**声明**（模式 2），所以变量键照样进问题清单。"""
        _write(tmp_path, 'from onconf import conf\nAPP = "app.post"\nconf(APP, doc="端口")\n')
        scan = scan_project(tmp_path)
        assert scan.decls == []
        assert len(scan.problems) == 1
        assert "is not a literal" in scan.problems[0]

    def test_a_doc_none_call_reads_instead_of_declaring(self, tmp_path: Path) -> None:
        """``doc=None`` 与没写 ``doc`` 等价 ⇒ 读 —— 与运行期的判据同源。"""
        _write(tmp_path, 'from onconf import conf\nconf("app.post", doc=None)\n')
        scan = scan_project(tmp_path)
        assert scan.decls == []
        assert scan.problems == []

    def test_duplicate_declarations_last_one_wins(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "from onconf import conf\nconf('a.port', 1)\nconf('a.port', 2)\n",
        )
        scan = scan_project(tmp_path)
        assert [item.value for item in scan.decls] == [2]
        assert scan.notes, "重复声明要留一句提醒"

    def test_a_bom_is_stripped_like_cpython_does(self, tmp_path: Path) -> None:
        """带 BOM 的源文件在 CPython 里合法；扫描必须对齐，不然整份文件被当成语法错误。"""
        (tmp_path / "bom.py").write_bytes(
            "\ufefffrom onconf import conf\nconf('a.port', 1)\n".encode("utf-8")
        )
        scan = scan_project(tmp_path)
        assert [item.key for item in scan.decls] == ["a.port"]
        assert not scan.problems

    def test_a_syntax_error_is_a_problem_not_a_crash(self, tmp_path: Path) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.b'\n")
        scan = scan_project(tmp_path)
        assert scan.decls == []
        assert any("syntax error" in item for item in scan.problems)

    def test_an_undecodable_file_is_a_problem(self, tmp_path: Path) -> None:
        (tmp_path / "broken.py").write_bytes(b"from onconf import conf\n# \xff\xfe\n")
        scan = scan_project(tmp_path)
        assert scan.decls == []
        assert any("cannot be read" in item for item in scan.problems)

    @pytest.mark.parametrize(
        ("source", "needle"),
        [
            ("from onconf import conf\nconf()\n", "no key"),
            ("from onconf import conf\nconf('a', 1, 'd', 'extra')\n", "positional arguments"),
            ("from onconf import conf\nconf('a', 1, value=2)\n", "both positionally"),
            ("from onconf import conf\nconf('a', 1, unknown=2)\n", "unknown parameter"),
            ("from onconf import conf\nconf(key='a', doc=1)\n", "doc of 'a' is not a string"),
            ("from onconf import conf\nconf(**{'a': 1})\n", "**kwargs"),
            ("from onconf import conf\nconf(2, 1)\n", "key is not a string"),
        ],
    )
    def test_malformed_calls_become_problems(
        self, tmp_path: Path, source: str, needle: str
    ) -> None:
        _write(tmp_path, source)
        scan = scan_project(tmp_path)
        assert scan.decls == []
        assert any(needle in item for item in scan.problems), scan.problems

    def test_skipped_directories_are_not_scanned(self, tmp_path: Path) -> None:
        vendor = tmp_path / ".venv" / "lib"
        vendor.mkdir(parents=True)
        _write(vendor, "from onconf import conf\nconf('from.vendor', 1)\n")
        assert scan_project(tmp_path).decls == []


# --------------------------------------------------------------------------- #
# build：完整重建
# --------------------------------------------------------------------------- #


class TestBuild:
    def test_rebuild_keeps_only_the_declaration_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "conf"
        home.mkdir()
        (home / "settings.json").write_text(
            json.dumps({"$schema": "schema/settings.json", "old.key": 1}) + "\n",
            encoding="utf-8",
        )
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080, '端口')\n")

        assert _run(tmp_path, monkeypatch, "build") == 0

        rebuilt = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert rebuilt["a.port"] == 8080
        assert "old.key" not in rebuilt, "完整重建只保留声明集"
        schema = json.loads((home / "schema" / "settings.json").read_text(encoding="utf-8"))
        assert schema["properties"]["a.port"] == {"description": "端口", "default": 8080}

    def test_path_rebuilds_elsewhere_and_leaves_the_home_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "conf"
        home.mkdir()
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        out = tmp_path / "out"

        assert _run(tmp_path, monkeypatch, "build", "--home", str(home), "--path", str(out)) == 0

        assert (out / "settings.json").exists()
        assert (out / "schema" / "settings.json").exists()
        assert list(home.iterdir()) == [], "--path 时原目录一个字节都不动"

    def test_dry_run_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "build", "--dry-run") == 0
        assert list(tmp_path.glob("**/*.json")) == []
        assert "--dry-run" in capsys.readouterr().out

    def test_multi_file_rebuild_splits_by_embedded_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(
            tmp_path,
            "from onconf import conf\n"
            "conf('app/net:net.port', 8080)\n"
            "conf('plain.key', 1)\n",
        )
        assert (
            _run(
                tmp_path,
                monkeypatch,
                "build",
                "--home",
                str(tmp_path / "conf"),
                "--no-one-file",
            )
            == 0
        )

        home = tmp_path / "conf"
        sub = json.loads((home / "app" / "net.json").read_text(encoding="utf-8"))
        assert sub["net.port"] == 8080
        assert sub["$schema"] == "../schema/settings.json"


# --------------------------------------------------------------------------- #
# sync：补缺 / 删除
# --------------------------------------------------------------------------- #


class TestSync:
    def test_sync_fills_missing_and_cleans_undeclared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "conf"
        home.mkdir()
        (home / "settings.json").write_text(
            json.dumps({"$schema": "schema/settings.json", "a.port": 9090, "ghost": 1}) + "\n",
            encoding="utf-8",
        )
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\nconf('a.name', 'demo')\n")

        assert _run(tmp_path, monkeypatch, "sync", "--home", str(home)) == 0

        data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert data["a.port"] == 9090, "既存值不被覆盖（运行期与命令行的共同底线）"
        assert data["a.name"] == "demo", "缺的补上"
        assert "ghost" not in data, "未声明的键被删掉"

    def test_sync_works_from_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**空目录直接 sync 也要能跑**：没有值文件、没有词表，语义上照样成立。

        命令行只依据当前代码 —— 有多少 `.py` 就扫多少，所以它不需要「先有一份配置」
        才能开始，重建与收敛是同一件事的两面。
        """
        home = tmp_path / "conf"
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080, '端口')\n")

        assert _run(tmp_path, monkeypatch, "sync", "--home", str(home)) == 0

        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["a.port"] == 8080
        assert (home / "schema" / "settings.json").exists()

    def test_sync_from_nothing_in_multi_file_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同上，但多文件开启：没有 `:` 的键与带路径的键各自落在该落的地方。"""
        home = tmp_path / "conf"
        _write(
            tmp_path,
            "from onconf import conf\n"
            "conf('plain.key', 1)\n"
            "conf('app/net:net.port', 8080)\n",
        )

        assert (
            _run(
                tmp_path,
                monkeypatch,
                "sync",
                "--home",
                str(home),
                "--no-one-file",
            )
            == 0
        )

        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["plain.key"] == 1
        assert (
            json.loads((home / "app" / "net.json").read_text(encoding="utf-8"))["net.port"] == 8080
        )

    def test_no_clean_keeps_undeclared_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "conf"
        home.mkdir()
        (home / "settings.json").write_text(
            json.dumps({"$schema": "schema/settings.json", "ghost": 1}) + "\n",
            encoding="utf-8",
        )
        _write(tmp_path, "from onconf import conf\nconf('a.name', 'demo')\n")

        assert _run(tmp_path, monkeypatch, "sync", "--home", str(home), "--no-clean") == 0

        data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert data["ghost"] == 1
        assert data["a.name"] == "demo"

    def test_problems_block_cleaning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """期望集不完整 ⇒ 一个键都不删（规则 1 的正确性前提），并以非 0 退出。"""
        home = tmp_path / "conf"
        home.mkdir()
        (home / "settings.json").write_text(
            json.dumps({"$schema": "schema/settings.json", "ghost": 1}) + "\n",
            encoding="utf-8",
        )
        _write(tmp_path, "from onconf import conf\nPORT = 8080\nconf('a.port', PORT)\n")

        assert _run(tmp_path, monkeypatch, "sync", "--home", str(home)) == 1
        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["ghost"] == 1

    def test_problems_are_fine_when_nothing_is_deleted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "conf"
        home.mkdir()
        (home / "settings.json").write_text(
            json.dumps({"$schema": "schema/settings.json", "ghost": 1}) + "\n",
            encoding="utf-8",
        )
        _write(tmp_path, "from onconf import conf\nPORT = 8080\nconf('a.port', PORT)\n")

        assert _run(tmp_path, monkeypatch, "sync", "--home", str(home), "--no-clean") == 0
        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["ghost"] == 1

    def test_dry_run_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "conf"
        home.mkdir()
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")

        assert _run(tmp_path, monkeypatch, "sync", "--home", str(home), "--dry-run") == 0
        assert list(home.iterdir()) == []

    def test_json_output_is_the_same_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080, '端口')\n")
        assert _run(tmp_path, monkeypatch, "build", "--dry-run", "--json") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["command"] == "build"
        assert payload["declarations"][0]["key"] == "a.port"
        assert payload["declarations"][0]["doc"] == "端口"
        assert payload["dry_run"] is True

    def test_human_output_is_english(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """命令行**自己写的**文本一律英文（路线图 2-077）。

        库产出的文本不在这条口径里：异常消息与计划里的 ``reason=`` 是库的数据。
        """
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080, '端口')\n")
        assert _run(tmp_path, monkeypatch, "build", "--dry-run") == 0
        out = capsys.readouterr().out
        assert "declared    : a.port" in out
        assert "total       : rebuilt 1 declaration(s)" in out
        assert not any("\u4e00" <= char <= "\u9fff" for char in out)

    def test_help_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as excinfo:
            main(["sync", "--help"])
        assert excinfo.value.code == 0
        assert list(tmp_path.iterdir()) == []


class TestCheck:
    """``check``：三个口径（代码 / 词表 / 值文件）的对比与报告。"""

    def _built(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
    ) -> None:
        """写一份声明并 ``build`` 一次 —— 让词表与值文件都跟上声明。"""
        _write(tmp_path, source)
        assert _run(tmp_path, monkeypatch, "build") == 0

    def test_a_clean_project_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._built(
            tmp_path, monkeypatch, "from onconf import conf\nconf('a.port', 8080, 'port')\n"
        )
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "check") == 0
        assert capsys.readouterr().out.splitlines() == ["All config items are OK."]

    def test_nothing_built_yet_reports_missing_and_unfilled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "check") == 5
        assert capsys.readouterr().out.splitlines() == [
            "missing     a.port",
            "unfilled    a.port",
            'Run "onconf sync" to align the vocabulary and the value files.',
        ]

    def test_drift_is_reported_in_all_four_ways(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """少一条声明、改值、改说明、再手塞一个未声明的键 —— 四类一起报。"""
        self._built(
            tmp_path,
            monkeypatch,
            "from onconf import conf\nconf('a.port', 8080, 'port')\nconf('a.host', 'localhost')\n",
        )
        _write(tmp_path, "from onconf import conf\nconf('a.port', 9090, 'the port')\n")
        values = tmp_path / "conf" / "settings.json"
        data = json.loads(values.read_text(encoding="utf-8"))
        data["a.legacy"] = 1
        values.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        assert _run(tmp_path, monkeypatch, "check") == 5
        out = capsys.readouterr().out
        assert "stale       a.host" in out
        assert "undeclared  a.legacy" in out
        assert "default     a.port        9090 => 8080" in out
        assert 'doc         a.port        "the port" => "port"' in out

    def test_directives_are_not_config_items(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``$schema`` 是指令键：值文件里有它，但它既不是配置项，也不该被报成未声明。"""
        self._built(tmp_path, monkeypatch, "from onconf import conf\nconf('a.port', 8080)\n")
        values = tmp_path / "conf" / "settings.json"
        assert "$schema" in json.loads(values.read_text(encoding="utf-8"))
        assert _run(tmp_path, monkeypatch, "check") == 0

    def test_verbose_adds_the_value_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "check") == 5
        assert "settings.json" not in capsys.readouterr().out
        assert _run(tmp_path, monkeypatch, "check", "--verbose") == 5
        assert "settings.json" in capsys.readouterr().out

    def test_json_is_the_same_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "check", "--json") == 5
        payload = json.loads(capsys.readouterr().out)
        assert payload["command"] == "check"
        assert payload["ok"] is False
        assert payload["summary"] == {
            "missing": 1,
            "stale": 0,
            "default": 0,
            "doc": 0,
            "unfilled": 1,
            "undeclared": 0,
        }
        assert payload["findings"][0] == {
            "kind": "missing",
            "key": "a.port",
            "path": "settings.json",
            "code": None,
            "vocabulary": None,
        }
        assert payload["warnings"] == []

    def test_check_writes_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._built(tmp_path, monkeypatch, "from onconf import conf\nconf('a.port', 8080)\n")
        home = tmp_path / "conf"

        def snapshot() -> dict[str, tuple[bytes, int]]:
            return {
                path.relative_to(tmp_path).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in sorted(home.rglob("*"))
                if path.is_file()
            }

        before = snapshot()
        assert _run(tmp_path, monkeypatch, "check") == 0
        assert snapshot() == before

    def test_a_non_literal_declaration_warns_without_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """警告不改变通过判定 —— 但也不能因此看不见；``--strict`` 才把它升级为失败。"""
        _write(tmp_path, "from onconf import conf\nAPP = 'a.port'\nconf(APP, 8080)\n")
        assert _run(tmp_path, monkeypatch, "check") == 0
        out = capsys.readouterr().out
        assert "All config items are OK." in out
        assert "warning:" in out
        assert "is not a literal" in out
        assert _run(tmp_path, monkeypatch, "check", "--strict") == 5

    def test_check_has_no_dry_run_and_no_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """它只做检查与报告：既不写文件（没有 `--dry-run`），也不改文件（没有 `--fix`）。"""
        monkeypatch.chdir(tmp_path)
        for flag in ("--dry-run", "--fix"):
            with pytest.raises(SystemExit) as excinfo:
                main(["check", flag])
            assert excinfo.value.code == 2
        assert list(tmp_path.iterdir()) == []


class TestGet:
    def test_four_columns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080, 'port')\n")
        assert _run(tmp_path, monkeypatch, "build") == 0
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "get", "a.port") == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0].split() == ["key", "value", "path", "doc"]
        assert lines[1].split() == ["a.port", "8080", "settings.json", "port"]

    def test_multi_file_reports_every_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """同名的键落在多个文件里 —— 有多少刷多少，这正是 `path` 那一列的用处。"""
        _write(
            tmp_path,
            "from onconf import conf\n"
            "conf('a:app.port', 1, 'in a')\nconf('b:app.port', 2, 'in b')\n",
        )
        assert _run(tmp_path, monkeypatch, "build", "--no-one-file") == 0
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "get", "app.port", "--no-one-file") == 0
        out = capsys.readouterr().out
        assert "a.json" in out
        assert "b.json" in out
        assert len(out.splitlines()) == 3  # 表头 + 两行

    def test_file_without_multi_file_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--file` 只在多文件模式下有意义；关闭时给它是用法错误，不静默忽略。"""
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "get", "a.port", "--file", "x") == 2
        assert "--file only applies" in capsys.readouterr().err

    def test_an_unregistered_key_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "get", "nope") == 1


class TestSet:
    def test_it_changes_the_value_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "build") == 0
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "set", "a.port", "9090") == 0
        assert capsys.readouterr().out.strip() == "OK"
        values = json.loads((tmp_path / "conf" / "settings.json").read_text(encoding="utf-8"))
        assert values["a.port"] == 9090

    def test_it_refuses_to_create_a_new_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "build") == 0
        assert _run(tmp_path, monkeypatch, "set", "nope", "1") == 1

    def test_an_ambiguous_key_is_refused_with_the_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path,
            "from onconf import conf\n"
            "conf('a:app.port', 1, 'in a')\nconf('b:app.port', 2, 'in b')\n",
        )
        assert _run(tmp_path, monkeypatch, "build", "--no-one-file") == 0
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "set", "app.port", "9", "--no-one-file") == 2
        err = capsys.readouterr().err
        assert "exists in more than one file" in err
        assert "1: app.port" in err
        assert "2: app.port" in err
        assert "Please specify the file" in err

    def test_default_writes_the_vocabulary_and_names_the_declaration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080, 'port')\n")
        assert _run(tmp_path, monkeypatch, "build") == 0
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "set", "--default", "a.port", "7070") == 0
        out = capsys.readouterr().out
        assert out.splitlines()[0] == "OK"
        assert "declared at main.py:2" in out
        schema = (tmp_path / "conf" / "schema" / "settings.json").read_text(encoding="utf-8")
        assert "7070" in schema

    def test_dry_run_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "build") == 0
        before = (tmp_path / "conf" / "settings.json").read_bytes()
        assert _run(tmp_path, monkeypatch, "set", "a.port", "9090", "--dry-run") == 0
        assert (tmp_path / "conf" / "settings.json").read_bytes() == before


class TestDiff:
    def test_a_change_is_one_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path,
            "from onconf import conf\n"
            "conf('a.port', 8080, 'port')\nconf('a.host', 'local', 'host')\n",
        )
        assert _run(tmp_path, monkeypatch, "build") == 0
        values = tmp_path / "conf" / "settings.json"
        data = json.loads(values.read_text(encoding="utf-8"))
        data.pop("a.host")
        values.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        assert _run(tmp_path, monkeypatch, "sync") == 0  # 补回 a.host ⇒ 一条 [Change]
        capsys.readouterr()

        assert _run(tmp_path, monkeypatch, "diff") == 0
        out = capsys.readouterr().out
        assert "settings.json : a.host" in out
        assert "=>" in out
        assert "a.port" not in out

    def test_no_change_is_said_out_loud(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "diff") == 0
        assert capsys.readouterr().out.strip() == "No changes recorded."


class TestFormat:
    def test_without_indent_nothing_is_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "build") == 0
        values = tmp_path / "conf" / "settings.json"
        # 先压成一行，好看出「没给 --indent 就一个字节都不写」
        values.write_text('{"a.port": 8080}\n', encoding="utf-8")
        before = values.read_bytes()
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "format") == 0
        assert "nothing was written" in capsys.readouterr().out
        assert values.read_bytes() == before

    def test_indent_reformats_and_keeps_the_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, "from onconf import conf\nconf('a.port', 8080)\n")
        assert _run(tmp_path, monkeypatch, "build") == 0
        values = tmp_path / "conf" / "settings.json"
        values.write_text('{"$schema": "schema/settings.json", "a.port": 8080}\n', encoding="utf-8")
        assert _run(tmp_path, monkeypatch, "format", "--indent", "4") == 0
        text = values.read_text(encoding="utf-8")
        assert '\n    "a.port": 8080' in text
        assert json.loads(text) == {"$schema": "schema/settings.json", "a.port": 8080}


class TestColor:
    """``--color`` 是命令行的渲染闸门：**非 TTY 逐字稳定，``--json`` 永不着色**。

    只测「闸门有没有接在输出上」；判定表本身归 ``test_style.py``。
    """

    _SOURCE = "from onconf import conf\nconf('a.port', 8080, 'port')\n"

    def _project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write(tmp_path, self._SOURCE)
        assert _run(tmp_path, monkeypatch, "build") == 0

    def test_a_pipe_gets_the_plain_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """缺省 ``auto`` + 不是终端 ⇒ 与上色前**逐字相同**。"""
        self._project(tmp_path, monkeypatch)
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "check") == 0
        assert capsys.readouterr().out == "All config items are OK.\n"

    def test_always_colours_a_pipe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._project(tmp_path, monkeypatch)
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "check", "--color=always") == 0
        out = capsys.readouterr().out
        assert "\x1b[32m" in out
        assert strip_ansi(out) == "All config items are OK.\n"

    def test_never_beats_force_color(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._project(tmp_path, monkeypatch)
        monkeypatch.setenv("FORCE_COLOR", "1")
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "check", "--color=never") == 0
        assert "\x1b[" not in capsys.readouterr().out

    def test_json_is_never_coloured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._project(tmp_path, monkeypatch)
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "check", "--json", "--color=always") == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out
        assert json.loads(out)["ok"] is True

    def test_the_kind_cell_carries_the_colour(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """值文件里手塞一个未声明的键：它是唯一标红的一类（收敛动作会动用户手写的字节）。"""
        self._project(tmp_path, monkeypatch)
        values = tmp_path / "conf" / "settings.json"
        data = json.loads(values.read_text(encoding="utf-8"))
        data["a.legacy"] = 1
        values.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "check", "--color=always") == 5
        out = capsys.readouterr().out
        assert "\x1b[1;31mundeclared\x1b[0m" in out
        assert "undeclared  a.legacy" in strip_ansi(out)

    def test_ok_is_coloured_and_still_reads_as_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._project(tmp_path, monkeypatch)
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "set", "a.port", "9090", "--color=always") == 0
        assert strip_ansi(capsys.readouterr().out) == "OK\n"

    def test_errors_are_labelled_on_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, self._SOURCE)
        assert _run(tmp_path, monkeypatch, "get", "a.nope", "--color=always") == 1
        err = capsys.readouterr().err
        assert err.startswith("\x1b[1;31monconf:\x1b[0m")
        assert "is not registered" in strip_ansi(err)

    def test_an_unknown_mode_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as caught:
            main(["check", "--color=blue"])
        assert caught.value.code == 2


class TestBootLayer:
    """命令行怎么知道引导层：代码 > 缺省，显式参数最大，算不出来的不猜。"""

    def test_the_code_decides_the_config_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\n"
            "AutoConf(home='conf')\n"
            "conf('a.port', 8080)\n",
        )
        assert _run(tmp_path, monkeypatch, "build") == 0
        assert (tmp_path / "conf" / "settings.json").is_file()
        capsys.readouterr()
        assert _run(tmp_path, monkeypatch, "check") == 0
        assert capsys.readouterr().out.strip() == "All config items are OK."

    def test_the_flag_beats_the_code(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\nAutoConf(home='conf')\nconf('a.port', 8080)\n",
        )
        other = tmp_path / "other"
        assert _run(tmp_path, monkeypatch, "build", "--home", str(other)) == 0
        assert (other / "settings.json").is_file()
        assert not (tmp_path / "conf").exists()

    def test_a_computed_home_is_resolved_in_a_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``home=config_root()`` 这种"先算再配"的形态：命令行拿得到真值。"""
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        _write(
            tmp_path,
            "import os\nfrom pathlib import Path\n\nfrom onconf import AutoConf, conf\n\n"
            "CONFIG_DIRNAME = 'config'\n\n\n"
            "def config_root() -> Path:\n"
            "    from_env = os.environ.get('CAIRN_CONFIG')\n"
            "    if from_env:\n"
            "        return Path(from_env)\n"
            "    return Path(__file__).resolve().parents[2] / CONFIG_DIRNAME\n\n\n"
            "AutoConf(home=config_root())\n"
            "conf('a.port', 8080)\n",
            name="src/pkg/conf.py",
        )
        monkeypatch.delenv("CAIRN_CONFIG", raising=False)
        assert _run(tmp_path, monkeypatch, "check", "--json") == 5
        payload = json.loads(capsys.readouterr().out)
        assert payload["boot"]["home"] == str(tmp_path / "config")
        assert payload["boot"]["sources"]["home"] == "code"
        assert payload["boot"]["origin"].endswith("src/pkg/conf.py:16")

    def test_the_boot_sources_are_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\n"
            "AutoConf(home='conf', file_name='app')\n"
            "conf('a.port', 8080)\n",
        )
        assert _run(tmp_path, monkeypatch, "build", "--json") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["boot"]["sources"] == {
            "home": "code",
            "file_name": "code",
            "file_type": "default",
            "no_one_file": "default",
            "log_path": "default",
        }
        assert payload["file_name"] == "app"

    def test_an_unresolvable_home_warns_and_strict_makes_it_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path,
            "import os\nfrom onconf import AutoConf, conf\n\n\n"
            "def here():\n    return os.environ['ONCONF_NOPE_NOT_SET']\n\n\n"
            "AutoConf(home=here())\n"
            "conf('a.port', 8080)\n",
        )
        monkeypatch.delenv("ONCONF_NOPE_NOT_SET", raising=False)
        assert _run(tmp_path, monkeypatch, "check") == 5  # 声明没 build，本身就不过
        assert "cannot resolve" in capsys.readouterr().out
        assert _run(tmp_path, monkeypatch, "check", "--strict") == 5

    def test_sync_refuses_to_clean_when_the_boot_layer_is_unsettled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path,
            "import os\nfrom onconf import AutoConf, conf\n\n\n"
            "def here():\n    return os.environ['ONCONF_NOPE_NOT_SET']\n\n\n"
            "AutoConf(home=here())\n"
            "conf('a.port', 8080)\n",
        )
        monkeypatch.delenv("ONCONF_NOPE_NOT_SET", raising=False)
        assert _run(tmp_path, monkeypatch, "sync") == 1
        assert "boot layer" in capsys.readouterr().out
        assert _run(tmp_path, monkeypatch, "sync", "--no-clean") == 0

    def test_the_snapshot_is_not_a_value_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """派生快照的后缀也是 ``.json``，多文件模式**不能**把它当成值文件。"""
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\nAutoConf(home='conf')\nconf('a.port', 8080)\n",
        )
        assert _run(tmp_path, monkeypatch, "build", "--no-one-file") == 0
        table = tmp_path / "conf" / ".onconf.json"
        assert table.is_file(), "可写命令跑完就该有这张表"
        before = table.read_bytes()
        # 表是按 indent=2 写的：要是 format 把它当值文件，那一行就会变成 indent=4。
        assert _run(tmp_path, monkeypatch, "format", "--indent", "4", "--no-one-file") == 0
        assert table.read_bytes() == before

    def test_a_write_command_refreshes_the_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """「代码是事实标准」：代码改了，下一次可写命令把表改成代码说的。"""
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\nAutoConf(home='conf')\nconf('a.port', 8080)\n",
        )
        assert _run(tmp_path, monkeypatch, "build") == 0
        table = tmp_path / "conf" / ".onconf.json"
        assert json.loads(table.read_text(encoding="utf-8"))["file_name"] == "settings"
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\n"
            "AutoConf(home='conf', file_name='app')\nconf('a.port', 8080)\n",
        )
        assert _run(tmp_path, monkeypatch, "sync", "--no-clean") == 0
        assert json.loads(table.read_text(encoding="utf-8"))["file_name"] == "app"

    def test_the_flags_never_leak_into_the_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """显式参数是**这一趟**的意图：它会改写值文件，但不改写下一次命令的缺省。"""
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\nAutoConf(home='conf')\nconf('a.port', 8080)\n",
        )
        assert _run(tmp_path, monkeypatch, "build", "--file-name", "other") == 0
        assert (tmp_path / "conf" / "other.json").is_file()
        table = tmp_path / "conf" / ".onconf.json"
        assert json.loads(table.read_text(encoding="utf-8"))["file_name"] == "settings"

    def test_a_dry_run_and_a_read_only_command_leave_no_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\nAutoConf(home='conf')\nconf('a.port', 8080)\n",
        )
        assert _run(tmp_path, monkeypatch, "build", "--dry-run") == 0
        assert not (tmp_path / "conf" / ".onconf.json").exists()
        assert _run(tmp_path, monkeypatch, "check") == 5  # 没建过，报 missing / unfilled
        assert not (tmp_path / "conf").exists(), "读路径连目录都不该造"

    def test_check_does_not_refresh_an_existing_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(
            tmp_path,
            "from onconf import AutoConf, conf\nAutoConf(home='conf')\nconf('a.port', 8080)\n",
        )
        assert _run(tmp_path, monkeypatch, "build") == 0
        table = tmp_path / "conf" / ".onconf.json"
        before = (table.read_bytes(), table.stat().st_mtime_ns)
        assert _run(tmp_path, monkeypatch, "check") == 0
        assert (table.read_bytes(), table.stat().st_mtime_ns) == before
