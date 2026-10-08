# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引导层发现的回归：静态扫描、白名单、一次性子进程求值、派生快照与优先级。

这一组用例分四段：

* **扫描** —— 只读 ``AutoConf(...)`` 的参数结构，读不懂的进问题清单；
* **求值** —— 白名单放行什么、拒绝什么，以及子进程失败时怎么"不猜"；
* **快照** —— 坏表 / 旧版本 / 地址对不上，一律当没有这张表；
* **优先级** —— 显式参数 > 代码 > 表 > 约定，以及 `home` 的自举例外。
"""

from __future__ import annotations

import ast
import json
from typing import TYPE_CHECKING

import pytest

from onconf import _boot
from onconf._engine import SNAPSHOT_NAME, SNAPSHOT_VERSION


if TYPE_CHECKING:
    from pathlib import Path


#: 用户那份"配置之前得先算"的形态：模块常量 + 环境旋钮 + `__file__` 相对路径。
_COMPUTED = """
import os
from pathlib import Path

from onconf import AutoConf

CONFIG_DIRNAME = "config"
ROOT_ENV = "CAIRN_CONFIG"


def config_root() -> Path:
    from_env = os.environ.get(ROOT_ENV)
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[2] / CONFIG_DIRNAME


AutoConf(home=config_root(), log_console=False)
"""


def _write(root: Path, source: str, name: str = "conf.py") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _snapshot(where: Path, **changes: object) -> None:
    """往 ``<home>`` 里塞一张手写的表（模拟引擎那次落表）。"""
    where.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "version": SNAPSHOT_VERSION,
        "generated_by": "onconf",
        "home": str(where.resolve()),
        "file_name": "settings",
        "file_type": "json",
        "no_one_file": False,
        "log_path": "",
        "declared_at": "app/conf.py:7",
        "recorded_at": "2026-01-01T00:00:00+00:00",
        "pid": 1,
    }
    payload.update(changes)
    (where / SNAPSHOT_NAME).write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #


class TestScan:
    def test_a_literal_declaration_reads_without_a_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全是字面量时**不进子进程** —— 这是常态，不该每次都拉一个解释器。"""
        _write(
            tmp_path,
            "from onconf import AutoConf\n"
            "AutoConf(home='config', file_name='app', no_one_file=True)\n",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(_boot, "_run_child", lambda _script: pytest.fail("不该进子进程"))
        layer = _boot.resolve_boot(tmp_path)
        assert layer.home == (tmp_path / "config").resolve()
        assert layer.file_name == "app"
        assert layer.no_one_file is True
        assert layer.sources["home"] == "code"
        assert layer.problems == []

    def test_the_bare_form_is_not_a_declaration(self, tmp_path: Path) -> None:
        """``AutoConf()`` 是「把单例取回来」，不是一次装配。"""
        _write(tmp_path, "from onconf import AutoConf\nAutoConf(log_console=False)\n")
        scan = _boot.scan_boot(tmp_path)
        assert scan.decls == []
        assert scan.problems == []

    def test_star_kwargs_cannot_be_read(self, tmp_path: Path) -> None:
        _write(tmp_path, "from onconf import AutoConf\nAutoConf(**{'home': 'x'})\n")
        scan = _boot.scan_boot(tmp_path)
        assert scan.problems
        assert "**kwargs" in scan.problems[0]

    def test_the_module_alias_counts(self, tmp_path: Path) -> None:
        _write(tmp_path, "import onconf\nonconf.AutoConf(home='x')\n")
        scan = _boot.scan_boot(tmp_path)
        assert scan.decls
        assert scan.decls[0].values == {"home": "x"}

    def test_two_disagreeing_declarations_are_a_problem(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "from onconf import AutoConf\n"
            "AutoConf(home='a', file_name='one')\n"
            "AutoConf(home='a', file_name='two')\n",
        )
        layer = _boot.resolve_boot(tmp_path)
        assert any("declared differently" in problem for problem in layer.problems)

    def test_an_ignored_keyword_is_not_a_boot_parameter(self, tmp_path: Path) -> None:
        _write(tmp_path, "from onconf import AutoConf\nAutoConf(home='x', log_console=False)\n")
        assert _boot.resolve_boot(tmp_path).problems == []


# --------------------------------------------------------------------------- #
# 求值：白名单 + 子进程
# --------------------------------------------------------------------------- #


class TestEvaluate:
    def test_a_computed_home_is_resolved_in_a_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`config_root()` 那种形态拿到的是**真值**，不是我们猜的。"""
        _write(tmp_path / "src" / "pkg", _COMPUTED)
        monkeypatch.delenv("CAIRN_CONFIG", raising=False)
        layer = _boot.resolve_boot(tmp_path)
        assert layer.home == (tmp_path / "config").resolve()
        assert layer.sources["home"] == "code"
        assert layer.problems == []

    def test_the_env_branch_is_seen_by_the_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """环境旋钮由**子进程**读它自己的环境 —— 与运行期同一个环境。"""
        _write(tmp_path / "src" / "pkg", _COMPUTED)
        monkeypatch.setenv("CAIRN_CONFIG", str(tmp_path / "elsewhere"))
        assert _boot.resolve_boot(tmp_path).home == (tmp_path / "elsewhere").resolve()

    def _evaluate(self, tmp_path: Path, source: str, expr: str) -> tuple[bool, object, str]:
        """把 ``expr`` 当作 ``AutoConf`` 的实参形态求一次；``source`` 是它所在的模块。"""
        path = _write(tmp_path, source)
        tree = ast.parse(source)
        node = ast.parse(expr, mode="eval").body
        return _boot.evaluate(node, path=path, tree=tree)

    def test_a_forbidden_call_is_refused(self, tmp_path: Path) -> None:
        ok, _, problem = self._evaluate(
            tmp_path,
            "import os\n\n\ndef probe():\n    return os.system('echo hi')\n",
            "os.system('echo hi')",
        )
        assert ok is False
        assert "os.system" in problem

    def test_a_forbidden_import_is_refused(self, tmp_path: Path) -> None:
        ok, _, problem = self._evaluate(
            tmp_path,
            "import shutil\n\n\ndef probe():\n    return shutil.which('x')\n",
            "shutil.which('x')",
        )
        assert ok is False
        assert "shutil" in problem

    def test_a_loop_is_refused(self, tmp_path: Path) -> None:
        ok, _, problem = self._evaluate(
            tmp_path,
            "def probe(x):\n    while True:\n        x = x\n    return x\n",
            "probe(1)",
        )
        assert ok is False
        assert "While" in problem

    def test_an_undefined_name_is_refused(self, tmp_path: Path) -> None:
        ok, _, problem = self._evaluate(tmp_path, "def probe():\n    return nowhere\n", "probe()")
        assert ok is False
        assert "nowhere" in problem

    def test_a_crashing_resolver_is_reported_not_guessed(self, tmp_path: Path) -> None:
        ok, _, problem = self._evaluate(tmp_path, "def probe():\n    return 1 / 0\n", "probe()")
        assert ok is False
        assert "zero" in problem.lower() or "resolver" in problem

    def test_a_runaway_resolver_is_stopped(self, tmp_path: Path) -> None:
        ok, _, problem = self._evaluate(
            tmp_path,
            "def probe():\n    return probe()\n\n\ndef other():\n    return probe()\n",
            "other()",
        )
        assert ok is False
        assert problem

    def test_the_probe_returns_real_python_semantics(self, tmp_path: Path) -> None:
        """摘出来的片段由**真解释器**跑，所以 `Path` 的行为与运行期一字不差。"""
        path = _write(
            tmp_path,
            "from pathlib import Path\n\n\ndef probe():\n"
            "    return Path(__file__).resolve().parent / 'sub' / '..' / 'config'\n",
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        node = ast.parse("probe()", mode="eval").body
        ok, value, problem = _boot.evaluate(node, path=path, tree=tree)
        assert ok is True, problem
        # `Path` 不归一 `..`：拿到的是**真解释器**算出来的那串，与运行期一字不差。
        assert value == str(tmp_path / "sub" / ".." / "config")


# --------------------------------------------------------------------------- #
# 派生快照
# --------------------------------------------------------------------------- #


class TestSnapshot:
    def test_a_good_table_is_read(self, tmp_path: Path) -> None:
        home = tmp_path / "conf"
        _snapshot(home, file_name="app", no_one_file=True)
        table = _boot.read_snapshot(home)
        assert table is not None
        assert (table.file_name, table.no_one_file) == ("app", True)
        assert table.declared_at == "app/conf.py:7"

    def test_a_missing_table_is_no_table(self, tmp_path: Path) -> None:
        assert _boot.read_snapshot(tmp_path / "conf") is None

    def test_a_corrupt_table_is_no_table(self, tmp_path: Path) -> None:
        home = tmp_path / "conf"
        home.mkdir()
        (home / SNAPSHOT_NAME).write_text("{not json", encoding="utf-8")
        assert _boot.read_snapshot(home) is None

    def test_an_older_version_is_no_table(self, tmp_path: Path) -> None:
        home = tmp_path / "conf"
        _snapshot(home, version=SNAPSHOT_VERSION + 1)
        assert _boot.read_snapshot(home) is None

    def test_a_table_that_names_another_home_is_no_table(self, tmp_path: Path) -> None:
        """表里说的地址与它所在的目录对不上 ⇒ 它是被搬过来的，整张不采信。"""
        home = tmp_path / "conf"
        _snapshot(home, home=str((tmp_path / "other").resolve()))
        assert _boot.read_snapshot(home) is None

    def test_a_badly_typed_table_is_no_table(self, tmp_path: Path) -> None:
        home = tmp_path / "conf"
        _snapshot(home, no_one_file="yes")
        assert _boot.read_snapshot(home) is None


# --------------------------------------------------------------------------- #
# 优先级
# --------------------------------------------------------------------------- #


class TestPriority:
    def test_the_flag_beats_the_code(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "from onconf import AutoConf\nAutoConf(home='code', file_name='app')\n")
        layer = _boot.resolve_boot(tmp_path, home="flag", file_name="cli")
        assert layer.home == (tmp_path / "flag").resolve()
        assert layer.file_name == "cli"
        assert layer.sources == {
            "home": "flag",
            "file_name": "flag",
            "file_type": "default",
            "no_one_file": "default",
            "log_path": "default",
        }

    def test_the_code_beats_the_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        home = tmp_path / "conf"
        _snapshot(home, file_name="from-table", no_one_file=True)
        _write(
            tmp_path, "from onconf import AutoConf\nAutoConf(home='conf', file_name='from-code')\n"
        )
        layer = _boot.resolve_boot(tmp_path)
        assert layer.file_name == "from-code"
        assert layer.sources["file_name"] == "code"
        # `no_one_file` 代码没说，就采信表；表与代码不一致的地方给一条"表过期了"。
        assert layer.no_one_file is True
        assert layer.sources["no_one_file"] == "snapshot"
        assert any("stale" in note for note in layer.notes)

    def test_the_table_fills_what_the_code_is_silent_about(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        home = tmp_path / "conf"
        _snapshot(home, file_name="app", log_path=str(home / "audit.log"))
        _write(tmp_path, "from onconf import AutoConf\nAutoConf(home='conf')\n")
        layer = _boot.resolve_boot(tmp_path)
        assert (layer.file_name, layer.sources["file_name"]) == ("app", "snapshot")
        assert layer.log_path.endswith("audit.log")

    def test_home_never_comes_from_the_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """表就住在 ``<home>`` 里，所以它不可能是 home 的来源（自举）。"""
        monkeypatch.chdir(tmp_path)
        home = tmp_path / "conf"
        _snapshot(home, file_name="app")
        layer = _boot.resolve_boot(tmp_path)
        assert layer.home == (tmp_path / "conf").resolve()
        assert layer.sources["home"] == "default"
        assert layer.file_name == "app"

    def test_the_environment_comes_before_the_convention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONCONF_HOME", str(tmp_path / "from-env"))
        layer = _boot.resolve_boot(tmp_path)
        assert layer.home == (tmp_path / "from-env").resolve()
        assert layer.sources["home"] == "env"

    def test_a_relative_log_path_is_not_a_stale_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """表里存的是**解析后**的落点，代码里写的是相对值 —— 这不是"表过期了"。"""
        monkeypatch.chdir(tmp_path)
        home = tmp_path / "conf"
        _snapshot(home, log_path=str(home / "logs" / "audit.log"))
        _write(
            tmp_path,
            "from onconf import AutoConf\nAutoConf(home='conf', log_path='logs/audit.log')\n",
        )
        layer = _boot.resolve_boot(tmp_path)
        assert layer.log_path == "logs/audit.log"
        assert layer.sources["log_path"] == "code"
        assert layer.notes == []

    def test_durable_values_ignore_the_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """落表的值只看代码 / 表 / 缺省：显式参数是一次性的，不许改下一次的缺省。"""
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "from onconf import AutoConf\nAutoConf(home='conf')\n")
        layer = _boot.resolve_boot(tmp_path, file_name="cli", no_one_file=True)
        assert (layer.file_name, layer.no_one_file) == ("cli", True)
        assert layer.durable["file_name"] == "settings"
        assert layer.durable["no_one_file"] is False
        assert layer.durable["home"] == (tmp_path / "conf").resolve()

    def test_durable_values_prefer_the_code_over_the_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        home = tmp_path / "conf"
        _snapshot(home, file_name="from-table")
        _write(
            tmp_path,
            "from onconf import AutoConf\nAutoConf(home='conf', file_name='from-code')\n",
        )
        layer = _boot.resolve_boot(tmp_path, file_name="cli")
        assert layer.durable["file_name"] == "from-code"

    def test_an_unresolvable_home_is_a_problem_not_a_guess(self, tmp_path: Path) -> None:
        """项目里有个算不出来的 ``home=``：出声，并且明确说"我用的是回退值"。"""
        _write(
            tmp_path,
            "import os\nfrom onconf import AutoConf\n\n\n"
            "def probe():\n    return os.environ['NOT_SET_ANYWHERE']\n\n\n"
            "AutoConf(home=probe())\n",
        )
        layer = _boot.resolve_boot(tmp_path)
        assert any("cannot resolve" in problem for problem in layer.problems)
        assert layer.sources["home"] == "default"

    def test_a_non_string_home_is_reported(self, tmp_path: Path) -> None:
        _write(tmp_path, "from onconf import AutoConf\nAutoConf(home=123)\n")
        layer = _boot.resolve_boot(tmp_path)
        assert any("not usable" in problem for problem in layer.problems)
