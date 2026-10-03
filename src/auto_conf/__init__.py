# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""auto_conf —— 本地文件配置引擎。

对外只有两个面（§15.2）::

    AutoConf(**engine)      配置**引擎自己**：配置目录、审计开关
    conf(key, value=...)    干所有的活：读 / 写 / 登记

``conf`` 的 op 靠**参数结构**推断，不是参数（§17.7）：``value`` 位空着就是读，
填了（哪怕填 ``None``）就是写。``AutoConf`` 的额外参数经 ``EngineParams``
透传 —— 它既是类型提示，也是运行时校验的依据（§15.4）。
"""

from __future__ import annotations

import atexit
from typing import Any, TypedDict, Unpack

from ._core import MISSING
from ._engine import Engine, default_home
from .errors import (
    ConfError,
    KeyHasNoValueError,
    KeyNotRegisteredError,
    TypeConflictError,
    UnknownEngineParamError,
)


__all__ = [
    "AutoConf",
    "ConfError",
    "Engine",
    "EngineParams",
    "KeyHasNoValueError",
    "KeyNotRegisteredError",
    "TypeConflictError",
    "UnknownEngineParamError",
    "conf",
]


class EngineParams(TypedDict, total=False):
    """引擎自身的可调参数 —— **唯一事实来源**（§15.5）。

    参数清单、默认值文档、运行时校验全部从这一个类型派生，
    所以它的注解必须完整且准确：写漏一个，``help`` 里就没有。
    """

    home: str
    audit: bool
    flush_window: float


_engine: Engine | None = None


def _sync_at_exit() -> None:
    """进程退出是一个**提交点**：此刻期望集完整，规则 1 才允许执行。"""
    if _engine is not None:
        _engine.sync()


atexit.register(_sync_at_exit)


def _reset() -> None:
    """仅供测试：丢掉单例。不是公开 API。"""
    global _engine  # noqa: PLW0603 - 丢掉单例就是这个函数的全部目的
    _engine = None


def _check_engine_params(params: dict[str, Any]) -> None:
    unknown = set(params) - set(EngineParams.__annotations__)
    if unknown:
        raise UnknownEngineParamError(
            f"未知的引擎参数 {sorted(unknown)}；"
            f"合法参数：{sorted(EngineParams.__annotations__)}"
        )


def AutoConf(**engine: Unpack[EngineParams]) -> Engine:  # noqa: N802 - 公开 API 就是这个名字
    """配置引擎自己。走约定时可完全不调它。

    v1 限制：引擎一旦起来就**不能就地改配置**（§15.3 的「口子」仍待实现）。
    无参数调用只是把它取回来。
    """
    global _engine  # noqa: PLW0603 - 单例的创建与取回
    _check_engine_params(dict(engine))

    if _engine is None:
        _engine = Engine(**engine)
    elif engine:
        raise ConfError(
            "引擎已经启动，v1 还不支持运行中改引擎配置；"
            "要换配置目录请在第一次调用之前设置。"
        )
    return _engine


def conf(
    key: str,
    value: Any = MISSING,
    *,
    doc: str | None = None,
    type: type | None = None,  # noqa: A002 - 参数名就是 API 的一部分（§15.1）
    force: bool = False,
    **engine: Unpack[EngineParams],
) -> Any:
    """读 / 写 / 登记一个配置项。

    * ``conf(key)``                     读；读不到就报错（键名错 / 部署漏配分两种）
    * ``conf(key, value)``              声明 + 写；**返回当前生效值**（值文件优先）
    * ``conf(key, value, doc="…")``     同上，并登记说明进词表
    * ``conf(key, doc="…")``            只登记不给值（必填键）⇒ 立刻取值，没配就报错

    判据不是「value 位空没空」，而是**这一行在不在声明**：任何 ``doc=`` / ``type=``
    的出现都让这一行变成声明。

    ``type=`` 只做**声明期一致性校验**，不参与读取期转换：引擎对值是透明的。
    ``force=`` 逐项覆盖文件里已有的值，没有全局开关。
    """
    target = AutoConf(**engine) if engine else _engine
    if target is None:
        target = AutoConf()
    return target(key, value, doc=doc, type=type, force=force)


def main() -> None:
    """控制台入口占位。命令行体系（交互式补全等）排在后面。"""
    print(f"auto_conf：配置目录 {default_home()}")  # noqa: T201 - 这就是控制台入口的活儿
