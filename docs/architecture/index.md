# 架构总览

本页范围：auto-conf 的模块划分、数据流与关键算法的入口位置。

⏳ 正文待补：等设计定稿后补齐。权威来源是
[设计稿](../design/DESIGN.md)——它本身也是**未定稿草案**；本页后续只做「实现视角的转述」，
不复制设计稿原文，也不把设计愿景写成既有能力。

## 正文补齐时至少要覆盖的设计稿章节

| 章节 | 主题 | 与代码的对应 |
|---|---|---|
| §3 键空间与词表 | 键是扁平的点分路径；词表记录类型、默认值、说明 | `_vocab.py` |
| §4 层叠与优先级 | 值文件与默认值的优先级（文件优先） | `_core.read_value` 的读取五步 |
| §17 事实权威：文件绝对优先 | 代码不权威，文件才是；声明只补写不覆盖 | 全部写入路径的前提 |
| §18 写入对账与读取推断 | 对账三集合、四条规则、指令键豁免 | `_core.reconcile` |
| §29 引擎装配收口 | 规则 1 需要「期望集完整」；`conf(key, doc=…)` 的归属；v1 的提交点 | `_engine.Engine` 的取舍依据 |

## 当前实现的位置

| 模块 | 职责 |
|---|---|
| [`_core.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_core.py) | 纯内存核心：对账四条规则、读取五步、类型推断与转换、声明集哈希 |
| [`_vocab.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_vocab.py) | 词表：三态持久化、JSON Schema 往返、哈希短路 |
| [`_json_backend.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_json_backend.py) | JSON 值后端：外科手术式回写 |
| [`_yaml_backend.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_yaml_backend.py) | YAML 值后端：注释、缩进、键序逐字保留 |
| [`_env_backend.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_env_backend.py) | `.env` 值后端：纯字符串，不做键名映射；`EnvSyntaxError` 也定义在这里 |
| [`_textscan.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_textscan.py) | 各后端共用的字节级扫描 |
| [`_lock.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_lock.py) | 跨进程排他锁：操作系统级锁（`msvcrt` / `fcntl`），进程崩溃由 OS 释放。**兜底路径**才用得上 |
| [`_owner.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_owner.py) | 专职写者：端点选举（抢绑即选举）、应用层认证、IPC、写者循环与会话线程 |
| [`_engine.py`](https://github.com/HanYang06/auto-conf/blob/main/src/auto_conf/_engine.py) | 引擎装配：路由（「我是不是写者」）、后端选择、提交点、原子落盘、`$schema` 指针 |

## 尚未定稿的部分

**并发已经收口**：专职写者（§32）与 OS 锁兜底（§31）都已落地，原子写与新建文件权限也补齐了。
仍未定稿的是：**短命进程之间的规则 1**（写者的声明集不是持久状态，§32.4）、前缀分片锁、
审计报告与审计事件流（§20 / §21，**下一阶段**）、把系统环境变量当配置源、按格式导出词表 ——
这些在[路线图](../roadmap.md)里标记为**未实现**，当前不可用；
它们的取舍与实测数据散落在设计稿的 §5、§13、§19、§22、§25、§30、§31、§32。
