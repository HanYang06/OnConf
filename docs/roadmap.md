# 路线图

本页范围：**能力的权威清单**——哪些已经能用、哪些还在路上、哪些当前完全不可用。

⏳ 正文待补：等设计定稿后补齐。本页只列状态与依据，不写实现方案；
方案层面的内容见[设计文档索引](design/index.md)（`init_config.md` / `file_support.md`
正在逐节替换旧稿 `DESIGN.md`）。

!!! info "数字口径"

    下面的口径取自 2026-10-04 的工作区快照：`uv run pytest` 全绿（每个模块一个测试文件，
    外加安全不变量）、`ruff check` 无告警、`mypy --strict` 无告警。
    具体数量会随提交变化，**能力归属不会**。

## 2.0 的范围与顺序（冻结）

2.0 只收**四根柱子**，其余一律不进 —— 有下游项目在等这个版本，所以范围优先于完整：

| 柱子 | 2.0 收什么 | 2.0 **不收**（→ 2.1+） |
|---|---|---|
| **1. 配置面 / API 面** | D01（已交付：三模式、`file_name`、`file_type`、`no_one_file`、无类型声明）；D02（已交付：包含性校验）；D03：**环境变量层不做**（`ONCONF_HOME` 只定位目录），词表形态不变 | `.env` 结构化值（D04，预计 2.2） |
| **2. 进程结构** | D05：独立 Alpha —— 按需拉起、短命、由 `AutoConf` 自举、**所有等待有上界**；运行期的规则 1 一并摘掉 | 读路由「量大」参数、数据交付边界（D07） |
| **3. 审核日志** | D06-3a：**文件通道强制、永远全量**；**终端通道可关、可按级别筛选**；`audit` 开关取消，审计路径改为独立参数 | 落盘四形式与加密、轮转与分流参数（2.1，加密还须先定密钥形态） |
| **4. 命令行** | D08：`build` / `sync`（已交付）+ `check` / `get` / `read` / `set` / `diff` / `format`（仅 JSON） | `add`（生成声明代码）、`remove`（单键删除）、日志分析视图（D10） |

**顺序（依赖驱动，不按编号）**：

```text
D03（一并裁掉环境变量层）
  → D05 进程结构（关键路径，最重）
    → D06-3a 审核日志（「终端回传发起方」那半依赖 D05 的执行点）
      → D08 命令行（依赖 D05 的执行点 + D06 的日志）
        → 2.0 发版：迁移说明 + CHANGELOG + README 状态表
```

**2.0 的破坏性变更**（要写进 CHANGELOG 与迁移说明）：`file_name` / `file_type` 缺省与
空串语义、多文件开关、运行期不再清理未声明的键、日志两通道与 `audit` 开关取消、
进程结构由「进程内写者线程」改为「独立 Alpha」。

**当前卡点**：D05 有 3 处口径没裁（拉起命令来源、事务判据、Alpha 不存在时的处置），
按 D05 自己的话「未定之前该项不落地」—— 它们是 2.0 关键路径上唯一的非工程阻塞。

## 已实现（当前可用）

| 能力 | 说明 | 位置 |
|---|---|---|
| JSON 值后端 | 外科手术式回写：未触及的字节逐字不动 | `src/onconf/_json_backend.py` |
| YAML 值后端 | 注释、缩进、键序逐字保留 | `src/onconf/_yaml_backend.py` |
| `.env` 值后端 | 纯字符串后端：只接受字符串值，不做键名映射，不认行内注释 | `src/onconf/_env_backend.py` |
| TOML 值后端 | 表头归一成点分键 | `src/onconf/_toml_backend.py` |
| 值文件选定 | `file_name`（缺省 `settings`）与 `file_type`（缺省 `"json"`）决定 `<home>/<file_name>.<ext>`。「按存在性挑第一个」已退役 | `Engine._values_path` |
| 多文件 | `no_one_file=True` 后键的 `<路径>:` 前缀寻址 `<home>/<路径>.<ext>`；一份词表、一把锁、每个 `(home, file_name)` 一个写者；路径段过包含性校验 | `_paths.py` + `Engine._address` |
| 命令行（头两条） | `onconf build`（按声明完整重建；`--path` 换输出目录）与 `onconf sync`（补缺 + 删未声明的键；`--no-clean` 只补缺）；声明靠静态扫描 `conf(...)` 调用 | `src/onconf/_cli.py` |
| 词表 | 三态持久化 + JSON Schema 往返 + 哈希短路；每键只记**键 / 说明 / 默认值**三样（类型声明已移除） | `src/onconf/_vocab.py` |
| 引擎装配 | `conf` / `AutoConf` 两个面接通，三种模式（读 / 声明 + 写 / 只登记）各自对应一种写法 | `src/onconf/_engine.py` |
| 引导层与值层分开 | 引导层参数（`home` / `file_type` / `log` / `audit` / `identity` / `flush_window` / `lock_timeout`）只能在第一次调用之前声明；值层每次从文件重读 | `__init__.AutoConf` |
| 用值当键 | 间接寻址，`conf(conf("app.key_name"))` | `_core.py` + `_engine.py` |
| `$schema` 指针 | 每次落盘都保证值文件里有指向词表的指针（放不下成员的后端除外） | `_engine.Engine._ensure_schema_pointer` |
| 异常族 | `ConfError` 与四个子类（`KeyNotRegisteredError` / `KeyHasNoValueError` / `UnknownEngineParamError` / `LockTimeoutError`；读取错误按责任方分成两类，`LockTimeoutError` 定义在 `_lock.py`）；另有三个**读期**的 `ValueError` 子类（`EnvSyntaxError` / `YamlFlatRequiredError` / `TomlFlatRequiredError`，定义在各后端），**不是** `ConfError` 子类 | `src/onconf/errors.py` |
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
| 项目重命名 | **已定案并完成**：展示名 `OnConf`，仓库 / PyPI / import / CLI 统一 `onconf`。含两处磁盘与环境变量层面的变更：词表字段 `x-onconf-hash`、`ONCONF_HOME` |
| 文档与 M5 收口 | `1.0.0` 已于 2026-10-04 发布（PyPI 上发布名 `OnConf`）；README、文档站与 CHANGELOG 都已同步到 1.0；**命令行已交付头两条**（`build` / `sync`），其余七条未实现 |
| 设计文档的逐步替换 | `docs/design/` 下新开 `init_config.md` / `file_support.md` / `log.md`，逐节替换旧稿 `DESIGN.md`；全部替换完成后旧稿删除 |

## 值文件类型的支持计划

「本质上以 JSON 为主」：JSON 是缺省值，也是能力最完整的一份；其余后端是**可选后端**，
不是并列默认。下面按**后端 × 能力**列状态与预计版本 —— 表里的版本号是**排期意向**，
不是承诺，落地时以本节的状态列为准（见[文件支持](design/file_support.md)）。

| 后端 | 标量读写 | `dict` / `list` | 备注 |
|---|---|---|---|
| JSON | ✅ 1.0（主后端） | ✅ 1.0 | 能放 `$schema` 成员；编辑器补全的落点 |
| YAML | ✅ 1.0 | ✅ 1.0 | 注释、锚点、键序原样保留；能放 `$schema` 成员 |
| TOML | ✅ 1.0 | ✅ 1.0（表/数组） | 表头归一成点分键；没有 `null`；放不下 `$schema` 成员 |
| `.env` | ✅ 1.0 | ⏳ 预计 **2.2** | 1.0 是**纯字符串**后端；`dict` / `list` 由 `env_file_dict` / `env_file_list` 两个布尔开关显式开启（默认都关），开启后写入压成字符串、读取尝试解回、解不回就返回字符串 |
| 多文件（键内嵌路径） | — | ✅ 已实现 | `no_one_file=True` + `conf("app/conf/net:net.id.post")`；与路径包含性校验同批落地（`src/onconf/_paths.py`） |
| 系统环境变量当配置源 | — | — | 未排期；`ONCONF_HOME` 目前只用来定位配置目录 |

## 未实现（当前不可用）

以下能力**当前完全不可用**，任何页面都不应把它们写成既有能力。
「批次」一列是本页对**先后**的唯一声明：**下一批** = 紧接着要做的；**未来** = 排在后面，
不承诺版本；**不计划** = 已判定不做。

| 未实现的能力 | 批次 | 归属与依据 |
|---|---|---|
| 日志两通道（终端可选 + 可按级别筛选；文件通道强制全量）与 `audit` 开关的取消、审计路径独立参数 | **下一批** | D06 / ISSUE-005。现状只有「去向」可改，级别是常量全集；`audit` 仍是布尔开关、路径写死 |
| 运行期的规则 1（清理未知键） | **下一批** | ISSUE-035：移出运行期、交给 `onconf sync`（已交付），运行期那条尚未摘掉。写者的声明集不是持久状态，写者一换人基准就重置（§32.4） |
| 落盘形式（明文 / 纯二进制 / 二进制加密 / 明文加密）、加密参数（算法 + 密钥）与轮转三组参数 | **未来** | D06 / D07（ISSUE-039 / 041 / 043）。现状 `AUDIT_MAX_BYTES` 与按大小轮转都写死。**加密还需先定密钥与算法形态**（不引新依赖 + sink 只收参数这两个前提下的落点） |
| `.env` 的 `dict` / `list` 值（`env_file_dict` / `env_file_list` 两个开关，编解码与解不回回落字符串） | **未来（预计 2.2）** | D04 / ISSUE-002 §5 / ISSUE-028 / 026 |
| 逐键覆盖已存在的值（`onconf set`） | **下一批（2.0）** | D08。现状：`sync` 只补缺、不覆盖；要改既存值用 `build` 的整篇重建（先备份或用 `--path`） |
| `check` / `get` / `read` / `diff` / `format`（仅 JSON） | **下一批（2.0）** | D08 / D09 / D10 |
| `add`（生成声明代码）、`remove`（单键删除）、日志分析视图 | **未来** | D09 / D10（`add` 要定「已存在时怎么办」，`remove` 见 ISSUE-047） |
| `check` 按「声明处字面量」出 warning | **下一批（2.0）** | ISSUE-051 / ISSUE-053；同见[初始化配置](design/init_config.md) §8 |
| 前缀分片锁 | **未来** | 当前是每个配置目录一把锁 |
| 按格式导出词表（当前只产出 JSON Schema 一份） | **未来** | — |
| 把系统环境变量当作配置**来源**（`ONCONF_HOME` 只用来定位配置目录） | **未来** | — |
| WAL（预写日志） | **不计划** | §32.7：攒批窗口负责合并突发写、声明可从代码重新推导、专职写者负责串行、读改写 + 原子替换负责顺序 —— WAL 要买的四件事都有别的来源 |

**已定、现在不动的一条**：值文件里的 `$schema` 指针**保持按载体能力**（只有能吃下成员的
后端才写，`.env` / `.toml` 跳过），不新增「要 / 不要」参数 —— `.env` 与 `.toml` 上没有落脚点，
开了也只能是空开关。

## 与 M1–M5 里程碑的对应

设计稿 §10 给出的里程碑是「建议」，不是承诺；下表的判据以本页上述三段为准。

| 里程碑 | 设计稿内容 | 当前状态 |
|---|---|---|
| M1 | 键空间 + 词表 + 层叠 + get/set，单进程纯内存 | **已完成**：核心、词表、引擎装配都在 |
| M2 | 三格式后端（JSON / YAML / .env / env）读写 | **大部分完成**：JSON、YAML、`.env`、TOML 可用；把系统环境变量当配置源未实现 |
| M3 | WAL + flush + 锁 | **基本完成**：跨进程 OS 锁、锁内按需重读、可选攒批窗口（`flush_window`）、原子写（临时文件 + `fsync` + `os.replace`）与新建文件 `0600` 都已落地；WAL **判定不做**（§32.7）。见[威胁模型](security/threat-model.md) |
| （§19.2 / §25） | 专职写者收口 | **已交付**（§32）：抢绑端点即选举、认证搬到应用层、OS 锁退居兜底。注意「全局声明集」只在写者**长命**时成立（§32.4） |
| M4 | 前缀控制 + 审计事件流 + rich 报告 | **部分完成**：审计事件流（§20 / §21）已交付；前缀控制（语义待定）与 rich 报告**未开始** —— `rich` 仍在运行时依赖里，没有代码使用它 |
| M5 | 文档、示例、CI | **接近完成**：`1.0.0` 已于 2026-10-04 发布；文档站、README 与 CHANGELOG 已就位；命令行已交付头两条（`build` / `sync`），其余七条未实现 |

## 相关页面

- [设计稿索引](design/index.md) —— 里程碑原文与阅读顺序。
- [架构总览](architecture/index.md) —— 已实现部分的模块划分。
- [变更日志](community/changelog.md) —— 已发布版本的真实变更。
