# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""scripts/check_links.py：仓库内引用检查。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_links.py"
REPO_ROOT = SCRIPT.parents[1]


def _load() -> Any:
    """按文件路径加载脚本（tests 不把 scripts 当包）。"""
    spec = importlib.util.spec_from_file_location("_onconf_check_links", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


links = _load()


def _problems(tmp_path: Path) -> list[str]:
    """对临时目录跑一遍相对链接检查。"""
    return links.check_relative_links(tmp_path, links.markdown_files(tmp_path))


def test_existing_relative_link_passes(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("b\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("[b](b.md)\n", encoding="utf-8")
    assert _problems(tmp_path) == []


def test_missing_relative_link_is_reported(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("[b](gone/b.md)\n", encoding="utf-8")
    problems = _problems(tmp_path)
    assert len(problems) == 1
    assert "a.md" in problems[0]
    assert "gone/b.md" in problems[0]


def test_directory_target_needs_an_index(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.md").write_text("[子目录](sub) 与 [子目录](sub/)\n", encoding="utf-8")
    assert len(_problems(tmp_path)) == 2

    (tmp_path / "sub" / "index.md").write_text("index\n", encoding="utf-8")
    assert _problems(tmp_path) == []


def test_anchors_and_external_urls_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "[锚点](#top) 与 [外链](https://example.com/x) 与 [邮件](mailto:a@b.c)\n",
        encoding="utf-8",
    )
    assert _problems(tmp_path) == []


def test_code_spans_and_fences_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "行内示例：`[x](gone.md)`\n\n```markdown\n[y](also-gone.md)\n```\n\n[真链接](real.md)\n",
        encoding="utf-8",
    )
    (tmp_path / "real.md").write_text("real\n", encoding="utf-8")
    assert _problems(tmp_path) == []


def test_reference_definitions_are_checked(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("[x][ref]\n\n[ref]: gone.md\n", encoding="utf-8")
    assert len(_problems(tmp_path)) == 1


def test_repo_urls_must_point_at_a_real_path(tmp_path: Path) -> None:
    root = tmp_path
    (root / "docs").mkdir()
    (root / "docs" / "real.md").write_text("real\n", encoding="utf-8")
    (root / "a.md").write_text(
        f"[真]({links.REPO_URL}/blob/main/docs/real.md) "
        f"[假]({links.REPO_URL}/tree/main/docs/gone)\n",
        encoding="utf-8",
    )
    problems = links.check_repo_urls(root, links.markdown_files(root))
    assert len(problems) == 1
    assert "docs/gone" in problems[0]


def test_main_reports_the_exit_code(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'Changelog = "{links.REPO_URL}/blob/main/docs/CHANGELOG/index.md"\n',
        encoding="utf-8",
    )
    assert links.main(["--root", str(tmp_path)]) == 1

    (tmp_path / "docs" / "CHANGELOG").mkdir(parents=True)
    (tmp_path / "docs" / "CHANGELOG" / "index.md").write_text("ok\n", encoding="utf-8")
    assert links.main(["--root", str(tmp_path)]) == 0


def test_this_repository_has_no_dangling_references() -> None:
    """真仓库上的回归：文档里出现的相对引用与本仓库地址都必须落到真实路径。"""
    markdown = links.markdown_files(REPO_ROOT)
    assert links.check_relative_links(REPO_ROOT, markdown) == []
    assert links.check_repo_urls(REPO_ROOT, [*markdown, REPO_ROOT / "pyproject.toml"]) == []
