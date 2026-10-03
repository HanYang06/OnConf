# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""auto_conf 的异常族。

读取错误刻意分成两类（§18.2）：它们的责任方不同，
用户应当能用 ``except`` 区分「我键名写错了」和「部署漏配了」。
"""

from __future__ import annotations


class ConfError(Exception):
    """auto_conf 所有异常的基类。"""


class KeyNotRegisteredError(ConfError):
    """配置不存在：词表里没有登记，代码也从没声明过。责任在调用方（键名写错）。"""


class KeyHasNoValueError(ConfError):
    """配置不合理：词表里有登记，但事实里没有值。责任在部署（漏配）。"""


class TypeConflictError(ConfError):
    """类型不一致，且无法转换到声明的类型。"""


class UnknownEngineParamError(ConfError, TypeError):
    """透传的引擎参数里有未定义的键（§15.4 规则 1：不许静默失效）。"""
