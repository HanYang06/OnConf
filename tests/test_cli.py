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
