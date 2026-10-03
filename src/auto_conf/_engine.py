# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""引擎装配：把核心、词表、后端接成一个能用的库。

## v1 的取舍（明确记下，不是遗漏）

**提交点是「立即」的，不是固定窗口。**

设计里 §13.3 的固定窗口（攒一批再写）是为了多进程下的写放大。
单进程 v1 不需要它，而且去掉之后语义反而更干净：

* ``conf(k, v)`` 当场对账 + 落盘 ⇒ 紧跟其后的 ``conf(k)`` 从文件读回来，
  天然满足 §17.9 R3「声明后立即读也走文件」；
* 写放大由**声明集哈希**（§18.7）挡住：声明集没变 ⇒ 整体跳过，一个字节都不写。

窗口 / WAL / 多进程留给 M3，接的是同一个 ``Engine``，接口不变。

## 目录约定（对齐真实产物）

``Cairn/config/`` 的真实布局是「值文件 + 它旁边的 schema 目录」，这里沿用::

    <home>/settings.json          值文件（用户手改）
    <home>/schema/settings.json   词表（**库自己的资产**，随便重写）

``<home>`` 由 ``home=`` 参数 / ``AUTO_CONF_HOME`` 环境变量 / 当前目录依次决定。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _env_backend, _json_backend, _yaml_backend
from ._core import MISSING, Action, Decl, read_value, reconcile
from ._vocab import Vocabulary
from .errors import ConfError, TypeConflictError


if TYPE_CHECKING:
    from collections.abc import Iterable


HOME_ENV = "AUTO_CONF_HOME"
VALUES_STEM = "settings"
SCHEMA_DIR = "schema"
SCHEMA_POINTER = f"{SCHEMA_DIR}/{VALUES_STEM}.json"

#: 后端模块必须提供同一组函数：
#: ``loads`` / ``iter_members`` / ``find`` / ``set_value`` /
#: ``append_key`` / ``delete_key`` / ``render``
_BACKENDS = {
    ".json": _json_backend,
    ".yaml": _yaml_backend,
    ".yml": _yaml_backend,
    ".env": _env_backend,
}

#: 只有「文件里能放一条 ``$schema`` 成员」的后端才吃得下词表指针（§28.6）。
#: ``.env`` 是纯 KEY=value，放不了 —— 硬塞只会让文件变成语法错误。
_POINTER_CAPABLE = frozenset({".json", ".yaml", ".yml"})

_VALUES_CANDIDATES = ("settings.yaml", "settings.yml", "settings.json", "settings.env")


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
    ) -> None:
        self.home = Path(home).resolve() if home is not None else default_home()
        self.values_path = _pick_values_file(self.home)
        self.schema_path = self.home / SCHEMA_DIR / f"{self.values_path.stem}.json"
        self.audit = audit

        suffix = self.values_path.suffix.lower()
        if suffix not in _BACKENDS:
            raise ConfError(f"不认识的值文件后缀：{self.values_path.name}")
        self.backend = _BACKENDS[suffix]

        self._decls: dict[str, Decl] = {}
        self._vocab = Vocabulary()
        self._facts: dict[str, Any] = {}
        self._text: str | None = None
        self._loaded = False

    # ------------------------------------------------------------------ 读

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
        self._ensure_loaded()
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
        self._decls[key] = decl

        # 增量声明：**只对这一个键**做补写 / 覆盖 / 补元数据。
        # 绝不在此刻做规则 1（清理未知数据）—— 期望集还不完整，
        # 此时清理会把文件里「还没声明到」的键全删掉。见 _core.reconcile 的说明。
        actions = reconcile(
            [decl],
            self._facts,
            self._vocab.as_dict(),
            force_keys={key} if force else frozenset(),
            clean_unknown=False,
        )
        if actions:
            self._commit(actions)

        return self.read(key)

    def sync(self) -> None:
        """提交点：此时**期望集完整**，规则 1（清理未知数据）才允许执行。"""
        self._ensure_loaded()
        if not self._decls:
            return
        actions = reconcile(list(self._decls.values()), self._facts, self._vocab.as_dict())
        if actions:
            self._commit(actions)

    # ------------------------------------------------------------- 加载 / 落盘

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        if self.values_path.exists():
            self._text = self.values_path.read_text(encoding="utf-8")
            self._facts = self.backend.loads(self._text)
        else:
            self._text = None
            self._facts = {}

        if self.schema_path.exists():
            raw = json.loads(self.schema_path.read_text(encoding="utf-8"))
            self._vocab = Vocabulary.from_schema(raw)

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
