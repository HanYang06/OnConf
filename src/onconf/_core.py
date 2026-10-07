# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""纯内存核心：不碰文件、不碰进程、不碰 IPC。

这里是全部语义的单一实现点，对应设计文档：

* 事实权威（文件 > 代码）
* 读写靠参数结构判定，``None`` 是合法值
* 写入 = 两条规则的对账（补缺 / 补元数据），**运行期不删任何键**
* 读取 = 两类错误分开

引擎**不做类型推断、也不做向声明类型的转换**：值是载体原生的，原样进出
（口径见 ``docs/design/file_support.md``）。词表也只有三样东西：键、说明、默认值。

**写入只有"补缺"与"补元数据"两种动作**：对文件里已经存在的值一律只读
（值不一致时产出 ``skip``，记一条"想改没改"）。删除是另一回事：
判据「事实里有、期望集里没有」只有在**期望集完整**时才成立，而运行期的期望集
永远只是「这个进程到目前为止声明过的」—— 多进程下必然误删别人的键。所以
``clean`` 动作不在这条路径上，它由 :func:`undeclared` 供给命令行的收敛路径
（见 ``docs/design/concurrency.md`` 与 ``docs/design/init_config.md``）。

覆盖既存值同理：它是人主动发起的命令行动作（``build`` / ``sync``）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .errors import KeyHasNoValueError, KeyNotRegisteredError


if TYPE_CHECKING:
    from collections.abc import Callable


# --------------------------------------------------------------------------- #
# 三态哨兵
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
    doc: str | None = None
    #: **审计用**的调用点（``app/config.py:12``）。它不参与对账，也不进声明集哈希 ——
    #: 换个调用位置不该让声明看起来「变了」，否则每次重构都会全量重写一遍。
    at: str = ""


@dataclass(frozen=True)
class VocabEntry:
    """词表里的一条登记 —— **库自己的资产**（归属权见 ``docs/design/file_support.md``）。"""

    key: str
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

    kind: str  # clean | fill | register | update_meta | skip
    key: str
    value: Any = MISSING
    old: Any = MISSING
    reason: str = ""

    def __str__(self) -> str:  # 便于测试断言可读
        return f"{self.kind}({self.key})"


# --------------------------------------------------------------------------- #
# 读取
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

    类型声明（``conf(..., type=int)``）已整体取消：词表不记类型，声明期也不做校验
    （口径见 ``docs/design/file_support.md``）。
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
# 写入：三集合全量对账
# --------------------------------------------------------------------------- #

DIRECTIVE_PREFIX = "$"
"""指令键的前缀。``$schema`` / ``$id`` / ``$comment`` 是**指令**，不是配置项。

真实产物里就有这一行（``Cairn/config/settings.json``）::

    {"$schema": "schema/settings.json", "pack.max.byte": 2147483648}

它必须**不参与对账**——否则规则 1「事实有、期望没有 ⇒ 清理」会在第一次运行时
把 ``$schema`` 删掉，等于删掉用户的编辑器工具链。指令也不许被声明。
"""


def is_directive(key: str) -> bool:
    """这个键是不是**指令**（``$`` 开头）。

    判据要喂**文件内**的键名：多文件模式下扁平键是 ``app/net:$schema``，拿它去判会漏，
    结果就是每次收敛都把那条指针删掉。
    """
    return key.startswith(DIRECTIVE_PREFIX)


def meta_diff(entry: VocabEntry, decl: Decl) -> tuple[bool, bool]:
    """词表条目与声明的两处差异：``(默认值不一致, 说明不一致)``。

    判据只有这一处 —— :func:`_meta_stale` 把它并成一个布尔量给运行期用，
    ``check`` 拆开按两类报，两边不会走偏。
    """
    want = NO_VALUE if decl.value is MISSING else decl.value
    return bool(entry.default != want), entry.doc != decl.doc


def _meta_stale(entry: VocabEntry | None, decl: Decl) -> bool:
    """词表是否需要更新：说明、或**默认值指纹**有变。"""
    if entry is None:
        return True
    default_differs, doc_differs = meta_diff(entry, decl)
    return default_differs or doc_differs


def reconcile(
    decls: list[Decl],
    facts: dict[str, Any],
    vocab: dict[str, VocabEntry],
) -> list[Action]:
    """把「代码声明的期望集」对到「事实集」上，产出动作清单。

    规则 2 补充缺失数据 / 3 补充缺失参数 / 4 保持原有数据。

    **没有"清理未知数据"这一条。** 它的判据是「事实里有、期望集里没有」，而期望集
    只有在一个**完整**的提交点才完整 —— 运行期一个进程的期望集永远只是它自己声明过的
    那部分，多进程下必然把别人的键当未知数据处理掉。删除因此被移出运行期，只在命令行的
    一次性收敛里发生，判据由 :func:`undeclared` 给出。

    情形 4（两边都有、值不一致）**没有例外**：以文件为准，产出一条 ``skip``。
    运行期路径不改文件里已经存在的值 —— 覆盖是命令行的显式人工动作（``build`` /
    ``sync``），代码只能补它没有的，不能改它已经有的（``docs/design/init_config.md``）。

    指令键（``$`` 开头）不参与对账，见 :data:`DIRECTIVE_PREFIX`。
    """
    actions: list[Action] = []
    declared = {d.key: d for d in decls}

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
            # 规则 4：值不一致 ⇒ 尊重文件。**运行期没有覆盖出口**：
            # 想改已存在的值是人主动做的事，走命令行的 build / sync。
            actions.append(Action("skip", key, old=facts[key], value=decl.value, reason="尊重文件"))
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


def undeclared(
    facts: dict[str, Any],
    declared: set[str],
    *,
    is_directive: Callable[[str], bool] = is_directive,
) -> list[Action]:
    """事实里有、声明集里没有的键 —— **只给命令行的收敛路径用**。

    这条判据只有在**期望集完整**时才成立，而完整只可能出现在「一次拿到全部声明」的
    场合：命令行静态扫描整个项目，得到的正好是一份完整声明集。运行期永远不完整，
    所以运行期不调用它（见 :func:`reconcile` 的说明）。

    指令键（``$`` 开头）豁免：``$schema`` 是给编辑器的指针、不是配置项，
    删掉它等于删掉用户的工具链。判据按**文件内**的键名判，所以调用方可以改喂
    （多文件模式下扁平键带着路径段前缀，见 :func:`is_directive`）。
    """
    return [
        Action("clean", key, old=value, reason="事实里有、声明集里没有")
        for key, value in facts.items()
        if key not in declared and not is_directive(key)
    ]


# --------------------------------------------------------------------------- #
# 声明集哈希
# --------------------------------------------------------------------------- #


def declaration_hash(decls: list[Decl]) -> str:
    """声明集指纹。对得上 ⇒ 写入阶段整体跳过（一个字节都不写）。

    这是**脏检查，不是锁**：对不上只意味着「这一次短路不成立」，
    于是走完整对账 —— 否则开发者永远没法改自己的代码。

    值用 ``["missing"]`` / ``["value", v]`` 两段式编码，不能写成
    ``None if v is MISSING else v`` —— 那会让「只登记」和「值就是 None」
    塌陷成同一个指纹，正是三态里最容易踩的那一脚。

    载荷只有键、说明、值三样：词表不再记类型，类型也就不该进指纹。
    """
    payload = [
        [d.key, d.doc, ["missing"] if d.value is MISSING else ["value", d.value]]
        for d in sorted(decls, key=lambda d: d.key)
    ]
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=repr)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
