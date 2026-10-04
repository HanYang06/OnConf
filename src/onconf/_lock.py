# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""跨进程排他锁：用**操作系统**的锁，不用自制锁文件。

为什么必须是 OS 锁：**进程崩溃时操作系统会自动释放它** —— 「死锁文件」这个经典
难题就此消失，不需要心跳、不需要超时判定、不需要「谁的 PID 还活着」的探测。
自制的 ``O_CREAT|O_EXCL`` 锁文件做不到这一点：进程一崩，锁文件留在那儿，
下一个进程要么卡死、要么得去猜它是不是陈旧的。那是在重新发明一个更差的轮子。

实现按平台分派，但**对调用方是一套 API**：Windows 走 ``msvcrt.locking``，
其它平台走 ``fcntl.flock``，两者都满足「进程退出即释放」。

平台分派刻意**不用 ``sys.platform`` 分支**：mypy 会按当前平台把另一支判成不可达
（``warn_unreachable``），于是那一支里 ``import`` 的名字就成了「未定义」。
改用 ``os.name`` 加动态导入 —— 运行时行为完全一样，静态检查也不再跟自己打架。
"""

from __future__ import annotations

import contextlib
import importlib
import os
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from .errors import ConfError


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: 拿不到锁时的重试间隔（秒）
_POLL = 0.01

#: ``msvcrt.locking`` 要锁的字节数（锁内容无所谓，只借它做互斥）
_ONE_BYTE = 1


class LockTimeoutError(ConfError):
    """在超时时间内没拿到锁。"""


@lru_cache(maxsize=1)
def _native() -> Any:
    """平台原生的锁模块：Windows 是 ``msvcrt``，其它是 ``fcntl``。"""
    return importlib.import_module("msvcrt" if os.name == "nt" else "fcntl")


def _try_acquire(fd: int) -> bool:
    module = _native()
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            module.locking(fd, module.LK_NBLCK, _ONE_BYTE)
        else:
            module.flock(fd, module.LOCK_EX | module.LOCK_NB)
    except OSError:
        return False
    return True


def _release(fd: int) -> None:
    module = _native()
    with contextlib.suppress(OSError):  # 释放失败不该盖住真正的异常
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            module.locking(fd, module.LK_UNLCK, _ONE_BYTE)
        else:
            module.flock(fd, module.LOCK_UN)


@contextmanager
def exclusive(path: Path, *, timeout: float = 10.0) -> Iterator[None]:
    """在 ``path`` 上拿排他锁；退出上下文时释放。

    锁文件本身是空文件（不存在也行），它只是个**握手点**：
    互斥语义完全由操作系统的锁提供，跟文件里写了什么无关。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        deadline = time.monotonic() + timeout
        while not _try_acquire(fd):
            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"{timeout:g} 秒内没能拿到锁：{path}。"
                    "如果另一个进程正卡在写盘上，它会拖住你；"
                    "如果它已经崩了，操作系统会自动放锁，不会变成死锁。"
                )
            time.sleep(_POLL)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)
