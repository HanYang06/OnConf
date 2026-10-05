# API 参考

本页的签名与说明由 mkdocstrings 从 `src/onconf/` 的**真实源码与 docstring** 生成，
因此上方的这段说明不复制任何签名——复制就会漂移。下面只讲两件事：
对外有哪两个面，以及必须记住的三条语义。

## 两个面

| 面 | 职责 |
|---|---|
| `AutoConf(**engine)` | 配置**引擎自己**：`home`（配置目录，缺省 `./conf`）、`file_type`（用哪个值文件，单值，`""` 等于 JSON）、`log`（强制日志的去向：`"stderr"` 默认 / `"stdout"` / 文件路径）、`audit`（是否再追加一份 `<home>/audit.log`）、`identity`（写进每行的 `服务@主机` 标记）、`flush_window`（攒批窗口，默认 `0` 即当场落盘）、`lock_timeout`（等 OS 锁的上限）。这些全是**引导层**参数：引擎起来之后不能再改 |
| `conf(key, value=MISSING, doc=None)` | 干所有的活：读 / 写 / 登记 |

## 三种模式

判据只有一句：**`value` 位填没填**。

| 模式 | 写法 | 语义 |
|---|---|---|
| 1 | `conf(key, value)`、`conf(key, value, doc)` | 声明 + 写；返回当前生效值（值文件优先） |
| 2 | `conf(key, doc=…)` | 只登记不给值（必填键）；随即按读的规则取值，没配就报错 |
| 3 | `conf(key)` | 读；文件值其次词表默认值 |

`None` / `""` / `0` 都算填了，`MISSING` 是唯一哨兵。`doc` 是第三个**位置**参数，
也是唯一的登记元数据——判据里不再出现第二个参数，参数面由此**封闭**。

## 三条语义

1. **运行期只补缺、不改已有**：文件里已有不同值时尊重文件（日志里记一条 `op=skip`），
   文件一个字节都不动。覆盖是人的决定，归命令行的 `build` / `sync`。
2. **返回值取载体原生类型**：引擎不推断也不转换。JSON / YAML / TOML 读回各自的原生类型，
   `.env` 一律 `str`；要 `int` 就在调用点写 `int(conf("PORT"))`。
3. **使用口不得配置引擎**：`conf(..., home=…)` 是 `TypeError`；引导层参数只能在
   `AutoConf` 里声明，而且必须在第一次调用之前。

!!! warning "v1 API 仍在收敛"

    公开 API 只有上面两个面（`__all__` 共 8 个符号：`AutoConf`、`conf`，加上
    `Engine`、`EngineParams` 与四个异常），但仍然**可能发生破坏性变更**：
    参数名、异常类名与返回值语义都还没有冻结。
    设计文档见[初始化配置](../design/init_config.md)与[文件支持](../design/file_support.md)。

## 自动生成的 API 文档

::: onconf
