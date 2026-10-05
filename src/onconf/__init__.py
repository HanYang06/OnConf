# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""onconf —— 本地文件配置引擎。

对外只有两个面（§15.2）::

    AutoConf(**engine)            配置**引擎自己**：配置目录、值文件类型、日志去向、审计、身份
    conf(key, value=…, doc=…)     干所有的活：读 / 写 / 登记

``conf`` 的模式靠**参数结构**推断，不是参数（§17.7）：``value`` 位空着就是读，
填了（哪怕填 ``None``）就是写；``value`` 空着而 ``doc`` 给出，就是「只登记不给值」。

使用口**不得配置引擎** —— 引擎参数只走 ``AutoConf``，经 ``EngineParams`` 校验：
它既是类型提示，也是运行时校验的依据（§15.4）。
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
    UnknownEngineParamError,
)


__all__ = [
    "AutoConf",
    "ConfError",
    "Engine",
    "EngineParams",
    "KeyHasNoValueError",
    "KeyNotRegisteredError",
    "UnknownEngineParamError",
    "conf",
]


class EngineParams(TypedDict, total=False):
    """引擎自身的可调参数 —— **唯一事实来源**（§15.5）。

    参数清单、默认值文档、运行时校验全部从这一个类型派生，
    所以它的注解必须完整且准确：写漏一个，``help`` 里就没有。

    这些全是**引导层**参数：决定引擎怎么装配，运行中不可改。
    """

    home: str
    file_type: str
    audit: bool
    flush_window: float
    lock_timeout: float
    log: str
    identity: str


_engine: Engine | None = None


def _sync_at_exit() -> None:
    """进程退出是一个**提交点**：此刻期望集完整，规则 1 才允许执行。

    落完盘顺手还回写者身份：端点早一点释放，下一个进程就早一点接上。
    """
    if _engine is not None:
        _engine.sync()
        _engine.close()


atexit.register(_sync_at_exit)


def _reset() -> None:
    """仅供测试：丢掉单例。不是公开 API。"""
    global _engine  # noqa: PLW0603 - 丢掉单例就是这个函数的全部目的
    if _engine is not None:
        _engine.close()
    _engine = None


def _check_engine_params(params: dict[str, Any]) -> None:
    unknown = set(params) - set(EngineParams.__annotations__)
    if unknown:
        raise UnknownEngineParamError(
            f"未知的引擎参数 {sorted(unknown)}；合法参数：{sorted(EngineParams.__annotations__)}"
        )


def AutoConf(**engine: Unpack[EngineParams]) -> Engine:  # noqa: N802 - 公开 API 就是这个名字
    """配置引擎自己。走约定时可完全不调它；无参数调用 = 把单例**取回来**。

    **引导层不可运行中改**：``home`` / ``file_type`` / ``lock_timeout`` 这些参数
    决定引擎怎么装配，改了等于改代码（§15.3 的「单例可变」定性作废）。引擎一旦
    起来再带参数调用会抛 ``ConfError`` —— 要换配置请在第一次调用之前设置。

    值层不受这条限制：值每次都从文件重新读。
    """
    global _engine  # noqa: PLW0603 - 单例的创建与取回
    _check_engine_params(dict(engine))

    if _engine is None:
        _engine = Engine(**engine)
    elif engine:
        raise ConfError(
            "引擎已经启动：引导层参数（配置目录 / 值文件类型 / 日志去向 / 审计 / 身份 / "
            "锁超时）不可运行中改，改了等于改代码。请在第一次调用之前设置。"
        )
    return _engine


def conf(key: str, value: Any = MISSING, doc: str | None = None) -> Any:
    """读 / 写 / 登记一个配置项 —— **三种模式，与写法一一对应**。

    * ``conf(key)``                     读；读不到就报错（键名错 / 部署漏配分两种）
    * ``conf(key, value)``              声明 + 写；**返回当前生效值**（值文件优先）
    * ``conf(key, value, doc)``         同上，并登记说明进词表
    * ``conf(key, doc="…")``            只登记不给值（必填键）⇒ 立刻取值，没配就报错

    判据**只看 ``value`` 位填没填**：``None`` / ``""`` / ``0`` 都是填了，
    ``MISSING`` 是唯一哨兵。``doc`` 是第三个位置参数，也是唯一的登记元数据 ——
    参数面自此封闭，以后新增参数不需要动判据。

    文件里已有不同值时**尊重文件**（只记一条 ``skip``）：运行期不覆盖既存值。
    覆盖是人主动发起的事，归命令行的 ``build`` / ``sync``，见
    ``docs/design/init_config.md``。
    """
    target = _engine if _engine is not None else AutoConf()
    return target(key, value, doc)


def main() -> None:
    """控制台入口占位。命令行体系（交互式补全等）排在后面。"""
    print(f"onconf：配置目录 {default_home()}")  # noqa: T201 - 这就是控制台入口的活儿
