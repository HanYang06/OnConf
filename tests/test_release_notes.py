# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""scripts/release_notes.py：Release 正文生成与发版收口。"""

from __future__ import annotations

import importlib.util
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


def test_repository_unreleased_page_matches_template() -> None:
    """仓库里的未发布页必须与脚本里的模板逐字一致，否则发版才发现漂移。"""
    page = Path(__file__).resolve().parents[1] / "docs" / "CHANGELOG" / "unreleased.md"
    text = page.read_text(encoding="utf-8")
    previous = text.rsplit("compare/v", 1)[1].split("...", 1)[0]
    assert text == notes.unreleased_text(previous)


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
    assert len(actions) == 3


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
