# OnConf

[![CI](https://github.com/HanYang06/OnConf/actions/workflows/ci.yml/badge.svg)](https://github.com/HanYang06/OnConf/actions/workflows/ci.yml)
[![CodeQL](https://github.com/HanYang06/OnConf/actions/workflows/codeql.yml/badge.svg)](https://github.com/HanYang06/OnConf/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/HanYang06/OnConf/badge)](https://securityscorecards.dev/viewer/?uri=github.com/HanYang06/OnConf)
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

> [!IMPORTANT]
> **`1.0.0` —— 首个稳定版**（2026-10-04）。公开 API 与磁盘格式从 1.0 起遵循
> [语义化版本](https://semver.org/lang/zh-CN/)：只有**主版本号**变更时才做破坏性变更，
> 每一次变更都记进[变更日志](CHANGELOG.md)。
> **`1.0` 与 `2.0` 都是破坏性变更版本**：**后续一律以 2.0 为准**；1.0 的形态见
> [路线图 1.0.x](docs/roadmap/1.0.x/roadmap.md)。
> **定位句的两个半句现在都有机制支撑**：「不丢一个字节」由外科手术式回写保证；
> 「不丢一次更新」由**写权限的角色**保证 —— 引擎不做跨进程协调，同一时刻只有一个写者
> 是部署责任：创建引擎实例的进程是属主，`fork` / `spawn` 派生出来的进程只读。
> 进程内的多个实例与多个线程由一把**纯内存**的锁互斥。
> 写入是原子的：同目录临时文件 → `fsync` → `os.replace`（POSIX 再加父目录 `fsync`），
> 并且沿用文件原本的行尾与权限位。
> 依赖它之前，请先读下面的「已知限制」与[威胁模型](docs/security/threat-model.md)。

文档站（含完整设计稿与威胁模型）：<https://hanyang06.github.io/OnConf/>

---

## 它是什么

一个配置引擎，面向那些把设置放在**人能直接阅读、也能随手手改的普通文件**里的程序。

- **代码里声明，文件说了算。** 你在 Python 里声明键（以及可选的说明）；磁盘上的文件是唯一
  事实来源。代码不是权威，运行期也绝不覆盖文件里已有的值。
- **外科手术式回写。** 引擎改一个键时，它不需要碰的每一个字节都停在原处——
  注释、缩进、键序、空行。
- **一个扁平键空间，以 JSON 为主。** `app.server.port` 指向同一个逻辑键，
  无论它落在 JSON、YAML、TOML 还是 `.env` 里。**JSON 是主值文件格式** —— 它是
  `file_type` 的缺省值、能力最完整的一份，也是 `$schema` 指针（编辑器补全）的落点；
  YAML / TOML / `.env` 是**可选后端**，不是与缺省并列的默认。
- **值文件旁边有词表。** 引擎维护一份描述「有哪些键」的 JSON Schema，
  于是你的编辑器能给配置文件补全与校验。
- **没有独立进程、没有守护进程、没有网络。** 它是一个跑在**你**进程里的库。唯一的机械是一个
  **写者线程**，住在最先抢绑到配置目录的那个进程里；它通过本地管道服务其它进程，用 `schema/`
  下的一把钥匙认证。不开任何端口，也不 spawn 子进程。

## 它不是什么

- **不是配置中心 / 设置服务。** 没有需要运维的服务。
- **不是密钥管理器。** 值就是明文文件。
- **不是分布式方案。** 跨机一致性是你发布系统的职责，不是这个库的。
- **不是 `pydantic-settings`。** 它不会把环境变量校验成一个类型化对象图；
  它让文件保持权威，并往文件里回写。

## 快速开始

`onconf` 已发布到 PyPI，发布名是 [`OnConf`](https://pypi.org/project/OnConf/)：

```bash
uv add onconf
```

或者从源码安装：

```bash
git clone https://github.com/HanYang06/OnConf.git
cd onconf
uv sync --all-groups
```

然后在任意空目录里：

```python
from onconf import AutoConf, conf

AutoConf(home="./conf")  # 可省略——省略时引擎按自己的约定找配置目录
conf("app.server.port", 8080)  # 声明 + 写；返回当前生效值
print(conf("app.server.port"))  # 读
```

上面这段是**实测**输出：

```console
$ uv run python -c "from onconf import conf; print(conf('app.server.port', 8080)); print(conf('app.server.port'))"
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
  "x-onconf-hash": "5778fdddf8dfa9be"
}
```

## 两个面

所有事情都经过两个可调用对象。这就是全部公开面。

| 面 | 职责 |
|---|---|
| `AutoConf(**engine)` | 配置**引擎自己**：`home`（配置目录，缺省 `./conf`）、`file_name`（值文件名主干，缺省 `settings`）、`file_type`（用哪个值文件，单值，缺省 `"json"`）、`no_one_file`（多文件：键的 `<路径>:` 前缀寻址 `<home>/<路径>.<ext>`）、`log_path`（审计文件的落点：空串 = `<home>/audit.log`，相对路径按 `<home>` 解析）、`log_console`（是否再把一份人读的刷到 `stderr`，缺省开）、`log_rotate` / `log_scrub` / `log_encode`（三个可选钩子：下一批写到哪个文件、落盘前怎么脱敏、最终落盘的字节）、`identity`（可选的 `服务@主机` 标记，写进每一行）、`flush_window`（攒批窗口，`0` = 当场落盘）。可省略——不调用它也能按约定工作。 |
| `conf(key, value=..., doc=...)` | 干所有的活：读、写、登记。 |

值文件的**名字**（以及多文件键里内嵌的路径）是这个库里唯一能到达文件系统的外部字符串，
所以它们只经过一道包含性校验：纯文件名、无分隔符、无 `..`、非绝对路径，且解析后仍在 `<home>` 之内。

`conf` 的模式**只看调用形态**，判据只有一句：**`value` 位填没填**。

```python
conf("app.port")                    # 读；键没有值就报错
conf("app.port", 9090)              # 声明 + 写；返回当前生效值
conf("app.port", 9090, "服务端口")   # 同上，并把说明登记进词表
conf("app.port", doc="服务端口")     # 只登记一个键、不给值（必填键）
```

四条硬口径：

- **`None` / `""` / `0` 都算填了**；`MISSING` 是唯一哨兵。
- 第 2 位置恒属 `value`，所以 `conf(key, x)` 永远是写；「只登记」只能由 `doc=` 关键字触发。
- `doc` 是第三个**位置**参数，也是唯一的登记元数据。判据只有这一位，
  参数面**封闭**：以后新增参数不需要动判据。
- 使用口**不能配置引擎**：`conf(..., home=…)` 是 `TypeError`。

几条容易踩的语义：

- **没有类型声明，引擎也从不转换值。** `.env` 给你的就是 `"8080"`；
  想要 `int` 就在调用点写 `int(conf("PORT"))`——显式，而且在哪儿转换一眼可见。
- **同一个键在不同后端可以读回不同类型，且刻意不承诺可移植**：`conf("app.tags")`
  在 JSON 上是列表 `["a", "b"]`，在 `.env` 上是字符串 `"['a', 'b']"`。这条差异不进词表
  —— 写在这里，因为「载体能表达就返回」就是全部规则。
- 读一个从未声明过的键抛 `KeyNotRegisteredError`；声明过但没值的键抛 `KeyHasNoValueError`。
- **运行期绝不覆盖文件里已有的值。** 文件里是 `8080`、代码声明 `9090`，
  文件一个字节都不动，日志里记一条 `op=skip`，返回值仍是当前生效的 `8080`。
  覆盖是人的决定：`onconf sync` 也不会碰既存值（只补缺、只删未声明的键），
  `onconf build` 则按声明**完整重建**值文件（先备份，或用 `--path`）。
- 运行期只写两样东西：**缺失的键**与**词表元数据**。
- 引擎配置分两层：**引导层**（`home` / `file_name` / `file_type` / `no_one_file` /
  `log_path` / `log_console` / `log_rotate` / `log_scrub` / `log_encode` / `identity` /
  `flush_window`）起来之后不能改
  ——改了等于改代码；**值层**随时可改，因为值每次都从文件重新读。
- **谁能写**由进程树决定，不靠开关：创建引擎实例的进程是**属主**（读 + 写 + 生成词表）；
  从它派生出来的进程——`fork`，或者继承了 `ONCONF_OWNER_PID` 的 `spawn` / `subprocess`
  ——**只读**，第一次想写就抛 `ConfError`。同一进程里的多个实例、多个线程共用一把内存锁，
  彼此不会盖掉对方的键。
- 提交点**默认是立即的**（`atexit` 触发最后一次 `sync()`）。攒批窗口需显式开启（`flush_window`）；
  开启后落盘发生在四个提交点：窗口到期 / 一次读 / `sync()` / 进程退出。

## 使用范式：**声明处必须字面量**

带上 `value` 的那些调用**就是规格本身**，所以键、值、说明都写成字面量：

```python
conf("app.post", 8080, "服务端口")                  # ✅
conf("slot.max.byte.b", 512, "格长档位之一")        # ✅
```

```python
APP_POST = "app.post"
conf(APP_POST, 8080)                 # ❌ Python 合法，但声明处不是字面量
for key, default in TIERS:
    conf(key, default)               # ❌ 同一件事，多绕了一层
conf(build_key(), 8080)              # ❌
```

**读取不受这条限制**：`conf("app.post")` 与 `conf(APP_POST)` 都可以 —— 读取不产生任何持久状态，
常量写错了会当场抛 `KeyNotRegisteredError`，不会静默。

**这是约定，不是强制检查**：它「合法但不合理」（Python 合法、在本库不合理），
库不去管你的代码。藏起来的声明会让你丢掉这些东西：

- **命令行看不见它。** `onconf build` / `onconf sync` 靠读 `conf(...)` 的实参得到声明，
  所以 `sync` 会把那个键当作「代码没声明」；存在这类调用时它**拒绝删除任何键**，
  宁可不动也不猜（想继续就加 `--no-clean`）。
- **静态复核看不见它。** `grep app.post` 找不到声明点，任何按调用点做的工具都找不到 ——
  包括计划中的 `check`（它只出 warning，永远不出 error）。
- **声明点不自证。** 计算出来的值与说明（`X if cond else Y`、f-string）在你查看的地方
  是看不见的；循环 / 数据结构那种写法更进一步：从代码里回答不了「我们到底有哪些配置项」。

值文件里的编辑器补全**不受影响** —— 词表是运行期按登记过的键生成的。

## 当前已实现

| 能力 | 状态 |
|---|---|
| **JSON 值后端 —— 主后端**（`file_type` 缺省值）—— 外科手术式回写 | ✅ |
| YAML 值后端 —— **可选**；注释、锚点、键序逐字保留 | ✅ |
| `.env` 值后端 —— **可选**；纯字符串，不认行内注释，不做键名映射 | ✅ |
| TOML 值后端 —— **可选**；表头归一成点分键 | ✅ |
| 词表（键空间）—— 持久化 + JSON Schema 往返 + 哈希短路。每个键只记三样：键、说明、默认值 | ✅ |
| 值文件选定 —— `file_name`（缺省 `settings`）与 `file_type`（单值，缺省 `"json"`）决定 `<home>/<file_name>.<ext>` | ✅ |
| **多文件** —— `no_one_file=True` 后键的 `<路径>:` 前缀寻址 `<home>/<路径>.<ext>`（例：`conf("app/conf/net:net.id.post", 8080)` → `<home>/app/conf/net.json`）。没有前缀的键仍落在默认文件。每个 `(home, file_name)` 一份词表；每一段内嵌路径都过包含性校验 | ✅ |
| 引擎装配 —— `conf` / `AutoConf` 端到端 | ✅ |
| **写权限由进程树定** —— 创建引擎实例的进程是**属主**（读 + 写 + 生成词表）；从它派生出来的进程**只读**，第一次想写就抛 `ConfError`：`fork` 靠 pid 核对认出来，`spawn` / `subprocess` 靠继承到的 `ONCONF_OWNER_PID` 认出来。命令行会清掉这个标记 —— 「想更新，拿命令行去」 | ✅ |
| **进程内互斥** —— 一份值文件一把**内存**锁，同进程的全部实例与线程共用，彼此不会盖掉对方的键；它从不碰文件系统 | ✅ |
| 按需重读 —— 指纹（`mtime` + 大小）同时看值文件与词表，**读之前与写之前**都校验一次，外部改动（或属主的提交）不会被漏掉 | ✅ |
| **原子写 + 有界重试** —— 同目录临时文件 → `fsync` → `os.replace`，POSIX 再加父目录 `fsync`；行尾与权限位原样保留，新建文件是 `0600`。Windows 上替换会短暂重试：并发**读者**持有文件句柄，而读者不加锁 | ✅ |
| 可选攒批窗口 —— `flush_window`（默认 `0`，当场落盘），窗口归**每个引擎自己** | ✅ |
| 用值当键（间接寻址）+ 每次落盘都保证 `$schema` 指针（仅 JSON / YAML —— `.env` 与 `.toml` 放不下成员，会直接跳过） | ✅ |
| 异常族 —— `ConfError` 作基类，含 `KeyNotRegisteredError`、`KeyHasNoValueError`、`UnknownEngineParamError`。`EnvSyntaxError`、`YamlFlatRequiredError`、`TomlFlatRequiredError` 是 `ValueError` 子类，**不会**被 `except ConfError` 捕获 | ✅ |
| **日志就是审计** —— 一份记录流、两个出口。**文件**出口恒写（`log_path`，缺省 `<home>/audit.log`）：只追加、`0600`、紧凑 `key=value`、完整日期、**永不截断**。**控制台**出口（`stderr`）可以关（`log_console=False`）；TTY 上由 `rich` 着色——只在那个分支里惰性导入，所以强制路径与管道既不多付代价、也永远看不到 ANSI。级别是 `[Read]` / `[Write]` / `[Change]` / `[Error]` 外加 `[Start]`；写全量（含 `op=skip`「想改没改」与 `op=noop`「本批声明已满足」），读按事务去重（`n=1000`）；每条写记录带调用点（`at=app/config.py:12`）、pid 与可选 `identity=`。三个可选钩子——`log_rotate`（下一批写到哪个文件；**轮转只换落点，绝不 rename 文件**）、`log_scrub`（落盘前脱敏）、`log_encode`（最终落盘的字节）——默认全是「什么都不做」。见[日志](docs/design/log.md) | ✅ |
| **运行期不删键** —— 只补缺、只补元数据；删除归 `onconf sync`（离线、单次、对着完整的声明集） | ✅ |
| 测试 —— 每个模块一个测试文件，外加安全不变量 | ✅ 本地全绿；CI 在 ubuntu / windows / macos 上跑 |
| **命令行（七条命令）** —— `onconf build` 按声明完整重建值文件与词表（`--path` 把整份重建写到新目录，原目录不动）；`onconf sync` 补缺并删除声明里没有的键（`--no-clean` 则一个键都不删）。声明靠**扫描项目里的 `conf(...)` 调用**、解读参数得到 —— 单函数 API 正是这件事的前提。两条命令都支持 `--dry-run`（一个字节都不写）与 `--json`；扫不动的调用会让 `sync` 拒绝删除任何键。`onconf check` 一个字节都不写地对比**三样** —— 代码里扫到的声明、词表、值文件 —— 按 `missing` / `stale` / `default` / `doc` / `unfilled` / `undeclared` 六类报；`--verbose` 补上每一处落在哪个文件，`--strict` 把 warning 也算作失败。`onconf get` 打出 `key` / `value` / `path` / `doc`（有几个文件存着这个键就打几行），`onconf set` 改已有键的值（`--default` 改词表里的默认值），`onconf diff` 列出审计日志里记下的变更，`onconf format --indent N` 重排 JSON 值文件的缩进 | ✅ `build` / `sync` / `check` / `get` / `set` / `diff` / `format`；`add` / `log` 尚未实现 |

## 路线图 —— 当前不可用

不要把计划建在这些之上，它们**尚未实现**：

| 能力 | 里程碑 |
|---|---|
| WAL（预写日志）—— **判定不做**：声明可从代码重新推导，而运行期只补缺、不改既存值，没有需要重放的东西 | 不计划 |
| C 加速器（未来）—— 做成 **extra**，不另开包名：`pip install onconf[c]` | — |
| 把系统环境变量当作配置**来源**（`ONCONF_HOME` 只用来定位配置目录） | — |
| 按格式导出词表 | — |
| `.env` 的 `dict` / `list` 值 —— 由 `env_file_dict` / `env_file_list` 两个布尔开关开启（默认都关）；标量仍是字符串 | 2.2（计划） |
| 其余两条命令行 —— `add` / `log` | 2.1 |
| `read`（文件级原始读取）—— 后移：只有日志能按二进制落盘（`log_encode`）才需要它，否则没有原始字节要读回来 | — |
| 命令行按 `pyproject.toml` / `.gitignore` 收敛扫描范围（现在是固定跳过名单 + 整个项目） | — |

完整清单见[路线图](docs/roadmap/README.md) —— 它是**范围与版本的唯一事实源**（条目编号 +
决策状态 + 版本分配）；[1.0.x](docs/roadmap/1.0.x/roadmap.md) 是已发布那一版的冻结记录。设计文档在
[`docs/design/`](docs/design/index.md)：[`init_config.md`](docs/design/init_config.md)、
[`file_support.md`](docs/design/file_support.md)、[`concurrency.md`](docs/design/concurrency.md)、
[`log.md`](docs/design/log.md) 与 [`cli.md`](docs/design/cli.md)。

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

CI 跑 **ubuntu / windows / macos × Python 3.14**，并强制：`ruff check`、`codespell`、
第三方许可清单检查（`python scripts/gen_third_party_notices.py --check`）、`mypy --strict`、
带覆盖率下限的 `pytest`、`bandit`、`pip-audit`、`zizmor`、`actionlint`、`gitleaks`、
CodeQL、依赖审查与 OpenSSF Scorecard。

`ruff format --check` 目前是**非阻塞**的（CI 里 `continue-on-error`）：团队决定在库还在写的
阶段不去重排既有文件。

## 安全

漏洞请走私密渠道——见 [`SECURITY.md`](SECURITY.md)。不要开公开 issue。

本项目承诺的不变量（每一条都有回归测试，见
[`tests/test_security_invariants.py`](tests/test_security_invariants.py)）：

- 默认路径**不开任何网络端口**、**不 spawn 子进程**
- YAML 配置只经 `yaml.safe_load` / `yaml.safe_load_all` 解析，绝不用 `yaml.load`（JSON 走 `json.loads`，TOML 走 `tomllib.loads`，`.env` 是纯文本逐行扫描）
- **外部字符串（值文件的名字、多文件键内嵌的路径）只经一道包含性校验到达文件系统** ——
  纯文件名或相对路径、无分隔符、无 `..`、非绝对路径，且解析后仍在 `<home>` 之内（`src/onconf/_paths.py`）
- 命令行**从不执行项目代码**：它用 `ast` 解析 `*.py`、读 `conf(...)` 的实参 —— 不 import、不 eval
- 不对配置内容做 `eval` / `exec` / `pickle`
- 审计文件（文件出口）只追加（`O_APPEND`）且按 `0600` 创建，父目录不由它创建；控制台出口可以关，文件出口关不掉

### 已知限制

| 限制 | 后果 |
|---|---|
| **「一个目录一个写者」是部署责任** | 引擎不拿跨进程锁、不做协调。两个平级进程同时写会互相盖掉键 —— 起进程之前先用 `onconf sync` 把配置落好，运行期保持只读 |
| **符号链接会被替换** | 写入走 `os.replace`：符号链接本身被替换成普通文件，链接目标一个字节都不会被写（链接就此断开） |
| **`ONCONF_HOME` 与 `ONCONF_OWNER_PID` 是可信输入** | 前者决定配置目录，后者决定本进程能不能写；两者都不做包含性校验 |
| **日志行原样记值** | `data=` / `old=` / `new=` 里就是真实值，而文件出口是**恒写**的 —— `<home>/audit.log`（只追加、`0600`）因此总带着真实值，没有开关可退。脱敏与加密是**你自己给的钩子**（`log_scrub` / `log_encode`），不是引擎自带的功能（威胁模型 T12） |
| **审计文件可能被多个进程追加** | 每个进程记自己的操作，而 `txn` 是按进程编号的 —— 文件里可能出现两个同号的批次。每行都带 pid，读的人据此分辨 |
| **代码改不了已经存在的值** | 文件里的值与代码声明的不一致时，运行期尊重文件（记一条 `op=skip`）并返回文件里的值。要改是**人**的决定：`onconf sync` 同样不碰既存值（只补缺、只删未声明的键），`onconf build` 则按声明**完整重建**值文件（先备份，或用 `--path`） |
| **运行期不删键** | 值文件会积累不再声明的键；清理靠 `onconf sync` |

完整分析（逐条威胁 + 代码依据）：[`docs/security/threat-model.md`](docs/security/threat-model.md)。

## 命令行

九条计划命令里已实现两条（`build` / `sync`）。它们靠**扫描项目里的 `conf(...)` 调用**
找到声明 —— 单函数 API 正是这件事的前提 —— 而且**从不 import 你的代码**：

```console
onconf build                # 按声明完整重建 <home>/settings.json 与词表
onconf build --path ./out   # 整份重建写到别处；原目录一个字节不动
onconf sync                 # 补缺，然后删掉声明里没有的键
onconf sync --no-clean      # 只补缺，一个键都不删
```

`--home` / `--file-name` / `--file-type` / `--no-one-file` 与 `AutoConf` 的参数一一对应；
`--dry-run` 一个字节都不写；`--json` 输出同一份数据的机器可读形态。
实参不是字面量（变量、循环、表达式）的调用扫不动：会被逐条列出来，此时 `sync`
**拒绝删除任何键**。

## 仓库结构

```text
src/onconf/
  __init__.py        # 两个面：AutoConf + conf
  _engine.py         # 引擎装配、目录约定、落盘、属主闸门
  _paths.py          # 外部字符串 → 路径的唯一入口（包含性校验）
  _core.py           # 对账：补缺 / 补元数据，外加命令行专用的 undeclared
  _cli.py            # onconf 入口：build / sync（声明靠 AST 扫描）
  _vocab.py          # 词表 + JSON Schema
  _textscan.py       # 各后端共用的字节级扫描
  _log.py            # 日志：一份记录流、两个出口、三个口子
  _json_backend.py   # JSON 值后端
  _yaml_backend.py   # YAML 值后端
  _env_backend.py    # .env 值后端
  _toml_backend.py   # TOML 值后端
  errors.py          # 异常族
tests/               # 每个模块一个测试文件 + 安全不变量
docs/                # 文档站源码（中文）
  design/init_config.md   # 两个面、引导层与值层、三种模式
  design/file_support.md  # 值文件选定、返回类型、后端、词表
  design/concurrency.md   # 谁能写、读看到什么、引擎明确不做的事
  design/log.md           # 日志与审计
  design/cli.md           # 命令矩阵：九条命令的语义、退出码、写不写字节
```

模块会随后端增加而变多，以 `src/onconf/` 本身为准。

## 参与贡献

先读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。提交信息遵循
[约定式提交](https://www.conventionalcommits.org/)，**允许中文 subject**。
参与即表示你同意 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。

## 许可

[Apache-2.0](LICENSE) © 2026 HanYang06。第三方组件见
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
