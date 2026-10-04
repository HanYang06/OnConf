# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""强制日志与审计（DESIGN §20 / §21）。

## 一条记录，两种渲染

记录本身只有一种，**渲染分成两种**（§21.5 约束 3）：

* **终端**（``log="stderr"`` / ``"stdout"``）：``HH:MM:SS.mmm`` + **弹性制表位对齐**，
  长文本列截断成 ``…``；
* **文件**（``audit=True`` 的 ``<home>/audit.log``，或 ``log=<路径>``）：完整日期 +
  ``key=value`` 紧凑形态，**永不截断** —— 文件那一份必须无损。

两者同源，所以不会出现「日志文件与终端说的不是一回事」。

## 四个级别

``[R]`` 读 / ``[W]`` 写（含 ``op=``）/ ``[C]`` 值真的变了（``old → new``）/ ``[E]`` 失败。

* **写全量、永不聚合**：每条对账动作一行，``op`` 取 fill / overwrite / clean /
  register / update_meta / skip / noop（§20.2 的 ``skip`` 尤其重要：值不一致但尊重
  文件、**想改没改**，不记它用户会以为声明没生效）；
* **读按事务去重聚合**：同一事务内重复读同一个键合并成一行 ``n=<次数>``（§20.1）。
  循环里 ``conf("x")`` 一万次只会留下一行；
* 读的记录**不立即输出**，而是攒在事务里等下一个提交点（写提交 / ``flush()`` /
  ``sync()`` / 进程退出）—— 这正是 §21.2 说的「批次本来就存在，批次内对齐因此免费」。
  代价要写明：纯读的程序在退出前看不到自己的日志行。

## 谁记账

**谁真正动了配置目录，谁记账。** 经 IPC 的请求由写者执行，所以由写者记 ——
但记录里的 ``pid`` / ``id=``（身份）/ ``at=``（调用点）仍然是**发起方**的：
调用点在客户端抓（写时一帧 ``sys._getframe``，§20.3），随声明一起过线。

客户端也会在**自己的终端**上补一份（写者把这一批记录回传），所以每个进程都看得见
自己发起的操作；**审计文件只由执行点写**，因此不会两个进程往同一个文件里交错。

## 不变量

* 日志的字段是**白名单**，不是「把整个值对象 dump 出去」；
* 审计文件**只追加不重写**（``O_APPEND``，0600），超过 ``AUDIT_MAX_BYTES`` 才按
  时间戳轮转成 ``audit-<时间戳>.log``；
* 日志写出失败**不阻断配置读写** —— 唯一的例外是审计文件：它的失败抛
  :class:`~onconf.errors.ConfError`（审计缺席不是「少看几行」）。
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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._core import MISSING, NO_VALUE
from .errors import ConfError


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import TextIO


#: 四个级别（§20.5：用大写 —— 视觉锚点、``grep '^\[W\]'`` 精确）
LEVEL_READ = "R"
LEVEL_WRITE = "W"
LEVEL_CHANGE = "C"
LEVEL_ERROR = "E"

#: 审计文件名（相对配置目录）
AUDIT_NAME = "audit.log"

#: 审计文件轮转阈值（字节）。只由写者轮转，所以不需要跨进程协调。
AUDIT_MAX_BYTES = 1 << 20

#: 日志去向：终端（stderr / stdout）或一个文件路径
TERMINAL_STDERR = "stderr"
TERMINAL_STDOUT = "stdout"

#: 弹性制表位的列间距（显示宽度，§21.1）
_GUTTER = 2

#: 终端渲染里「长文本列」的上限（显示宽度）。文件那一份永不截断（§21.5 约束 1）
_MAX_CELL = 48

#: 可以截断的列（键名、文件名、时间、事务号**不截断**，§21.5 约束 2）
_CLIPPABLE = ("data=", "old=", "new=", "msg=", "reason=")

#: ANSI 颜色码是**零宽**的，算宽度前必须先剥掉（§21.3）
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

#: 抓调用点时最多往上找几帧，避免病态栈把热路径拖慢
_MAX_FRAMES = 8

_PACKAGE_DIR = Path(__file__).resolve().parent
_PACKAGE_PREFIX = os.path.normcase(str(_PACKAGE_DIR)) + os.sep


# --------------------------------------------------------------------------- #
# 显示宽度：必须用显示宽度，不能用 len()（§21.3）
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
class Origin:
    """一条记录的**发起方**：pid + 可选身份（§20.3）。"""

    pid: int = 0
    identity: str = ""


@dataclass(frozen=True)
class Record:
    """一条日志 / 审计记录。**纯数据**，可以直接过 IPC 回传给发起方。"""

    level: str
    txn: int
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


@dataclass(frozen=True)
class Reply:
    """一次就地执行的应答：值 + 这一批记录 + 「是不是别的进程替我干的」。"""

    value: Any = None
    records: tuple[Record, ...] = ()
    remote: bool = False


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
    """抓**调用点**（``app/config.py:12``，§20.3）。

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
    """时间戳：终端 ``HH:MM:SS.mmm``，文件带完整日期（审计要跨天查，§20.6）。"""
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


def _head_cells(record: Record, *, full_date: bool) -> list[str]:
    """标识这一行的前缀：级别、时间、事务、键、文件，以及可选的 id / origin / op。"""
    cells = [
        f"[{record.level}]-[{_stamp(full_date=full_date)}]-[txn={record.txn} pid={record.pid}]",
        f"item={record.item or '-'}",
        f"file={record.file or '-'}",
    ]
    if record.identity:
        cells.append(f"id={record.identity}")
    if record.origin:
        cells.append(f"origin={record.origin}")
    if record.op:
        cells.append(f"op={record.op}")
    return cells


def _value_cells(record: Record) -> list[str]:
    """值那一组：``[C]`` 永远写 old / new（缺席记 ``-``），其余按有没有写。"""
    if record.level == LEVEL_CHANGE:
        # ``[C]`` 的要点就是「从什么变成什么」（§20.6）。
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
        cells.append(f"at={record.at}")
    if record.err:
        cells.append(f"err={record.err}")
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
    """弹性制表位的落地：列宽 = 该批最宽的那一格，且**只增不减**（§21.2）。"""
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
    """文件形态：``key=value`` 紧凑、不补空格、**永不截断**（§21.5 约束 1）。"""
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


# --------------------------------------------------------------------------- #
# 审计器
# --------------------------------------------------------------------------- #


def _rotate_if_needed(path: Path) -> None:
    """审计文件超过阈值就按时间戳轮转。**只追加、不重写**（§20.4）。"""
    try:
        if path.stat().st_size < AUDIT_MAX_BYTES:
            return
    except FileNotFoundError:
        return
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    target = path.with_name(f"{path.stem}-{stamp}{path.suffix}")
    suffix = 1
    while target.exists():
        suffix += 1
        target = path.with_name(f"{path.stem}-{stamp}-{suffix}{path.suffix}")
    path.replace(target)


def _append_file(path: Path, text: str, *, rotate: bool) -> None:
    """追加写入（``O_APPEND`` + 0600）。一次 ``os.write``，不重写、不截断。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if rotate:
        _rotate_if_needed(path)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(handle, text.encode("utf-8"))
    finally:
        os.close(handle)


class AuditLog:
    """一个引擎的日志 / 审计收口点。

    线程安全：写者的会话线程与主线程都会进来，所以缓冲、事务号与列宽都在锁里。
    """

    def __init__(
        self,
        *,
        audit_path: Path | None,
        log: str | os.PathLike[str] = TERMINAL_STDERR,
        identity: str = "",
    ) -> None:
        self.audit_path = audit_path
        self.identity = identity
        #: 当前记录的发起方。执行远端请求前由 :class:`~onconf._engine.Engine` 临时改写，
        #: 所以审计里的 ``pid`` / ``id=`` 是**发起方**的，不是执行点的。
        self.origin = Origin(pid=os.getpid(), identity=identity)
        self._log = os.fspath(log)
        self._lock = threading.Lock()
        self._pending: list[Record] = []
        self._reads: dict[tuple[str, str], int] = {}
        self._txn: int | None = None
        self._next_txn = 1
        self._widths: list[int] = []
        self._op: list[Record] | None = None

    # ------------------------------------------------------------------ 记录

    def read(self, *, item: str, file: str, source: str, data: Any) -> Record:
        """记一次读。同一事务内重复读同一个键会**合并**成一行 ``n=<次数>``。"""
        return self._record(
            Record(level=LEVEL_READ, txn=0, pid=0, item=item, file=file, origin=source, data=data)
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
        """记一条对账动作。**写全量，不聚合**（§20.1）。"""
        return self._record(
            Record(
                level=LEVEL_WRITE,
                txn=0,
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
        """记一次**真正的值变化**：``old → new``（§20.2 缺的第一样东西）。"""
        return self._record(
            Record(level=LEVEL_CHANGE, txn=0, pid=0, item=item, file=file, old=old, new=new, at=at)
        )

    def failed(
        self, *, item: str, file: str, err: str, message: str = "", at: str = ""
    ) -> Record:
        """记一次失败。**失败必须留痕**，否则审计只记录成功的历史（§20.2）。"""
        return self._record(
            Record(
                level=LEVEL_ERROR,
                txn=0,
                pid=0,
                item=item,
                file=file,
                err=err,
                message=message,
                at=at,
            )
        )

    # ------------------------------------------------------ 事务 / 操作边界

    def begin_op(self) -> None:
        """开一个操作作用域：这期间产生的记录会被 :meth:`end_op` 一次性取走。"""
        with self._lock:
            self._op = []

    def end_op(self) -> tuple[Record, ...]:
        """收一个操作作用域：返回**这次操作自己产生**的记录（不含别人的）。"""
        with self._lock:
            records = tuple(self._op) if self._op is not None else ()
            self._op = None
            return records

    def close_txn(self) -> tuple[Record, ...]:
        """收口一个事务：输出并清空攒着的记录，下一个事务拿新的事务号。"""
        with self._lock:
            records = tuple(self._pending)
            self._pending.clear()
            self._reads.clear()
            self._txn = None
            if records:
                self._emit_log(records)
                self._emit_audit_file(records)
            return records

    def render_remote(self, records: Iterable[Record]) -> None:
        """把**别的进程**执行出来的记录补到自己终端上（审计文件不重复写）。

        这里也要拿锁：客户端的多个线程可能同时在收自己那一份，而渲染会推进列宽。
        """
        batch = tuple(records)
        if not batch:
            return
        with self._lock:
            self._emit_log(batch)

    # ------------------------------------------------------------------ 内部

    def _record(self, record: Record) -> Record:
        with self._lock:
            stamped = self._stamp(record)
            if stamped.level == LEVEL_READ:
                key = (stamped.item, stamped.file)
                index = self._reads.get(key)
                if index is not None:
                    merged = replace(self._pending[index], count=self._pending[index].count + 1)
                    self._pending[index] = merged
                    self._remember(merged)
                    return merged
                self._reads[key] = len(self._pending)
            self._pending.append(stamped)
            self._remember(stamped)
            return stamped

    def _remember(self, record: Record) -> None:
        if self._op is not None:
            self._op.append(record)

    def _stamp(self, record: Record) -> Record:
        if self._txn is None:
            self._txn = self._next_txn
            self._next_txn += 1
        return replace(record, txn=self._txn, pid=self.origin.pid, identity=self.origin.identity)

    def _emit_log(self, records: Sequence[Record]) -> None:
        """人读的那一路：终端对齐（或日志文件紧凑）。它失败不阻断配置读写。"""
        if self._log == TERMINAL_STDERR:
            self._write_stream(sys.stderr, _render_terminal(records, self._widths))
        elif self._log == TERMINAL_STDOUT:
            self._write_stream(sys.stdout, _render_terminal(records, self._widths))
        else:
            with contextlib.suppress(OSError):
                _append_file(
                    Path(self._log), _render_compact(records, full_date=True), rotate=False
                )

    def _emit_audit_file(self, records: Sequence[Record]) -> None:
        """机读的那一路：append-only 审计文件。**它失败是有代价的，所以抛出来。**"""
        if self.audit_path is None:
            return
        try:
            _append_file(
                self.audit_path, _render_compact(records, full_date=True), rotate=True
            )
        except OSError as exc:
            raise ConfError(f"审计文件写入失败：{self.audit_path}（{exc}）") from exc

    @staticmethod
    def _write_stream(stream: TextIO | None, text: str) -> None:
        if stream is None:  # pragma: no cover - 解释器收尾时 stderr 可能已经没了
            return
        with contextlib.suppress(OSError, ValueError):
            stream.write(text)
            stream.flush()
