# OnConf

> **配置不再有动词：同一个名字读它、写它，两个方向都不丢——不丢一个字节，也不丢一次更新。**
>
> `Configuration has no verbs: one name reads and writes it, in both directions, without losing a byte or an update.`
>
> 以上是**官方定位句**：中文与英文同源，改一句必须同步改另一句，并同步
> `README.md`、`README.zh-CN.md`、`pyproject.toml` 的 `description`
> 与本文件的 `site_description`。

**尚未发布到 PyPI。** 当前版本 `0.1.0`，开发状态 Pre-Alpha：公开 API 仍在收敛，
可能发生破坏性变更；真正的命令行尚未实现（以[路线图](roadmap.md)为准）。

定位句的两个半句现在**都有机制支撑**：「不丢一个字节」由外科手术式回写保证；
「不丢一次更新」由**专职写者**保证 —— 谁先抢绑到配置目录的端点，谁就是唯一的读写者，
其余进程经 `multiprocessing.connection` 发请求，跨进程 OS 锁 + 锁内按需重读退居兜底
（见[威胁模型](security/threat-model.md) 的 T4）。
**持久性也已经兑现**：值文件与词表都经同目录临时文件 → `fsync` → `os.replace` 落盘，
崩溃中途不会留下半截文件（T5）。

## 当前状态

下表是 2026-10-04 的工作区快照，不是承诺。

| 项 | 现状 |
|---|---|
| 版本 | `0.1.0` |
| 开发状态 | Pre-Alpha（`Development Status :: 2 - Pre-Alpha`，PyPI 未发布） |
| 公开 API | `AutoConf` / `conf` 两个面，`__all__` 共 9 个符号 |
| 值后端 | JSON、YAML、TOML、`.env`（字符串后端） |
| 提交点 | 每次 `conf(key, value)` 当场对账并落盘；进程退出时 `atexit` 触发 `Engine.sync()` |
| 日志与审计 | 强制日志（`log=` 选去向，**不可关闭**）+ 可选 append-only 审计文件（`audit=True` → `<home>/audit.log`）；见[设计稿 §20 / §21](design/DESIGN.md) |
| 测试 | 见[路线图](roadmap.md)的状态小节 |

## 已实现的能力

- **JSON 值后端**：外科手术式回写，未触及的字节逐字不动。
- **YAML 值后端**：注释、缩进、键序逐字保留。
- **`.env` 值后端**：纯字符串后端，不做键名映射，不认行内注释（`#` 出现在值里时就是值的一部分）。
- **TOML 值后端**：表头归一成点分键。
- **词表**：三态持久化 + JSON Schema 往返 + 哈希短路，落在 `<home>/schema/` 下。
- **引擎装配**：`conf` / `AutoConf` 两个面端到端接通，声明到读回可用。
- **用值当键**：支持 `conf(conf("app.key_name"))` 这类间接寻址。
- **`$schema` 指针**：每次落盘都保证值文件里有指向词表的指针（**能吃下成员的后端**才写；
  `.env` 与 TOML 放不下成员，跳过）。
- **专职写者**：谁先抢绑到配置目录的端点，谁就是唯一的读写者；其余进程经
  `multiprocessing.connection` 发请求。**抢绑本身就是选举**，不涉及锁文件（[设计稿 §32](design/DESIGN.md)）。
- **跨进程排他锁**：操作系统级锁（Windows `msvcrt.locking`、其它 `fcntl.flock`），进程崩溃由 OS 释放；拿不到锁抛 `LockTimeoutError` —— 专职写者不在时由它兜底。
- **锁内按需重读**：指纹（`mtime` + 大小）同时看值文件与词表，别人刚登记的键不会被挤掉。
- **原子写**：同目录临时文件 → `fsync` → `os.replace`（POSIX 再加父目录 `fsync`），行尾与权限位原样保留。
- **可选攒批窗口**：`flush_window`（默认 `0`，即当场落盘）。
- **日志与审计**：强制 `[R]` / `[W]` / `[C]` / `[E]` 事件流（去向可改、**不可关闭**），
  写全量、读按事务去重（`n=`），写记录带调用点与 pid；`audit=True` 再落一份
  append-only 的 `<home>/audit.log`（`0600`、按大小轮转）。终端用**显示宽度**对齐。
- **异常族**：`ConfError` 连同 `KeyNotRegisteredError` / `KeyHasNoValueError` /
  `TypeConflictError` / `UnknownEngineParamError`；另有 `LockTimeoutError`（在 `_lock.py`，
  也是 `ConfError` 的子类）与三个**读期**的 `ValueError` 子类
  （`EnvSyntaxError` / `YamlFlatRequiredError` / `TomlFlatRequiredError`，
  `except ConfError` 接不住它们）。见[快速开始](getting-started.md)的常见问题。

尚未实现的能力（把系统环境变量当作配置源、真正的命令行）**当前不可用**，
一份完整清单见[路线图](roadmap.md)。

## 最小示例

```python
from onconf import AutoConf, conf

AutoConf(home="./conf")      # 可省略，走约定
conf("app.server.port", 8080)  # 声明 + 写，返回当前生效值
print(conf("app.server.port")) # 读
```

`conf(key, value)` 的返回值是**当前生效值**，不是刚传进去的默认值：值文件里已有的值优先。

跑完这段代码，磁盘上会有这些文件：

```text
conf/
  settings.json          # 值文件：{ "$schema": "schema/settings.json", "app.server.port": 8080 }
  schema/
    settings.json        # 词表：库自己的资产，整篇重写
    settings.lock        # 跨进程锁的握手点（空文件）
    settings.key         # 专职写者的认证码（0600；POSIX 上还有 settings.sock 端点文件）
```

后两个是库自己的簿记，不用手改；`.env` / TOML 值文件不写 `$schema` 指针。

`$schema` 指针让编辑器知道词表在哪，从而对这份文件给出补全与校验。
进程退出时 `atexit` 会再触发一次 `Engine.sync()`，把这一轮的声明集收口。

## 下一步

- [快速开始](getting-started.md) —— 环境要求、安装、目录约定、异常怎么区分。
- [路线图](roadmap.md) —— 已实现 / 进行中 / 未实现，以及与 M1–M5 里程碑的对应。
- [设计稿索引](design/index.md) —— `docs/design/DESIGN.md` 是**未定稿**的设计草案。
- [API 参考](api/index.md) —— 由源码 docstring 直接生成。
