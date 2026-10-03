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

import ast
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .errors import KeyHasNoValue, KeyNotRegistered, TypeConflict

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


MISSING = _Sentinel("MISSING")
"""调用时「参数位没填」。空着 ⇒ 读；填了（哪怕 ``None``）⇒ 写。"""

NO_VALUE = _Sentinel("NO_VALUE")
"""词表里「登记了但没有值」。读它要报错，与「值是 ``None``」语义不同。"""


# --------------------------------------------------------------------------- #
# §18.3 类型推断
# --------------------------------------------------------------------------- #

_TRUE_WORDS = frozenset({"true", "yes", "on"})
_FALSE_WORDS = frozenset({"false", "no", "off"})


def infer(text: str) -> Any:
    """从文件里读到的字符串推出「草稿类型」。

    判定顺序刻意固定：布尔词 → int → float → 结构 → str。
    ``"0"`` / ``"1"`` 判为 ``int`` 而不是 ``bool``（配置里数字远比布尔常见，
    布尔只认 ``true/false/yes/no/on/off`` 这些词），这样才有可预测性。
    """
    s = text.strip()
    if not s:
        return ""

    low = s.lower()
    if low in _TRUE_WORDS:
        return True
    if low in _FALSE_WORDS:
        return False

    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass

    # 结构推断解析：不同语言的结构表达不一致，所以 json 失败再退到 literal_eval
    if s[0] in "{[":
        try:
            return json.loads(s)
        except ValueError:
            pass
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return text
    if s[0] == "(":
        try:
            got = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return text
        if isinstance(got, tuple):
            return got

    return text


def coerce(value: Any, target: type | None) -> Any:
    """把推断值向**声明类型**收敛。声明类型是最终目标，推断只是中间态。

    两个刻意的陷阱处理：

    * ``isinstance(True, int)`` 为真，所以 ``bool`` → ``int`` 必须显式转换；
    * ``bool("false")`` 在 Python 里是 ``True``，绝不能用 ``target(value)`` 硬转。
    """
    if target is None or target is Any:
        return value

    if isinstance(value, target) and not (target is int and isinstance(value, bool)):
        return value

    if target is bool:
        if isinstance(value, str):
            low = value.strip().lower()
            if low in _TRUE_WORDS:
                return True
            if low in _FALSE_WORDS:
                return False
            raise TypeConflict(f"无法把 {value!r} 转成 bool")
        if isinstance(value, (int, float)):
            return bool(value)
        raise TypeConflict(f"无法把 {type(value).__name__} 转成 bool")

    try:
        return target(value)
    except (TypeError, ValueError) as exc:
        raise TypeConflict(
            f"类型不一致：得到 {type(value).__name__} ({value!r})，"
            f"声明要求 {target.__name__}"
        ) from exc


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
# §18.2 读取五步
# --------------------------------------------------------------------------- #


def read_value(
    key: str,
    facts: dict[str, Any],
    vocab: dict[str, VocabEntry],
    *,
    declared_type: type | None = None,
) -> ReadResult:
    """读一个配置项。

    1. 去事实（文件）里找；
    2. 找到就拿（``None`` 也是值）；
    3. 找不到就去词表翻译：词表也没有 ⇒ ``KeyNotRegistered``；
       词表有而事实没有 ⇒ ``KeyHasNoValue``（两类错误责任方不同）；
    4. 字符串先推断类型；
    5. 向声明类型收敛，转不过去 ⇒ ``TypeConflict``。
    """
    if key in facts:
        raw: Any = facts[key]
        origin = "file"
    else:
        entry = vocab.get(key)
        if entry is None:
            raise KeyNotRegistered(f"配置不存在：{key!r}（词表里没有登记）")
        if entry.default is NO_VALUE:
            raise KeyHasNoValue(f"配置不合理：{key!r} 已登记，但事实里没有值")
        raw = entry.default
        origin = "vocab"

    if isinstance(raw, str):
        raw = infer(raw)

    target = declared_type
    if target is None and key in vocab:
        target = vocab[key].type

    return ReadResult(key=key, value=coerce(raw, target), origin=origin)


# --------------------------------------------------------------------------- #
# §18.1 写入 = 三集合全量对账
# --------------------------------------------------------------------------- #


def _meta_stale(entry: VocabEntry | None, decl: Decl) -> bool:
    """词表是否需要更新：类型、文档、或**默认值指纹**（§17.8）有变。"""
    if entry is None:
        return True
    if entry.type != decl.type or entry.doc != decl.doc:
        return True
    want = NO_VALUE if decl.value is MISSING else decl.value
    return entry.default != want


def reconcile(
    decls: list[Decl],
    facts: dict[str, Any],
    vocab: dict[str, VocabEntry],
    *,
    force: bool = False,
) -> list[Action]:
    """把「代码声明的期望集」对到「事实集」上，产出动作清单。

    规则 1 清理未知数据 / 2 补充缺失数据 / 3 补充缺失参数 / 4 保持原有数据。
    ``force=True`` 是情形 4 的唯一例外，且**逐项生效、没有全局开关**（§18.6）。
    """
    actions: list[Action] = []
    declared = {d.key: d for d in decls}

    # 规则 1：事实有、期望没有 ⇒ 清理
    for key, fact_value in facts.items():
        if key not in declared:
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
            if force:
                actions.append(
                    Action("overwrite", key, value=decl.value, old=facts[key], reason="force=True")
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
