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
| [路线图 §1.9](../roadmap/2.0.x/roadmap.md) | 外部字符串（值文件名、键内嵌路径）到路径的唯一入口 | `_paths.py`（包含性校验） |
| [路线图 §4](../roadmap/2.0.x/roadmap.md) | 命令行：声明靠静态扫描 `conf(...)`，不执行项目代码 | `_cli.py` |

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

**并发已经收口**：专职写者与 OS 锁兜底都已落地，原子写与新建文件权限也补齐了。
**命令行已交付头两条**（`build` / `sync`），其余七条（`check` / `format` / `diff` / `read` /
`get` / `set` / `add`）未实现；运行期不清理未声明的键、日志两通道与落盘形式、
前缀分片锁、把系统环境变量当配置源、按格式导出词表 ——
这些在[2.0.x 路线图](../roadmap/2.0.x/roadmap.md)里标为 `待实现` / 2.1+，当前不可用；
每条的原因与代价都写在那份路线图里。
