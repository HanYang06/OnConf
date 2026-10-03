<!--
  TODO(rename): 项目名与仓库地址尚未定案。定案后需全局替换的字符串：
    auto-conf / auto_conf / HanYang06/auto-conf / hanyang06.github.io/auto-conf
  替换点：README.md、README.zh-CN.md、pyproject.toml、mkdocs.yml、CONTRIBUTING.md、
          SECURITY.md、SUPPORT.md、docs/**、.github/**、NOTICE、CODE_OF_CONDUCT.md。
-->

# auto-conf

[![CI](https://github.com/HanYang06/auto-conf/actions/workflows/ci.yml/badge.svg)](https://github.com/HanYang06/auto-conf/actions/workflows/ci.yml)
[![CodeQL](https://github.com/HanYang06/auto-conf/actions/workflows/codeql.yml/badge.svg)](https://github.com/HanYang06/auto-conf/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/HanYang06/auto-conf/badge)](https://securityscorecards.dev/viewer/?uri=github.com/HanYang06/auto-conf)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/downloads/)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue.svg)](pyproject.toml)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](.pre-commit-config.yaml)

[English](README.md) · **简体中文**

> **配置不再有动词：同一个名字读它、写它，两个方向都不丢——不丢一个字节，也不丢一次更新。**
>
> **Configuration has no verbs: one name reads and writes it, in both directions, without losing a byte or an update.**

上面两句是**官方定位句**：中文与英文同源，改一句必须同步改另一句，并同步
`README.md`、`pyproject.toml` 的 `description`、`mkdocs.yml` 的 `site_description`
与 `docs/index.md`。

> [!WARNING]
> **Pre-Alpha（`0.1.0`）—— 只可用于评估，不要上生产。**
> 公开 API 与磁盘格式都可能在没有弃用期的情况下变更。
> **定位句的最后半句是 M3 的验收标准，不是已交付的事实。**
> 「不丢一个字节」这一半已实现并被测试覆盖（外科手术式回写）；
> 「不丢一次更新」这一半**还没有**——目前没有文件锁，写入也不是原子的，
> 崩溃或并发写入仍可能丢更新、或把配置文件截断。
> 依赖它之前，请先读下面的「已知限制」与[威胁模型](docs/security/threat-model.md)。

文档站（含完整设计稿与威胁模型）：<https://hanyang06.github.io/auto-conf/>

---

## 它是什么

一个配置引擎，面向那些把设置放在**人能直接阅读、也能随手手改的普通文件**里的程序。

- **代码里声明，文件说了算。** 你在 Python 里声明键与类型；磁盘上的文件是唯一事实来源。
  代码不是权威。
- **外科手术式回写。** 引擎改一个键时，它不需要碰的每一个字节都停在原处——
  注释、缩进、键序、空行。
- **一个扁平键空间，多个后端。** `app.server.port` 指向同一个逻辑键，
  无论它落在 JSON、YAML、TOML 还是 `.env` 里。
- **值文件旁边有词表。** 引擎维护一份描述「有哪些键」的 JSON Schema，
  于是你的编辑器能给配置文件补全与校验。
- **没有服务、没有守护进程、没有网络。** 它是一个跑在你进程里的库。

## 它不是什么

- **不是配置中心 / 设置服务。** 没有需要运维的服务。
- **不是密钥管理器。** 值就是明文文件。
- **不是分布式方案。** 跨机一致性是你发布系统的职责，不是这个库的。
- **不是 `pydantic-settings`。** 它不会把环境变量校验成一个类型化对象图；
  它让文件保持权威，并往文件里回写。

## 快速开始

`auto-conf` **还没有发布到 PyPI**（发布名仍在定案中）。从源码安装：

```bash
git clone https://github.com/HanYang06/auto-conf.git
cd auto-conf
uv sync --all-groups
```

然后在任意空目录里：

```python
from auto_conf import AutoConf, conf

AutoConf(home="./conf")        # 可省略——省略时引擎按自己的约定找配置目录
conf("app.server.port", 8080)  # 声明 + 写；返回当前生效值
print(conf("app.server.port")) # 读
```

上面这段是**实测**输出：

```console
$ uv run python -c "from auto_conf import conf; print(conf('app.server.port', 8080)); print(conf('app.server.port'))"
8080
8080
```

它会生成两个文件：

```jsonc
// ./conf/settings.json —— 这是你的文件，随手改
{
  "$schema": "schema/settings.json",
  "app.server.port": 8080
}
```

```jsonc
// ./conf/schema/settings.json —— 引擎自己的资产，按需整体重写
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "app.server.port": { "default": 8080 }
  },
  "x-auto-conf-hash": "5778fdddf8dfa9be"
}
```

## 两个面

所有事情都经过两个可调用对象。这就是全部公开面。

| 面 | 职责 |
|---|---|
| `AutoConf(**engine)` | 配置**引擎自己**：`home`（配置目录）与 `audit`。可省略——不调用它也能按约定工作。 |
| `conf(key, value=..., *, doc=..., type=..., force=..., **engine)` | 干所有的活：读、写、登记。 |

`conf` 从**调用形态**推断这次要做什么，而不是靠一个 `op` 参数：

```python
conf("app.port")                    # 读；键没有值就报错
conf("app.port", 9090)              # 声明 + 写；返回当前生效值
conf("app.port", doc="服务端口")     # 只登记一个键、不给值（必填键）
conf("app.port", 9090, force=True)  # 覆盖文件里已有的值
```

几条容易踩的语义：

- `type=` **只做声明期一致性校验**。引擎对值是透明的，读取期从不转换。
  想从 `.env` 里拿到 `int`？写 `int(conf("PORT"))`——显式，而且在调用点看得见。
- 读一个从未声明过的键抛 `KeyNotRegisteredError`；声明过但没值的键抛
  `KeyHasNoValueError`；值与自己声明的类型冲突抛 `TypeConflictError`。
- 提交点是**立即**的（`atexit` 触发最后一次 `sync()`），不是攒批窗口。
- 引擎是单例：起来之后不能就地改配置。

## 当前已实现

| 能力 | 状态 |
|---|---|
| JSON 值后端 —— 外科手术式回写 | ✅ |
| YAML 值后端 —— 注释、锚点、键序逐字保留 | ✅ |
| `.env` 值后端 —— 纯字符串，不认行内注释，不做键名映射 | ✅ |
| TOML 值后端 —— 表头归一成点分键 | ✅ |
| 词表（键空间）—— 持久化 + JSON Schema 往返 + 哈希短路 | ✅ |
| 引擎装配 —— `conf` / `AutoConf` 端到端 | ✅ |
| 用值当键（间接寻址）+ 每次落盘都保证 `$schema` 指针 | ✅ |
| 异常族 —— `ConfError`、`KeyNotRegisteredError`、`KeyHasNoValueError`、`TypeConflictError`、`UnknownEngineParamError`、`EnvSyntaxError` | ✅ |
| 测试 —— 每个模块一个测试文件，外加安全不变量 | ✅ 本地全绿；CI 在 ubuntu / windows / macos 上跑 |

## 路线图 —— 当前不可用

不要把计划建在这些之上，它们**尚未实现**：

| 能力 | 里程碑 |
|---|---|
| 文件锁 + WAL + 前缀分片锁（真正安全的跨进程写） | M3 |
| 原子写（临时文件 + rename）与 `fsync` | M3 |
| 新建配置文件的最小权限（`0600`） | M3 |
| 事务攒批 / 写合并 | M3 |
| 审计报告与审计事件流（`audit=` 目前被接受但不起作用） | M4 |
| 把系统环境变量当作配置**来源**（`AUTO_CONF_HOME` 只用来定位配置目录） | — |
| 按格式导出词表 | — |
| IPC（TCP loopback + HTTP）与子进程写者模型 | — |
| 真正的命令行（`auto-conf` 目前只打印配置目录就退出） | — |

完整清单见 [`docs/roadmap.md`](docs/roadmap.md)；设计稿见
[`docs/design/DESIGN.md`](docs/design/DESIGN.md)（中文，未定稿）。

## 质量门槛

```bash
uv run pre-commit install --install-hooks   # 一次性
uv run ruff check .
uv run mypy                                  # strict
uv run pytest
uv run pytest --cov --cov-report=term-missing
uv run bandit -c pyproject.toml -r src
uv run pip-audit
uv run zizmor .github/workflows
```

CI 跑 **ubuntu / windows / macos × Python 3.14**，并强制：`ruff check`、`mypy --strict`、
带覆盖率下限的 `pytest`、`bandit`、`pip-audit`、`zizmor`、`actionlint`、`gitleaks`、
CodeQL、依赖审查与 OpenSSF Scorecard。

`ruff format --check` 目前是**非阻塞**的（CI 里 `continue-on-error`）：团队决定在库还在写的
阶段不去重排既有文件。

## 安全

漏洞请走私密渠道——见 [`SECURITY.md`](SECURITY.md)。不要开公开 issue。

本项目承诺的不变量（每一条都有回归测试，见
[`tests/test_security_invariants.py`](tests/test_security_invariants.py)）：

- 默认路径**不开任何网络端口**、**不 spawn 子进程**
- 配置只经 `yaml.safe_load` 解析，绝不用 `yaml.load`
- 键名永不变成文件系统路径
- 不对配置内容做 `eval` / `exec` / `pickle`

### 已知限制

| 限制 | 后果 |
|---|---|
| **没有文件锁** | 多个进程同时写同一个值文件会丢更新，或写出交错内容 |
| **写入不是原子的** | 写入中途崩溃可能留下被截断的配置文件（`write_text`，无临时文件 + rename，无 `fsync`） |
| **不设置文件权限** | 新建文件沿用系统 umask；在 umask 022 的 POSIX 系统上，含密钥的 `.env` 可能对同组或其他用户可读 |
| **符号链接会被跟随** | 值文件是符号链接时，写入会落到链接目标上 |
| **`AUTO_CONF_HOME` 是可信输入** | 它决定配置目录，库不做目录包含性校验 |

完整分析（逐条威胁 + 代码依据）：[`docs/security/threat-model.md`](docs/security/threat-model.md)。

## 仓库结构

```text
src/auto_conf/
  __init__.py        # 两个面：AutoConf + conf
  _engine.py         # 引擎装配、目录约定、落盘
  _core.py           # 对账：三集合算法
  _vocab.py          # 词表 + JSON Schema
  _textscan.py       # 各后端共用的字节级扫描
  _json_backend.py   # JSON 值后端
  _yaml_backend.py   # YAML 值后端
  _env_backend.py    # .env 值后端
  _toml_backend.py   # TOML 值后端
  errors.py          # 异常族
tests/               # 每个模块一个测试文件 + 安全不变量
docs/                # 文档站源码（中文）
  design/DESIGN.md   # 设计稿 —— 对「意图」权威，对「现状」不权威
```

模块会随后端增加而变多，以 `src/auto_conf/` 本身为准。

## 参与贡献

先读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。提交信息遵循
[约定式提交](https://www.conventionalcommits.org/)，**允许中文 subject**。
参与即表示你同意 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。

## 许可

[Apache-2.0](LICENSE) © 2026 HanYang06。第三方组件见
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
