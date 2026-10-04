# API 参考

本页的签名与说明由 mkdocstrings 从 `src/onconf/` 的**真实源码与 docstring** 生成，
因此上方的这段说明不复制任何签名——复制就会漂移。下面只讲两件事：
对外有哪两个面，以及必须记住的三条语义。

## 两个面

| 面 | 职责 |
|---|---|
| `AutoConf(**engine)` | 配置**引擎自己**：`home`（配置目录）、`audit`（审计开关，**当前不起作用**）、`flush_window`（攒批窗口，默认 `0` 即当场落盘）。`home` 也可由 `ONCONF_HOME` 或当前目录决定 |
| `conf(key, value=MISSING, *, doc=None, type=None, force=False, **engine)` | 干所有的活：读 / 写 / 登记 |

## 三条语义

1. `conf(key)` 是读；`conf(key, value)` 是声明 + 写，且**返回当前生效值**（值文件优先，
   不是刚传进去的默认值）；`conf(key, doc="…")` 只登记不给值，紧接着按读的规则取值。
2. `type=` **只做声明期一致性校验**：它回答「你给的默认值和声明的类型对不对」，
   不参与读取期转换。引擎对值是透明的，值原样进出。
3. 判据不是「`value` 位空没空」，而是**这一行在不在声明**：任何 `doc=` / `type=` 的出现
   都让这一行变成声明。

!!! warning "v1 API 仍在收敛"

    公开 API 只有上面两个面（`__all__` 共 9 个符号：`AutoConf`、`conf`、`Engine`、
    `EngineParams`、`ConfError` 与四个异常子类），但仍然**可能发生破坏性变更**：
    参数名、异常类名与返回值语义都还没有冻结。设计上尚未拍板的条目以
    `docs/design/DESIGN.md` 中带 ❓ 的小节为准。

## 自动生成的 API 文档

::: onconf
