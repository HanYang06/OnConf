# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引擎装配：把核心、词表、后端接成一个能用的库。

## 提交点：默认**当场落盘**，攒批窗口按需开

``flush_window`` **默认 0** —— 声明立刻落盘。这不是保守，是「文件是绝对权威」
这条一旦成立，**写入的可见性延迟就是对它的削弱**：别的进程去读那个文件时，
看不到你刚声明的东西，而多进程恰恰是本项目的目标场景之一。

而且实测支持这个默认值：稳态下词表 diff 会让对账产出**空动作**，一个字节都不写，
所以「每次声明都写」并不等于写放大。

需要攒批的是**启动期一口气声明很多键**这种突发场景，而那正是调用方自己知道的事：

.. code-block:: python

    AutoConf(home="…", flush_window=0.2)  # 攒一批再写

窗口一旦开启，落盘发生在这些提交点：**窗口到期 / 一次读 / ``sync()`` / 进程退出**。
前三个**不做规则 1**（期望集可能还不完整，），只有 ``sync()`` 与进程退出做。

## 并发：一个**专职写者**，OS 锁当安全网

一个配置目录上，**谁抢绑到端点谁就是唯一的读写者**（:mod:`onconf._owner`）。
四个公开出口（``read`` / ``declare`` / ``flush`` / ``sync``）都先问一句「我是不是
写者」：是就就地干，不是就把请求交给写者（见 :meth:`Engine._channel`）。于是磁盘上
的读改写只有一个进程在做，其余进程只是发请求。

端点这条路不通（建不出来、环境奇怪）时逐层退让，最后**退回就地做** —— 那正是
下面这套锁要顶住的场合。**正确性从来不靠 IPC 撑着**。

攒批窗口是**每个引擎自己**的：声明先在本地攒着，交出去时才走一次
``OP_COMMIT``。窗口要是挪到写者身上，客户端显式配的 ``flush_window`` 就被静默
忽略了。

写者不在了的时候，兜底仍旧是下面的老办法。

## 掉到兜底时：OS 锁 + 锁内按需重读

多进程同时提交时，每个进程在锁里**重读一遍磁盘**再对账、再原子替换。
没有这一步就会出现「A 和 B 各自基于同一份旧内容写回，后写的把先写的整段盖掉」。
重读只在文件真的变过时才发生（比 mtime + size），所以单进程连续提交不会退化成
「每次都把整篇读一遍」。

锁用的是操作系统的锁（见 :mod:`onconf._lock`），所以进程崩溃时它会被自动释放，
不会留下死锁。

## 落盘是原子的，而且不碰不该碰的字节

值文件与词表都经 :func:`_atomic_write_text`：同目录临时文件 → ``fsync`` →
``os.replace``，再 ``fsync`` 父目录（POSIX）。行尾按文件原本的样子写回，所以
Windows 上不会把用户的 LF 文件偷偷改成 CRLF；已存在文件的权限位也原样保留。

## 目录约定（对齐真实产物）

::

    <home>/settings.json          值文件（用户手改）；名字由 ``file_name``、后缀由 ``file_type``
    <home>/schema/settings.json   词表（**库自己的资产**，随便重写；一份，与值文件个数无关）
    <home>/schema/settings.lock   锁的握手点（空文件；库里自己的簿记）
    <home>/schema/settings.key    写者端点的认证码（0600；库里自己的簿记）
    <home>/audit.log              审计文件（append-only；``audit=True`` 才有）

``<home>`` 由 ``home=`` 参数 / ``ONCONF_HOME`` 环境变量 / ``./conf`` 依次决定。
文件名主干由 ``file_name``（缺省 ``settings``）、后缀由 ``file_type``（缺省 **字面**
``"json"``）决定；两者都是**单值**参数，改了等于换一个值文件，必须重启。

**多文件**（``no_one_file=True``）：键里的 ``<路径>:`` 前缀决定它落在
``<home>/<路径>.<ext>`` 的哪个文件里，没有前缀的键仍落在默认文件
``<home>/<file_name>.<ext>``。词表仍然只有一份（``schema/<file_name>.json``），
每个值文件的 ``$schema`` 指针按自己的层级算出相对路径。归这个引擎管的文件 =
**默认文件 + 当前声明集引用到的路径段**；磁盘上其它值文件一个字节都不动。

## 日志与审计

日志**不可关闭**，只能改去向（``log="stderr"`` 默认 / ``"stdout"`` / 一个文件路径）；
``audit=True`` 再加一份 append-only 的 ``<home>/audit.log``。四个级别
``[R]/[W]/[C]/[E]`` 与对齐规则见 :mod:`onconf._audit`。

**记账在执行点**：谁真正动了配置目录，谁写日志。经 IPC 的请求由写者执行、由写者记，
但记录里的 ``pid`` / ``id=`` / ``at=`` 仍是**发起方**的（调用点在客户端抓，随声明过线；
这两个身份字段都按线程存，免得应答线程把远端身份漏到主线程自己身上）。

客户端补的是**执行点这一次真正输出出去的**记录（写 / 变更 / 被这次提交收口的读），
审计文件不重复写。两条推论要记住：远端失败时客户端那一侧本来是空的，所以
:meth:`Engine._log_remote_failure` 会在**发起方**也记一条 ``[E]``；而纯远端的读会攒在
写者的事务里等它的下一个提交点，因此不一定出现在客户端的日志里 —— 权威流是审计文件。
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _env_backend, _json_backend, _paths, _toml_backend, _yaml_backend
from ._audit import (
    AUDIT_NAME,
    TERMINAL_STDERR,
    AuditLog,
    Origin,
    Record,
    Reply,
    call_site,
    error_kind,
)
from ._core import MISSING, Action, Decl, read_value, reconcile
from ._lock import exclusive
from ._vocab import Vocabulary
from .errors import ConfError


if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import ModuleType


HOME_ENV = "ONCONF_HOME"
#: 值文件名的缺省主干。**可被 ``file_name`` 参数覆盖**，所以它只是缺省值，
#: 不再是「写死的名字」。
DEFAULT_FILE_NAME = "settings"
#: 兼容旧名：历史上它是写死的文件名主干，现在与 :data:`DEFAULT_FILE_NAME` 同源。
VALUES_STEM = DEFAULT_FILE_NAME
SCHEMA_DIR = "schema"
LOCK_SUFFIX = ".lock"
#: 缺省值文件类型：**字面 ``"json"``**，不是空串隐含出来的 json。
DEFAULT_FILE_TYPE = "json"
#: 缺省值文件的 ``$schema`` 指针（多文件模式下每个文件按自己的层级算出相对路径）。
SCHEMA_POINTER = f"{SCHEMA_DIR}/{DEFAULT_FILE_NAME}.json"

#: 攒批窗口的默认值（秒）。**0 = 每次声明当场落盘**。
#: 见模块文档：默认立即是语义决定，不是保守。
DEFAULT_FLUSH_WINDOW = 0.0


def _detect_newline(raw: bytes) -> str:
    r"""文件原本的行尾：出现 CRLF 就按 CRLF 写回，否则按 LF。

    这是「未触及的字节逐字不动」的一部分。``Path.write_text`` 在 ``newline=None``
    下会把 ``\\n`` 翻成 ``os.linesep`` —— 在 Windows 上等于**每次回写都把用户的
    LF 文件改成 CRLF**，那正是在碰那些不该碰的字节。
    """
    return "\r\n" if b"\r\n" in raw else "\n"


def _decode_universal(raw: bytes) -> str:
    """等价于 ``Path.read_text`` 的通用换行归一：CRLF 与孤立 CR 都变成 LF。"""
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _fsync_directory(directory: Path) -> None:
    """POSIX 上 rename 的持久化由**父目录**负责；Windows 不允许以 O_RDONLY 开目录。"""
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_text(path: Path, text: str, *, newline: str) -> None:
    """同目录临时文件 + ``fsync`` + ``os.replace`` 的原子替换。

    少任何一步这条都不成立：

    * **同目录**：``os.replace`` 只在同一文件系统内原子，跨设备会退化成复制。
    * **fsync 文件**：否则只是目录项换了，掉电后可能指向尚未落盘的内容。
    * **fsync 父目录**（POSIX）：rename 本身是目录项的改动，由目录的 fsync 保证持久。
    * **沿用原权限位**：临时文件是 0600，直接替换会把用户特意放宽的权限收窄；
      已存在的文件按原样保留，新建文件才拿 mkstemp 的 0600。
    * **``newline`` 用文件原本的行尾**：见 :func:`_detect_newline`。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            tmp.chmod(stat.S_IMODE(path.stat().st_mode))
        tmp.replace(path)
        replaced = True
    finally:
        if not replaced:
            with contextlib.suppress(OSError):
                tmp.unlink()
    _fsync_directory(path.parent)


#: 后端模块必须提供同一组函数与常量：
#: ``EMPTY_TEXT`` / ``loads`` / ``iter_members`` / ``find`` / ``set_value`` /
#: ``append_key`` / ``delete_key`` / ``render``
#:
#: ``EMPTY_TEXT`` 是**新建值文件时的种子**：它得让 ``append_key`` 能插进第一个键，
#: 所以 JSON 是 ``"{}"``，另外三种后端的空文本本身就是合法骨架。
_BACKENDS = {
    ".json": _json_backend,
    ".yaml": _yaml_backend,
    ".yml": _yaml_backend,
    ".env": _env_backend,
    ".toml": _toml_backend,
}

#: 只有「文件里能放一条 ``$schema`` 成员」的后端才吃得下词表指针。
#: ``.env`` / ``.toml`` 放不了成员 —— 硬塞只会让文件变成语法错误。
#: （TOML 那边另有 Taplo 的 ``#:schema`` 注释指令，留待后续。）
_POINTER_CAPABLE = frozenset({".json", ".yaml", ".yml"})

#: ``file_type`` 的合法取值 → 值文件后缀。**空串不再是合法取值**：
#: 缺省值是字面的 ``"json"``，默认值只有一个来源，不靠空串隐含的语义。
_FILE_TYPES = {
    "json": ".json",
    "yaml": ".yaml",
    "yml": ".yml",
    "toml": ".toml",
    "env": ".env",
}


def _file_suffix(file_type: str) -> str:
    """``file_type`` → 值文件后缀。取值非法当场报错，消息里列出全部合法取值。"""
    try:
        return _FILE_TYPES[file_type]
    except KeyError:
        raise ConfError(
            f"不认识的 file_type：{file_type!r}；合法取值：{sorted(_FILE_TYPES)}"
        ) from None


def _values_path(home: Path, file_name: str, suffix: str) -> Path:
    """值文件路径 = ``<home>/<file_name><suffix>``，**经包含性校验**。

    名字与后缀分开传，是因为多文件模式的后缀来自同一个 ``file_type``、名字却来自
    键里内嵌的路径段（见 :mod:`onconf._paths`）。
    """
    return _paths.values_path(home, file_name, suffix)


def _schema_pointer(values_path: Path, schema_path: Path) -> str:
    """值文件里的 ``$schema`` 指针：**从值文件所在目录到词表的相对路径**。

    单文件（``<home>/settings.json``）算出来就是 ``schema/settings.json``；多文件
    （``<home>/app/conf/net.json``）算出来是 ``../../schema/settings.json``。
    指针是给编辑器解析的，必须以值文件所在目录为基准，所以不能写死。
    """
    return Path(os.path.relpath(schema_path, values_path.parent)).as_posix()


def default_home() -> Path:
    """按约定发现配置目录：显式参数 → 环境变量 → ``./conf``。"""
    return Path(os.environ.get(HOME_ENV) or "conf").resolve()


@dataclass
class _FileState:
    """一个值文件在内存里的样子（多文件模式下会有很多个）。

    ``key`` 是**路径段**：空串表示默认文件 ``<home>/<file_name><ext>``，其余是键里
    ```:`` 左边那段相对路径。``facts`` 里的键是**文件内**的键名（不含路径段）。
    """

    key: str
    path: Path
    text: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    newline: str = field(default_factory=lambda: os.linesep)


def _owner_module() -> ModuleType:
    """``_owner`` 模块（就地导入）。

    **只能就地导入**：``_owner`` 在导入期就要本模块的目录常量
    （``SCHEMA_DIR`` / ``VALUES_STEM``），模块级导入会成环。

    （:mod:`onconf._lock` 那边也是就地导入的 —— 同一类理由，那边还多一条
    mypy 的 ``warn_unreachable``。）
    """
    from . import _owner  # noqa: PLC0415 - 见上：打断循环导入

    return _owner


class Engine:
    """一个配置目录 = 一个引擎。"""

    def __init__(
        self,
        home: str | os.PathLike[str] | None = None,
        *,
        file_name: str = DEFAULT_FILE_NAME,
        file_type: str = DEFAULT_FILE_TYPE,
        no_one_file: bool = False,
        audit: bool = False,
        flush_window: float = DEFAULT_FLUSH_WINDOW,
        lock_timeout: float = 10.0,
        log: str | os.PathLike[str] = TERMINAL_STDERR,
        identity: str = "",
    ) -> None:
        self.home = Path(home).resolve() if home is not None else default_home()
        #: 值文件名主干 —— **纯文件名**，缺省 ``settings``，经包含性校验。
        self.file_name = _paths.file_name_stem(file_name)
        #: 值文件类型（单值）。缺省**字面** ``"json"``，空串不是合法取值。必须重启才改。
        self.file_type = file_type
        self.suffix = _file_suffix(file_type)
        #: 多文件开关：开了之后键里的 ``<路径>:`` 前缀参与寻址（缺省关）。
        self.no_one_file = no_one_file
        #: 默认值文件。多文件模式下它是「没有路径段的键」的落点，所以仍在。
        self.values_path = _values_path(self.home, self.file_name, self.suffix)
        self.schema_path = self.home / SCHEMA_DIR / f"{self.file_name}.json"
        self.lock_path = self.home / SCHEMA_DIR / f"{self.file_name}{LOCK_SUFFIX}"
        self.audit = audit
        self.flush_window = flush_window
        self.lock_timeout = lock_timeout
        #: 应用 / 主机身份，记进 ``id=``。
        self.identity = identity
        #: 日志与审计的收口点。``audit=True`` 时它同时写 ``<home>/audit.log``。
        self._audit = AuditLog(
            audit_path=(self.home / AUDIT_NAME) if audit else None,
            log=log,
            identity=identity,
        )

        if self.suffix not in _BACKENDS:  # pragma: no cover - _file_suffix 已经挡了
            raise ConfError(f"不认识的值文件后缀：{self.values_path.name}")
        self.backend = _BACKENDS[self.suffix]

        self._decls: dict[str, Decl] = {}
        self._pending: dict[str, Decl] = {}
        self._window_started: float | None = None
        self._vocab = Vocabulary()
        #: 路径段 → 值文件状态。**空串是默认文件**，永远在；多文件模式下还有别的。
        self._files: dict[str, _FileState] = {}
        self._stamp: tuple[Any, ...] | None = None
        self._loaded = False
        #: 本引擎的通道，懒建。``_owner`` 只能用绑定方法传进来当写者的执行入口，
        #: 所以这里存的是不透明句柄（见 :meth:`_channel`）。
        self._chan: Any = None
        #: 最近一条「已经记过账」的异常。远端失败要补记时认一下它，免得就地执行
        #: （写者自己 / 退到底）那条路把同一件事记两遍。
        self._logged_failure: BaseException | None = None
        #: ``[Start]`` 只记一次（第一次真正用到这个引擎时）。
        self._started = False

    # ------------------------------------------------------------ 键 → 文件寻址

    def _address(self, key: str) -> tuple[str, str]:
        """全键 → ``(路径段, 文件内键名)``。

        **多文件关闭时路径段恒为空串**：``conf("a:b")`` 就是一个普通字面键，
        ``:`` 不参与任何解析。打开之后才按**第一个** ``:`` 切，
        左边是相对路径、右边是文件内的键。
        """
        if self.no_one_file and ":" in key:
            path_part, inner = key.split(":", 1)
            return path_part, inner
        return "", key

    def _file_key(self, path_part: str, inner: str) -> str:
        """``(路径段, 文件内键名)`` → 全键（``_address`` 的逆）。"""
        return f"{path_part}:{inner}" if path_part else inner

    def _file_for(self, path_part: str) -> _FileState:
        """取（必要时建）某个路径段对应的值文件状态。路径在这里**过包含性校验**。"""
        state = self._files.get(path_part)
        if state is None:
            name = path_part or self.file_name
            state = _FileState(key=path_part, path=_values_path(self.home, name, self.suffix))
            self._files[path_part] = state
        return state

    def _label(self, path_part: str) -> str:
        """审计里的 ``file=``：默认文件就是文件名，子目录用相对 ``home`` 的路径。

        用相对路径而不是纯文件名：多文件模式下 ``a/net.json`` 与 ``b/net.json``
        同名，只写文件名分不清动的是哪一个。
        """
        path = self._file_for(path_part).path
        try:
            return path.relative_to(self.home).as_posix()
        except ValueError:  # pragma: no cover - 包含性校验已经保证在 home 之内
            return path.name

    # ------------------------------------------------------------------ 两个面

    def __call__(self, key: str, value: Any = MISSING, doc: str | None = None) -> Any:
        """判别式：**只看 ``value`` 位填没填**。

        写法与模式一一对应，不做任何推断：

        * ``conf(key)`` —— 读；
        * ``conf(key, value)`` / ``conf(key, value, doc)`` —— 声明 + 写；
        * ``conf(key, doc=…)`` —— 只登记（空结构），随即按读的规则取值。

        ``None`` / ``""`` / ``0`` 都是**填了**，``MISSING`` 是唯一哨兵。
        ``doc`` 是第三个位置参数，也是唯一的登记元数据 —— 判据里不再出现第二个
        参数，参数面自此**封闭**：以后新增参数不需要动判据。
        """
        if not isinstance(key, str):
            raise TypeError(
                f"键必须是字符串，拿到 {key.__class__.__name__}（{key!r}）。"
                "如果是 conf(conf(…)) 这种间接寻址，说明内层取到的值不是键名。"
            )
        if value is MISSING and doc is None:
            return self.read(key)
        return self.declare(key, value, doc=doc)

    def read(self, key: str) -> Any:
        """读一个配置项。**先把待写交出去**，否则可能读不到自己刚声明的事实。"""
        self._ensure_started()
        self._load_audited(item=key)
        self._commit_local(clean=False)
        if self._is_writer():
            return self._read_local(key)
        owner = _owner_module()
        try:
            reply: Reply = self._channel().submit(
                owner.Request(
                    op=owner.OP_READ,
                    key=key,
                    pid=os.getpid(),
                    identity=self.identity or None,
                )
            )
        except Exception as exc:
            self._log_remote_failure(exc, item=key)
            raise
        self._collect_remote(reply)
        return reply.value

    def declare(self, key: str, value: Any = MISSING, doc: str | None = None) -> Any:
        """声明 / 写一个配置项。**返回当前生效值**（值文件优先，不是默认值）。

        ``value`` 位空着（``MISSING``）⇒ **只登记不给值**：词表里记一条「有键无值」，
        随后按读的规则取值 —— 没配就抛 ``KeyHasNoValueError``。这正是「启动即校验
        必填项」的用法。

        ``doc`` 给了就写进词表；文件里**已有不同值**时尊重文件（产出一条 ``skip``，
        一个字节都不写）。运行期没有覆盖出口：覆盖既存值是人主动发起的事，
        归命令行的 ``build`` / ``sync``（见 ``docs/design/init_config.md``）。
        """
        at = call_site()
        self._ensure_started()
        self._load_audited(item=key)
        decl = Decl(key=key, value=value, doc=doc, at=at)
        self._pending[key] = decl
        self._decls[key] = decl

        if self.flush_window <= 0 or self._window_expired():
            self._commit_local(clean=False)
        elif self._window_started is None:
            self._window_started = time.monotonic()

        return self._effective(key, decl)

    # ------------------------------------------------------------------ 提交点

    def flush(self) -> None:
        """把待提交的声明交出去。**不做规则 1**（期望集可能还不完整，见 ）。"""
        self._commit_local(clean=False)
        self._audit.close_txn()

    def sync(self) -> None:
        """完整提交点：此刻**期望集完整**，规则 1（清理未知数据）才允许执行。"""
        self._commit_local(clean=True)
        self._audit.close_txn()

    def close(self) -> None:
        """放下写者身份（或断开连接）。下一个进程会接上。

        顺手把审计收口：纯读的程序也要在退出前把攒着的 ``[R]`` 行交出去。

        **它不是提交点**：攒着的声明要在 ``flush()`` / ``sync()`` 里才交出去。
        ``atexit`` 那条路会先 ``sync()`` 再 ``close()``，但直接调 ``close()``
        （``flush_window > 0`` 时）会把还没交的声明丢掉 —— 要收口请显式 ``sync()``。
        """
        try:
            self._audit.close_txn()
        finally:
            if self._chan is not None:
                self._chan.close()
                self._chan = None

    # ------------------------------------------------------ 攒批窗口（本引擎的）

    def _commit_local(self, *, clean: bool) -> None:
        """把本地攒着的声明**交出去**。

        谁交：写者就地做（:meth:`_commit_pending`），客户端打包发一批
        （:meth:`_send_batch`）。所以攒批窗口是**每个引擎自己**的 —— 别人当了写者，
        不该把这一侧显式配的 ``flush_window`` 静默丢掉。

        窗口留在客户端还有第二个好处：突发期省下的是 **IPC 往返**，不只是磁盘写。
        """
        self._ensure_loaded()
        self._window_started = None
        if self._is_writer():
            self._commit_pending(clean=clean)
            return
        self._send_batch(clean=clean)

    def _send_batch(self, *, clean: bool) -> None:
        """把攒着的声明交给写者。交出去清空的是**缓冲区**，不是声明本身。"""
        decls = tuple(self._pending.values())
        self._pending.clear()
        if not decls and not clean:
            return
        owner = _owner_module()
        try:
            reply: Reply = self._channel().submit(
                owner.Request(
                    op=owner.OP_COMMIT,
                    decls=decls,
                    clean=clean,
                    pid=os.getpid(),
                    identity=self.identity or None,
                )
            )
        except Exception as exc:
            # 归属不到具体某个键：整批都可能失败。键名只用于记录，不改变异常。
            self._log_remote_failure(exc, item=decls[0].key if len(decls) == 1 else "")
            raise
        self._collect_remote(reply)

    def _is_writer(self) -> bool:
        """本引擎是不是就是那个专职写者（「端点整条路不通」的退化也算）。"""
        return bool(self._channel().is_mine())

    def _channel(self) -> Any:
        """本引擎的通道，懒建。**一个引擎一条** —— 不是「一个配置目录一条」。

        同一进程里两个引擎指着同一个配置目录完全正常（测试里到处都是）。按目录
        共用一条通道的话，第二个引擎会被塞进第一个引擎的通道，它的声明就落到
        **另一个引擎**的声明集上了。
        """
        if self._chan is None:
            owner = _owner_module()
            self._chan = owner.Channel(
                self,
                self._execute_local,
                on_link=self._linked,
                on_send=self._sent,
            )
        return self._chan

    # ------------------------------------------------- 进程结构的三行日志

    def _ensure_started(self) -> None:
        """第一次真正用到这个引擎时记一行 ``[Start]``。

        放在「第一次读 / 写」而不是 ``__init__``：构造一个从不使用的引擎不该产生日志，
        而且 ``Engine(...)`` 本身不该因为审计文件写不出去而失败。这一行是**信息性**的，
        所以连它自己的写出失败也吞掉 —— 真正落盘时的审计失败照旧抛。
        """
        if self._started:
            return
        self._started = True
        self._audit.started(file=self.values_path.name)
        with contextlib.suppress(ConfError):
            self._audit.close_txn()

    def _linked(self, op: str) -> None:
        """通道和写者的关系定下来了：``bind`` / ``connect`` / ``fallback``。"""
        self._audit.linked(op=op, file=self.values_path.name)
        with contextlib.suppress(ConfError):
            self._audit.close_txn()

    def _sent(self, request: Any) -> None:
        """一次请求**真的过了 IPC** —— 只有 :meth:`onconf._owner.Channel._try_remote` 会调它。

        退到就地执行时不会走到这里：那条路没有「发送」这回事。
        """
        owner = _owner_module()
        self._audit.sent(
            op=request.op,
            item=request.key,
            file=self.values_path.name,
            data=len(request.decls) if request.op == owner.OP_COMMIT else MISSING,
        )
        with contextlib.suppress(ConfError):
            self._audit.close_txn()

    # ------------------------------------------ 就地执行（只有写者会走这条路）

    def _execute_local(self, request: Any) -> Reply:
        """**就地执行一条请求**。这是终点：调它一定动文件，不再问「我是不是写者」。

        它以绑定方法的形式交给 :class:`onconf._owner.Channel` 当写者的执行入口，
        所以不需要为它开一个公开面 —— 公开面仍然只有 ``AutoConf`` 和 ``conf``。

        记账的口径也定在这里：**执行点写日志**，但记录里的 ``pid`` / ``id=``
        用请求里带来的**发起方**信息；``at=`` 早已随声明一起过线。回传的
        :class:`~onconf._audit.Reply` 带着这一批记录，客户端据此在自己的终端上补一份。
        """
        owner = _owner_module()
        previous = self._audit.origin
        # ``pid`` 为 None ⇒ 这条请求是本进程自己发起的，用执行点自己的身份；
        # 否则身份就是**发起方**的——它没设就是没设，不拿写者的服务名去顶。
        self._audit.origin = (
            Origin(pid=os.getpid(), identity=self.identity)
            if request.pid is None
            else Origin(pid=request.pid, identity=request.identity or "")
        )
        self._audit.begin_op()
        value: Any = None
        try:
            if request.op == owner.OP_READ:
                value = self._read_local(request.key)
            elif request.op == owner.OP_COMMIT:
                self._merge(request.decls, clean=request.clean)
            else:
                raise ConfError(f"不认识的请求：{request.op!r}")
        finally:
            records = self._audit.end_op()
            self._audit.origin = previous
        return Reply(value=value, records=records)

    def _read_local(self, key: str) -> Any:
        """读一个配置项（**就地**）。先把待写落盘，否则读不到自己刚声明的事实。"""
        self._ensure_loaded()
        self._commit_pending(clean=False)
        return self._read_audited(key)

    def _read_audited(self, key: str) -> Any:
        """``read_value`` + 一条 ``[R]``（或失败时的 ``[E]``）。

        读的记录**不在这里收口**：同一事务里重复读同一个键要合并成 ``n=<次数>``
        ，所以它留在缓冲里等下一个提交点（写提交 / ``flush`` / ``sync`` /
        退出）。失败的记录则当场落账 —— 异常一抛就没有下一个提交点了。
        """
        try:
            result = read_value(key, self._facts_view(), self._vocab.as_dict())
        except ConfError as exc:
            self._log_failure(exc, item=key)
            raise
        self._audit.read(
            item=key,
            file=self._label_for_key(key),
            source=result.origin,
            data=result.value,
        )
        return result.value

    def _label_for_key(self, key: str) -> str:
        """某个键落在哪个值文件 —— 审计里的 ``file=``。

        定位不到（键里内嵌的路径本身就非法，或者引擎还没加载）时退回默认值文件名：
        留痕的目的地不能因为「定位失败」而丢掉这一条记录。
        """
        try:
            return self._label(self._address(key)[0])
        except ConfError:
            return self.values_path.name

    def _collect_remote(self, reply: Reply) -> None:
        """别的进程替我执行时，把它**这一次真正输出出去的**记录补到自己终端上。

        审计文件不重复写：那份归执行点（写者），只有一个写者就不会交错。
        """
        if reply.remote:
            self._audit.render_remote(reply.records)

    def _log_failure(
        self,
        exc: BaseException,
        *,
        item: str = "",
        at: str = "",
    ) -> None:
        """失败留痕：记一条 ``[E]`` 并当场收口。**调用方负责继续抛。**

        当场收口是因为异常一抛，后面就没有提交点会替这条记录收尾了。
        审计**自己**写不出去时不在这里抛：那会盖住真正的异常，而调用方要诊断的是配置那件事。
        """
        self._audit.failed(
            item=item,
            file=self._label_for_key(item),
            err=error_kind(exc),
            message=str(exc),
            at=at,
        )
        self._logged_failure = exc
        with contextlib.suppress(ConfError):
            self._audit.close_txn()

    def _log_remote_failure(self, exc: BaseException, *, item: str = "") -> None:
        """远端执行失败时，在**发起方自己这一侧**也留一条痕。

        执行点已经记过账（写者的日志/审计文件里有），但发起方的日志去向本来是空的：
        ``except KeyNotRegisteredError`` 抓得到，可它自己的日志里什么都没有。

        就地执行（写者自己 / 退到底）那两条路已经记过，用 ``_logged_failure`` 认一下，
        避免同一件事在同一个进程里记两遍。
        """
        if self._logged_failure is exc:
            return
        self._log_failure(exc, item=item)

    def _load_audited(self, *, item: str) -> None:
        """加载值文件 / 词表；**失败也要留痕**。

        文件坏了（后端抛 ``ValueError`` 子类）、后端不认这种构造 —— 这些都不是
        「代码写错键名」，但一样必须出现在审计里，否则审计只记录成功的历史。
        """
        try:
            self._ensure_loaded()
        except (ConfError, OSError, TypeError, ValueError, KeyError) as exc:
            self._log_failure(exc, item=item)
            raise

    def _merge(self, decls: Iterable[Decl], *, clean: bool) -> None:
        """把别人交来的声明并进自己的声明集，然后提交。

        **这就是专职写者多买到的东西**：它的 ``_decls`` 是**所有进程**声明的并集，
        所以规则 1（清理未知数据）拿到的基准是完整的。硬锁做不到这一点 ——
        每个进程只知道自己那份。
        """
        for decl in decls:
            self._decls[decl.key] = decl
            # 也要进 ``_pending``：``_commit_pending`` 在「没有待写且不清理」时直接
            # 早退，只填 ``_decls`` 的话这批声明根本提交不出去。
            self._pending[decl.key] = decl
        self._commit_pending(clean=clean)

    def _window_expired(self) -> bool:
        if self._window_started is None:
            return False
        return (time.monotonic() - self._window_started) >= self.flush_window

    def _commit_pending(self, *, clean: bool) -> tuple[Record, ...]:
        """提交一批声明。**对账动作同时也是审计记录**。

        返回这一批产生的记录；真正的输出在 :meth:`onconf._audit.AuditLog.close_txn`
        里完成 —— 它顺手把攒在同一个事务里的读一起收口，所以批次内能对齐。

        失败必须留痕：锁拿不到、后端拒绝一个值……都先记一条 ``[E]``
        再原样抛出，不静默吞掉。
        """
        self._ensure_loaded()
        self._window_started = None
        if not self._pending and not clean:
            return ()

        batch = tuple(self._pending.values())
        self._pending.clear()
        if not self._decls:
            return ()

        records: list[Record] = []
        try:
            self._ensure_loaded()
            # 锁内重读：别的进程可能刚写过。少了这一步就是「各写各的，后写的盖掉先写的」。
            with exclusive(self.lock_path, timeout=self.lock_timeout):
                self._reload_if_changed()
                actions = self._reconcile_all(list(self._decls.values()), clean=clean)
                if actions:
                    self._commit(actions)
                records = self._action_records(actions, batch)
        # 后端拒绝一个值抛的是 TypeError / ValueError（TOML 没有 null、YAML 落不成单行……），
        # 文件坏了抛的是后端的 ValueError 子类，盘满 / 没权限是 OSError —— 它们都要留痕，
        # 不能只记 ConfError。
        except (ConfError, OSError, TypeError, ValueError, KeyError) as exc:
            self._log_failure(exc)
            raise
        # 正常路径才在这里收口：审计写不出去就抛（审计缺席不是「少看几行」）。
        # 不放进 finally，是因为 finally 里抛出的异常会盖掉上面那条真正的失败。
        self._audit.close_txn()
        return tuple(records)

    def _reconcile_all(self, decls: list[Decl], *, clean: bool) -> list[Action]:
        """**按值文件分组**做对账，再拼成一份动作清单。

        多文件模式下规则 1 的判据是「**这个文件里**有、期望集里没有」—— 分组不能省：
        拿全部事实去对全部声明，A 文件里的键会被判成 B 文件的未知数据而被删掉。
        分组之后每个文件各自跑一遍三集合算法，**期望集仍是全局的那一份**。

        加载范围只到「当前声明集引用到的文件」：磁盘上其它值文件不归这个引擎管，
        一个字节都不会动（也就不会被规则 1 清理）。
        """
        groups: dict[str, list[Decl]] = {}
        for decl in decls:
            groups.setdefault(self._address(decl.key)[0], []).append(decl)

        actions: list[Action] = []
        for path_part, group in sorted(groups.items()):
            if path_part not in self._files:
                self._load_file(path_part)
            state = self._file_for(path_part)
            facts = {
                self._file_key(path_part, inner): value for inner, value in state.facts.items()
            }
            actions.extend(reconcile(group, facts, self._vocab.as_dict(), clean_unknown=clean))
        return actions

    def _action_records(self, actions: Iterable[Action], batch: tuple[Decl, ...]) -> list[Record]:
        """对账动作 → 审计记录。**写全量**；本批里无事可做的声明留一行 ``op=noop``。

        ``noop`` 是给「用户必须看得见本次运行声明了哪些键」那条要求用的，
        否则「我的声明到底生效没有」只能靠猜。只给**本批**的声明补 noop，所以不会
        退化成「每次提交都把全部已声明键刷一遍」。
        """
        records: list[Record] = []
        covered: set[str] = set()
        for action in actions:
            covered.add(action.key)
            decl = self._decls.get(action.key)
            at = decl.at if decl is not None else ""
            file = self._label_for_key(action.key)
            if action.kind == "skip":
                # 「值不一致但尊重文件、想改没改」—— old / new 都要留。
                records.append(
                    self._audit.wrote(
                        item=action.key,
                        file=file,
                        op=action.kind,
                        old=action.old,
                        new=action.value,
                        reason=action.reason,
                    )
                )
            else:
                records.append(
                    self._audit.wrote(
                        item=action.key,
                        file=file,
                        op=action.kind,
                        data=action.value,
                        old=action.old,
                        reason=action.reason,
                    )
                )
            if action.kind in ("fill", "clean"):
                records.append(
                    self._audit.changed(
                        item=action.key,
                        file=file,
                        old=action.old,
                        new=action.value,
                        at=at,
                    )
                )
        records.extend(
            self._audit.wrote(
                item=decl.key,
                file=self._label_for_key(decl.key),
                op="noop",
                at=decl.at,
            )
            for decl in batch
            if decl.key not in covered
        )
        return records

    def _effective(self, key: str, decl: Decl) -> Any:
        """``declare`` 该返回什么：**当前生效值**（值文件优先）。

        这条修的是 Cairn 的 D5：声明返回默认值、取值返回文件值，会让同一键的相邻
        两行拿到不同结果。现在两者都以事实为准。
        """
        facts = self._facts_view()
        if key in facts:
            return facts[key]
        if decl.value is MISSING:
            # 只登记不给值 ⇒ 登记得先算数（所以先交出去），再按读的规则取值。
            # 必须重读磁盘：**登记是写者做的**，词表是它写到磁盘上的，我们内存里
            # 这份还是旧的 —— 不重读就会把「登记了但没值」误报成「没登记」。
            self._commit_local(clean=False)
            self._reload()
            return self._read_audited(key)
        return decl.value

    # ------------------------------------------------------------- 加载 / 落盘

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._reload()

    def _known_path_parts(self) -> list[str]:
        """归这个引擎管的值文件：默认文件 + 当前声明集引用到的每个路径段。"""
        parts = {""}
        parts.update(self._address(key)[0] for key in self._decls)
        return sorted(parts)

    def _load_file(self, path_part: str) -> _FileState:
        """把一个值文件读进内存（不存在就是空状态）。"""
        state = self._file_for(path_part)
        if state.path.exists():
            raw = state.path.read_bytes()
            state.newline = _detect_newline(raw)
            state.text = _decode_universal(raw)
            state.facts = self.backend.loads(state.text)
        else:
            state.text = None
            state.facts = {}
        return state

    def _facts_view(self) -> dict[str, Any]:
        """把「路径段 + 文件内键名」摊平成**全键 → 值**，供 :func:`_core.read_value` 用。"""
        view: dict[str, Any] = {}
        for path_part, state in self._files.items():
            for inner, value in state.facts.items():
                view[self._file_key(path_part, inner)] = value
        return view

    @staticmethod
    def _file_stamp(path: Path) -> tuple[int, int] | None:
        """一个文件的指纹（mtime + size）；不存在返回 ``None``。"""
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _disk_stamp(self) -> tuple[Any, ...]:
        """已加载的每个值文件 + 词表的「指纹」，用来判断要不要重读。

        词表也必须看：只动词表的提交（例如「只登记不给值」）不会碰值文件，
        只看值文件就会漏掉它，然后把别人刚登记的键从词表里挤掉。
        """
        files = tuple(self._file_stamp(state.path) for _, state in sorted(self._files.items()))
        return (files, self._file_stamp(self.schema_path))

    def _reload_if_changed(self) -> None:
        """锁内重读 —— 但只在磁盘真的变过时才读，免得退化成每次全篇重读。"""
        if self._disk_stamp() != self._stamp:
            self._reload()

    def _reload(self) -> None:
        """从磁盘重读事实与词表。锁内调用，所以看到的是别人的最新提交。

        加载范围 = **默认文件 + 当前声明集引用到的每个路径段**（见 :meth:`_known_path_parts`）。
        """
        for path_part in self._known_path_parts():
            self._load_file(path_part)

        if self.schema_path.exists():
            raw_schema = self.schema_path.read_bytes()
            self._vocab = Vocabulary.from_schema(json.loads(_decode_universal(raw_schema)))

        self._stamp = self._disk_stamp()

    def _commit(self, actions: Iterable[Action]) -> None:
        """把对账动作落到各自的值文件上，再整篇重写词表。"""
        action_list = list(actions)
        by_part: dict[str, list[Action]] = {}
        for action in action_list:
            by_part.setdefault(self._address(action.key)[0], []).append(action)

        for path_part, group in sorted(by_part.items()):
            self._commit_one(path_part, group)

        # 词表是**库自己的资产**（归属权见 docs/design/file_support.md），
        # 所以整篇重写是合法的，不需要外科手术
        self._vocab.apply(action_list, list(self._decls.values()))
        _atomic_write_text(
            self.schema_path,
            json.dumps(self._vocab.to_schema(), indent=2, ensure_ascii=False) + "\n",
            newline=self._file_for("").newline,
        )
        self._stamp = self._disk_stamp()

    def _commit_one(self, path_part: str, actions: list[Action]) -> None:
        """把一批动作落到**一个**值文件上（外科手术式回写）。"""
        state = self._file_for(path_part)
        creating = state.text is None
        # 新建文件时从后端给的**种子**起步：JSON 要 ``"{}"``，另外三种后端空文本即可。
        original: str = state.text if state.text is not None else self.backend.EMPTY_TEXT
        # 指针先补、动作后落 —— 反过来的话，等落完动作文件已经不是空对象了。
        text = self._ensure_schema_pointer(original, state)

        for action in actions:
            inner = self._address(action.key)[1]
            if action.kind == "fill":
                if self.backend.find(text, inner) is None:
                    text = self.backend.append_key(text, inner, action.value)
                else:
                    text = self.backend.set_value(text, inner, action.value)
                state.facts[inner] = action.value
            elif action.kind == "clean":
                if self.backend.find(text, inner) is not None:
                    text = self.backend.delete_key(text, inner)
                state.facts.pop(inner, None)

        if creating or text != original:
            _atomic_write_text(state.path, text, newline=state.newline)
            state.text = text

    def _ensure_schema_pointer(self, text: str, state: _FileState) -> str:
        """值文件必须带 ``$schema`` 指针（能吃下的后端）。

        没有它，编辑器就不知道词表在哪 —— 用户面对一个几十项的配置只能靠翻文件
        所以这条**不是新建时才补，是每次落盘都保证有**。
        它是**指令**不是配置键，不参与对账。

        指针是**从这一个值文件的所在目录**到词表的相对路径：多文件模式下每个文件
        算出来的都不一样（``app/conf/net.json`` 要写 ``../../schema/settings.json``）。

        ``.env`` 之类放不下成员的后端直接跳过：硬塞只会让文件变成语法错误。
        """
        if state.path.suffix.lower() not in _POINTER_CAPABLE:
            return text
        if self.backend.find(text, "$schema") is not None:
            return text
        seeded: str = self.backend.append_key(
            text, "$schema", _schema_pointer(state.path, self.schema_path)
        )
        return seeded
