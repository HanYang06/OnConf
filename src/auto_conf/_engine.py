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

    AutoConf(home="…", flush_window=0.2)   # 攒一批再写

窗口一旦开启，落盘发生在这些提交点：**窗口到期 / 一次读 / ``sync()`` / 进程退出**。
前三个**不做规则 1**（期望集可能还不完整，§29.1），只有 ``sync()`` 与进程退出做。

## 并发：OS 锁 + 锁内按需重读的读改写

多进程同时提交时，每个进程在锁里**重读一遍磁盘**再对账、再原子替换。
没有这一步就会出现「A 和 B 各自基于同一份旧内容写回，后写的把先写的整段盖掉」。
重读只在文件真的变过时才发生（比 mtime + size），所以单进程连续提交不会退化成
「每次都把整篇读一遍」。

锁用的是操作系统的锁（见 :mod:`auto_conf._lock`），所以进程崩溃时它会被自动释放，
不会留下死锁。

## 目录约定（对齐真实产物）

::

    <home>/settings.json          值文件（用户手改）
    <home>/schema/settings.json   词表（**库自己的资产**，随便重写）
    <home>/schema/settings.lock   锁的握手点（空文件；库里自己的簿记）

``<home>`` 由 ``home=`` 参数 / ``AUTO_CONF_HOME`` 环境变量 / 当前目录依次决定。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _env_backend, _json_backend, _toml_backend, _yaml_backend
from ._core import MISSING, Action, Decl, read_value, reconcile
from ._lock import exclusive
from ._vocab import Vocabulary
from .errors import ConfError, TypeConflictError


if TYPE_CHECKING:
    from collections.abc import Iterable


HOME_ENV = "AUTO_CONF_HOME"
VALUES_STEM = "settings"
SCHEMA_DIR = "schema"
SCHEMA_POINTER = f"{SCHEMA_DIR}/{VALUES_STEM}.json"
LOCK_SUFFIX = ".lock"

#: 攒批窗口的默认值（秒）。**0 = 每次声明当场落盘**。
#: 见模块文档：默认立即是语义决定，不是保守。
DEFAULT_FLUSH_WINDOW = 0.0

#: 后端模块必须提供同一组函数：
#: ``loads`` / ``iter_members`` / ``find`` / ``set_value`` /
#: ``append_key`` / ``delete_key`` / ``render``
_BACKENDS = {
    ".json": _json_backend,
    ".yaml": _yaml_backend,
    ".yml": _yaml_backend,
    ".env": _env_backend,
    ".toml": _toml_backend,
}

#: 只有「文件里能放一条 ``$schema`` 成员」的后端才吃得下词表指针（§28.6）。
#: ``.env`` / ``.toml`` 放不了成员 —— 硬塞只会让文件变成语法错误。
#: （TOML 那边另有 Taplo 的 ``#:schema`` 注释指令，留待后续。）
_POINTER_CAPABLE = frozenset({".json", ".yaml", ".yml"})

_VALUES_CANDIDATES = (
    "settings.yaml",
    "settings.yml",
    "settings.json",
    "settings.toml",
    "settings.env",
)


def default_home() -> Path:
    """按约定发现配置目录：显式参数 → 环境变量 → 当前目录。"""
    return Path(os.environ.get(HOME_ENV) or ".").resolve()


def _pick_values_file(home: Path) -> Path:
    for name in _VALUES_CANDIDATES:
        candidate = home / name
        if candidate.exists():
            return candidate
    return home / "settings.json"


def _type_matches(value: object, declared: type) -> bool:
    """声明期一致性校验用。``bool`` 是 ``int`` 的子类，要单独挡掉。"""
    if declared is int and isinstance(value, bool):
        return False
    return isinstance(value, declared)


class Engine:
    """一个配置目录 = 一个引擎。"""

    def __init__(
        self,
        home: str | os.PathLike[str] | None = None,
        *,
        audit: bool = False,
        flush_window: float = DEFAULT_FLUSH_WINDOW,
        lock_timeout: float = 10.0,
    ) -> None:
        self.home = Path(home).resolve() if home is not None else default_home()
        self.values_path = _pick_values_file(self.home)
        self.schema_path = self.home / SCHEMA_DIR / f"{self.values_path.stem}.json"
        self.lock_path = self.home / SCHEMA_DIR / f"{self.values_path.stem}{LOCK_SUFFIX}"
        self.audit = audit
        self.flush_window = flush_window
        self.lock_timeout = lock_timeout

        suffix = self.values_path.suffix.lower()
        if suffix not in _BACKENDS:
            raise ConfError(f"不认识的值文件后缀：{self.values_path.name}")
        self.backend = _BACKENDS[suffix]

        self._decls: dict[str, Decl] = {}
        self._pending: dict[str, Decl] = {}
        self._forced: set[str] = set()
        self._window_started: float | None = None
        self._vocab = Vocabulary()
        self._facts: dict[str, Any] = {}
        self._text: str | None = None
        self._stamp: tuple[Any, ...] | None = None
        self._loaded = False

    # ------------------------------------------------------------------ 两个面

    def __call__(
        self,
        key: str,
        value: Any = MISSING,
        *,
        doc: str | None = None,
        type: type | None = None,  # noqa: A002 - 参数名就是 API 的一部分
        force: bool = False,
    ) -> Any:
        """判别式（§17.7 + §15.1）。

        两个位置在文档里曾经打架过，这里把口径钉死：

        * ``conf(key)`` —— **什么声明元数据都没带** ⇒ 读；
        * ``conf(key, value)`` / ``conf(key, doc=…)`` / ``conf(key, type=…)``
          ⇒ 声明。后两者的 value 位是空的，即**只登记不给值**（「必填键」），
          紧接着按读的规则取值 —— 没配就报错，这正是「启动即校验必填项」的用法。

        也就是说，判据不是「value 位空没空」，而是**这一行到底在不在声明**。
        """
        if not isinstance(key, str):
            raise TypeError(
                f"键必须是字符串，拿到 {key.__class__.__name__}（{key!r}）。"
                "如果是 conf(conf(…)) 这种间接寻址，说明内层取到的值不是键名。"
            )
        if value is MISSING and doc is None and type is None:
            return self.read(key)
        return self.declare(key, value, doc=doc, type=type, force=force)

    def read(self, key: str) -> Any:
        """读一个配置项。**先把待写落盘**，否则可能读不到自己刚声明的事实。"""
        self._ensure_loaded()
        self.flush()
        return read_value(key, self._facts, self._vocab.as_dict()).value

    def declare(
        self,
        key: str,
        value: Any,
        *,
        doc: str | None = None,
        type: type | None = None,  # noqa: A002 - 参数名就是 API 的一部分
        force: bool = False,
    ) -> Any:
        """声明 / 写一个配置项。**返回当前生效值**（值文件优先，不是默认值）。

        ``type=`` 只做**声明期一致性校验**：它回答「你给的默认值和声明的类型对不对」，
        **不参与读取期转换**——引擎对值是透明的（值原样进出）。
        """
        if value is not MISSING and type is not None and not _type_matches(value, type):
            raise TypeConflictError(
                f"{key!r} 的默认值 {value!r} 不符合声明的类型 {type.__name__}"
            )

        self._ensure_loaded()
        decl = Decl(key=key, value=value, type=type, doc=doc)
        self._pending[key] = decl
        self._decls[key] = decl
        if force:
            self._forced.add(key)

        if self.flush_window <= 0 or self._window_expired():
            self.flush()
        elif self._window_started is None:
            self._window_started = time.monotonic()

        return self._effective(key, decl, force=force)

    # ------------------------------------------------------------------ 提交点

    def flush(self) -> None:
        """把待提交的声明落盘。**不做规则 1**（期望集可能还不完整，见 §29.1）。"""
        self._commit_pending(clean=False)

    def sync(self) -> None:
        """完整提交点：此刻**期望集完整**，规则 1（清理未知数据）才允许执行。"""
        self._commit_pending(clean=True)

    def _window_expired(self) -> bool:
        if self._window_started is None:
            return False
        return (time.monotonic() - self._window_started) >= self.flush_window

    def _commit_pending(self, *, clean: bool) -> None:
        self._ensure_loaded()
        self._window_started = None
        if not self._pending and not clean:
            return

        self._pending.clear()
        if not self._decls:
            return

        # 锁内重读：别的进程可能刚写过。少了这一步就是「各写各的，后写的盖掉先写的」。
        with exclusive(self.lock_path, timeout=self.lock_timeout):
            self._reload_if_changed()
            actions = reconcile(
                list(self._decls.values()),
                self._facts,
                self._vocab.as_dict(),
                force_keys=frozenset(self._forced),
                clean_unknown=clean,
            )
            self._forced.clear()
            if actions:
                self._commit(actions)

    def _effective(self, key: str, decl: Decl, *, force: bool) -> Any:
        """``declare`` 该返回什么：**当前生效值**（值文件优先）。

        这条修的是 Cairn 的 D5：声明返回默认值、取值返回文件值，会让同一键的相邻
        两行拿到不同结果。现在两者都以事实为准。
        """
        if not force and key in self._facts:
            return self._facts[key]
        if decl.value is MISSING:
            # 只登记不给值 ⇒ 登记得先算数（所以先落盘），再按读的规则取值
            self.flush()
            return read_value(key, self._facts, self._vocab.as_dict()).value
        return decl.value

    # ------------------------------------------------------------- 加载 / 落盘

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._reload()

    def _disk_stamp(self) -> tuple[Any, ...]:
        """值文件与词表的「指纹」（mtime + size），用来判断要不要重读。

        两个都看：只动词表的提交（例如「只登记不给值」）不会碰值文件，
        只看值文件就会漏掉它，然后把别人刚登记的键从词表里挤掉。
        """

        def one(path: Path) -> tuple[int, int] | None:
            try:
                stat = path.stat()
            except FileNotFoundError:
                return None
            return (stat.st_mtime_ns, stat.st_size)

        return (one(self.values_path), one(self.schema_path))

    def _reload_if_changed(self) -> None:
        """锁内重读 —— 但只在磁盘真的变过时才读，免得退化成每次全篇重读。"""
        if self._disk_stamp() != self._stamp:
            self._reload()

    def _reload(self) -> None:
        """从磁盘重读事实与词表。锁内调用，所以看到的是别人的最新提交。"""
        if self.values_path.exists():
            self._text = self.values_path.read_text(encoding="utf-8")
            self._facts = self.backend.loads(self._text)
        else:
            self._text = None
            self._facts = {}

        if self.schema_path.exists():
            raw = json.loads(self.schema_path.read_text(encoding="utf-8"))
            self._vocab = Vocabulary.from_schema(raw)

        self._stamp = self._disk_stamp()

    def _commit(self, actions: Iterable[Action]) -> None:
        """把对账动作落到两个文件上。"""
        creating = self._text is None
        original = self._text if self._text is not None else "{}"
        # 指针先补、动作后落 —— 反过来的话，等落完动作文件已经不是空对象了。
        text = self._ensure_schema_pointer(original)

        for action in actions:
            if action.kind in ("fill", "overwrite"):
                if self.backend.find(text, action.key) is None:
                    text = self.backend.append_key(text, action.key, action.value)
                else:
                    text = self.backend.set_value(text, action.key, action.value)
                self._facts[action.key] = action.value
            elif action.kind == "clean":
                if self.backend.find(text, action.key) is not None:
                    text = self.backend.delete_key(text, action.key)
                self._facts.pop(action.key, None)

        if creating or text != original:
            self.values_path.parent.mkdir(parents=True, exist_ok=True)
            self.values_path.write_text(text, encoding="utf-8")
            self._text = text

        # 词表是**库自己的资产**（§18.6），所以整篇重写是合法的，不需要外科手术
        self._vocab.apply(actions, list(self._decls.values()))
        self.schema_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema_path.write_text(
            json.dumps(self._vocab.to_schema(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._stamp = self._disk_stamp()

    def _ensure_schema_pointer(self, text: str) -> str:
        """值文件必须带 ``$schema`` 指针（能吃下的后端）。

        没有它，编辑器就不知道词表在哪 —— 用户面对一个几十项的配置只能靠翻文件
        （§27.3）。所以这条**不是新建时才补，是每次落盘都保证有**。
        它是**指令**不是配置键，不参与对账（§18.1）。

        ``.env`` 之类放不下成员的后端直接跳过：硬塞只会让文件变成语法错误。
        """
        if self.values_path.suffix.lower() not in _POINTER_CAPABLE:
            return text
        if self.backend.find(text, "$schema") is not None:
            return text
        seeded: str = self.backend.append_key(text, "$schema", SCHEMA_POINTER)
        return seeded
