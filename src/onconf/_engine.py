# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引擎装配：把核心、词表、后端接成一个能用的库。

## 提交点：默认**当场落盘**，攒批窗口按需开

``flush_window`` **默认 0** —— 声明立刻落盘。「文件是绝对权威」这条一旦成立，
**写入的可见性延迟就是对它的削弱**：读那个文件的人（同进程、派生进程、用户的编辑器）
看不到你刚声明的东西。

需要攒批的是**启动期一口气声明很多键**这种突发场景，而那正是调用方自己知道的事：

.. code-block:: python

    AutoConf(home="…", flush_window=0.2)  # 攒一批再写

窗口一旦开启，落盘发生在这些提交点：**窗口到期 / 一次读 / ``flush()`` / ``sync()`` /
进程退出**。

## 写权限：属主进程，派生的一律只读

引擎不做并发协调 —— 没有锁、没有独立写者进程、没有 IPC、没有端点、没有待折日志。
取而代之的是一条**由进程树保证**的规则：**创建这个实例的进程是属主**，它读写、生成词表；
从它派生出来的进程一律只读。

判据不是探测、不是约定，而是一次 pid 核对：实例记下创建它的 pid，落盘前比一次 —— 对不上
就说明这个实例是 ``fork`` 出来的（内存被复制了，写权不该跟着复制）。

**边界**：``spawn`` 出来的进程（Windows 上 ``multiprocessing`` 的默认方式，以及任何
``subprocess``）是**全新进程**，它自己建实例、自己就是属主 —— pid 核对在这种平台上不触发。
要让它只读，靠的是调用方自己不写，或者干脆用命令行先把配置落好、运行期全部只读。

于是三种部署形态都有确定答案：

* 单进程：创建者就是属主，读写；
* 主进程 + 子进程：主进程写，派生出来的子进程天然只读；
* N 个平级进程：各自都是属主 —— **不在保障范围**，配置归命令行离线写
  （``onconf build`` / ``sync``）。

代价写在明面上：**同一时刻只有一个写者是调用方的部署责任**。引擎不探测、不等待、不加锁、
不猜。口径与取舍见 ``docs/design/concurrency.md``。

攒批窗口是**每个引擎自己**的：声明先在本地攒着，到提交点才一次性交出去。

## 读：指纹校验 + 按需重读

读**任何进程都能做**。代价是「读的时候属主可能正在替换文件」，所以两件事必须同时成立：

* **读之前先比指纹**（``mtime`` + 大小），文件变过就重读。少了这一步，进程内存会
  永远停在第一次加载的样子 —— 属主进程后来的写、用户的手改，它都看不见，
  「值每次从文件重新读」就成了一句空话；
* **读的寻址按被读的键自己决定**加载哪个值文件。多文件模式下，一个进程完全可以读
  别人声明过的键，只看「本进程声明过哪些路径段」会读到词表默认值而不是文件值。

## 落盘是原子的，而且不碰不该碰的字节

值文件与词表都经 :func:`_atomic_write_text`：同目录临时文件 → ``fsync`` →
``os.replace``，再 ``fsync`` 父目录（POSIX）。行尾按文件原本的样子写回，所以
Windows 上不会把用户的 LF 文件偷偷改成 CRLF；已存在文件的权限位也原样保留。

替换那一步带**有界重试**（:func:`_replace_with_retry`）：Windows 上 ``os.replace``
撞上一个正在读这个文件的进程会报 ``ERROR_ACCESS_DENIED``，而读者不参与互斥、也不该
参与，所以由替换这一侧等它几百毫秒。

## 目录约定（对齐真实产物）

::

    <home>/settings.json          值文件（用户手改）；名字由 ``file_name``、后缀由 ``file_type``
    <home>/schema/settings.json   词表（**库自己的资产**，随便重写；一份，与值文件个数无关）
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
``audit=True`` 再加一份 append-only 的 ``<home>/audit.log``。级别与对齐规则见
:mod:`onconf._audit`。

**谁发起谁记账**：这里没有第二个执行点，所以记录里的 ``pid`` / ``id=``（身份）/
``at=``（调用点）都取自本进程。审计文件可能被多个进程同时追加 —— 那是预期的，
不是缺陷：``O_APPEND`` 加上每行自带进程信息就足以解析。
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _env_backend, _json_backend, _paths, _toml_backend, _yaml_backend
from ._audit import (
    AUDIT_NAME,
    TERMINAL_STDERR,
    AuditLog,
    Record,
    call_site,
    error_kind,
)
from ._core import MISSING, Action, Decl, is_directive, read_value, reconcile, undeclared
from ._vocab import Vocabulary
from .errors import ConfError


if TYPE_CHECKING:
    from collections.abc import Iterable


HOME_ENV = "ONCONF_HOME"
#: 值文件名的缺省主干。**可被 ``file_name`` 参数覆盖**，所以它只是缺省值，
#: 不再是「写死的名字」。
DEFAULT_FILE_NAME = "settings"
#: 兼容旧名：历史上它是写死的文件名主干，现在与 :data:`DEFAULT_FILE_NAME` 同源。
VALUES_STEM = DEFAULT_FILE_NAME
SCHEMA_DIR = "schema"
#: 缺省值文件类型：**字面 ``"json"``**，不是空串隐含出来的 json。
DEFAULT_FILE_TYPE = "json"
#: 缺省值文件的 ``$schema`` 指针（多文件模式下每个文件按自己的层级算出相对路径）。
SCHEMA_POINTER = f"{SCHEMA_DIR}/{DEFAULT_FILE_NAME}.json"

#: 攒批窗口的默认值（秒）。**0 = 每次声明当场落盘**。
#: 见模块文档：默认立即是语义决定，不是保守。
DEFAULT_FLUSH_WINDOW = 0.0

#: Windows 上 ``os.replace`` 因为**并发读者**失败的错误码：拒绝访问 / 共享冲突 /
#: 锁冲突。读者不参与互斥（见模块文档），所以只能由替换这一侧让一步。
_RETRYABLE_WINERRORS = frozenset({5, 32, 33})

#: 替换的重试次数与间隔（秒）。最坏情况约 0.2 秒，实测足以穿过读者的读窗口。
_REPLACE_ATTEMPTS = 40
_REPLACE_INTERVAL = 0.005

#: 属主 pid 沿**环境变量**传给子进程：``fork`` 靠继承内存就能看出来（pid 对不上），
#: 而 ``spawn`` / ``subprocess`` 出来的是全新进程、什么都不继承 —— 只能靠这个标记
#: 告诉它「你已经属于某个属主了」。它是**可信输入**（同 ``ONCONF_HOME``）。
OWNER_ENV = "ONCONF_OWNER_PID"

#: 进程内的互斥表：同一份值文件上的多个实例、以及同一实例的多个线程，共用一把锁。
#: **纯内存**，不落任何文件、不碰操作系统 —— 跨进程那条禁令仍然是调用方的部署责任。
_INSTANCE_LOCKS: dict[tuple[str, str, str], threading.RLock] = {}
_INSTANCE_LOCKS_GUARD = threading.Lock()


def _instance_lock(home: Path, file_name: str, suffix: str) -> threading.RLock:
    """取（必要时建）某份值文件在**本进程内**的锁。

    键是 ``(配置目录, 值文件名主干, 后缀)``：同一份值文件共锁，不同的互不影响 ——
    拿一个全局大锁会把互不相干的配置目录也串起来。
    """
    key = (os.path.normcase(str(home)), file_name, suffix)
    with _INSTANCE_LOCKS_GUARD:
        lock = _INSTANCE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _INSTANCE_LOCKS[key] = lock
        return lock


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
    * **替换那一步重试**：见 :func:`_replace_with_retry` —— 读者不参与互斥，
      Windows 上并发读者会让替换失败。
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
        _replace_with_retry(tmp, path)
        replaced = True
    finally:
        if not replaced:
            with contextlib.suppress(OSError):
                tmp.unlink()
    _fsync_directory(path.parent)


def _replace_with_retry(tmp: Path, target: Path) -> None:
    """``os.replace`` + **有界重试**（Windows）。

    Windows 上替换一个**正被别人打开**的文件会失败（``ERROR_ACCESS_DENIED`` 之类），
    而 Python 的 ``os.open`` 不带 ``FILE_SHARE_DELETE``。我们**故意不让读者参与互斥**
    （见模块文档：读要快，而且 Windows 没有共享锁），所以只能由替换这一侧等一小会儿。
    读者的读窗口是微秒级的，实测多进程持续提交时重试几百毫秒就足够。

    只在 Windows 的这三个错误码上重试：POSIX 的 ``PermissionError``（不可变文件、
    权限不足）是真实错误，重试没有意义也不该掩盖它。
    """
    for attempt in range(1, _REPLACE_ATTEMPTS + 1):
        try:
            tmp.replace(target)
        except PermissionError as exc:
            retryable = (
                os.name == "nt" and getattr(exc, "winerror", None) in _RETRYABLE_WINERRORS
            )
            if not retryable or attempt == _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_INTERVAL)
        else:
            return


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

    ``loaded`` 区分「读过这个文件」与「只是知道它的路径」：指纹只看**读过**的文件，
    而读一个键之前必须先把它所属的文件读进来（否则会拿着空事实去查词表，
    把「文件里有值」误报成「只有默认值」）。
    """

    key: str
    path: Path
    text: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    newline: str = field(default_factory=lambda: os.linesep)
    loaded: bool = False


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
        #: 创建这个实例的进程 = **属主**。两个来源：``fork`` 复制了内存（pid 对不上），
        #: 或者 ``spawn`` / ``subprocess`` 出来的子进程读到了父进程留下的 ``ONCONF_OWNER_PID``。
        inherited = os.environ.get(OWNER_ENV)
        if inherited is not None and inherited.isdigit():
            self._owner_pid = int(inherited)
        else:
            self._owner_pid = os.getpid()
            os.environ[OWNER_ENV] = str(self._owner_pid)
        #: **进程内**互斥：同一份值文件上的多个实例（或同一实例的多个线程）共用这一把。
        self._lock = _instance_lock(self.home, self.file_name, self.suffix)
        self.audit = audit
        self.flush_window = flush_window
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
        #: 最近一条「已经记过账」的异常（避免同一件事在同一个进程里记两遍）。
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

    def _assert_owner(self) -> None:
        """落盘前的闸门：**只有创建这个实例的进程**能写。

        「同一时刻只有一个写者」这条保证由**进程树**给，不需要谁发誓：``fork`` 会把内存
        复制给子进程，但写权不该跟着被复制，所以 pid 对不上就一律只读。

        当场报错，不静默降级：派生进程第一次想写的时候就会炸，而且错误里写着两条出路。
        N 个**平级**进程各自建实例不在保障范围 —— 那是部署问题，正确姿势是用命令行
        离线把配置写好，运行期全部只读。
        """
        if os.getpid() != self._owner_pid:
            raise ConfError(
                f"这个引擎实例是从 pid={self._owner_pid} 派生出来的：派生进程只读。"
                "要改配置请让属主进程写，或者用命令行的 onconf build / sync 离线写。"
            )

    def read(self, key: str) -> Any:
        """读一个配置项。

        四步都不能省：先把待提交的声明交出去（否则读不到自己刚声明的事实），
        再把**这个键所属的值文件**读进来（多文件模式下它未必在本进程的声明集里），
        最后比一次指纹 —— 属主进程或用户的手改过文件就重读，绝不拿陈旧内存当事实。
        """
        with self._lock:
            self._ensure_started()
            self._load_audited(item=key)
            self._commit_pending()  # 先把自己的待写交出去，否则读不到自己刚声明的事实
            self._open_for(key)
            self._reload_if_changed()
            return self._read_audited(key)

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
        with self._lock:
            self._assert_owner()
            self._ensure_started()
            self._load_audited(item=key)
            decl = Decl(key=key, value=value, doc=doc, at=at)
            self._pending[key] = decl
            self._decls[key] = decl

            if self.flush_window <= 0 or self._window_expired():
                self._commit_pending()
            elif self._window_started is None:
                self._window_started = time.monotonic()

            return self._effective(key, decl)

    # ------------------------------------------------------------------ 提交点

    def flush(self) -> None:
        """把待提交的声明交出去，并收口日志。**不删除任何键。**

        运行期没有删除动作（见 :func:`onconf._core.reconcile`），所以它与
        :meth:`sync` 现在是同一件事。
        """
        with self._lock:
            self._commit_pending()
            self._audit.close_txn()

    def sync(self) -> None:
        """完整提交点：把待提交的声明交出去，并收口日志。

        「完整提交点」这个名字留着是为了语义（这里期望集确实是完整的），但它**不再
        意味着清理** —— 删除只在命令行的收敛路径上发生，判据见
        :func:`onconf._core.undeclared`。
        """
        self.flush()

    def close(self) -> None:
        """收口日志。

        **它不是提交点**：攒着的声明要在 ``flush()`` / ``sync()`` 里才交出去；
        ``atexit`` 那条路会先 ``sync()`` 再 ``close()``，但直接调 ``close()``
        （``flush_window > 0`` 时）会把还没交的声明丢掉。
        """
        self._audit.close_txn()

    # ---------------------------------------------------------------- 启动留痕

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

    def _open_for(self, key: str) -> None:
        """把**这个键所属**的值文件读进来（没读过才读）。

        读的寻址必须按被读的键自己决定：多文件模式下，一个进程完全可以读别人声明的键，
        而它的路径段不在本进程的声明集里 —— 只看声明集就会拿着空事实去查词表，
        把「文件里有值」误报成「只有默认值」。
        """
        path_part = self._address(key)[0]
        if not self._file_for(path_part).loaded:
            self._load_file(path_part)

    # ------------------------------------------------------------ 执行留痕

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

    def _window_expired(self) -> bool:
        if self._window_started is None:
            return False
        return (time.monotonic() - self._window_started) >= self.flush_window

    def _commit_pending(self) -> tuple[Record, ...]:
        """提交一批声明。**对账动作同时也是审计记录**。

        返回这一批产生的记录；真正的输出在 :meth:`onconf._audit.AuditLog.close_txn`
        里完成 —— 它顺手把攒在同一个事务里的读一起收口，所以批次内能对齐。

        失败必须留痕：后端拒绝一个值……都先记一条 ``[E]`` 再原样抛出，不静默吞掉。
        """
        self._ensure_loaded()
        self._window_started = None
        if not self._pending:
            return ()  # 读路径走到这里：没有待写，不需要写权限

        self._assert_owner()
        batch = tuple(self._pending.values())
        self._pending.clear()
        if not self._decls:
            return ()

        records: list[Record] = []
        try:
            # 属主是唯一的写者，所以这里不需要任何跨进程互斥。重读仍然要：用户的手改
            # 或者别的属主（部署违规时）都可能动过文件，指纹对不上就重载。
            self._reload_if_changed()
            actions = self._reconcile_all(list(self._decls.values()))
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

    def _reconcile_all(self, decls: list[Decl]) -> list[Action]:
        """**按值文件分组**做对账，再拼成一份动作清单。

        分组不能省：一个文件的事实只能对**属于它**的那些声明，拿全部事实去对全部声明
        会让 A 文件里的键看起来像 B 文件的东西。分组之后每个文件各自跑一遍，期望集
        仍是全局的那一份。

        加载范围只到「当前声明集引用到的文件」：磁盘上其它值文件不归这个引擎管，
        一个字节都不会动。
        """
        groups: dict[str, list[Decl]] = {}
        for decl in decls:
            groups.setdefault(self._address(decl.key)[0], []).append(decl)

        actions: list[Action] = []
        for path_part, group in sorted(groups.items()):
            state = self._file_for(path_part)
            if not state.loaded:
                self._load_file(path_part)
            facts = {
                self._file_key(path_part, inner): value for inner, value in state.facts.items()
            }
            actions.extend(reconcile(group, facts, self._vocab.as_dict()))
        return actions

    def _remove_undeclared(self) -> list[Action]:
        """**命令行专用**：删掉声明集里没有的键。

        这是运行期唯一不走的删除路径 —— 判据「事实里有、声明集里没有」只有在期望集
        完整时才成立，而完整只出现在「一次拿到全部声明」这种场合：命令行静态扫描整个
        项目，得到的正好是一份完整声明集。所以它不挂在 ``conf()`` 的任何一条出口上，
        只由 ``onconf sync`` 调用。

        动手前必须重读：删的是**磁盘上的**事实，不是内存里那份。
        """
        with self._lock:
            self._assert_owner()
            self._ensure_loaded()
            self._reload()
            removals = undeclared(
                self._facts_view(),
                set(self._decls),
                # 指令豁免要按**文件内**的键名判：多文件模式下扁平键带着路径段前缀。
                is_directive=lambda key: is_directive(self._address(key)[1]),
            )
            if removals:
                self._commit(removals)
                self._action_records(removals, ())
            self._audit.close_txn()
            return removals

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
            # 必须重读磁盘：登记是写到词表文件里的，内存里这份还是旧的 ——
            # 不重读就会把「登记了但没值」误报成「没登记」。
            self._commit_pending()
            self._reload()
            return self._read_audited(key)
        return decl.value

    # ------------------------------------------------------------- 加载 / 落盘

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._reload()

    def _load_file(self, path_part: str) -> _FileState:
        """把一个值文件读进内存（不存在就是空状态），并标记它**读过了**。"""
        state = self._file_for(path_part)
        if state.path.exists():
            raw = state.path.read_bytes()
            state.newline = _detect_newline(raw)
            state.text = _decode_universal(raw)
            state.facts = self.backend.loads(state.text)
        else:
            state.text = None
            state.facts = {}
        state.loaded = True
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
        """已**读过**的每个值文件 + 词表的「指纹」，用来判断要不要重读。

        词表也必须看：只动词表的提交（例如「只登记不给值」）不会碰值文件，
        只看值文件就会漏掉它，然后把刚登记的键从词表里挤掉。
        """
        files = tuple(
            self._file_stamp(state.path)
            for _, state in sorted(self._files.items())
            if state.loaded
        )
        return (files, self._file_stamp(self.schema_path))

    def _reload_if_changed(self) -> None:
        """磁盘真的变过才重读，免得退化成每次全篇重读。

        读路径与写路径都调它：读的时候属主可能刚提交，写的时候更是必须看到最新事实。
        """
        if self._disk_stamp() != self._stamp:
            self._reload()

    def _reload(self) -> None:
        """从磁盘重读事实与词表。

        加载范围 = **默认值文件 + 这个引擎碰过的每个值文件**（声明集引用到的路径段，
        以及读过的键所属的文件）。默认文件必须永远在内 —— 它一个键都没被声明过时也是
        这个引擎的值文件，漏掉它就等于「空引擎不读任何文件」。
        """
        for path_part in sorted({"", *self._files}):
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
