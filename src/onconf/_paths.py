# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
r"""外部字符串 → 路径的**唯一入口**：包含性校验。

值文件的名字（``file_name``）与多文件模式下键里内嵌的路径段，都是**外部字符串**。
它们是这个库里唯一能把写入带出配置目录的入口，所以只允许在这一个模块里拼成路径。

五条规则缺一不可：

1. 单文件的 ``file_name`` 必须是**纯文件名**；多文件的路径段必须是**相对路径**；
2. 不含 ``\\``（Windows 分隔符），也不含盘符形态（``C:``）；
3. 路径分量里不许出现空段、``.``、``..``；
4. 不接受空字符串与 NUL；
5. **解析之后必须仍在 ``<home>`` 之内** —— 前四条是语法，这一条才是目的。

任何一条不成立都抛 :class:`~onconf.errors.ConfError`，消息里带上出问题的那一段，
因为这条错误最终要落到用户的键字符串上，说清「是哪一段不合法」比说「非法」有用。
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NoReturn

from .errors import ConfError


if TYPE_CHECKING:
    from pathlib import Path


#: 一律拒绝的分隔符：``/`` 是允许的（多文件路径段），``\\`` 不是。
_SEPARATORS = ("/", "\\")

#: 盘符形态（``C:``）至少两个字符
_DRIVE_LETTER_LENGTH = 2


def _reject(what: str, why: str) -> NoReturn:
    raise ConfError(f"{what}不合法（{why}）：值文件名与键内嵌路径都必须落在配置目录之内")


def file_name_stem(name: str) -> str:
    """校验单文件的文件名主干，返回它本身。

    ``settings`` 这样的**纯文件名**才合法：不含分隔符、不是 ``.`` / ``..``、
    不带盘符、不含 NUL。名字后面由 :func:`values_path` 统一补后缀。
    """
    if not name:
        _reject(f"文件名 {name!r}", "空字符串")
    if "\x00" in name:
        _reject(f"文件名 {name!r}", "含 NUL")
    if any(sep in name for sep in _SEPARATORS):
        _reject(f"文件名 {name!r}", "含路径分隔符")
    if name in (".", ".."):
        _reject(f"文件名 {name!r}", "是目录分量")
    if ":" in name:
        _reject(f"文件名 {name!r}", "含盘符分隔符或键内嵌路径的冒号")
    return name


def relative_parts(path_part: str) -> tuple[str, ...]:
    r"""校验多文件的路径段（``app/conf/net``），返回它的分量。

    只走 ``/``：``\\`` 一律拒绝，这样同一个键在 Windows 与 POSIX 上解析结果一致，
    不会出现「本机合法、CI 上写穿了」的差异。
    """
    if not path_part:
        _reject("键内嵌路径 ''", "空字符串")
    if "\x00" in path_part:
        _reject(f"键内嵌路径 {path_part!r}", "含 NUL")
    if "\\" in path_part:
        _reject(f"键内嵌路径 {path_part!r}", "含 Windows 分隔符")
    if path_part.startswith("/"):
        _reject(f"键内嵌路径 {path_part!r}", "是绝对路径")
    if len(path_part) >= _DRIVE_LETTER_LENGTH and path_part[1] == ":":  # pragma: no cover
        _reject(f"键内嵌路径 {path_part!r}", "带盘符")

    # 先按**原文**切：``PurePosixPath`` 会把 ``a//b`` 与 ``./a`` 归一掉，那样就漏检了。
    for part in path_part.split("/"):
        if part in ("", ".", ".."):
            _reject(f"键内嵌路径 {path_part!r}", f"含目录分量 {part!r}")

    pure = PurePosixPath(path_part)
    if pure.is_absolute():  # pragma: no cover - 上面已经挡了开头的 '/'
        _reject(f"键内嵌路径 {path_part!r}", "是绝对路径")
    return pure.parts


def values_path(home: Path, path_part: str, suffix: str) -> Path:
    """把「配置目录 + 路径段 + 后缀」拼成值文件路径，并验证包含性。

    ``path_part`` 为纯文件名（单文件）或相对路径（多文件）。最后一段补 ``suffix``：
    ``app/conf/net`` + ``.json`` ⇒ ``<home>/app/conf/net.json``。

    第 5 条规则在**解析之后**判：``home`` 自身可能是个符号链接（macOS 的 ``/tmp``
    就是），所以要拿解析过的两边比；已经存在的符号链接指向外侧时，``resolve()``
    会把它展开成越界的真实路径，于是同样被拒。
    """
    parts = relative_parts(path_part) if "/" in path_part else (file_name_stem(path_part),)
    target = home.joinpath(*parts)
    target = target.with_name(target.name + suffix)

    base = home.resolve()
    resolved = target.resolve()
    if resolved != base and not resolved.is_relative_to(base):
        _reject(f"值文件路径 {path_part!r}", "解析后越出配置目录")
    return target
