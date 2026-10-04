# 路线图

本页范围：**能力的权威清单**——哪些已经能用、哪些还在路上、哪些当前完全不可用。

⏳ 正文待补：等设计定稿后补齐。本页只列状态与依据，不写实现方案；
方案层面的内容见[设计稿](design/DESIGN.md)（未定稿草案）。

!!! info "数字口径"

    下面的口径取自 2026-10-04 的工作区快照：`uv run pytest` 全绿（每个模块一个测试文件，
    外加安全不变量）、`ruff check` 无告警、`mypy --strict` 无告警。
    具体数量会随提交变化，**能力归属不会**。

## 已实现（当前可用）

| 能力 | 说明 | 位置 |
|---|---|---|
| JSON 值后端 | 外科手术式回写：未触及的字节逐字不动 | `src/onconf/_json_backend.py` |
| YAML 值后端 | 注释、缩进、键序逐字保留 | `src/onconf/_yaml_backend.py` |
| `.env` 值后端 | 纯字符串后端：只接受字符串值，不做键名映射，不认行内注释 | `src/onconf/_env_backend.py` |
| TOML 值后端 | 表头归一成点分键 | `src/onconf/_toml_backend.py` |
| 词表 | 三态持久化 + JSON Schema 往返 + 哈希短路 | `src/onconf/_vocab.py` |
| 引擎装配 | `conf` / `AutoConf` 两个面接通，声明到读回端到端可用 | `src/onconf/_engine.py` |
| 用值当键 | 间接寻址，`conf(conf("app.key_name"))` | `_core.py` + `_engine.py` |
| `$schema` 指针 | 每次落盘都保证值文件里有指向词表的指针（放不下成员的后端除外） | `_engine.Engine._ensure_schema_pointer` |
| 异常族 | `ConfError` 与五个子类（读取错误按责任方分成两类；`LockTimeoutError` 定义在 `_lock.py`）；另有三个**读期**的 `ValueError` 子类（`EnvSyntaxError` / `YamlFlatRequiredError` / `TomlFlatRequiredError`，定义在各后端），**不是** `ConfError` 子类 | `src/onconf/errors.py` |
| 提交点 | 每次 `conf(key, value)` 当场对账落盘；`atexit` 触发 `Engine.sync()`；`flush_window > 0` 时改为四个提交点（窗口到期 / 一次读 / `sync()` / 进程退出） | `__init__._sync_at_exit` |
| 跨进程排他锁 | 操作系统级锁（Windows `msvcrt.locking`、其它 `fcntl.flock`），进程崩溃由 OS 释放；超时抛 `LockTimeoutError` | `src/onconf/_lock.py` |
| 锁内按需重读 | 指纹（`mtime` + 大小）**同时**看值文件与词表，避免把别人刚登记的键挤掉 | `Engine._reload_if_changed` |
| 专职写者 | 谁先抢绑到配置目录的端点，谁就是唯一的读写者；其余进程经 `multiprocessing.connection` 发请求。**抢绑即选举**，不涉及锁文件；认证在应用层，等待有界 | `src/onconf/_owner.py` |
| 原子写 | 同目录临时文件 → `fsync` → `os.replace`，POSIX 再加父目录 `fsync`；沿用文件原本的**行尾**与权限位 | `Engine._atomic_write_text` |
| 日志与审计 | 强制 `[Read]` / `[Write]` / `[Change]` / `[Error]` 事件流，外加进程结构三行 `[Start]`（引擎起来）/ `[Link]`（bind / connect / fallback）/ `[Send]`（一次请求真的过了 IPC）：去向可改（`log="stderr"` 默认 / `"stdout"` / 文件）、**不可关闭**；写全量（含 `op=skip` / `op=noop`）、读按事务去重（`n=`）；写记录带调用点、pid 与可选 `identity=`；终端按**显示宽度**弹性对齐、文件形态紧凑且不截断；`audit=True` 追加写 append-only 的 `<home>/audit.log`（`0600`、按大小轮转） | `src/onconf/_audit.py`（设计稿 §20 / §21） |

## 进行中（已开始，尚未交付）

| 事项 | 现状 |
|---|---|
| 声明集哈希的整体短路 | 声明集哈希**已经算出来并写进词表**（`x-onconf-hash`），但引擎还没用它做「整体跳过」，当前靠词表逐项 diff 达到等效效果（设计稿 §29.3 也是这么记的） |
| 运行中改引擎配置 | v1 只允许在第一次调用之前设置 `home` / `log` / `audit` / `identity` / `flush_window`；引擎起来后再带参数调用 `AutoConf(...)` 会抛 `ConfError` |
| 项目重命名 | **已定案并完成**：展示名 `OnConf`，仓库 / PyPI / import / CLI 统一 `onconf`。含两处磁盘与环境变量层面的变更：词表字段 `x-onconf-hash`、`ONCONF_HOME` |
| 文档与 M5 收口 | `1.0.0` 已于 2026-10-04 发布（PyPI 上发布名 `OnConf`）；README、文档站与 CHANGELOG 都已同步到 1.0；**剩余的硬缺口只有命令行** —— `onconf` 入口仍是占位 |

## 未实现（当前不可用）

以下能力**当前完全不可用**，任何页面都不应把它们写成既有能力：

| 未实现的能力 | 归属里程碑 |
|---|---|
| WAL（预写日志） | **判定不做**（§32.7）：攒批窗口负责合并突发写、声明可从代码重新推导、专职写者负责串行、读改写 + 原子替换负责顺序 —— WAL 要买的四件事都有别的来源 |
| 短命进程之间的规则 1（清理未知键） | **待定的设计问题**（§32.4）：写者的声明集不是持久状态，写者一换人基准就重置。倾向把规则 1 限定在「单写者且长命」的前提下 —— 多进程 + 短命进程下没有任何一个进程知道完整期望集 |
| 前缀分片锁 | —（当前是每个配置目录一把锁） |
| 把系统环境变量当作配置源（`ONCONF_HOME` 目前只用来定位配置目录） | — |
| 按格式导出词表（当前只产出 JSON Schema 一份） | — |
| 真正的命令行（`onconf` 入口目前只打印配置目录） | M5 |

## 与 M1–M5 里程碑的对应

设计稿 §10 给出的里程碑是「建议」，不是承诺；下表的判据以本页上述三段为准。

| 里程碑 | 设计稿内容 | 当前状态 |
|---|---|---|
| M1 | 键空间 + 词表 + 层叠 + get/set，单进程纯内存 | **已完成**：核心、词表、引擎装配都在 |
| M2 | 三格式后端（JSON / YAML / .env / env）读写 | **大部分完成**：JSON、YAML、`.env`、TOML 可用；把系统环境变量当配置源未实现 |
| M3 | WAL + flush + 锁 | **基本完成**：跨进程 OS 锁、锁内按需重读、可选攒批窗口（`flush_window`）、原子写（临时文件 + `fsync` + `os.replace`）与新建文件 `0600` 都已落地；WAL **判定不做**（§32.7）。见[威胁模型](security/threat-model.md) |
| （§19.2 / §25） | 专职写者收口 | **已交付**（§32）：抢绑端点即选举、认证搬到应用层、OS 锁退居兜底。注意「全局声明集」只在写者**长命**时成立（§32.4） |
| M4 | 前缀控制 + 审计事件流 + rich 报告 | **部分完成**：审计事件流（§20 / §21）已交付；前缀控制（语义待定）与 rich 报告**未开始** —— `rich` 仍在运行时依赖里，没有代码使用它 |
| M5 | 文档、示例、CI | **接近完成**：`1.0.0` 已于 2026-10-04 发布；文档站、README 与 CHANGELOG 已就位；**命令行仍是占位**（唯一硬缺口） |

## 相关页面

- [设计稿索引](design/index.md) —— 里程碑原文与阅读顺序。
- [架构总览](architecture/index.md) —— 已实现部分的模块划分。
- [变更日志](community/changelog.md) —— 已发布版本的真实变更。
