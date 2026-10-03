# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""专职写者：**谁绑上端点，谁就是唯一的读写者**（DESIGN §19 / §25 / §26）。

## 选主不是加锁，是抢绑端点

实测（``multiprocessing.connection``，Windows 命名管道）::

    ① 第一个 Listener 绑上        : ok
    ② 第二个 Listener 绑同一地址  : 被拒（PermissionError）

抢绑本身就是一次**原子操作** —— 操作系统保证同一个地址只有一个能绑上。
所以「谁是写者」不需要锁文件，只需要一个**命名空间**：协调借的是命名空间的
原子性，不是临界区的排他性。它因此不需要心跳、不需要判活、不会留下死锁文件。

## 专职写者到底多买了什么

不是「多一层机械」，是三件锁做不到的事：

1. **全局声明集**。规则 1（清理未知数据）必须拿**完整**声明集当基准，而每个
   进程只知道自己那份。写者是唯一收口点，它看得见所有人 —— 跨进程的规则 1
   因此才安全（§19.3）。
2. **全局去抖**。攒批窗口挂在写者身上，收的是**所有**进程的声明；没有写者时，
   窗口只能是各进程互不相干的局部窗口。
3. **重读次数**。N 个进程各提交 M 次 = N×M 轮「读改写」；有写者时，磁盘上的
   读改写只由它一个做，别人只是发请求。

## 一个配置目录 = 一个独立的 IPC 世界（§26.2）

端点名由**配置目录的绝对路径**派生：两个项目、两份配置永远不撞，用户也不需要
配端口或路径。认证码落 ``<home>/schema/settings.key``（0600）。

## 认证码为什么不用 ``authkey=``，而是自己打招呼

``multiprocessing`` 的 ``authkey`` 会在 ``Client(...)`` 的**构造函数里**做一次
挑战应答。问题是这一步**没有超时**：只要端点上「有人听、没人答」，构造函数就
永远不返回 —— ``conf()`` 直接挂死。踩到过一次，栈是::

    _recv_bytes → answer_challenge → Client → connect() → Channel.__init__()

所以认证挪到应用层：连上之后先发一句 ``("hello", 认证码)``，**带超时地**等
``"welcome"``。认证强度一样（对面还是得先出示同一把钥匙），但**等待有界**。

顺带说清楚这把钥匙的定位：**它不是密码学边界**。真正的边界是配置目录的
文件系统 ACL —— 能读 ``settings.key`` 的进程本来就能读 ``settings.json``。
它防的是**串台**（连错了端点），不是**攻击**。

## 三个坑

* ``Client(...)`` 在构造函数里就完成握手 ⇒ 「先 Client 再 accept」是**死等**。
  已经改成自己打招呼，所以这条不再适用于本模块，但 ``authkey=`` 一开就会回来。
* ``Listener.close()`` **关不掉正在 ``accept()`` 的那个 handle**。看
  ``PipeListener.accept``::

      self._handle_queue.append(self._new_handle())  # 先补一个新实例
      handle = self._handle_queue.pop(0)  # 取走最早那个去阻塞等待

  ``close()`` 清的是队列里那个**新的**，而阻塞等待的那个由线程自己拿着。
  后果是端点名不消失 ⇒ 下一个进程永远抢绑不到（写者真空）。所以 ``close()``
  末尾要开一条空连接把线程**叫醒**（:meth:`Owner._wake`）。
* ``send`` / ``recv`` 底层是 pickle。这里 pickle 的是**调用方自己 Python 代码里
  给出的声明**（``conf("port", 8080)``），不是从文件里读来的不可信内容；文件内容
  永远只走 ``yaml.safe_load`` 那一套（§26.3）。信道是本地且只连同用户的。

## 每个请求都是**幂等**的

``read`` / ``declare`` / ``sync`` 重复执行结果相同（文件是绝对权威），所以写者
半路死掉时**重发是安全的** —— 这是「断线就重连重试」敢写的前提。
"""

from __future__ import annotations

import contextlib
import hashlib
import multiprocessing.connection as ipc
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._core import MISSING
from ._engine import SCHEMA_DIR, VALUES_STEM
from ._lock import LockTimeoutError
from .errors import (
    ConfError,
    KeyHasNoValueError,
    KeyNotRegisteredError,
    TypeConflictError,
)


if TYPE_CHECKING:
    from ._engine import Engine

    #: ``Client()`` / ``accept()`` 给回来的是 ``Connection`` 或 ``PipeConnection``
    #: —— 它俩在 typeshed 里是**兄弟**（都继承私有的 ``_ConnectionBase``），没有
    #: 公共父类，于是每一处注解都躲不开那个联合。我们只用
    #: ``send`` / ``recv`` / ``poll`` / ``close``，两边签名一模一样，收成 ``Any``
    #: 比把同一串联合抄六遍干净得多。
    Conn = Any

#: Windows 命名管道的**全局**命名空间前缀
_PIPE_PREFIX = r"\\.\pipe\auto-conf-"

#: 端点名里的哈希长度：够长到不撞，够短到还能一眼认出是它
_HASH_CHARS = 24

#: 认证码长度（字节）
_KEY_BYTES = 32

#: 认证码文件名（相对配置目录）
KEY_NAME = f"{SCHEMA_DIR}/{VALUES_STEM}.key"

#: 打招呼用的两句话
_HELLO = "hello"
_WELCOME = "welcome"

#: 打完招呼等回话的上限（秒）。**所有等待都必须有界**：一个连上却不说话的对端
#: 不许把 ``conf()`` 挂住。对面是活的话，这一句是微秒级的。
HELLO_TIMEOUT = 0.5

#: ``Owner.close()`` 等应答线程收摊的上限（秒）
_JOIN_TIMEOUT = 2.0

#: 三个 op —— 与 :class:`Engine` 的三个入口一一对应，没有第四个
OP_READ = "read"
OP_DECLARE = "declare"
OP_SYNC = "sync"


# --------------------------------------------------------------------------- #
# 选主：端点 / 认证码 / 抢绑
# --------------------------------------------------------------------------- #


def endpoint_for(home: Path) -> str:
    r"""端点名：**只由配置目录决定**，别的什么都不看。

    Windows 把名字放进全局命名空间，所以只能哈希（路径塞不进去）；POSIX 用配置
    目录里的 socket 文件，按构造就已经隔离了。

    Windows 上先 ``normcase``：``D:\a`` 与 ``d:\a`` 是同一个目录，但字符串不同
    —— 不折叠大小写就会出现**两个写者写着同一个目录**，那正是这个模块要防的事。
    """
    if os.name == "nt":
        seed = os.path.normcase(str(home))
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:_HASH_CHARS]
        return f"{_PIPE_PREFIX}{digest}"
    return str(home / SCHEMA_DIR / f"{VALUES_STEM}.sock")


def authkey_for(home: Path) -> str:
    """认证码（十六进制）：**原子创建**，保证并发的首次调用者拿到的是同一把。

    「创建」和「写入」必须是一步。先 ``O_CREAT|O_EXCL`` 再 ``write`` 会留下一个
    **空文件**的窗口：并发的读者正好读到这里就拿到空字符串，两边的钥匙分叉，
    其中一个从此连不上自己刚绑上的端点 —— 这种 bug 只在并发下露头，最难查。
    ``os.link`` 正是要的那个原语：目标已存在就失败，而内容**早就写好了**。
    """
    path = home / KEY_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(_KEY_BYTES).hex()
    staging = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}")
    staging.write_text(key, encoding="ascii")
    staging.chmod(0o600)  # 硬链接共享 inode，所以权限得在链接之前上好
    try:
        with contextlib.suppress(FileExistsError):
            os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)
    return path.read_text(encoding="ascii").strip()


def claim(home: Path) -> ipc.Listener | None:
    """抢绑端点：抢到就是写者，返回 ``Listener``；抢不到返回 ``None``。

    **这个返回值就是选举结果**，没有第二次确认 —— 抢绑是原子的。
    """
    address = endpoint_for(home)
    if os.name != "nt":  # pragma: no cover - 本机是 Windows；POSIX 见 _reap_stale
        _reap_stale(address, authkey_for(home))
    try:
        return ipc.Listener(address)
    except OSError:
        return None


def connect(home: Path, *, timeout: float = HELLO_TIMEOUT) -> Conn | None:
    """连当前写者并打完招呼；没人在、或没人答话，都返回 ``None``。

    **两次有界**：``Client(...)`` 不再做握手（无超时的那一步已经搬走），
    我们自己的招呼又带 ``timeout``。所以这个函数不会把调用方挂死。
    """
    if not (home / KEY_NAME).exists():
        return None
    return _hello(endpoint_for(home), authkey_for(home), timeout)


def _hello(address: str, key: str, timeout: float) -> Conn | None:
    """连上 + 自报认证码 + 带超时地等欢迎。不成功就把连接收拾干净。"""
    try:
        conn = ipc.Client(address)
    except OSError:
        return None
    try:
        conn.send((_HELLO, key))
        if not conn.poll(timeout) or conn.recv() != _WELCOME:
            conn.close()
            return None
    except OSError, EOFError:
        with contextlib.suppress(OSError):
            conn.close()
        return None
    return conn


def _reap_stale(address: str, key: str) -> None:  # pragma: no cover - POSIX 专用
    """POSIX：写者**崩了**会在磁盘上留下 socket 文件，得先探活再决定清不清。

    探活就是正经打一次招呼：有写者就拿到 ``welcome``，没有就解绑重来。
    （Windows 不需要这段：命名管道随进程消失，不会有残留。）
    """
    path = Path(address)
    if not path.exists():
        return
    conn = _hello(address, key, HELLO_TIMEOUT)
    if conn is not None:
        conn.close()
        return
    with contextlib.suppress(OSError):
        path.unlink()


# --------------------------------------------------------------------------- #
# 线上格式
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Request:
    """一次请求。三个 op 对应 :class:`Engine` 的三个入口，没有别的。"""

    op: str
    key: str = ""
    value: Any = MISSING
    type: type | None = None
    doc: str | None = None
    force: bool = False


#: 异常**按名字过线**，不让异常对象过线：那等于让写者隔空给客户端构造对象，
#: 而我们连 pickle 都不肯为文件内容开（§26.3）。认识的名字就还原成原类型，
#: 不认识的一律降级成 ``ConfError`` —— 类型丢了，但「为什么」一点不少。
_ERROR_KINDS: dict[str, type[ConfError]] = {
    cls.__name__: cls
    for cls in (
        LockTimeoutError,
        KeyNotRegisteredError,
        KeyHasNoValueError,
        TypeConflictError,
        ConfError,
    )
}

#: 远端失败的内部标记。**不能用 ``None``**：``sync()`` 成功时返回的就是 ``None``。
_RETRY = object()


def apply_request(engine: Engine, request: Request) -> Any:
    """把请求施加到引擎上。**只有写者会调它** —— 这就是「唯一读写」的落点。"""
    if request.op == OP_READ:
        return engine.read(request.key)
    if request.op == OP_DECLARE:
        return engine.declare(
            request.key,
            request.value,
            doc=request.doc,
            type=request.type,
            force=request.force,
        )
    if request.op == OP_SYNC:
        engine.sync()
        return None
    raise ConfError(f"不认识的请求：{request.op!r}（只有 read / declare / sync）")


# --------------------------------------------------------------------------- #
# 写者
# --------------------------------------------------------------------------- #


class Owner:
    """本进程里的那个写者：**一个引擎，一个端点，一个应答线程**。

    端点一绑上，别的进程就只能发请求，磁盘上的读改写从此只有这一个线程在做。
    自己的请求走本地直调 —— 不给自己的 IPC 排队。
    """

    def __init__(self, engine: Engine, listener: ipc.Listener) -> None:
        self.engine = engine
        self._listener = listener
        self._key = authkey_for(engine.home)
        #: 写者自己的两个调用方（主线程 + 应答线程）也要互斥：引擎不是线程安全的
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._current: Conn | None = None
        self._worker: threading.Thread | None = None

    @classmethod
    def claim(cls, engine: Engine) -> Owner | None:
        """试着当写者；抢不到说明别人已经在当，返回 ``None``。"""
        listener = claim(engine.home)
        return None if listener is None else cls(engine, listener)

    def start(self) -> None:
        """开应答线程。**必须赶在客户端连上来之前** —— 见模块文档那个死等的坑。"""
        if self._worker is None:
            self._worker = threading.Thread(
                target=self._serve,
                name="auto-conf-owner",
                daemon=True,
            )
            self._worker.start()

    def submit(self, request: Request) -> Any:
        """写者自己的请求：本地直调，不绕 IPC。"""
        with self._lock:
            return apply_request(self.engine, request)

    def close(self) -> None:
        """下班。**这里的顺序就是全部要点**，而且只能是这样：

        1. 举旗 ``_closed``；
        2. 关掉手上那条连接 —— 线程要是卡在 ``recv()``，这样才醒得过来；
        3. 开一条空连接，叫醒卡在 ``accept()`` 里的线程；
        4. **等它真的退出**；
        5. 这时才 ``listener.close()``。

        第 5 步必须排在第 4 步后面。``PipeListener.accept()`` 是**先造一个备用
        实例、再去阻塞等待**的（见模块文档第三个坑）：线程要是在 ``close()``
        之后才进 ``accept()``，那个备用实例就**没人关**了 —— 端点名一直挂着，
        下一个进程永远抢绑不到（写者真空）。先 join 掉线程，就没有这个窗口。
        """
        self._closed.set()
        with self._lock, contextlib.suppress(OSError):
            if self._current is not None:
                self._current.close()
        self._wake()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=_JOIN_TIMEOUT)
        with contextlib.suppress(OSError):
            self._listener.close()

    def _wake(self) -> None:
        """开一条空连接，把卡在 ``accept()`` 里的线程叫醒。

        线程醒来第一件事是看 ``_closed``，然后收摊走人。没人听的时候这句直接
        失败，无视即可。
        """
        with contextlib.suppress(OSError):
            ipc.Client(endpoint_for(self.engine.home)).close()

    # ---------------------------------------------------------------- 应答线程

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                conn = self._listener.accept()
            except OSError, EOFError:
                return
            self._current = conn
            try:
                if self._greet(conn):
                    self._handle(conn)
            finally:
                self._current = None
                with contextlib.suppress(OSError):
                    conn.close()

    def _greet(self, conn: Conn) -> bool:
        """验一下对面的认证码，回一句欢迎。**有界**：不说话的连接直接放弃。"""
        try:
            if not conn.poll(HELLO_TIMEOUT):
                return False
            hello = conn.recv()
        except Exception:  # noqa: BLE001 - 坏客户端不许带走应答线程
            return False
        if not (isinstance(hello, tuple) and hello[0] == _HELLO and hello[1] == self._key):
            return False
        conn.send(_WELCOME)
        return True

    def _handle(self, conn: Conn) -> None:
        """一条连接可以连着发很多次请求，所以这里是内层循环。"""
        while not self._closed.is_set():
            try:
                request = conn.recv()
            except Exception:  # noqa: BLE001 - 坏客户端不许带走应答线程
                return
            try:
                conn.send(_respond(self, request))
            except Exception:  # noqa: BLE001 - 客户端半路走了也只是它的事
                return


def _respond(owner: Owner, request: Request) -> tuple[str, Any]:
    """应答：``("ok", 值)`` 或 ``("err", (异常名, 消息))``。

    ``BaseException`` 不许过：``KeyboardInterrupt`` 是**写者进程自己的**中断，
    不该被当成一条应答发给客户端。
    """
    try:
        return ("ok", owner.submit(request))
    except Exception as exc:  # noqa: BLE001 - 客户端要的是「为什么」，不是断连
        return ("err", (type(exc).__name__, str(exc)))


# --------------------------------------------------------------------------- #
# 通道：一个进程面对一个配置目录的那条路
# --------------------------------------------------------------------------- #


class Channel:
    """三层，逐层退让：

    1. **我是写者** ⇒ 本地直调（不绕 IPC）；
    2. **别人是写者** ⇒ 走 IPC；
    3. **两条都不通** ⇒ 退回直写（OS 锁还在，是保险）。

    第 3 层是安全网，不是常规路径：它让「端点建不出来」这种环境问题退化成
    「性能差一点」，而不是「库不能用」。正确性从来不靠 IPC 撑着。
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        #: 一条连接不能被两个线程同时收发，所以整轮往返都在这把锁里
        self._lock = threading.Lock()
        self._client: Conn | None = None
        self._writer: Owner | None = None
        self._attach()

    # -------------------------------------------------------------------- 装配

    def _attach(self) -> None:
        """决定自己是谁：先看有没有现成的写者，没有就自己当。

        **全程尽力而为**：端点这条路整个不通（配置目录只读、文件系统不支持
        硬链接、端点被谁的残留占着……）不该让 ``conf()`` 失败 —— 退回直写就是。
        """
        try:
            self._client = connect(self.engine.home)
            if self._client is not None:
                return
            writer = Owner.claim(self.engine)
            if writer is None:
                # 抢绑失败 ⇒ 有人在我们探测之后绑上了。这是正常竞态，再连一次。
                self._client = connect(self.engine.home)
                return
        except OSError, ConfError:
            self._client = None
            self._writer = None
            return
        self._writer = writer
        writer.start()

    # -------------------------------------------------------------------- 出口

    def submit(self, request: Request) -> Any:
        """发一次请求。请求是幂等的，所以「断了重发」天生安全。"""
        with self._lock:
            return self._send(request)

    def close(self) -> None:
        """还回写者身份（或断开连接）。下一个进程会接上。"""
        with self._lock:
            if self._client is not None:
                with contextlib.suppress(OSError):
                    self._client.close()
                self._client = None
            if self._writer is not None:
                self._writer.close()
                self._writer = None

    # -------------------------------------------------------------------- 内部

    def _send(self, request: Request) -> Any:
        outcome = self._route(request)
        if outcome is _RETRY:
            # 写者没了，或者本来就没连上 —— 重新装配一次，也许这次该我当写者。
            self._attach()
            outcome = self._route(request)
        if outcome is _RETRY:
            # 退到底：直写。OS 锁还在，别的进程进不来，正确性不靠 IPC 撑着。
            return apply_request(self.engine, request)
        return outcome

    def _route(self, request: Request) -> Any:
        """按当前身份发一次；发不出去返回 :data:`_RETRY`。

        身份一律先取到**局部变量**再判：``mypy`` 会把 ``self._writer`` 的收窄
        一路带过方法调用（它不认为 ``_attach()`` 能改它），于是「重新装配之后再
        判一次」会被判成不可达。走局部变量就没这个事。
        """
        writer = self._writer
        if writer is not None:
            return writer.submit(request)
        client = self._client
        if client is None:
            return _RETRY
        outcome = self._try_remote(client, request)
        if outcome is _RETRY:
            self._client = None
        return outcome

    @staticmethod
    def _try_remote(client: Conn, request: Request) -> Any:
        """发一轮往返。断了返回 :data:`_RETRY`，业务异常照原样抛回去。"""
        try:
            client.send(request)
            status, payload = client.recv()
        except EOFError, OSError:
            return _RETRY
        if status == "ok":
            return payload
        name, message = payload
        raise _ERROR_KINDS.get(name, ConfError)(message)


# --------------------------------------------------------------------------- #
# 每进程一个通道（按配置目录）
# --------------------------------------------------------------------------- #

_CHANNELS: dict[Path, Channel] = {}
_REGISTRY = threading.Lock()


def channel_for(engine: Engine) -> Channel:
    """取（或建）本进程面对这个配置目录的通道。一个目录一个，进程内共用。"""
    with _REGISTRY:
        existing = _CHANNELS.get(engine.home)
        if existing is None:
            existing = Channel(engine)
            _CHANNELS[engine.home] = existing
        return existing


def close_channels() -> None:
    """关掉本进程的所有通道（测试与进程退出用）。"""
    with _REGISTRY:
        existing = list(_CHANNELS.values())
        _CHANNELS.clear()
    for channel in existing:
        channel.close()
