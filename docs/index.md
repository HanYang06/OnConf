# auto-conf

> Declarative configuration over plain local files — files stay authoritative, concurrent processes never lose an update.
>
> 声明式配置，落在普通的本地文件上 —— 文件永远是权威，并发进程不会丢更新。

**尚未发布到 PyPI。** 当前版本 `0.1.0`，开发状态 Pre-Alpha：公开 API 仍在收敛，
可能发生破坏性变更；并发写入、事务与审计尚未实现（以[路线图](roadmap.md)为准）。

## 当前状态

下表是 2026-10-04 的工作区快照，不是承诺。

| 项 | 现状 |
|---|---|
| 版本 | `0.1.0` |
| 开发状态 | Pre-Alpha（`Development Status :: 2 - Pre-Alpha`，PyPI 未发布） |
| 公开 API | `AutoConf` / `conf` 两个面，`__all__` 共 9 个符号 |
| 值后端 | JSON、YAML、`.env`（字符串后端） |
| 提交点 | 每次 `conf(key, value)` 当场对账并落盘；进程退出时 `atexit` 触发 `Engine.sync()` |
| 测试 | 见[路线图](roadmap.md)的状态小节 |

## 已实现的能力

- **JSON 值后端**：外科手术式回写，未触及的字节逐字不动。
- **YAML 值后端**：注释、缩进、键序逐字保留。
- **`.env` 值后端**：纯字符串后端，不做键名映射，不认行内注释（`#` 出现在值里时就是值的一部分）。
- **词表**：三态持久化 + JSON Schema 往返 + 哈希短路，落在 `<home>/schema/` 下。
- **引擎装配**：`conf` / `AutoConf` 两个面端到端接通，声明到读回可用。
- **用值当键**：支持 `conf(conf("app.key_name"))` 这类间接寻址。
- **`$schema` 指针**：每次落盘都保证值文件里有指向词表的指针。
- **异常族**：`ConfError` 及其四类子类，见 [快速开始](getting-started.md)的常见问题。

尚未实现的能力（WAL 与文件锁、原子写、事务攒批、审计事件流、TOML 后端、把系统环境变量
当作配置源、IPC、真正的命令行）**当前不可用**，一份完整清单见[路线图](roadmap.md)。

## 最小示例

```python
from auto_conf import AutoConf, conf

AutoConf(home="./conf")      # 可省略，走约定
conf("app.server.port", 8080)  # 声明 + 写，返回当前生效值
print(conf("app.server.port")) # 读
```

`conf(key, value)` 的返回值是**当前生效值**，不是刚传进去的默认值：值文件里已有的值优先。

跑完这段代码，磁盘上会有两个文件：

```text
conf/
  settings.json          # 值文件：{ "$schema": "schema/settings.json", "app.server.port": 8080 }
  schema/
    settings.json        # 词表：库自己的资产，整篇重写
```

`$schema` 指针让编辑器知道词表在哪，从而对这份文件给出补全与校验。
进程退出时 `atexit` 会再触发一次 `Engine.sync()`，把这一轮的声明集收口。

## 下一步

- [快速开始](getting-started.md) —— 环境要求、安装、目录约定、异常怎么区分。
- [路线图](roadmap.md) —— 已实现 / 进行中 / 未实现，以及与 M1–M5 里程碑的对应。
- [设计稿索引](design/index.md) —— `docs/design/DESIGN.md` 是**未定稿**的设计草案。
- [API 参考](api/index.md) —— 由源码 docstring 直接生成。
