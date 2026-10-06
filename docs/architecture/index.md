# 架构总览

本页范围：onconf 的模块划分、数据流与关键算法的入口位置。

⏳ 正文待补：等设计定稿后补齐。权威来源是[设计稿索引](../design/index.md)——
`init_config.md` / `file_support.md` / `log.md`；本页只做「实现视角的转述」，
不复制设计稿原文，也不把设计愿景写成既有能力。

## 正文补齐时至少要覆盖的设计稿章节

| 出处 | 主题 | 与代码的对应 |
|---|---|---|
| [文件支持 §1](../design/file_support.md) | 值文件由 `file_name` + `file_type` 决定；多文件走键内嵌路径 | `_engine._values_path`、`_paths.py` |
| [初始化配置 §4](../design/init_config.md) | 三种模式靠 `value` 位判定；`doc` 是唯一的登记元数据 | `_engine.__call__` |
| [初始化配置 §5](../design/init_config.md) | 运行期只补缺；文件里已有的值一律只读 | `_core.reconcile` |
| [文件支持 §6](../design/file_support.md) | 词表只记键、说明、默认值三样 | `_vocab.py` |
| [文件支持 §7](../design/file_support.md) | 外科手术式回写：未被触及的字节逐字不动 | `_json_backend` 等四个后端 |
| [路线图 2-009](../roadmap/2.x.md) | 外部字符串（值文件名、键内嵌路径）到路径的唯一入口 | `_paths.py`（包含性校验） |
| [路线图 2-042](../roadmap/2.x.md) | 命令行：声明靠静态扫描 `conf(...)`，不执行项目代码 | `_cli.py` |

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
| [`_engine.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_engine.py) | 引擎装配：属主闸门、后端选择、提交点、原子落盘、`$schema` 指针 |
| [`errors.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/errors.py) | 异常族：`ConfError` 与各子类；读期的 `ValueError` 子类定义在各后端 |

## 尚未定稿的部分

**并发已经出清**：没有锁、没有独立写者进程、没有 IPC —— 写权限由进程树定（创建实例的
进程是属主，`fork` 出来的只读），同一时刻只有一个写者是调用方的部署责任。口径见
[并发模型](../design/concurrency.md)。
**命令行已交付头两条**（`build` / `sync`），`check` / `get` / `read` / `set` / `diff` /
`format` 与 `add` / `remove` 未实现；落盘形式与轮转参数、按格式导出词表、把系统环境变量
当作配置源仍在增量的未来段里 —— 当前不可用。范围与版本以[路线图](../roadmap/README.md)
为准，本页不重复那份清单。
