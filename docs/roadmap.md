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
| JSON 值后端 | 外科手术式回写：未触及的字节逐字不动 | `src/auto_conf/_json_backend.py` |
| YAML 值后端 | 注释、缩进、键序逐字保留 | `src/auto_conf/_yaml_backend.py` |
| `.env` 值后端 | 纯字符串后端：只接受字符串值，不做键名映射，不认行内注释 | `src/auto_conf/_env_backend.py` |
| TOML 值后端 | 表头归一成点分键 | `src/auto_conf/_toml_backend.py` |
| 词表 | 三态持久化 + JSON Schema 往返 + 哈希短路 | `src/auto_conf/_vocab.py` |
| 引擎装配 | `conf` / `AutoConf` 两个面接通，声明到读回端到端可用 | `src/auto_conf/_engine.py` |
| 用值当键 | 间接寻址，`conf(conf("app.key_name"))` | `_core.py` + `_engine.py` |
| `$schema` 指针 | 每次落盘都保证值文件里有指向词表的指针（放不下成员的后端除外） | `_engine.Engine._ensure_schema_pointer` |
| 异常族 | `ConfError` 与四个子类（读取错误按责任方分成两类）；另有 `.env` 后端的 `EnvSyntaxError`（`ValueError` 子类，定义在 `_env_backend.py`） | `src/auto_conf/errors.py` |
| 提交点 | 每次 `conf(key, value)` 当场对账落盘；`atexit` 触发 `Engine.sync()` | `__init__._sync_at_exit` |

## 进行中（已开始，尚未交付）

| 事项 | 现状 |
|---|---|
| 声明集哈希的整体短路 | 声明集哈希**已经算出来并写进词表**（`x-auto-conf-hash`），但引擎还没用它做「整体跳过」，当前靠词表逐项 diff 达到等效效果（设计稿 §29.3 也是这么记的） |
| 运行中改引擎配置 | v1 只允许在第一次调用之前设置 `home` / `audit`；引擎起来后再带参数调用 `AutoConf(...)` 会抛 `ConfError` |
| `audit=` 开关 | 参数会被接受并通过校验，但**当前不产生任何行为**（`Engine.audit` 只被赋值，没有读者）；真正的审计留给 M4 |
| 项目重命名 | **只剩项目名与仓库 URL 待定案**（定位句已定稿，见两份 README）；定案后需统一替换，替换点已在 `pyproject.toml`、`mkdocs.yml`、两份 README 与 `docs/` 中标注 |
| 文档与 M5 收口 | README 与文档站骨架已就位；示例与 CI 侧的门槛联动仍在收口，命令行仍是占位 |

## 未实现（当前不可用）

以下能力**当前完全不可用**，任何页面都不应把它们写成既有能力：

| 未实现的能力 | 归属里程碑 |
|---|---|
| WAL（预写日志） | M3 |
| 跨进程文件锁 | M3 |
| 前缀分片锁 | M3 |
| 原子写（临时文件 + `rename`）与 `fsync` | M3 |
| 新建配置文件的权限收紧 | M3 |
| 事务攒批去抖（固定窗口提交） | M3 |
| 审计报告与审计事件流 | M4 |
| 把系统环境变量当作配置源（`AUTO_CONF_HOME` 目前只用来定位配置目录） | — |
| IPC（TCP loopback + HTTP）与子进程写者模型 | — |
| 按格式导出词表（当前只产出 JSON Schema 一份） | — |
| 真正的命令行（`auto-conf` 入口目前只打印配置目录） | M5 |

## 与 M1–M5 里程碑的对应

设计稿 §10 给出的里程碑是「建议」，不是承诺；下表的判据以本页上述三段为准。

| 里程碑 | 设计稿内容 | 当前状态 |
|---|---|---|
| M1 | 键空间 + 词表 + 层叠 + get/set，单进程纯内存 | **已完成**：核心、词表、引擎装配都在 |
| M2 | 三格式后端（JSON / YAML / .env / env）读写 | **大部分完成**：JSON、YAML、`.env`、TOML 可用；把系统环境变量当配置源未实现 |
| M3 | WAL + flush + 锁 | **未开始**：多进程并发写仍不安全（无锁、写入非原子、不设权限），见[威胁模型](security/threat-model.md) |
| M4 | 前缀控制 + 审计事件流 + rich 报告 | **未开始**：`rich` 已在运行时依赖里，但还没有任何代码使用它 |
| M5 | 文档、示例、CI | **进行中**：文档站骨架已就位；命令行仍是占位 |

## 相关页面

- [设计稿索引](design/index.md) —— 里程碑原文与阅读顺序。
- [架构总览](architecture/index.md) —— 已实现部分的模块划分。
- [变更日志](community/changelog.md) —— 已发布版本的真实变更。
