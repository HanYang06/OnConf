# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""日志：**一份记录流，两个出口**。

## 一个东西，两个出口

「审计」不是另一件东西 —— 落盘的那一份就是审计。记录只有一种，出口有两个：

* **文件**（缺省 ``<home>/audit.log``，落点由 ``log_path`` 给）：完整日期 + 紧凑
  ``key=value``，**永不截断**。这个出口**没有开关**，引擎实例一旦跑起来就写；
* **控制台**（``stderr``）：``HH:MM:SS.mmm`` + **弹性制表位对齐**，长文本列截断成
  ``…``；``log_console=False`` 关掉它。

两者同源，所以不会出现「日志文件与终端说的不是一回事」。

## 五个级别：配置事实四个，加一行启动

``[Read]`` 读 / ``[Write]`` 写（含 ``op=``）/ ``[Change]`` 值真的变了（``old → new``）/
``[Error]`` 失败，以及 ``[Start]`` 引擎起来了（pid / ``id=`` / 值文件）。

* **写与启动全量、永不聚合**：每条对账动作一行，``op`` 取 fill / register /
  update_meta / skip / noop；
* **读按事务去重聚合**：同一事务内重复读同一个键合并成一行 ``n=<次数>``。
  循环里 ``conf("x")`` 一万次只会留下一行；
* 读的记录**不立即输出**，而是攒在事务里等下一个提交点（写提交 / ``flush()`` /
  ``sync()`` / 进程退出）—— 这正是「批次本来就存在，批次内对齐因此免费」。
  代价要写明：纯读的程序在退出前看不到自己的日志行。``[Start]`` 立即输出
  （它描述的是「此刻这个进程在干什么」，攒着就失去意义了）。

## 谁记账

**谁发起谁记账**：这里没有第二个执行点，所以 ``pid`` / ``id=``（身份）/ ``at=``
（调用点）都取自本进程；调用点在写时抓一帧（``sys._getframe``）。

审计文件因此**可能被多个进程同时追加** —— 那是预期的，不是缺陷：``O_APPEND``
保证每一批以追加方式落盘，每行自带 ``txn=… pid=…``，解析者据此分辨批次。

## 三个口子

默认全是「不做」—— 不轮转、不脱敏、不编码：

* ``rotate``：拿到**当前落点**与已写字节数，返回**这一批写到哪个文件**。轮转是
  「换落点」而不是「搬文件」：引擎**绝不 rename 已经在写的文件**（改名会让已经写下
  的审计在别的进程眼里凭空消失）；
* ``scrub``：一条记录进、一条记录出，落盘前脱敏；
* ``encode``：渲染后的字节进、落盘字节出，加密 / 压缩都行。密钥由调用方给，
  引擎不生成、不推导、不保管。

## 不变量

* 日志的字段是**白名单**，不是「把整个值对象 dump 出去」；
* 审计文件**只追加不重写**（``O_APPEND``，0600），**父目录不由它创建** ——
  建 ``<home>`` 属于值文件写入那条路，写不出去就当场报错；
* 日志写出失败**不阻断配置读写**（连渲染失败都不阻断）—— 唯一的例外是审计文件：
  它的失败抛 :class:`~onconf.errors.ConfError`（审计缺席不是「少看几行」）。
  唯一的例外之例外是 ``[Start]`` 这一行信息性的记录：它是「顺带说一下」，
  不该拦住第一次 ``conf()``；
* ``import onconf`` **不导入 rich**：它只在 TTY 的终端渲染分支里惰性导入，
  非 TTY 走纯文本、逐字稳定。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._core import MISSING, NO_VALUE
from .errors import ConfError


if TYPE_CHECKING:
    from typing import TextIO


#: 四个**配置事实**级别（用完整词：一眼看得懂比少敲几个字母重要）：
#: 一眼看得懂比少敲几个字母重要，``grep '^\[Write\]'`` 一样精确。
LEVEL_READ = "Read"
LEVEL_WRITE = "Write"
LEVEL_CHANGE = "Change"
LEVEL_ERROR = "Error"

#: 进程自己的生命周期：现在只有启动这一件事值得记（引擎起来了）。
LEVEL_START = "Start"

#: 审计文件的缺省名（相对配置目录）。落点由 ``log_path`` 决定。
LOG_NAME = "audit.log"

#: 轮转策略：``(当前落点, 已写字节数) -> 这一批写到哪个文件``。
#: 返回同一个路径就是「不轮转」。**换落点，不是搬文件**。
RotateHook = Callable[[Path, int], Path]

#: 脱敏钩子：``记录 -> 记录``。落盘前改掉任意字段。
ScrubHook = Callable[["Record"], "Record"]

#: 落盘编码钩子：``渲染后的字节 -> 落盘字节``。
EncodeHook = Callable[[bytes], bytes]

#: 弹性制表位的列间距（显示宽度，）
_GUTTER = 2

#: 终端渲染里「长文本列」的上限（显示宽度）。文件那一份永不截断
_MAX_CELL = 48

#: 可以截断的列（键名、文件名、时间、事务号**不截断**）
_CLIPPABLE = ("data=", "old=", "new=", "msg=", "reason=")

#: ANSI 颜色码是**零宽**的，算宽度前必须先剥掉
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

#: 级别 → rich 样式。**只给级别那一格上色**，其余保持默认前景色：
#: 上色是给人看的，落盘那一份一个字节都不受影响。
_LEVEL_STYLE: dict[str, str] = {
    LEVEL_READ: "dim",
    LEVEL_WRITE: "cyan",
    LEVEL_CHANGE: "green",
    LEVEL_ERROR: "bold red",
    LEVEL_START: "bold",
}

#: 抓调用点时最多往上找几帧，避免病态栈把热路径拖慢
_MAX_FRAMES = 8

_PACKAGE_DIR = Path(__file__).resolve().parent
_PACKAGE_PREFIX = os.path.normcase(str(_PACKAGE_DIR)) + os.sep


# --------------------------------------------------------------------------- #
# 显示宽度：必须用显示宽度，不能用 len()
# --------------------------------------------------------------------------- #


def strip_ansi(text: str) -> str:
    """剥掉 ANSI 颜色码。算显示宽度之前必须做这一步，否则一上色列就歪。"""
    return _ANSI.sub("", text)


def _char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def cell_len(text: str) -> int:
    """字符串的**显示宽度**（全角算 2，组合字符算 0，ANSI 不算）。

    ``len("配置")`` 是 2，显示宽度是 4 —— 用 ``len()`` 补空格，中文那几行会偏列。
    """
    return sum(_char_width(char) for char in strip_ansi(text))


def _truncate(text: str, limit: int) -> str:
    """按显示宽度截断并加 ``…``（只在终端渲染层调用）。"""
    if cell_len(text) <= limit:
        return text
    kept: list[str] = []
    used = 0
    for char in strip_ansi(text):
        width = _char_width(char)
        if used + width > limit - 1:
            break
        kept.append(char)
        used += width
    return "".join(kept) + "…"


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Record:
    """一条日志 / 审计记录。**纯数据**。

    ``txn`` 为 ``None`` 表示「登记时再分配」；显式写 ``0`` 表示**不属于任何配置事务**
    （``[Start]`` 这类生命周期记录）—— 生命周期不该被算进某一批配置变更里。
    """

    level: str
    txn: int | None
    pid: int
    item: str
    file: str
    identity: str = ""
    op: str = ""
    origin: str = ""
    data: Any = MISSING
    old: Any = MISSING
    new: Any = MISSING
    at: str = ""
    err: str = ""
    message: str = ""
    count: int = 1
    reason: str = ""


#: 内建异常按**精确类名**单独定名：它们去掉 ``Error`` 之后太含糊（``TypeError`` → ``type``）。
#: 用的是精确匹配，所以 ``YamlFlatRequiredError`` 这类子类仍走自己的名字。
_PLAIN_KINDS: dict[str, str] = {
    "TypeError": "type-error",
    "ValueError": "value-error",
    "KeyError": "key-error",
    "OSError": "os-error",
}


def error_kind(exc: BaseException) -> str:
    """异常类名 → ``err=`` 的 kebab-case。

    ``KeyNotRegisteredError`` → ``key-not-registered``；``TypeError`` → ``type-error``；
    连续大写按一个词处理（``JSONDecodeError`` → ``json-decode``，不是 ``j-s-o-n-decode``）。
    """
    name = type(exc).__name__
    if name in _PLAIN_KINDS:
        return _PLAIN_KINDS[name]
    kebab = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "-", name)
    return kebab.lower().removesuffix("-error")


def call_site(max_frames: int = _MAX_FRAMES) -> str:
    """抓**调用点**（``app/config.py:12``，）。

    抓一帧比 ``inspect.stack()`` 便宜两个数量级（约 1 µs vs 几百 µs）。
    这里自动跳过本包内部的帧，所以「经 ``conf()`` 调用」与「直接调 ``Engine``」
    两种写法都能指回用户的真实位置。抓不到就返回空串（记录里那一列省略）。
    """
    frame = sys._getframe(1)  # noqa: SLF001 - 便宜两个数量级，这就是选它的全部理由
    for _ in range(max_frames):
        # 走 getattr 是为了让「栈顶之后没有帧了」这句留在**运行时**：直接写
        # ``frame.f_back`` 会被 mypy 判成永不为 None，于是这条判断成了不可达代码。
        parent = getattr(frame, "f_back", None)
        if parent is None:  # pragma: no cover - 栈顶之后没有帧，正常调用走不到
            return ""
        frame = parent
        filename = frame.f_code.co_filename
        if not os.path.normcase(filename).startswith(_PACKAGE_PREFIX):
            return f"{filename}:{frame.f_lineno}"
    return ""  # pragma: no cover - 8 帧都还在本包内部，正常调用走不到


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #


def _stamp(*, full_date: bool) -> str:
    """时间戳：终端 ``HH:MM:SS.mmm``，文件带完整日期（审计要跨天查，）。"""
    now = time.time()
    milliseconds = int(now * 1000) % 1000
    pattern = "%Y-%m-%dT%H:%M:%S" if full_date else "%H:%M:%S"
    return f"{time.strftime(pattern, time.localtime(now))}.{milliseconds:03d}"


def _fmt(value: Any) -> str:
    """值的紧凑写法：``-`` 表示缺席（``MISSING`` / ``NO_VALUE``），其余走 JSON。"""
    if value is MISSING or value is NO_VALUE:
        return "-"
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        if value == "" or any(char.isspace() for char in value):
            return json.dumps(value, ensure_ascii=False)
        return value
    return json.dumps(value, ensure_ascii=False, default=repr)


def _one_line(text: str) -> str:
    """把 CR / LF 折成可见转义。

    键名与身份是调用方给的：里面塞一个换行就能**伪造出额外的审计行**（一行变三行，
    而且看起来跟真的一模一样）。所以这几个字段必须压成一行。
    """
    return text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\r")


def _head_cells(record: Record, *, full_date: bool) -> list[str]:
    """标识这一行的前缀：级别、时间、事务、键、文件，以及可选的 id / origin / op。"""
    cells = [
        f"[{record.level}]-[{_stamp(full_date=full_date)}]-[txn={record.txn} pid={record.pid}]",
        f"item={_one_line(record.item) or '-'}",
        f"file={_one_line(record.file) or '-'}",
    ]
    if record.identity:
        cells.append(f"id={_one_line(record.identity)}")
    if record.origin:
        cells.append(f"origin={_one_line(record.origin)}")
    if record.op:
        cells.append(f"op={_one_line(record.op)}")
    return cells


def _value_cells(record: Record) -> list[str]:
    """值那一组：``[C]`` 永远写 old / new（缺席记 ``-``），其余按有没有写。"""
    if record.level == LEVEL_CHANGE:
        # ``[C]`` 的要点就是「从什么变成什么」。
        return [f"old={_fmt(record.old)}", f"new={_fmt(record.new)}"]
    cells: list[str] = []
    if record.data is not MISSING:
        cells.append(f"data={_fmt(record.data)}")
    if record.old is not MISSING:
        cells.append(f"old={_fmt(record.old)}")
    if record.new is not MISSING:
        cells.append(f"new={_fmt(record.new)}")
    return cells


def _tail_cells(record: Record) -> list[str]:
    """尾部那一组：读计数、调用点、错误、消息、原因。"""
    cells: list[str] = []
    if record.level == LEVEL_READ:
        cells.append(f"n={record.count}")
    if record.at:
        cells.append(f"at={_one_line(record.at)}")
    if record.err:
        cells.append(f"err={_one_line(record.err)}")
    if record.message:
        cells.append(f"msg={_fmt(record.message)}")
    if record.reason:
        cells.append(f"reason={_fmt(record.reason)}")
    return cells


def _cells(record: Record, *, full_date: bool) -> list[str]:
    """一条记录 → 一串 ``key=value`` 单元格（顺序固定，便于机器解析）。"""
    return [
        *_head_cells(record, full_date=full_date),
        *_value_cells(record),
        *_tail_cells(record),
    ]


def _aligned(rows: list[list[str]], widths: list[int]) -> str:
    """弹性制表位的落地：列宽 = 该批最宽的那一格，且**只增不减**。"""
    for cells in rows:
        for index, cell in enumerate(cells[:-1]):
            while len(widths) <= index:
                widths.append(0)
            widths[index] = max(widths[index], cell_len(cell))
    lines: list[str] = []
    for cells in rows:
        parts: list[str] = []
        for index, cell in enumerate(cells):
            if index == len(cells) - 1:
                parts.append(cell)
                continue
            padding = widths[index] + _GUTTER - cell_len(cell)
            parts.append(cell + " " * max(padding, 1))
        lines.append("".join(parts))
    return "\n".join(lines) + "\n"


def _render_compact(records: Sequence[Record], *, full_date: bool) -> str:
    """文件形态：``key=value`` 紧凑、不补空格、**永不截断**。"""
    return "".join(" ".join(_cells(record, full_date=full_date)) + "\n" for record in records)


def _render_terminal(records: Sequence[Record], widths: list[int]) -> str:
    """终端形态：长文本列截断 + 弹性制表位对齐。"""
    rows = []
    for record in records:
        cells = _cells(record, full_date=False)
        rows.append(
            [_truncate(cell, _MAX_CELL) if cell.startswith(_CLIPPABLE) else cell for cell in cells]
        )
    return _aligned(rows, widths)


def _is_tty(stream: TextIO) -> bool:
    """终端判定：非 TTY 一律走纯文本，**绝不让 ANSI 漏进管道与 CI 日志**。"""
    return bool(stream.isatty())


def _rich_write(lines: Sequence[str]) -> None:
    """TTY 上把**已经排好**的行交给 rich 上色。

    rich 只负责着色：宽度、截断与对齐仍然是上面那套（定宽表格一旦自动折行，
    对齐就毁了）。导入点在这里 —— ``import onconf`` 与文件那一份都不碰 rich。
    """
    from rich.console import Console  # noqa: PLC0415 - 惰性导入正是这一条的全部要点
    from rich.text import Text  # noqa: PLC0415 - 同上

    console = Console(file=sys.stderr, highlight=False, soft_wrap=True, force_terminal=True)
    for line in lines:
        token, separator, rest = line.partition("]-[")
        text = Text()
        text.append(token, style=_LEVEL_STYLE.get(token.strip("[]"), ""))
        text.append(separator + rest)
        console.print(text)


# --------------------------------------------------------------------------- #
# 审计器
# --------------------------------------------------------------------------- #


def _append_file(path: Path, data: bytes) -> None:
    """追加写入（``O_APPEND`` + 0600）。不重写、不截断、**不创建父目录**。

    父目录的创建归值文件那条路：审计不该成为「凭空造出一棵目录树」的触发者。
    写不出去就当场报错，由调用方转成 :class:`~onconf.errors.ConfError`。

    ``os.write`` **允许短写**（磁盘满、``RLIMIT_FSIZE``）：不看返回值就会把一批记录
    截在一个记录中间，而且一声不吭。所以这里写到写完为止。
    """
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        data_view = memoryview(data)
        while data_view:
            written = os.write(handle, data_view)
            if written <= 0:  # pragma: no cover - 正常文件系统不会返回 0；防死循环
                raise OSError(f"写入没有进展：{path}")
            data_view = data_view[written:]
    finally:
        os.close(handle)


class Log:
    """一个引擎的日志收口点：**一份记录流，两个出口**。

    线程安全：一个进程里的多个线程都可能进来，所以缓冲、事务号与列宽都在锁里。
    """

    def __init__(
        self,
        *,
        path: Path,
        console: bool = True,
        rotate: RotateHook | None = None,
        scrub: ScrubHook | None = None,
        encode: EncodeHook | None = None,
        identity: str = "",
    ) -> None:
        #: 文件出口的当前落点。轮转钩子只改它，引擎从不搬动已有文件。
        self.path = path
        self.identity = identity
        self._console = console
        self._rotate = rotate
        self._scrub = scrub
        self._encode = encode
        self._lock = threading.Lock()
        self._pending: list[Record] = []
        self._reads: dict[tuple[str, str], int] = {}
        self._txn: int | None = None
        self._next_txn = 1
        self._widths: list[int] = []

    # ------------------------------------------------------------------ 记录

    def read(self, *, item: str, file: str, source: str, data: Any) -> Record:
        """记一次读。同一事务内重复读同一个键会**合并**成一行 ``n=<次数>``。"""
        return self._record(
            Record(
                level=LEVEL_READ, txn=None, pid=0, item=item, file=file, origin=source, data=data
            )
        )

    def wrote(
        self,
        *,
        item: str,
        file: str,
        op: str,
        data: Any = MISSING,
        old: Any = MISSING,
        new: Any = MISSING,
        reason: str = "",
        at: str = "",
    ) -> Record:
        """记一条对账动作。**写全量，不聚合**。"""
        return self._record(
            Record(
                level=LEVEL_WRITE,
                txn=None,
                pid=0,
                item=item,
                file=file,
                op=op,
                data=data,
                old=old,
                new=new,
                reason=reason,
                at=at,
            )
        )

    def changed(self, *, item: str, file: str, old: Any, new: Any, at: str = "") -> Record:
        """记一次**真正的值变化**：``old → new``。"""
        return self._record(
            Record(
                level=LEVEL_CHANGE, txn=None, pid=0, item=item, file=file, old=old, new=new, at=at
            )
        )

    def failed(self, *, item: str, file: str, err: str, message: str = "", at: str = "") -> Record:
        """记一次失败。**失败必须留痕**，否则审计只记录成功的历史。"""
        return self._record(
            Record(
                level=LEVEL_ERROR,
                txn=None,
                pid=0,
                item=item,
                file=file,
                err=err,
                message=message,
                at=at,
            )
        )

    # ------------------------------------------------------------ 生命周期

    def started(self, *, file: str) -> Record:
        """记一次「**引擎起来了**」：生命周期里最先出现的那一行。

        它只带 pid / ``id=`` / 值文件名 —— 「谁在什么时候开始用这个配置目录」。
        """
        return self._record(Record(level=LEVEL_START, txn=0, pid=0, item="", file=file))

    # ------------------------------------------------------------ 事务边界

    def close_txn(self) -> tuple[Record, ...]:
        """收口一个事务：输出攒着的记录，下一个事务拿新的事务号。

        审计文件写失败**没有重试**：缓冲已经清空，这一批只留在终端那一份里。
        """
        with self._lock:
            records = tuple(self._pending)
            self._pending.clear()
            self._reads.clear()
            self._txn = None
            emitted = self._scrubbed(records)
            if emitted:
                self._emit(emitted)
            return emitted

    # ------------------------------------------------------------------ 内部

    def _scrubbed(self, records: Sequence[Record]) -> tuple[Record, ...]:
        """把脱敏钩子套在这一批上。没有钩子就是原样 —— 默认不做任何脱敏。"""
        if self._scrub is None:
            return tuple(records)
        return tuple(self._scrub(record) for record in records)

    def _target(self) -> Path:
        """这一批写到哪个文件。**换落点，不搬文件**：引擎从不 rename 已有文件。"""
        if self._rotate is None:
            return self.path
        size = 0
        with contextlib.suppress(FileNotFoundError):
            size = self.path.stat().st_size
        self.path = self._rotate(self.path, size)
        return self.path

    def _record(self, record: Record) -> Record:
        with self._lock:
            stamped = self._stamp(record)
            if stamped.level == LEVEL_READ:
                key = (stamped.item, stamped.file)
                index = self._reads.get(key)
                if index is not None:
                    merged = replace(self._pending[index], count=self._pending[index].count + 1)
                    self._pending[index] = merged
                    return merged
                self._reads[key] = len(self._pending)
            self._pending.append(stamped)
            return stamped

    def _stamp(self, record: Record) -> Record:
        """补上进程身份；``txn`` 只在记录没带的时候分配。

        生命周期记录（``[Start]``）显式带 ``txn=0``：它不属于任何一个配置事务，
        硬塞一个号只会让「哪一批变更」这件事变得含糊。
        """
        txn = record.txn
        if txn is None:
            if self._txn is None:
                self._txn = self._next_txn
                self._next_txn += 1
            txn = self._txn
        return replace(record, txn=txn, pid=os.getpid(), identity=self.identity)

    def _emit(self, records: Sequence[Record]) -> None:
        """两路输出**互不牵连**：审计文件失败要抛，但不能让终端那一份跟着丢。

        所以：先写审计文件（失败先记下），再写日志（自己吞掉 IO 错），最后才把审计的
        失败抛出去。反过来的话，一个坏掉的日志去向会顺手毁掉审计那一批。
        """
        failure: ConfError | None = None
        try:
            self._emit_file(records)
        except ConfError as exc:
            failure = exc
        self._emit_console(records)
        if failure is not None:
            raise failure

    def _emit_console(self, records: Sequence[Record]) -> None:
        """人读的那一路：终端对齐（TTY 上再着色）。**它失败不阻断配置读写。**

        整段都吞：不只是 IO —— 值里有什么东西让**渲染**炸了（``__repr__`` 抛、
        循环引用……）也不该让一次 ``conf()`` 失败。日志是配套设施，不是事务的一部分；
        审计那一路（另一份）才是「写不出去要出声」的那个。
        """
        with contextlib.suppress(Exception):
            if not self._console:
                return
            text = _render_terminal(records, self._widths)
            if _is_tty(sys.stderr):
                _rich_write(text.splitlines())
            else:
                self._write_stream(sys.stderr, text)

    def _emit_file(self, records: Sequence[Record]) -> None:
        """机读的那一路：append-only 审计文件。**它失败是有代价的，所以抛出来。**"""
        try:
            target = self._target()
            _append_file(target, self._encoded(_render_compact(records, full_date=True)))
        except OSError as exc:
            raise ConfError(f"审计文件写入失败：{self.path}（{exc}）") from exc

    def _encoded(self, text: str) -> bytes:
        """渲染结果 → 落盘字节。没有编码钩子就是 UTF-8。"""
        data = text.encode("utf-8")
        return data if self._encode is None else self._encode(data)

    @staticmethod
    def _write_stream(stream: TextIO | None, text: str) -> None:
        if stream is None:  # pragma: no cover - 解释器收尾时 stderr 可能已经没了
            return
        with contextlib.suppress(OSError, ValueError):
            stream.write(text)
            stream.flush()
