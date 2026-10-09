# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""发布工具：变更日志页 ⇄ GitHub Release 正文，以及发版时的收口。

两条子命令：

``body``
    读 ``docs/CHANGELOG/<版本>.md``，把页内的相对链接换成指向仓库的绝对链接，
    补上站点版本页地址，输出可以直接喂给 ``gh release create --notes-file`` 的正文。
    该版本页不存在时以退出码 1 结束 —— 发版链因此拿不到正文，宁可失败也不发一个
    没有变更记录的版本。

``finalize``
    把 ``docs/CHANGELOG/unreleased.md`` 收成 ``docs/CHANGELOG/<版本>.md``（标题补日期、
    对比链接换成该版本），给索引页补一行，再重新开一张未发布页。三件事一次做完，
    省掉手工搬运带来的笔误。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Sequence

REPO_URL = "https://github.com/HanYang06/OnConf"
SITE_URL = "https://hanyang06.github.io/OnConf"
CHANGELOG_DIR = Path("docs") / "CHANGELOG"
INDEX_NAME = "index.md"
UNRELEASED_NAME = "unreleased.md"
INDEX_UNRELEASED_LINE = "- [未发布](unreleased.md)"

# 未发布页的模板。仓库里的 docs/CHANGELOG/unreleased.md 必须与它一致 —— 由
# tests/test_release_notes.py 钉住，免得模板漂移之后发版才发现。
UNRELEASED_TEMPLATE = """## [Unreleased]

下一版的条目写在这里：人维护，一个 `fix:` / `feat:` 一行。发版时整页收成
`docs/CHANGELOG/<版本>.md`（标题补日期），本页重新开一张 —— 一条命令做完：
`uv run python scripts/release_notes.py finalize <版本>`。口径见
[变更日志的维护口径](../community/changelog.md)。

### Added

### Changed

### Fixed

[Unreleased]: {repo}/compare/v{previous}...HEAD
"""

_INLINE_LINK_RE = re.compile(r"\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")
_DEFINITION_RE = re.compile(r"^(\[[^\]]+\]:\s*)(\S+)\s*$", re.MULTILINE)


def repo_root() -> Path:
    """返回仓库根目录：本脚本所在目录的上一级。"""
    return Path(__file__).resolve().parents[1]


def version_key(name: str) -> tuple[int, ...]:
    """把版本页的文件名转成可比较的键；不是纯数字点分版本时返回空元组。"""
    parts = name.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return ()
    return tuple(int(part) for part in parts)


def version_pages(directory: Path) -> list[str]:
    """列出目录里所有版本页的版本号，按版本从小到大排序。"""
    versions = [path.stem for path in directory.glob("*.md") if version_key(path.stem)]
    return sorted(versions, key=version_key)


def previous_version(directory: Path, version: str) -> str | None:
    """返回比 ``version`` 小的最新版本页；没有更早的版本页时返回 None。"""
    target = version_key(version)
    earlier = [item for item in version_pages(directory) if version_key(item) < target]
    return earlier[-1] if earlier else None


def _absolute_target(target: str, source: Path, root: Path) -> str:
    """把页内相对目标换成仓库绝对 URL；外部链接与锚点原样返回。"""
    if "://" in target or target.startswith(("#", "mailto:", "tel:")):
        return target
    path_text, _, fragment = target.partition("#")
    if not path_text:
        return target
    try:
        relative = (source.parent / path_text).resolve().relative_to(root.resolve())
    except ValueError:
        return target
    url = f"{REPO_URL}/blob/main/{relative.as_posix()}"
    return f"{url}#{fragment}" if fragment else url


def with_absolute_links(text: str, source: Path, root: Path) -> str:
    """把一页变更日志里的相对链接与引用定义换成绝对链接。

    Release 正文不在仓库上下文里，相对链接在那里解析不到东西。

    Args:
        text: 该页的 Markdown 正文。
        source: 正文来自哪个文件（相对目标以它为基准解析）。
        root: 仓库根目录。

    Returns:
        替换后的正文。
    """

    def inline(match: re.Match[str]) -> str:
        title = match.group(2) or ""
        return f"]({_absolute_target(match.group(1), source, root)}{title})"

    def definition(match: re.Match[str]) -> str:
        return f"{match.group(1)}{_absolute_target(match.group(2), source, root)}"

    return _DEFINITION_RE.sub(definition, _INLINE_LINK_RE.sub(inline, text))


def unreleased_text(previous: str) -> str:
    """返回未发布页应有的全文；``previous`` 是刚发出去的那个版本。"""
    return UNRELEASED_TEMPLATE.format(repo=REPO_URL, previous=previous)


def build_body(root: Path, version: str) -> str:
    """生成该版本的 GitHub Release 正文。

    Args:
        root: 仓库根目录。
        version: 版本号，对应 ``docs/CHANGELOG/<版本>.md``。

    Returns:
        该页正文（相对链接已绝对化）加上站点版本页与索引的地址。

    Raises:
        FileNotFoundError: 该版本页不存在。
    """
    page = root / CHANGELOG_DIR / f"{version}.md"
    if not page.is_file():
        raise FileNotFoundError(page)
    body = with_absolute_links(page.read_text(encoding="utf-8"), page, root).rstrip("\n")
    footer = (
        "\n\n---\n\n"
        f"- 站点版本页：{SITE_URL}/CHANGELOG/{version}/\n"
        f"- 变更日志索引：{SITE_URL}/CHANGELOG/\n"
    )
    return body + footer


def _insert_index_line(index: Path, line: str) -> None:
    """把新版本那一行插进索引页的「未发布」之后。"""
    lines = index.read_text(encoding="utf-8").splitlines()
    for position, entry in enumerate(lines):
        if entry.strip() == INDEX_UNRELEASED_LINE:
            lines.insert(position + 1, line)
            break
    else:
        raise ValueError(f"{index} 里找不到 {INDEX_UNRELEASED_LINE!r} 这一行")
    index.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def finalize(root: Path, version: str, date: str | None = None) -> list[str]:
    """把未发布页收成该版本页，重置未发布页，并给索引补一行。

    Args:
        root: 仓库根目录。
        version: 这次发出去的版本号。
        date: 发布日期（``YYYY-MM-DD``）；缺省用本机当天。

    Returns:
        实际做了哪几件事，供调用方打印。

    Raises:
        FileNotFoundError: 未发布页不存在。
        FileExistsError: 该版本页已经存在（重复收口）。
        ValueError: 找不到上一个版本页，或未发布页里缺对比链接定义。
    """
    directory = root / CHANGELOG_DIR
    unreleased = directory / UNRELEASED_NAME
    target = directory / f"{version}.md"
    if not unreleased.is_file():
        raise FileNotFoundError(unreleased)
    if target.exists():
        raise FileExistsError(target)
    previous = previous_version(directory, version)
    if previous is None:
        raise ValueError("找不到更早的版本页，无法确定对比基准")
    stamp = date or datetime.now(UTC).astimezone().date().isoformat()

    text = unreleased.read_text(encoding="utf-8")
    text = text.replace("## [Unreleased]", f"## [{version}] - {stamp}", 1)
    old_url = f"[Unreleased]: {REPO_URL}/compare/v{previous}...HEAD"
    if old_url not in text:
        raise ValueError(f"{unreleased.name} 里找不到对比链接定义 {old_url!r}")
    text = text.replace(old_url, f"[{version}]: {REPO_URL}/compare/v{previous}...v{version}", 1)
    target.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")

    unreleased.write_text(unreleased_text(version), encoding="utf-8", newline="\n")

    line = f"- [{version}]({version}.md) —— {stamp}"
    _insert_index_line(directory / INDEX_NAME, line)

    return [
        f"新建 {target.relative_to(root).as_posix()}（对比基准 v{previous}）",
        f"重置 {unreleased.relative_to(root).as_posix()}",
        f"索引补一行：{line}",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：``body`` / ``finalize`` 两条子命令。"""
    parser = argparse.ArgumentParser(description="变更日志 → GitHub Release 正文")
    subcommands = parser.add_subparsers(dest="command", required=True)

    body = subcommands.add_parser("body", help="生成该版本的 Release 正文")
    body.add_argument("version", help="版本号，例如 2.1.0")
    body.add_argument("--output", type=Path, help="写到文件（缺省打到标准输出）")

    finish = subcommands.add_parser("finalize", help="把未发布页收成该版本页")
    finish.add_argument("version", help="版本号，例如 2.2.0")
    finish.add_argument("--date", help="发布日期 YYYY-MM-DD（缺省本机当天）")

    args = parser.parse_args(argv)
    root = repo_root()

    if args.command == "body":
        try:
            text = build_body(root, args.version)
        except FileNotFoundError:
            missing = (CHANGELOG_DIR / f"{args.version}.md").as_posix()
            print(
                f"{missing} 不存在：先跑 "
                f"`uv run python scripts/release_notes.py finalize {args.version}`",
                file=sys.stderr,
            )
            return 1
        if args.output is not None:
            args.output.write_text(text, encoding="utf-8", newline="\n")
        else:
            print(text, end="")
        return 0

    try:
        actions = finalize(root, args.version, args.date)
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f"收口失败：{error}", file=sys.stderr)
        return 1
    for action in actions:
        print(action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
