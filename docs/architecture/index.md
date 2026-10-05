# 架构总览

本页范围：onconf 的模块划分、数据流与关键算法的入口位置。

⏳ 正文待补：等设计定稿后补齐。权威来源是
[设计稿](../design/DESIGN.md)——它本身也是**未定稿草案**；本页后续只做「实现视角的转述」，
不复制设计稿原文，也不把设计愿景写成既有能力。

## 正文补齐时至少要覆盖的设计稿章节

| 章节 | 主题 | 与代码的对应 |
|---|---|---|
| §3 键空间与词表 | 键是扁平的点分路径；词表只记键、说明、默认值三样（类型声明已取消） | `_vocab.py` |
| §4 层叠与优先级 | 值文件与默认值的优先级（文件优先） | `_core.read_value` 的读取 |
| §17 事实权威：文件绝对优先 | 代码不权威，文件才是；声明只补写不覆盖 | 全部写入路径的前提 |
| §18 写入对账与读取 | 对账三集合、四条规则、指令键豁免；读取**不推断、不转换** | `_core.reconcile` |
| §29 引擎装配收口 | 规则 1 需要「期望集完整」；`conf(key, doc=…)` 的归属；v1 的提交点 | `_engine.Engine` 的取舍依据 |
| D01 / D02 | 外部字符串（值文件名、键内嵌路径）到路径的唯一入口 | `_paths.py`（包含性校验） |
| D08 | 命令行：声明靠静态扫描 `conf(...)`，不执行项目代码 | `_cli.py` |

## 当前实现的位置

| 模块 | 职责 |
|---|---|
| [`_core.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_core.py) | 纯内存核心：对账四条规则、读取、声明集哈希 |
| [`_paths.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_paths.py) | 外部字符串 → 路径的唯一入口：包含性校验（纯文件名 / 相对路径、无分隔符、无 `..`、非绝对、解析后仍在 `<home>` 内） |
| [`_cli.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_cli.py) | 命令行：`build` / `sync`；声明靠 `ast` 扫描 `conf(...)` 调用（不 import、不 eval） |
| [`_vocab.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_vocab.py) | 词表：三态持久化、JSON Schema 往返、哈希短路 |
| [`_json_backend.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_json_backend.py) | JSON 值后端：外科手术式回写 |
| [`_yaml_backend.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_yaml_backend.py) | YAML 值后端：注释、缩进、键序逐字保留 |
| [`_env_backend.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_env_backend.py) | `.env` 值后端：纯字符串，不做键名映射；`EnvSyntaxError` 也定义在这里 |
| [`_toml_backend.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_toml_backend.py) | TOML 值后端：表头归一成点分键，注释与键序逐字保留；`TomlFlatRequiredError` 也定义在这里 |
| [`_textscan.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_textscan.py) | 各后端共用的字节级扫描 |
| [`_lock.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_lock.py) | 跨进程排他锁：操作系统级锁（`msvcrt` / `fcntl`），进程崩溃由 OS 释放。**兜底路径**才用得上 |
| [`_owner.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_owner.py) | 专职写者：端点选举（抢绑即选举）、应用层认证、IPC、写者循环与会话线程 |
| [`_engine.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_engine.py) | 引擎装配：路由（「我是不是写者」）、后端选择、提交点、原子落盘、`$schema` 指针 |
| [`errors.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/errors.py) | 异常族：`ConfError` 与各子类；`LockTimeoutError` 在 `_lock.py`，读期的 `ValueError` 子类定义在各后端 |

## 尚未定稿的部分

**并发已经收口**：专职写者（§32）与 OS 锁兜底（§31）都已落地，原子写与新建文件权限也补齐了。
**命令行已交付头两条**（`build` / `sync`），其余七条（`check` / `format` / `diff` / `read` /
`get` / `set` / `add`）未实现；规则 1 移出运行期（ISSUE-035）、日志两通道与落盘形式、
前缀分片锁、把系统环境变量当配置源、按格式导出词表 ——
这些在[路线图](../roadmap.md)里标记为**未实现**，当前不可用；
它们的取舍与实测数据散落在设计稿的 §5、§13、§19、§22、§25、§30、§31、§32。
