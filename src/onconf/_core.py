# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""纯内存核心：不碰文件、不碰进程、不碰 IPC。

这里是全部语义的单一实现点，对应设计文档：

* §17   事实权威（文件 > 代码）
* §17.7 读写靠参数结构判定，``None`` 是合法值
* §18.1 写入 = 三集合全量对账（四条规则）
* §18.2 读取 = 五步 + 两类错误
* §18.3 类型推断 → 与声明比对 → 转换
* §18.7 声明集哈希（脏检查，不是锁）
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .errors import KeyHasNoValueError, KeyNotRegisteredError


if TYPE_CHECKING:
    from collections.abc import Container


# --------------------------------------------------------------------------- #
# 三态哨兵（§17.7）
# --------------------------------------------------------------------------- #


class _Sentinel:
    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name

    def __bool__(self) -> bool:
        return False

    def __reduce__(self) -> str:
        """过线时**按名字还原成模块级那个单例**，不是重建一个同名对象。

        没有这一条，哨兵跨进程就废了：pickle 默认会构造出一个**新的**
        ``_Sentinel``，于是对面那句 ``value is MISSING`` 永远是 ``False``
        —— 「只登记不给值」会静默变成「给了一个哨兵当值」。
        ``__reduce__`` 返回字符串是 pickle 的约定：这个对象就是本模块里
        叫这个名字的全局对象。
        """
        return self._name


MISSING = _Sentinel("MISSING")
"""调用时「参数位没填」。空着 ⇒ 读；填了（哪怕 ``None``）⇒ 写。"""

NO_VALUE = _Sentinel("NO_VALUE")
"""词表里「登记了但没有值」。读它要报错，与「值是 ``None``」语义不同。"""


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Decl:
    """代码侧的一次声明（写模式的参数）。"""

    key: str
    value: Any = MISSING  # MISSING ⇒ 只登记不给值（词表里记 NO_VALUE）
    type: type | None = None
    doc: str | None = None


@dataclass(frozen=True)
class VocabEntry:
    """词表里的一条登记 —— **库自己的资产**（§18.6 归属权）。"""

    key: str
    type: type | None = None
    doc: str | None = None
    default: Any = NO_VALUE  # NO_VALUE ⇒ 无默认值；None ⇒ 默认值就是 None


@dataclass(frozen=True)
class ReadResult:
    key: str
    value: Any
    origin: str  # "file" | "vocab"


@dataclass(frozen=True)
class Action:
    """对账产出的一条动作（纯数据，可直接喂给审计日志）。"""

    kind: str  # clean | fill | register | update_meta | skip | overwrite
    key: str
    value: Any = MISSING
    old: Any = MISSING
    reason: str = ""

    def __str__(self) -> str:  # 便于测试断言可读
        return f"{self.kind}({self.key})"


# --------------------------------------------------------------------------- #
# §18.2 读取
# --------------------------------------------------------------------------- #


def read_value(
    key: str,
    facts: dict[str, Any],
    vocab: dict[str, VocabEntry],
) -> ReadResult:
    """读一个配置项。**取到就返回，一个字节都不加工。**

    1. 去事实（文件）里找；
    2. 找到就拿（``None`` 也是值）；
    3. 找不到就去词表翻译：词表也没有 ⇒ ``KeyNotRegisteredError``；
       词表有而事实没有 ⇒ ``KeyHasNoValueError``（两类错误责任方不同）。

    这里**没有**类型推断，也**没有**类型转换 —— 引擎对值是**透明**的：
    文件里是 ``"8080"``，读回来就是字符串 ``"8080"``，不会变成 ``8080``。

    （这条是被测试抓出来的：早先这里挂着一层 ``infer``，于是 JSON 里
    一个字符串值会莫名其妙变成数字。要数字请在取用处显式 ``int(…)``，
    这样「哪里发生了转换」在代码里一眼可见。）

    声明期的 ``type=`` 只做**一致性校验**，不参与读取。
    """
    if key in facts:
        return ReadResult(key=key, value=facts[key], origin="file")

    entry = vocab.get(key)
    if entry is None:
        raise KeyNotRegisteredError(f"配置不存在：{key!r}（词表里没有登记）")
    if entry.default is NO_VALUE:
        raise KeyHasNoValueError(f"配置不合理：{key!r} 已登记，但事实里没有值")
    return ReadResult(key=key, value=entry.default, origin="vocab")


# --------------------------------------------------------------------------- #
# §18.1 写入 = 三集合全量对账
# --------------------------------------------------------------------------- #

DIRECTIVE_PREFIX = "$"
"""指令键的前缀。``$schema`` / ``$id`` / ``$comment`` 是**指令**，不是配置项。

真实产物里就有这一行（``Cairn/config/settings.json``）::

    {"$schema": "schema/settings.json", "pack.max.byte": 2147483648}

它必须**不参与对账**——否则规则 1「事实有、期望没有 ⇒ 清理」会在第一次运行时
把 ``$schema`` 删掉，等于删掉用户的编辑器工具链。指令也不许被声明。
"""


def _is_directive(key: str) -> bool:
    return key.startswith(DIRECTIVE_PREFIX)


def _meta_stale(entry: VocabEntry | None, decl: Decl) -> bool:
    """词表是否需要更新：类型、文档、或**默认值指纹**（§17.8）有变。"""
    if entry is None:
        return True
    if entry.type != decl.type or entry.doc != decl.doc:
        return True
    want = NO_VALUE if decl.value is MISSING else decl.value
    return bool(entry.default != want)


def reconcile(
    decls: list[Decl],
    facts: dict[str, Any],
    vocab: dict[str, VocabEntry],
    *,
    force_keys: Container[str] = frozenset(),
    clean_unknown: bool = True,
) -> list[Action]:
    """把「代码声明的期望集」对到「事实集」上，产出动作清单。

    规则 1 清理未知数据 / 2 补充缺失数据 / 3 补充缺失参数 / 4 保持原有数据。

    ``force_keys`` 是情形 4 的唯一例外，且**逐项生效、没有全局开关**（§18.6）：
    只有列在里面的键才允许覆盖文件里已有的值。

    ``clean_unknown`` 为什么必须是个开关
    ------------------------------------
    规则 1 的判据是「事实里有、**期望集**里没有」。可它只有在**期望集完整**时
    才成立。而引擎一次 ``conf()`` 调用只知道**到目前为止**声明过的键：

    .. code-block:: python

        conf("a.b", 1)      # 此刻期望集只有 {a.b}
        conf("c.d", 2)      # 此刻期望集只有 {a.b, c.d}

    如果第一次调用就按规则 1 对账，文件里所有**还没声明到**的键都会被当成
    「未知数据」清掉。所以：

    * **增量声明**走 ``clean_unknown=False``，只做补写 / 覆盖 / 补元数据；
    * **提交点**（``sync()`` / 进程退出）期望集完整，才允许 ``clean_unknown=True``。

    这不是性能优化，是**正确性前提**。

    指令键（``$`` 开头）不参与对账，见 :data:`DIRECTIVE_PREFIX`。
    """
    actions: list[Action] = []
    declared = {d.key: d for d in decls}

    # 规则 1：事实有、期望没有 ⇒ 清理（指令键豁免；且必须期望集完整）
    if clean_unknown:
        for key, fact_value in facts.items():
            if key in declared or _is_directive(key):
                continue
            actions.append(
                Action("clean", key, old=fact_value, reason="事实里有、代码没声明")
            )

    for key, decl in declared.items():
        stale = _meta_stale(vocab.get(key), decl)

        if key not in facts:
            # 规则 2：期望有、事实没有 ⇒ 补写（无默认值则只登记）
            if decl.value is MISSING:
                actions.append(Action("register", key, reason="无默认值，只登记进词表"))
            else:
                actions.append(Action("fill", key, value=decl.value, reason="事实里没有"))
            if stale:
                actions.append(
                    Action(
                        "update_meta",
                        key,
                        value=NO_VALUE if decl.value is MISSING else decl.value,
                        reason="登记元数据",
                    )
                )
            continue

        # 两边都有
        if decl.value is not MISSING and facts[key] != decl.value:
            # 规则 4：值不一致 ⇒ 尊重文件
            if key in force_keys:
                actions.append(
                    Action("overwrite", key, value=decl.value, old=facts[key], reason="force")
                )
            else:
                actions.append(
                    Action("skip", key, old=facts[key], value=decl.value, reason="尊重文件")
                )
        if stale:
            # 规则 3：补充缺失参数（含默认值指纹更新 —— 只动词表，不动文件）
            actions.append(
                Action(
                    "update_meta",
                    key,
                    value=NO_VALUE if decl.value is MISSING else decl.value,
                    reason="补充缺失参数",
                )
            )

    return actions


# --------------------------------------------------------------------------- #
# §18.7 声明集哈希
# --------------------------------------------------------------------------- #


def _type_name(t: type | None) -> str | None:
    return None if t is None else f"{t.__module__}.{t.__qualname__}"


def declaration_hash(decls: list[Decl]) -> str:
    """声明集指纹。对得上 ⇒ 写入阶段整体跳过（一个字节都不写）。

    这是**脏检查，不是锁**：对不上只意味着「这一次短路不成立」，
    于是走完整对账 —— 否则开发者永远没法改自己的代码。

    值用 ``["missing"]`` / ``["value", v]`` 两段式编码，不能写成
    ``None if v is MISSING else v`` —— 那会让「只登记」和「值就是 None」
    塌陷成同一个指纹，正是 §17.7 三态里最容易踩的那一脚。
    """
    payload = [
        [
            d.key,
            _type_name(d.type),
            d.doc,
            ["missing"] if d.value is MISSING else ["value", d.value],
        ]
        for d in sorted(decls, key=lambda d: d.key)
    ]
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=repr)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
