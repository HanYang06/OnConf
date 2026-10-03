# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 HanYang06 <jihanyang123@163.com>
"""生成 ``THIRD_PARTY_NOTICES.md``：运行时依赖闭包 + 许可证声明。

## 为什么要有这个脚本

``NOTICE`` 只覆盖本项目自己的归属。被分发出去的 wheel 里还有一批**运行时依赖**，
它们的许可证必须随发行物一并可查——这份文件就是那份可查的东西。

## 数据从哪来（两个来源，各管一段）

1. **依赖闭包**：``uv export --no-dev --no-emit-project``。用 ``uv`` 而不是自己遍历
   ``pyproject.toml``，是因为闭包要跟 ``uv.lock`` 一致，而不是跟手写的依赖列表一致。
   ``--no-dev`` 同时排除 dev / docs 依赖组：开发期工具不进发行物。
2. **许可证与链接**：``importlib.metadata`` 读**已安装分发**的元数据。它读的是
   真实装上的那份，所以看到的就是用户拿到的那份。

## 许可证字段的优先级（新元数据格式优先）

``License-Expression``（PEP 639，Metadata-Version 2.4+，SPDX 表达式）
→ 所有 ``Classifier: License ::`` 分类器 → ``License`` 字段 → ``UNKNOWN``。

## 输出必须是**可复现**的

同一份 ``uv.lock`` 在任何平台上生成的字节必须完全相同，否则 CI 的 ``--check`` 就是噪声。
所以正文里**不写**机器相关的信息：不写 Python 版本、不写平台、不写 site-packages 的绝对路径
（分发内许可证文件只写相对 ``site-packages`` 的路径）。

## 用法

    uv run python scripts/gen_third_party_notices.py           # 生成 / 覆盖
    uv run python scripts/gen_third_party_notices.py --check   # 校验，不一致则退出码 1
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from importlib.metadata import Distribution, PackageMetadata


REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "THIRD_PARTY_NOTICES.md"

#: 只依赖标准库：脚本要能在最小环境里跑起来（见模块 docstring）。
UV_EXPORT_ARGS = (
    "export",
    "--no-dev",
    "--no-emit-project",
    "--format",
    "requirements-txt",
    "--no-hashes",
)

GENERATE_COMMAND = "uv run python scripts/gen_third_party_notices.py"
CHECK_COMMAND = f"{GENERATE_COMMAND} --check"

#: 单个许可证文本超过这个长度就截断（老包的 ``License`` 字段会塞进整篇许可证全文）。
_MAX_LICENSE_CELL = 120

#: 分发内可能承载许可证全文的路径前缀。
_LICENSE_PREFIXES = ("licenses/", "license/")
_LICENSE_FILENAMES = ("license", "licence", "copying", "notice", "copyright")


@dataclass(frozen=True)
class Requirement:
    """``uv export`` 里的一行：包名、版本、可选的环境标记。"""

    name: str
    version: str
    marker: str | None


@dataclass(frozen=True)
class Package:
    """一个运行时依赖：闭包里的声明 + 已安装分发的元数据。"""

    name: str
    version: str
    marker: str | None
    metadata_name: str
    metadata_version: str
    license_text: str
    license_source: str
    home_page: str | None
    project_urls: list[tuple[str, str]]
    license_files: list[str]


# --------------------------------------------------------------------------- #
# 依赖闭包
# --------------------------------------------------------------------------- #


def _requirements_from_uv() -> list[Requirement]:
    """用 ``uv export`` 取运行时依赖闭包。拿不到就退出，不静默降级。"""
    uv = shutil.which("uv")
    if uv is None:
        sys.exit(
            "找不到 uv 可执行文件。本脚本用 `uv export` 计算运行时依赖闭包，"
            "请先安装 uv 并确保它在 PATH 上：https://docs.astral.sh/uv/"
        )

    completed = subprocess.run(  # noqa: S603 —— 参数是写死的元组，不含外部输入
        [uv, *UV_EXPORT_ARGS],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=REPO_ROOT,
    )
    if completed.returncode != 0:
        sys.exit(
            f"`uv export` 失败（退出码 {completed.returncode}）：\n"
            f"{completed.stderr.strip()}\n"
            "请在仓库根目录确认 uv.lock 与 pyproject.toml 一致后重试。"
        )

    requirements: list[Requirement] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        spec, _, marker = line.partition(";")
        name, separator, version = spec.strip().partition("==")
        if not separator or not name.strip() or not version.strip():
            sys.exit(f"无法解析 `uv export` 的输出行：{raw_line!r}（期望 `name==version`）。")
        requirements.append(
            Requirement(name=name.strip(), version=version.strip(), marker=marker.strip() or None)
        )

    if not requirements:
        sys.exit(
            "`uv export` 没有输出任何运行时依赖。"
            "请确认 pyproject.toml 的 [project].dependencies 非空且 uv.lock 已更新。"
        )

    requirements.sort(key=lambda requirement: requirement.name.lower())
    return requirements


# --------------------------------------------------------------------------- #
# 元数据
# --------------------------------------------------------------------------- #


def _clean(value: str | None) -> str | None:
    """把元数据里的多行文本压成单行；``UNKNOWN`` 视同没有。"""
    if value is None:
        return None
    flattened = " ".join(value.split())
    if not flattened or flattened.upper() == "UNKNOWN":
        return None
    return flattened


def _truncate(text: str, limit: int = _MAX_LICENSE_CELL) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _license_of(metadata: PackageMetadata) -> tuple[str, str]:
    """按 PEP 639 → 分类器 → 旧字段的顺序取许可证，返回（文本，来源字段）。"""
    expression = _clean(metadata.get("License-Expression"))
    if expression is not None:
        return expression, "License-Expression"

    classifiers = [
        classifier.removeprefix("License :: ")
        for classifier in metadata.get_all("Classifier") or []
        if classifier.startswith("License :: ")
    ]
    if classifiers:
        return "; ".join(classifiers), "Classifier: License ::"

    legacy = _clean(metadata.get("License"))
    if legacy is not None:
        return _truncate(legacy), "License"

    return "UNKNOWN", "未声明"


def _project_urls(metadata: PackageMetadata) -> list[tuple[str, str]]:
    """``Project-URL`` 是 ``Label, URL`` 形式，可能有多个。"""
    urls: list[tuple[str, str]] = []
    for entry in metadata.get_all("Project-URL") or []:
        label, separator, url = entry.partition(",")
        if separator and label.strip() and url.strip():
            urls.append((label.strip(), url.strip()))
    return urls


def _license_files(dist: Distribution) -> list[str]:
    """分发内承载许可证全文的文件，路径相对 ``site-packages``（可复现）。"""
    found: list[str] = []
    for file in dist.files or []:
        path = str(file).replace("\\", "/")
        if ".dist-info/" not in path:
            continue
        relative = path.split(".dist-info/", 1)[1]
        lowered = relative.lower()
        if lowered.startswith(_LICENSE_PREFIXES) or lowered.split("/")[-1].startswith(
            _LICENSE_FILENAMES
        ):
            found.append(path)
    return sorted(found)


def _load(requirement: Requirement) -> Package:
    """读已安装分发的元数据。读不到就退出——静默写 UNKNOWN 等于把问题埋进发行物。"""
    try:
        dist = distribution(requirement.name)
    except PackageNotFoundError:
        marker_note = f"（环境标记：{requirement.marker}）" if requirement.marker else ""
        sys.exit(
            f"运行时依赖 {requirement.name}=={requirement.version} 没有安装在当前解释器里"
            f"{marker_note}。请先 `uv sync`（或 `uv sync --all-groups`）再运行本脚本。"
        )

    metadata = dist.metadata
    license_text, license_source = _license_of(metadata)
    return Package(
        name=requirement.name,
        version=requirement.version,
        marker=requirement.marker,
        metadata_name=_clean(metadata.get("Name")) or requirement.name,
        metadata_version=_clean(metadata.get("Metadata-Version")) or "UNKNOWN",
        license_text=license_text,
        license_source=license_source,
        home_page=_clean(metadata.get("Home-page")),
        project_urls=_project_urls(metadata),
        license_files=_license_files(dist),
    )


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #


def _render_header(packages: list[Package]) -> list[str]:
    return [
        "# 第三方软件声明",
        "",
        "> 本文件由 `scripts/gen_third_party_notices.py` **自动生成，请勿手工编辑**。",
        "> 任何手工改动都会在下一次生成时被覆盖，并使 CI 的 `--check` 失败。",
        "",
        "## 生成方式",
        "",
        "```bash",
        "# 重新生成",
        GENERATE_COMMAND,
        "",
        "# 校验（与当前文件不一致则退出码 1）",
        CHECK_COMMAND,
        "```",
        "",
        (
            "依赖清单由 `uv export --no-dev --no-emit-project --format requirements-txt"
            " --no-hashes` 得出，许可证信息由 `importlib.metadata` 从**已安装分发**的元数据读出。"
        ),
        "",
        "本文件覆盖 auto-conf 的**运行时依赖闭包**（含传递依赖），不含 dev / docs 依赖组；",
        "后两组只在开发期使用，不进入发行物。auto-conf 自身的许可证见仓库根目录的 `LICENSE`",
        "与 `NOTICE`（Apache-2.0）。",
        "",
        (
            "许可证列优先取 PEP 639 的 `License-Expression`（SPDX 表达式），其次为 "
            "`Classifier: License ::` 分类器，再次为旧式 `License` 字段；都没有时记为 `UNKNOWN`。"
            "许可证全文随各分发一并提供，路径见下方逐包明细（相对 `site-packages`），"
            "也可在对应的上游页面获取。"
        ),
        "",
        f"当前运行时依赖数量：**{len(packages)}**。",
        "",
        "## 汇总",
        "",
        "| 包 | 版本 | 许可证 | 许可证来源 | 环境标记 |",
        "|---|---|---|---|---|",
    ]


def _render_table(packages: list[Package]) -> list[str]:
    lines: list[str] = []
    for package in packages:
        marker = f"`{package.marker}`" if package.marker else "—"
        lines.append(
            f"| {package.metadata_name} | {package.version} | {package.license_text} "
            f"| {package.license_source} | {marker} |"
        )
    return lines


def _render_detail(package: Package) -> list[str]:
    lines = [
        f"### {package.metadata_name} {package.version}",
        "",
        f"- 元数据名称：`{package.metadata_name}`",
        f"- Metadata-Version：`{package.metadata_version}`",
        f"- 许可证：{package.license_text}（来源：{package.license_source}）",
    ]

    if package.marker:
        lines.append(f"- 环境标记：`{package.marker}`")
    else:
        lines.append("- 环境标记：无（所有平台都装）")

    if package.home_page:
        lines.append(f"- Home-page：<{package.home_page}>")
    else:
        lines.append("- Home-page：元数据未声明")

    if package.project_urls:
        links = "；".join(f"{label} <{url}>" for label, url in package.project_urls)
        lines.append(f"- Project-URL：{links}")
    else:
        lines.append("- Project-URL：元数据未声明")

    if package.license_files:
        shipped = "、".join(f"`{path}`" for path in package.license_files)
        lines.append(f"- 许可证全文（随分发提供，路径相对 `site-packages`）：{shipped}")
    else:
        lines.append("- 许可证全文：该分发未随包提供许可证文件，以元数据声明为准")

    lines.append(f"- 上游页面：<https://pypi.org/project/{package.name}/{package.version}/>")
    lines.append("")
    return lines


def render(packages: list[Package]) -> str:
    """把全部包渲染成最终的 Markdown 文本（LF 行尾、末尾单换行）。"""
    lines = _render_header(packages)
    lines += _render_table(packages)
    lines += ["", "## 逐包明细", ""]
    for package in packages:
        lines += _render_detail(package)
    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def collect() -> str:
    """算闭包 + 读元数据 + 渲染，返回最终文本。"""
    return render([_load(requirement) for requirement in _requirements_from_uv()])


def _write(text: str) -> None:
    r"""UTF-8 无 BOM、LF 行尾（``newline="\n"`` 关掉 Windows 上的换行翻译）。"""
    OUTPUT_PATH.write_text(text, encoding="utf-8", newline="\n")


def _check(text: str) -> int:
    if not OUTPUT_PATH.exists():
        print(
            f"{OUTPUT_PATH.name} 不存在。请先运行：{GENERATE_COMMAND}",
            file=sys.stderr,
        )
        return 1
    current = OUTPUT_PATH.read_text(encoding="utf-8")
    if current != text:
        print(
            f"{OUTPUT_PATH.name} 与运行时依赖闭包不一致。请运行：{GENERATE_COMMAND}",
            file=sys.stderr,
        )
        return 1
    print(f"{OUTPUT_PATH.name} 与运行时依赖闭包一致。")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口：默认生成，``--check`` 只校验不写。"""
    parser = argparse.ArgumentParser(
        prog="gen_third_party_notices.py",
        description="生成 THIRD_PARTY_NOTICES.md（运行时依赖闭包的许可证声明）。",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验现有文件是否与当前依赖闭包一致，不一致时退出码 1（供 CI 使用）。",
    )
    args = parser.parse_args(argv)

    text = collect()
    if args.check:
        return _check(text)

    _write(text)
    print(f"已写入 {OUTPUT_PATH.name}（{len(text.splitlines())} 行）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
