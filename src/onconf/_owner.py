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
   **前提是写者得活着**：声明集不是持久状态，写者一换人，并集就没了，接着上来
   的新写者会拿自己那一份去清理。进程起一个退一个的用法踩在这个前提之外
   （``tests/test_engine.py::TestRealProcesses`` 里两条测试正好各占一边）。
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

## 四个坑

* ``Client(...)`` 在构造函数里就完成握手 ⇒ 「先 Client 再 accept」是**死等**。
  已经改成自己打招呼，所以这条不再适用于本模块，但 ``authkey=`` 一开就会回来。
* ``Listener.close()`` **关不掉正在 ``accept()`` 的那个 handle**。看
  ``PipeListener.accept``::

      self._handle_queue.append(self._new_handle())  # 先补一个新实例
      handle = self._handle_queue.pop(0)  # 取走最早那个去阻塞等待

  ``close()`` 清的是队列里那个**新的**，而阻塞等待的那个由线程自己拿着。
  后果是端点名不消失 ⇒ 下一个进程永远抢绑不到（写者真空）。所以 ``close()``
  末尾要开一条空连接把线程**叫醒**（:meth:`Owner._wake`）。
* **一条连接不能串行服务**。第一版 ``_serve`` 是 accept 完就蹲在 ``_handle``
  里 ``recv``，于是客户端 A 的整条会话把端口堵死：客户端 B **连得上，却没人跟
  它握手**，它只会得出「没有写者」的结论。单客户端时完全看不出来，一多客户端
  就必炸。现在 ``accept`` 只负责接，接到就交给一个会话线程。
* ``send`` / ``recv`` 底层是 pickle。这里 pickle 的是**调用方自己 Python 代码里
  给出的声明**（``conf("port", 8080)``），不是从文件里读来的不可信内容；文件内容
  永远只走 ``yaml.safe_load`` 那一套（§26.3）。信道是本地且只连同用户的。

## 每个请求都是**幂等**的

``read`` 与 ``commit`` 重复执行结果相同（文件是绝对权威），所以写者半路死掉时
**重发是安全的** —— 这是「断线就重连重试」敢写的前提。
"""

from __future__ import annotations

import contextlib
import hashlib
import multiprocessing.connection as ipc
import os
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._audit import Reply
from ._engine import DEFAULT_FILE_NAME, SCHEMA_DIR
from ._lock import LockTimeoutError
from .errors import (
    ConfError,
    KeyHasNoValueError,
    KeyNotRegisteredError,
)


if TYPE_CHECKING:
    from collections.abc import Callable

    from ._core import Decl
    from ._engine import Engine

    #: ``Client()`` / ``accept()`` 给回来的是 ``Connection`` 或 ``PipeConnection``
    #: —— 它俩在 typeshed 里是**兄弟**（都继承私有的 ``_ConnectionBase``），没有
    #: 公共父类，于是每一处注解都躲不开那个联合。我们只用
    #: ``send`` / ``recv`` / ``poll`` / ``close``，两边签名一模一样，收成 ``Any``
    #: 比把同一串联合抄六遍干净得多。
    Conn = Any

    #: 通道给引擎的两个回调（``[Link]`` / ``[Send]``，见 ``Engine._linked`` / ``_sent``）
    _OnLink = Callable[[str], None]
    _OnSend = Callable[["Request"], None]

#: Windows 命名管道的**全局**命名空间前缀
_PIPE_PREFIX = r"\\.\pipe\onconf-"

#: 端点名里的哈希长度：够长到不撞，够短到还能一眼认出是它
_HASH_CHARS = 24

#: 认证码长度（字节）
_KEY_BYTES = 32

def key_path(home: Path, stem: str = DEFAULT_FILE_NAME) -> Path:
    """认证码文件路径：``<home>/schema/<stem>.key``。

    ``stem`` 就是引擎的 ``file_name``。**必须带上它**：同一个配置目录上的两个引擎
    如果值文件名不同，就是两套互不相干的簿记（值文件、词表、锁、端点、钥匙全都
    不同名），共用一个端点会让请求落到**另一个引擎**的声明集上。
    """
    return home / SCHEMA_DIR / f"{stem}.key"

#: 打招呼用的两句话
_HELLO = "hello"
_WELCOME = "welcome"

#: 打完招呼等回话的上限（秒）。**所有等待都必须有界**：一个连上却不说话的对端
#: 不许把 ``conf()`` 挂住。对面是活的话，这一句是微秒级的。
HELLO_TIMEOUT = 0.5

#: ``Owner.close()`` 等应答线程收摊的上限（秒）
_JOIN_TIMEOUT = 2.0

#: 两个 op —— 与「读」和「交一批声明」一一对应，没有第三个
#:
#: 注意这里**没有** ``sync``：攒批窗口是**每个引擎自己**的（§30），声明先在本地
#: 攒着，交出去时才走 ``OP_COMMIT``，``clean`` 只是这一批带的开关。窗口要是挪到
#: 写者身上，客户端显式配的 ``flush_window`` 就被静默忽略了。
OP_READ = "read"
OP_COMMIT = "commit"


# --------------------------------------------------------------------------- #
# 选主：端点 / 认证码 / 抢绑
# --------------------------------------------------------------------------- #


#: POSIX 上 ``AF_UNIX`` 的 ``sun_path`` 只有 **104 字节**（含结尾 NUL）。超了
#: ``ipc.Listener(address)`` 直接抛错，而 :meth:`Channel._attach` 是**尽力而为**的
#: —— 于是专职写者**静默失效**，所有请求退到就地执行。macOS 的 pytest ``tmp_path``
#: （``/private/var/folders/…``）一测就超，所以这里再留点余量。
SOCKET_PATH_LIMIT = 100

#: 短端点的兜底目录。``S108``/``B108`` 防的是「把文件写进共享的 ``/tmp``」——
#: 这里正是要用它，而且端点落在那下面**只有本人可进**的子目录里；只在 ``TMPDIR``
#: 自己被设得离谱长、第一个候选装不下时才轮到它。
_FALLBACK_TMP = Path("/tmp")  # noqa: S108  # nosec B108


def _short_socket(home: Path, stem: str) -> Path:
    """路径太长时的**短端点**：临时目录下一个只有本人可进的子目录。

    名字仍然只由**解析后的配置目录 + 值文件名**决定（哈希），所以同一个
    ``(目录, 文件名)`` 在每个进程里算出的端点完全一样 —— 只是它不再住在配置目录里。
    ``stem`` 也要进哈希：同一目录上的两个引擎文件名不同时，短端点不能撞在一起。
    ``0o700`` 那个子目录是补回来的隔离：端点在共享的临时目录里，别人能连上就等于能冒充写者。
    """
    seed = f"{home}\x00{stem}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:_HASH_CHARS]
    uid = getattr(os, "getuid", lambda: 0)()  # Windows 没有 getuid；这条分支也不在 Windows 上走
    for base in (Path(tempfile.gettempdir()), _FALLBACK_TMP):
        directory = base / f"onconf-{uid}"
        candidate = directory / f"onconf-{digest}.sock"
        with contextlib.suppress(OSError):
            directory.mkdir(mode=0o700, exist_ok=True)
            # ``exist_ok`` **不修**一个已经存在的松权限目录，所以每个进程都顺手
            # ``chmod`` 一遍 —— 「隔离在临时目录里补回来」这句话得有凭据。
            directory.chmod(0o700)
        if len(str(candidate).encode("utf-8")) <= SOCKET_PATH_LIMIT:
            return candidate
    return _FALLBACK_TMP / f"onconf-{digest}.sock"  # pragma: no cover - TMPDIR 长到离谱时


def endpoint_for(home: Path, stem: str = DEFAULT_FILE_NAME) -> str:
    r"""端点名：**只由配置目录 + 值文件名决定**，别的什么都不看。

    Windows 把名字放进全局命名空间，所以只能哈希（路径塞不进去）；POSIX 用配置
    目录里的 socket 文件，按构造就已经隔离了。

    Windows 上先 ``normcase``：``D:\a`` 与 ``d:\a`` 是同一个目录，但字符串不同
    —— 不折叠大小写就会出现**两个写者写着同一个目录**，那正是这个模块要防的事。
    ``stem`` 也进哈希：同一目录、不同值文件名是两个引擎，不该共用一个写者。

    **``stem`` 就是这里的全部身份**：``file_type`` 与 ``no_one_file`` 不进端点。
    于是同一 ``(home, file_name)`` 上的两个引擎会共用一个写者，请求由**写者自己的**
    引擎执行 —— 客户端如果用了不同的值文件类型或多文件开关，落盘会按写者的布局走。
    这是刻意的取舍：把类型也塞进端点会让两个引擎同时重写同一份词表。约定是
    「一个 ``(home, file_name)`` 只有一种值文件配置」，README 的已知限制里写着。

    POSIX 上路径太长时改用 :func:`_short_socket` 的短名字（仍然只由这两样决定）。
    不这么做的话，macOS 上稍微深一点的路径就会让专职写者失效 —— 那是**静默**的，
    只有从「所有请求都退到就地执行」才能看出来。
    """
    if os.name == "nt":
        seed = f"{os.path.normcase(str(home))}\x00{stem}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:_HASH_CHARS]
        return f"{_PIPE_PREFIX}{digest}"
    natural = str(home / SCHEMA_DIR / f"{stem}.sock")
    if len(natural.encode("utf-8")) <= SOCKET_PATH_LIMIT:
        return natural
    return str(_short_socket(home, stem))


def authkey_for(home: Path, stem: str = DEFAULT_FILE_NAME) -> str:
    """认证码（十六进制）：**原子创建**，保证并发的首次调用者拿到的是同一把。

    「创建」和「写入」必须是一步。先 ``O_CREAT|O_EXCL`` 再 ``write`` 会留下一个
    **空文件**的窗口：并发的读者正好读到这里就拿到空字符串，两边的钥匙分叉，
    其中一个从此连不上自己刚绑上的端点 —— 这种 bug 只在并发下露头，最难查。
    ``os.link`` 正是要的那个原语：目标已存在就失败，而内容**早就写好了**。
    """
    path = key_path(home, stem)
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


def claim(home: Path, stem: str = DEFAULT_FILE_NAME) -> ipc.Listener | None:
    """抢绑端点：抢到就是写者，返回 ``Listener``；抢不到返回 ``None``。

    **这个返回值就是选举结果**，没有第二次确认 —— 抢绑是原子的。
    """
    address = endpoint_for(home, stem)
    if os.name != "nt":  # pragma: no cover - 本机是 Windows；POSIX 见下面两个函数
        _ensure_endpoint_dir(address)
        _reap_stale(address)
    try:
        return ipc.Listener(address)
    except OSError:
        return None


def _ensure_endpoint_dir(address: str) -> None:
    """POSIX：socket 文件得落在一个**已经存在**的目录里 —— ``bind`` 不会替你建。

    ``<home>/schema`` 不存在时 ``bind`` 就是 ``ENOENT``，而 :func:`claim` 把它翻译成
    「抢不到」，于是**第一个写者都当不上**、所有请求退到就地执行（Linux CI 上 16 条
    测试一起倒）。这一步以前没有：目录是靠 :func:`claim` 顺手调 :func:`authkey_for`
    的 ``mkdir`` 建出来的 —— 一个副作用。写者本来就会自己读钥匙，所以那个调用一挪走，
    这个隐式依赖就露出来了。macOS 上看不见：那边走了短端点，目录由 :func:`_short_socket`
    建。Windows 不用这一段：命名管道不进文件系统。
    """
    with contextlib.suppress(OSError):
        Path(address).parent.mkdir(parents=True, exist_ok=True)


def connect(
    home: Path, *, stem: str = DEFAULT_FILE_NAME, timeout: float = HELLO_TIMEOUT
) -> Conn | None:
    """连当前写者并打完招呼；没人在、或没人答话，都返回 ``None``。

    **两次有界**：``Client(...)`` 不再做握手（无超时的那一步已经搬走），
    我们自己的招呼又带 ``timeout``。所以这个函数不会把调用方挂死。
    """
    if not key_path(home, stem).exists():
        return None
    return _hello(endpoint_for(home, stem), authkey_for(home, stem), timeout)


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


def _endpoint_is_alive(address: str) -> bool:  # pragma: no cover - POSIX 专用
    """端点上**有没有人在听** —— 只 ``connect``，不打招呼、不认证。

    这里**不能**拿 :func:`_hello` 当探活：打招呼是有状态的，写者得先 ``accept()``
    再读那句 ``hello``。写者一忙（正在做一轮读改写），问候就排在那儿等到超时 ——
    于是**活写者的端点被判成残骸删掉**，下一个进程绑上来，同一个目录就有了两个
    写者。那正是这个模块存在的理由。

    ``ipc.Client(address)`` 不带 ``authkey`` 就**不做**挑战应答（3.14 起
    ``authkey=None`` 不再被补成进程默认钥匙），构造函数里只剩一次即时的
    ``connect(2)``：有人在听就成功，文件只是崩溃留下的残骸就当场拒绝。
    """
    try:
        conn = ipc.Client(address)
    except OSError:
        return False
    conn.close()
    return True


def _reap_stale(address: str) -> None:  # pragma: no cover - POSIX 专用
    """POSIX：写者**崩了**会在磁盘上留下 socket 文件，得先探活再决定清不清。

    只在**没人听**的时候才清。活着、只是一时没空理的写者必须原样留着：删掉它的
    端点不会让它下班，只会让它变成一个还在写文件的幽灵。
    （Windows 不需要这段：命名管道随进程消失，不会有残留。）
    """
    path = Path(address)
    if not path.exists():
        return
    if _endpoint_is_alive(address):
        return
    with contextlib.suppress(OSError):
        path.unlink()


# --------------------------------------------------------------------------- #
# 线上格式
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Request:
    """一次请求：要么读一个键，要么交一批声明（客户端攒够了的那些）。"""

    op: str
    key: str = ""
    decls: tuple[Decl, ...] = ()
    clean: bool = False
    #: **发起方**的 pid 与身份。审计记的是「谁发起的」而不是「谁执行的」（§20.3），
    #: 所以这两个字段跟着请求过线；声明自己的调用点则在 :attr:`Decl.at` 上。
    #: 两者都是 ``None`` 表示**本进程自己发起的**请求（只有这时才用执行点的身份）；
    #: 远端来的请求即便没设身份也只是「没有身份」，不该被冠上写者的服务名。
    pid: int | None = None
    identity: str | None = None


#: 写者的执行入口。``Engine`` 把自己的**就地执行**方法以绑定方法的形式传进来，
#: 所以引擎不必为了这个开一个公开面（那会变成第三个 API 面）。
_Exec = Any


#: 异常**按名字过线**，不让异常对象过线：那等于让写者隔空给客户端构造对象，
#: 而我们连 pickle 都不肯为文件内容开（§26.3）。认识的名字就还原成原类型，
#: 不认识的一律降级成 ``ConfError`` —— 类型丢了，但「为什么」一点不少。
_ERROR_KINDS: dict[str, type[ConfError]] = {
    cls.__name__: cls
    for cls in (
        LockTimeoutError,
        KeyNotRegisteredError,
        KeyHasNoValueError,
        ConfError,
    )
}

#: 远端失败的内部标记。**不能用 ``None``**：``commit`` 成功时返回的就是 ``None``。
_RETRY = object()


# --------------------------------------------------------------------------- #
# 写者
# --------------------------------------------------------------------------- #


class Owner:
    """本进程里的那个写者：**一个引擎，一个端点，一个应答线程**。

    端点一绑上，别的进程就只能发请求，磁盘上的读改写从此只有这一个线程在做。
    """

    def __init__(self, engine: Engine, listener: ipc.Listener, execute: _Exec) -> None:
        self.engine = engine
        self._execute = execute
        self._listener = listener
        self._key = authkey_for(engine.home, engine.file_name)
        #: 写者自己的两个调用方（主线程 + 应答线程）也要互斥：引擎不是线程安全的
        self._lock = threading.Lock()
        self._closed = threading.Event()
        #: 还开着的会话连接。``close()`` 靠它把卡在 ``recv()`` 的会话线程叫醒。
        self._sessions: set[Conn] = set()
        self._sessions_lock = threading.Lock()
        self._worker: threading.Thread | None = None

    @classmethod
    def claim(cls, engine: Engine, execute: _Exec) -> Owner | None:
        """试着当写者；抢不到说明别人已经在当，返回 ``None``。"""
        listener = claim(engine.home, engine.file_name)
        return None if listener is None else cls(engine, listener, execute)

    def start(self) -> None:
        """开应答线程。**必须赶在客户端连上来之前** —— 见模块文档那个死等的坑。"""
        if self._worker is None:
            self._worker = threading.Thread(
                target=self._serve,
                name="onconf-owner",
                daemon=True,
            )
            self._worker.start()

    def submit(self, request: Request) -> Any:
        """写者自己的请求：本地直调，不绕 IPC，也不给自己的 IPC 排队。"""
        with self._lock:
            return self._execute(request)

    def close(self) -> None:
        """下班。**这里的顺序就是全部要点**，而且只能是这样：

        1. 举旗 ``_closed``；
        2. 关掉所有还开着的会话连接 —— 会话线程要是卡在 ``recv()``，这样才醒；
        3. 开一条空连接，叫醒卡在 ``accept()`` 里的线程；
        4. **等它真的退出**；
        5. 这时才 ``listener.close()``。

        第 5 步必须排在第 4 步后面。``PipeListener.accept()`` 是**先造一个备用
        实例、再去阻塞等待**的（见模块文档第三个坑）：线程要是在 ``close()``
        之后才进 ``accept()``，那个备用实例就**没人关**了 —— 端点名一直挂着，
        下一个进程永远抢绑不到（写者真空）。先 join 掉线程，就没有这个窗口。
        """
        self._closed.set()
        with self._sessions_lock:
            live = list(self._sessions)
        for conn in live:
            with contextlib.suppress(OSError):
                conn.close()
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
            ipc.Client(endpoint_for(self.engine.home, self.engine.file_name)).close()

    # ---------------------------------------------------------------- 应答线程

    def _serve(self) -> None:
        """只干一件事：**接**。接到就交给一个会话线程，立刻回去接下一个。

        绝不能在这里 inline 服务：``_handle`` 会一直占着 ``recv``，于是客户端 A
        的整条会话把端口堵死 —— 客户端 B 连得上，却**没人跟它握手**，它只会以为
        「没有写者」。这条是踩出来的：单客户端时看不出来，一多客户端就必炸。
        """
        while not self._closed.is_set():
            try:
                conn = self._listener.accept()
            except OSError, EOFError:
                return
            session = threading.Thread(target=self._session, args=(conn,), daemon=True)
            session.start()

    def _session(self, conn: Conn) -> None:
        """一条连接一个会话线程，活到这条连接结束（或写者下班）。"""
        with self._sessions_lock:
            self._sessions.add(conn)
        try:
            if self._greet(conn):
                self._handle(conn)
        finally:
            with self._sessions_lock:
                self._sessions.discard(conn)
            with contextlib.suppress(OSError):
                conn.close()

    def _greet(self, conn: Conn) -> bool:
        """验一下对面的认证码，回一句欢迎。**有界**：不说话的连接直接放弃。"""
        try:
            if not conn.poll(HELLO_TIMEOUT):
                return False
            hello = conn.recv()
        except Exception:  # noqa: BLE001 - 坏客户端不许带走会话线程
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
            except Exception:  # noqa: BLE001 - 坏客户端不许带走会话线程
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
    """**一个引擎一条通道**（不是「一个目录一条」）。

    三层，逐层退让：

    1. **我是写者** ⇒ 本地直调（不绕 IPC）；
    2. **别人是写者** ⇒ 走 IPC；
    3. **两条都不通** ⇒ 退回直写（OS 锁还在，是保险）。

    第 3 层是安全网，不是常规路径：它让「端点建不出来」这种环境问题退化成
    「性能差一点」，而不是「库不能用」。正确性从来不靠 IPC 撑着。

    按引擎而不是按目录管理，是因为同一进程里完全可能有两个引擎指着同一个配置
    目录（测试里到处都是）。按目录的话，第二个引擎会被塞进第一个引擎的通道里，
    它的声明就落到了**另一个引擎**的声明集上。
    """

    def __init__(
        self,
        engine: Engine,
        execute: _Exec,
        *,
        on_link: _OnLink | None = None,
        on_send: _OnSend | None = None,
    ) -> None:
        self.engine = engine
        self._execute = execute
        #: 两个可选回调，让 ``Engine`` 能记 ``[Link]`` / ``[Send]``（§20 的进程结构）。
        #: 通道不直接碰引擎的审计器 —— 那是引擎的私事，而且 ``_owner`` 也在就地导入它。
        self._on_link = on_link
        self._on_send = on_send
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
            self._client = connect(self.engine.home, stem=self.engine.file_name)
            if self._client is not None:
                self._notify_link("connect")
                return
            writer = Owner.claim(self.engine, self._execute)
            if writer is None:
                # 抢绑失败 ⇒ 有人在我们探测之后绑上了。这是正常竞态，再连一次。
                self._client = connect(self.engine.home, stem=self.engine.file_name)
                self._notify_link("connect" if self._client is not None else "fallback")
                return
        except OSError, ConfError:
            self._client = None
            self._writer = None
            self._notify_link("fallback")
            return
        self._writer = writer
        writer.start()
        self._notify_link("bind")

    # -------------------------------------------------------------------- 出口

    def _notify_link(self, op: str) -> None:
        """告诉引擎「关系定下来了」。回调是尽力而为的，不许影响选主。"""
        if self._on_link is not None:
            self._on_link(op)

    def _notify_send(self, request: Request) -> None:
        """告诉引擎「这一次请求真的发出去了」。"""
        if self._on_send is not None:
            self._on_send(request)

    def is_mine(self) -> bool:
        """本通道的写者是不是本引擎自己。

        **刻意不加锁**：路由会在持着 ``_lock`` 时重入这一问（写者的执行入口会
        回到引擎，引擎再问一次「我是不是写者」），加锁就是自己跟自己死锁。
        这个字段只在 ``_attach`` / ``close`` 里改，而那两处都持锁，所以读到的是
        一个稳定的答案。
        """
        return self._writer is not None

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
            # 退到底：就地干。OS 锁还在，别的进程进不来，正确性不靠 IPC 撑着。
            return self._execute(request)
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

    def _try_remote(self, client: Conn, request: Request) -> Any:
        """发一轮往返。断了返回 :data:`_RETRY`，业务异常照原样抛回去。

        这里也是唯一「真的过了 IPC」的地方，所以 ``[Send]`` 由它触发 ——
        退到就地执行那条路没有「发送」这回事。重发（写者换了人）会再记一行：
        那是真的又发了一次。
        """
        self._notify_send(request)
        try:
            client.send(request)
            status, payload = client.recv()
        except EOFError, OSError:
            return _RETRY
        if status == "ok":
            # 这一轮是**别的进程**执行的：客户端据此把自己终端那一份补上
            # （审计文件不重复写，那份归执行点，见 ``Engine._collect_remote``）。
            # 认识 ``Reply`` 才补标记：版本错配时拿到别的形状，宁可当普通值返回，
            # 也不要在这里炸出一个 reachable 不到的 ``TypeError``。
            return replace(payload, remote=True) if isinstance(payload, Reply) else payload
        name, message = payload
        raise _ERROR_KINDS.get(name, ConfError)(message)
