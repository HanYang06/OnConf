# OnConf

> **配置不再有动词：同一个名字读它、写它，两个方向都不丢——不丢一个字节，也不丢一次更新。**
>
> `Configuration has no verbs: one name reads and writes it, in both directions, without losing a byte or an update.`
>
> 以上是**官方定位句**：中文与英文同源，改一句必须同步改另一句，并同步
> `README.md`、`README.zh-CN.md`、`pyproject.toml` 的 `description`
> 与本文件的 `site_description`。

**已发布到 PyPI**，发布名 [`OnConf`](https://pypi.org/project/OnConf/)。当前版本 `1.0.0`，
首个稳定版：公开 API 与磁盘格式从 1.0 起遵循语义化版本，只在**主版本号**变更时才做
破坏性变更；命令行已交付头七条（`build` / `sync` / `check` / `get` / `set` / `diff` / `format`），
其余两条尚未实现
（以[路线图](roadmap/README.md)为准）。

定位句的两个半句现在**都有机制支撑**：「不丢一个字节」由外科手术式回写保证；
「不丢一次更新」由**写权限的角色**保证 —— 引擎不做跨进程协调，创建实例的进程是属主、
派生出来的进程只读，同进程内的实例与线程由一把纯内存的锁互斥
（见[并发模型](design/concurrency.md) 与[威胁模型](security/threat-model.md) 的 T4）。
**持久性也已经兑现**：值文件与词表都经同目录临时文件 → `fsync` → `os.replace` 落盘，
崩溃中途不会留下半截文件（T5）。

## 当前状态

下表是 2026-10-04 的工作区快照，不是承诺。

| 项 | 现状 |
|---|---|
| 版本 | `1.0.0`（2026-10-04 发布，PyPI 上是 [`OnConf`](https://pypi.org/project/OnConf/)） |
| 开发状态 | 稳定（classifier `Development Status :: 5 - Production/Stable`） |
| 公开 API | `AutoConf` / `conf` 两个面，`__all__` 共 8 个符号 |
| 值后端 | JSON（缺省）、YAML、TOML、`.env`（字符串后端）；多文件由 `no_one_file` 开启 |
| 提交点 | 每次 `conf(key, value)` 当场对账并落盘；进程退出时 `atexit` 触发 `Engine.sync()` |
| 日志 | 一份记录流、两个出口：文件出口**恒写**（`log_path`，缺省 `<home>/audit.log`），控制台出口可关（`log_console`）；见[日志](design/log.md) |
| 测试 | 见[路线图](roadmap/README.md) |

## 已实现的能力

- **JSON 值后端**：外科手术式回写，未触及的字节逐字不动。
- **YAML 值后端**：注释、缩进、键序逐字保留。
- **`.env` 值后端**：纯字符串后端，不做键名映射，不认行内注释（`#` 出现在值里时就是值的一部分）。
- **TOML 值后端**：表头归一成点分键。
- **词表**：三态持久化 + JSON Schema 往返 + 哈希短路，落在 `<home>/schema/` 下。
- **引擎装配**：`conf` / `AutoConf` 两个面端到端接通，三种模式（读 / 声明 + 写 / 只登记）
  各自对应一种写法。
- **多文件**：`no_one_file=True` 后键的 `<路径>:` 前缀寻址 `<home>/<路径>.<ext>`；每个
  `(home, file_name)` 一份词表。值文件名（`file_name`）与内嵌路径都过包含性校验。
- **命令行**：`onconf build`（按声明完整重建）与 `onconf sync`（补缺 + 删未声明的键），
  声明靠静态扫描 `conf(...)` 调用得到；`onconf check` 不写一个字节地对比代码 / 词表 /
  值文件三个口径；`get` / `set` / `diff` / `format` 分别取值、改值、查变更历史、重排缩进。
  其余两条（`add` / `log`）尚未实现（`read` 后移，见路线图 2-073）。
- **用值当键**：支持 `conf(conf("app.key_name"))` 这类间接寻址。
- **`$schema` 指针**：每次落盘都保证值文件里有指向词表的指针（**能吃下成员的后端**才写；
  `.env` 与 TOML 放不下成员，跳过）。
- **写权限由进程树定**：创建实例的进程是属主（读 + 写 + 生成词表）；`fork` / `spawn`
  派生出来的进程只读，第一次想写就抛 `ConfError`。命令行会清掉属主标记 ——「想更新，
  拿命令行去」。
- **进程内互斥**：一份值文件一把纯内存的锁，同进程的全部实例与线程共用。
- **按需重读**：指纹（`mtime` + 大小）同时看值文件与词表，读之前与写之前都校验一次，
  外部改动不会被漏掉。
- **原子写**：同目录临时文件 → `fsync` → `os.replace`（POSIX 再加父目录 `fsync`），行尾与权限位原样保留；Windows 上替换带短暂重试（并发读者持有句柄）。
- **可选攒批窗口**：`flush_window`（默认 `0`，即当场落盘）。
- **运行期不删键**：只补缺、只补元数据；删除归 `onconf sync`。
- **日志就是审计**：一份记录流、两个出口。文件出口恒写（`log_path`，缺省
  `<home>/audit.log`：只追加、`0600`、永不截断），控制台出口（`stderr`）可关；TTY 上由
  `rich` 着色（惰性导入，非 TTY 无 ANSI）。写全量、读按事务去重（`n=`），写记录带调用点与
  pid；轮转 / 脱敏 / 编码三个口子默认都不做。终端用**显示宽度**对齐。
- **异常族**：`ConfError` 连同 `KeyNotRegisteredError` / `KeyHasNoValueError` /
  `UnknownEngineParamError`，以及三个**读期**的 `ValueError` 子类
  （`EnvSyntaxError` / `YamlFlatRequiredError` / `TomlFlatRequiredError`，
  `except ConfError` 接不住它们）。见[快速开始](getting-started.md)的常见问题。

尚未实现的能力（把系统环境变量当作配置源、`add` / `log` 两条命令行）
**当前不可用**，一份完整清单见[路线图](roadmap/README.md)。

## 最小示例

```python
from onconf import AutoConf, conf

AutoConf(home="./conf")  # 可省略，走约定
conf("app.server.port", 8080)  # 声明 + 写，返回当前生效值
print(conf("app.server.port"))  # 读
```

`conf(key, value)` 的返回值是**当前生效值**，不是刚传进去的默认值：值文件里已有的值优先。

跑完这段代码，磁盘上会有这些文件：

```text
conf/
  settings.json          # 值文件：{ "$schema": "schema/settings.json", "app.server.port": 8080 }
  schema/
    settings.json        # 词表：库自己的资产，整篇重写
```

第二个是库自己的簿记，不用手改；`.env` / TOML 值文件不写 `$schema` 指针。

`$schema` 指针让编辑器知道词表在哪，从而对这份文件给出补全与校验。
进程退出时 `atexit` 会再触发一次 `Engine.sync()`，把这一轮的声明集收口。

## 下一步

- [快速开始](getting-started.md) —— 环境要求、安装、目录约定、异常怎么区分。
- [路线图](roadmap/README.md) —— 范围与版本的**唯一事实源**：条目卡片（编号 + 决策状态 +
  设计关联 + 版本分配）与按版本归集的清单；[1.0.x](roadmap/1.0.x/roadmap.md) 是它的冻结页。
- [设计稿索引](design/index.md) —— 初始化配置 / 文件支持 / 并发模型 / 日志 / 命令行五份设计口径。
- [API 参考](api/index.md) —— 由源码 docstring 直接生成。
