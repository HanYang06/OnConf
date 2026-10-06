# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""onconf —— 本地文件配置引擎。

对外只有两个面::

    AutoConf(**engine)            配置**引擎自己**：配置目录、值文件类型、日志落点与开关、身份
    conf(key, value=…, doc=…)     干所有的活：读 / 写 / 登记

``conf`` 的模式靠**参数结构**推断，不是参数：``value`` 位空着就是读，
填了（哪怕填 ``None``）就是写；``value`` 空着而 ``doc`` 给出，就是「只登记不给值」。

使用口**不得配置引擎** —— 引擎参数只走 ``AutoConf``，经 ``EngineParams`` 校验：
它既是类型提示，也是运行时校验的依据。
"""

from __future__ import annotations

import atexit
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

from ._core import MISSING
from ._engine import Engine
from .errors import (
    ConfError,
    KeyHasNoValueError,
    KeyNotRegisteredError,
    UnknownEngineParamError,
)


if TYPE_CHECKING:
    from ._log import EncodeHook, RotateHook, ScrubHook


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
    """引擎自身的可调参数 —— **唯一事实来源**。

    参数清单、默认值文档、运行时校验全部从这一个类型派生，
    所以它的注解必须完整且准确：写漏一个，`AutoConf` 的运行时校验就漏一个。

    这些全是**引导层**参数：决定引擎怎么装配，运行中不可改。
    """

    home: str
    file_name: str
    file_type: str
    no_one_file: bool
    log_path: str
    log_console: bool
    log_rotate: RotateHook
    log_scrub: ScrubHook
    log_encode: EncodeHook
    flush_window: float
    identity: str


_engine: Engine | None = None


def _sync_at_exit() -> None:
    """进程退出是一个**提交点**：把攒着的声明交出去，再收口日志。

    这里不做任何删除 —— 运行期不删键（见 ``docs/design/concurrency.md``），
    所以退出只是「把还没交的交出去」。
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

    **引导层不可运行中改**：``home`` / ``file_name`` / ``file_type`` / ``no_one_file``
    这些参数决定引擎怎么装配，改了等于改代码。引擎一旦起来再带参数调用会抛 ``ConfError``
    —— 要换配置请在第一次调用之前设置。

    **写权限由进程树定，不需要谁发誓**：创建这个实例的进程是**属主**，读写、生成词表；
    ``fork`` 出来的子进程自动只读 —— 内存会被复制，写权不跟着走。``spawn`` / ``subprocess``
    出来的进程是全新进程，它自己就是属主（Windows 上没有 ``fork``，这条因此不触发）。
    N 个**平级**进程各自建实例属于调用方的部署问题，引擎不探测、不加锁、不兜底。
    """
    global _engine  # noqa: PLW0603 - 单例的创建与取回
    _check_engine_params(dict(engine))

    if _engine is None:
        _engine = Engine(**engine)
    elif engine:
        raise ConfError(
            "引擎已经启动：引导层参数（配置目录 / 值文件名 / 值文件类型 / 多文件开关 / "
            "日志落点与开关 / 身份）不可运行中改，改了等于改代码。"
            "请在第一次调用之前设置。"
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
