# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""scripts/release_notes.py：Release 正文生成与发版收口。"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_notes.py"


def _load() -> Any:
    """按文件路径加载脚本（tests 不把 scripts 当包，也没给它加 sys.path）。"""
    spec = importlib.util.spec_from_file_location("_onconf_release_notes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notes = _load()

INDEX_SAMPLE = """# 变更日志

- [未发布](unreleased.md)
- [2.1.0](2.1.0.md) —— 2026-10-09
"""

MKDOCS_SAMPLE = """nav:
  - 变更日志:
      - 变更索引: CHANGELOG/index.md
      - 未发布: CHANGELOG/unreleased.md
      - 2.1.0（2026-10-09）: CHANGELOG/2.1.0.md
"""


def _changelog(tmp_path: Path) -> Path:
    """搭一棵最小的变更日志目录树。"""
    directory = tmp_path / "docs" / "CHANGELOG"
    directory.mkdir(parents=True)
    (directory / "index.md").write_text(INDEX_SAMPLE, encoding="utf-8")
    (directory / "2.1.0.md").write_text("## [2.1.0] - 2026-10-09\n", encoding="utf-8")
    (directory / "unreleased.md").write_text(
        notes.unreleased_text("2.1.0"),
        encoding="utf-8",
    )
    return directory


def _mkdocs(tree: Path) -> Path:
    """在最小树里放一份逐版列页的 nav（与仓库里那一份同样的缩进）。"""
    config = tree / "mkdocs.yml"
    config.write_text(MKDOCS_SAMPLE, encoding="utf-8")
    return config


def test_repository_unreleased_page_keeps_the_shape() -> None:
    """未发布页可以有条目，但骨架必须在：标题、三个分区、指向 HEAD 的对比定义。"""
    page = Path(__file__).resolve().parents[1] / "docs" / "CHANGELOG" / "unreleased.md"
    assert _unreleased_shape_ok(page.read_text(encoding="utf-8"))


def test_unreleased_template_keeps_the_same_shape() -> None:
    """发版收口写回的那一页，与仓库里那一页必须是同一种骨架。"""
    assert _unreleased_shape_ok(notes.unreleased_text("2.1.0"))


def _unreleased_shape_ok(text: str) -> bool:
    """未发布页的骨架判据。"""
    compare = re.search(
        r"^\[Unreleased\]: https://github\.com/HanYang06/OnConf/compare/v\d+\.\d+\.\d+\.\.\.HEAD$",
        text,
        re.MULTILINE,
    )
    return (
        text.startswith("## [Unreleased]\n")
        and "### Added" in text
        and "### Changed" in text
        and "### Fixed" in text
        and compare is not None
    )


def test_version_pages_ignore_non_versions(tmp_path: Path) -> None:
    for name in ("2.0.0.md", "unreleased.md", "index.md", "10.0.0.md", "2.10.0.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert notes.version_pages(tmp_path) == ["2.0.0", "2.10.0", "10.0.0"]


def test_previous_version_picks_the_nearest_earlier_page(tmp_path: Path) -> None:
    for name in ("0.1.0.md", "2.0.0.md", "2.1.0.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert notes.previous_version(tmp_path, "2.2.0") == "2.1.0"
    assert notes.previous_version(tmp_path, "2.1.0") == "2.0.0"
    assert notes.previous_version(tmp_path, "0.2.0") == "0.1.0"
    assert notes.previous_version(tmp_path, "0.1.0") is None


def test_with_absolute_links_rewrites_only_relative_targets(tmp_path: Path) -> None:
    page = tmp_path / "docs" / "CHANGELOG" / "2.1.0.md"
    page.parent.mkdir(parents=True)
    page.write_text("x", encoding="utf-8")
    text = "- [路线图](../roadmap/2.x.md) 与 [外链](https://example.com/a) 与 [锚点](#top)\n"
    result = notes.with_absolute_links(text, page, tmp_path)
    assert "https://github.com/HanYang06/OnConf/blob/main/docs/roadmap/2.x.md" in result
    assert "https://example.com/a" in result
    assert "[锚点](#top)" in result


def test_build_body_appends_site_links(tmp_path: Path) -> None:
    directory = _changelog(tmp_path)
    (directory / "2.1.0.md").write_text(
        "## [2.1.0] - 2026-10-09\n\n- 修好了[路线图](../roadmap/2.x.md)里的一处示例。\n",
        encoding="utf-8",
    )
    body = notes.build_body(tmp_path, "2.1.0")
    assert "## [2.1.0] - 2026-10-09" in body
    assert "https://github.com/HanYang06/OnConf/blob/main/docs/roadmap/2.x.md" in body
    assert "https://hanyang06.github.io/OnConf/CHANGELOG/2.1.0/" in body
    assert body.endswith("\n")


def test_build_body_rejects_a_missing_page(tmp_path: Path) -> None:
    _changelog(tmp_path)
    with pytest.raises(FileNotFoundError):
        notes.build_body(tmp_path, "9.9.9")


def test_finalize_moves_the_page_and_reopens_unreleased(tmp_path: Path) -> None:
    directory = _changelog(tmp_path)
    actions = notes.finalize(tmp_path, "2.2.0", "2026-11-01")

    released = (directory / "2.2.0.md").read_text(encoding="utf-8")
    assert released.startswith("## [2.2.0] - 2026-11-01")
    assert f"[2.2.0]: {notes.REPO_URL}/compare/v2.1.0...v2.2.0" in released
    assert (directory / "unreleased.md").read_text(encoding="utf-8") == notes.unreleased_text(
        "2.2.0",
    )

    index = (directory / "index.md").read_text(encoding="utf-8")
    new_line = "- [2.2.0](2.2.0.md) —— 2026-11-01"
    assert index.index("- [未发布](unreleased.md)") < index.index(new_line)
    assert index.index(new_line) < index.index("- [2.1.0](2.1.0.md)")
    assert len(actions) == 4


def test_finalize_inserts_the_version_into_mkdocs_nav(tmp_path: Path) -> None:
    """收口要把版本页补进 nav：插在「未发布」之后，缩进与相邻行一致。"""
    _changelog(tmp_path)
    config = _mkdocs(tmp_path)
    actions = notes.finalize(tmp_path, "2.2.0", "2026-11-01")

    lines = config.read_text(encoding="utf-8").splitlines()
    entry = "      - 2.2.0（2026-11-01）: CHANGELOG/2.2.0.md"
    assert entry in lines
    position = lines.index(entry)
    assert lines[position - 1] == "      - 未发布: CHANGELOG/unreleased.md"
    assert lines[position + 1] == "      - 2.1.0（2026-10-09）: CHANGELOG/2.1.0.md"
    assert any("mkdocs.yml" in action for action in actions)


def test_finalize_skips_mkdocs_when_the_config_is_absent(tmp_path: Path) -> None:
    """最小树里没有 mkdocs.yml：跳过 nav，不因此失败。"""
    _changelog(tmp_path)
    actions = notes.finalize(tmp_path, "2.2.0", "2026-11-01")

    assert not (tmp_path / "mkdocs.yml").exists()
    assert len(actions) == 4
    assert any("无需改动" in action for action in actions)


def test_finalize_does_not_duplicate_an_existing_nav_line(tmp_path: Path) -> None:
    """导航里已经有这一行时原样保留，不重复插。"""
    _changelog(tmp_path)
    config = _mkdocs(tmp_path)
    entry = "      - 2.2.0（2026-11-01）: CHANGELOG/2.2.0.md"
    config.write_text(
        MKDOCS_SAMPLE.replace(
            "      - 2.1.0（2026-10-09）: CHANGELOG/2.1.0.md\n",
            f"      - 2.1.0（2026-10-09）: CHANGELOG/2.1.0.md\n{entry}\n",
        ),
        encoding="utf-8",
    )

    notes.finalize(tmp_path, "2.2.0", "2026-11-01")

    text = config.read_text(encoding="utf-8")
    assert text.count("CHANGELOG/2.2.0.md") == 1
    assert text.count("      - 未发布: CHANGELOG/unreleased.md") == 1


def test_finalize_refuses_an_existing_version_page(tmp_path: Path) -> None:
    directory = _changelog(tmp_path)
    (directory / "2.2.0.md").write_text("## [2.2.0] - 2026-01-01\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        notes.finalize(tmp_path, "2.2.0", "2026-11-01")


def test_main_body_writes_the_requested_file(tmp_path: Path, monkeypatch: Any) -> None:
    directory = _changelog(tmp_path)
    monkeypatch.setattr(notes, "repo_root", lambda: tmp_path)
    output = tmp_path / "release-body.md"
    assert notes.main(["body", "2.1.0", "--output", str(output)]) == 0
    assert "## [2.1.0] - 2026-10-09" in output.read_text(encoding="utf-8")
    assert notes.main(["body", "9.9.9"]) == 1
    assert directory.is_dir()
