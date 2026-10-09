# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""仓库内引用检查：相对链接与指向本仓库的地址必须落到真实存在的路径上。

文档站构建（``mkdocs build --strict``）只校验 ``docs/`` 内部页面之间的链接；
README / SECURITY / pyproject / 已发布的那条版本线里的引用它一概看不见 —— 文件一搬，
这些引用就静默变成 404，而人眼在几十个文件里扫不出来（踩过一次，手工对了两小时）。

本脚本把两类引用钉到文件系统上：

1. **相对链接**：Markdown 里指向仓库内文件的地址，目标必须存在；指向目录时该目录下
   必须有 ``index.md`` 或 ``README.md``（否则站点上落到 404）。
2. **本仓库地址**：``https://github.com/HanYang06/OnConf/{blob,tree}/main/<路径>`` 里的
   ``<路径>`` 必须存在。扫描范围是全部 Markdown 加 ``pyproject.toml``（它的
   ``[project.urls]`` 会烘进 PyPI 元数据）。

代码块与行内代码里的内容不参与检查（那里写的是示例，不是引用）。退出码非 0 表示存在
悬空引用，每一处都打印文件与目标。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

REPO_URL = "https://github.com/HanYang06/OnConf"
BRANCH = "main"
# pyproject 里的 [project.urls] 会进 PyPI 元数据，所以它跟 Markdown 一起查。
EXTRA_URL_FILES = (Path("pyproject.toml"),)
SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "site",
    }
)
# 目录索引：指向目录的链接只有在这些文件存在时才算有效。
DIRECTORY_INDEXES = ("index.md", "README.md")

_FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_MARKDOWN_LINK_RE = re.compile(r"\]\(\s*(?:<([^>]*)>|([^)\s]+))(?:\s+\"[^\"]*\")?\s*\)")
_DEFINITION_RE = re.compile(r"^[ \t]*\[[^\]]+\]:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
_REPO_URL_RE = re.compile(
    re.escape(REPO_URL) + r"/(?:blob|tree)/" + BRANCH + r"/([^\s)#?\"']+)",
)


def repo_root() -> Path:
    """返回仓库根目录：本脚本所在目录的上一级。"""
    return Path(__file__).resolve().parents[1]


def strip_code(text: str) -> str:
    """去掉围栏代码块与行内代码，只留下真正的正文。"""
    return _INLINE_CODE_RE.sub("", _FENCE_RE.sub("", text))


def link_targets(text: str) -> Iterator[str]:
    """产出正文里全部链接目标（行内链接与引用定义）。"""
    for match in _MARKDOWN_LINK_RE.finditer(text):
        yield match.group(1) or match.group(2)
    for match in _DEFINITION_RE.finditer(text):
        yield match.group(1)


def markdown_files(root: Path) -> list[Path]:
    """列出需要检查的 Markdown 文件（跳过虚拟环境与站点产物）。"""
    found: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        directory = Path(current)
        found.extend(directory / name for name in filenames if name.endswith(".md"))
    return sorted(found)


def _local_target(target: str, source: Path) -> Path | None:
    """把链接目标解析成本地路径；外部链接、锚点与纯查询串返回 None。"""
    if "://" in target or target.startswith(("#", "mailto:", "tel:")):
        return None
    path_text = target.split("#", 1)[0].split("?", 1)[0]
    if not path_text:
        return None
    return (source.parent / path_text).resolve()


def _target_exists(path: Path) -> bool:
    """判断链接目标是否可用：文件本身存在，或目录里有索引页。"""
    if path.is_file():
        return True
    if path.is_dir():
        return any((path / name).is_file() for name in DIRECTORY_INDEXES)
    return False


def check_relative_links(root: Path, files: Iterable[Path]) -> list[str]:
    """检查相对链接与引用定义，返回悬空引用的描述（每项一行）。"""
    problems: list[str] = []
    for source in files:
        text = strip_code(source.read_text(encoding="utf-8"))
        for target in link_targets(text):
            resolved = _local_target(target, source)
            if resolved is None or _target_exists(resolved):
                continue
            problems.append(
                f"{source.relative_to(root).as_posix()}: 相对链接悬空 -> {target}",
            )
    return problems


def check_repo_urls(root: Path, files: Iterable[Path]) -> list[str]:
    """检查指向本仓库的 blob / tree 地址，返回路径不存在的描述。"""
    problems: list[str] = []
    for source in files:
        text = strip_code(source.read_text(encoding="utf-8"))
        for match in _REPO_URL_RE.finditer(text):
            if (root / match.group(1)).exists():
                continue
            where = source.relative_to(root).as_posix()
            problems.append(f"{where}: 仓库地址指向不存在的路径 -> {match.group(1)}")
    return problems


def main(argv: Iterable[str] | None = None) -> int:
    """命令行入口：扫一遍仓库，打印悬空引用并以退出码报告结论。"""
    parser = argparse.ArgumentParser(description="检查仓库内引用是否落到真实存在的路径")
    parser.add_argument("--root", type=Path, help="仓库根目录（缺省为脚本所在的仓库）")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = (args.root or repo_root()).resolve()

    markdown = markdown_files(root)
    metadata = [path for name in EXTRA_URL_FILES if (path := root / name).is_file()]
    problems = [
        *check_relative_links(root, markdown),
        *check_repo_urls(root, [*markdown, *metadata]),
    ]
    for problem in problems:
        print(problem, file=sys.stderr)
    print(
        f"检查了 {len(markdown)} 个 Markdown 文件与 {len(metadata)} 个元数据文件："
        f"{len(problems)} 处悬空引用",
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
