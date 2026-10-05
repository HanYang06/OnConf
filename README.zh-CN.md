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
> **定位句的两个半句现在都有机制支撑**：「不丢一个字节」由外科手术式回写保证；
> 「不丢一次更新」由**专职写者**保证 —— 谁先抢绑到配置目录的端点，谁就是唯一的读写者，
> 其余进程通过本地命名管道（Windows）/ Unix socket（POSIX）发请求；跨进程 **OS** 锁 +
> 锁内按需重读退居兜底。
> 写入现在也是原子的：同目录临时文件 → `fsync` → `os.replace`（POSIX 再加父目录 `fsync`），
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
- **一个扁平键空间，多个后端。** `app.server.port` 指向同一个逻辑键，
  无论它落在 JSON、YAML、TOML 还是 `.env` 里。
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
| `AutoConf(**engine)` | 配置**引擎自己**：`home`（配置目录，缺省 `./conf`）、`file_name`（值文件名主干，缺省 `settings`）、`file_type`（用哪个值文件，单值，缺省 `"json"`）、`no_one_file`（多文件：键的 `<路径>:` 前缀寻址 `<home>/<路径>.<ext>`）、`log`（强制日志的去向：`"stderr"` 默认 / `"stdout"` / 一个文件路径）、`audit`（再把每行追加进 `<home>/audit.log`）、`identity`（可选的 `服务@主机` 标记，写进每一行）、`flush_window`（攒批窗口，`0` = 当场落盘）、`lock_timeout`。可省略——不调用它也能按约定工作。 |
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
- `doc` 是第三个**位置**参数，也是唯一的登记元数据。判据里不再出现第二个参数，
  参数面自此**封闭**：以后新增参数不需要动判据。
- 使用口**不能配置引擎**：`conf(..., home=…)` 是 `TypeError`。

几条容易踩的语义：

- **类型声明已取消，引擎也从不转换值。** `.env` 给你的就是 `"8080"`；
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
  `log` / `audit` / `identity` / `flush_window` / `lock_timeout`）起来之后不能改
  ——改了等于改代码；**值层**随时可改，因为值每次都从文件重新读。
- 提交点**默认是立即的**（`atexit` 触发最后一次 `sync()`）。攒批窗口需显式开启（`flush_window`）；
  开启后落盘发生在四个提交点：窗口到期 / 一次读 / `sync()` / 进程退出。

## 当前已实现

| 能力 | 状态 |
|---|---|
| JSON 值后端 —— 外科手术式回写 | ✅ |
| YAML 值后端 —— 注释、锚点、键序逐字保留 | ✅ |
| `.env` 值后端 —— 纯字符串，不认行内注释，不做键名映射 | ✅ |
| TOML 值后端 —— 表头归一成点分键 | ✅ |
| 词表（键空间）—— 持久化 + JSON Schema 往返 + 哈希短路。每个键只记三样：键、说明、默认值 | ✅ |
| 值文件选定 —— `file_name`（缺省 `settings`）与 `file_type`（单值，缺省 `"json"`）决定 `<home>/<file_name>.<ext>`；「按存在性挑第一个」已退役 | ✅ |
| **多文件** —— `no_one_file=True` 后键的 `<路径>:` 前缀寻址 `<home>/<路径>.<ext>`（例：`conf("app/conf/net:net.id.post", 8080)` → `<home>/app/conf/net.json`）。没有前缀的键仍落在默认文件。词表一份、锁一把、每个 `(home, file_name)` 一个写者；每一段内嵌路径都过包含性校验 | ✅ |
| 引擎装配 —— `conf` / `AutoConf` 端到端 | ✅ |
| 跨进程排他锁 —— **操作系统**级锁（Windows `msvcrt.locking`、其它 `fcntl.flock`），进程崩溃也由 OS 释放；等 10 秒拿不到抛 `LockTimeoutError` | ✅ |
| 锁内按需重读 —— 指纹（`mtime` + 大小）同时看值文件与词表，别人刚登记的键不会被挤掉 | ✅ |
| **专职写者** —— 谁先绑上端点，谁就是唯一的读写者；其余进程通过 `multiprocessing.connection` 发请求。**抢绑本身就是选举**，所以不涉及锁文件（DESIGN §32） | ✅ |
| **原子写** —— 同目录临时文件 → `fsync` → `os.replace`，POSIX 再加父目录 `fsync`；行尾与权限位原样保留，新建文件是 `0600` | ✅ |
| 可选攒批窗口 —— `flush_window`（默认 `0`，当场落盘），窗口挂在**客户端**侧，所以每个引擎的窗口归自己 | ✅ |
| 用值当键（间接寻址）+ 每次落盘都保证 `$schema` 指针（仅 JSON / YAML —— `.env` 与 `.toml` 放不下成员，会直接跳过） | ✅ |
| 异常族 —— `ConfError` 作基类，含 `KeyNotRegisteredError`、`KeyHasNoValueError`、`UnknownEngineParamError` 与 `LockTimeoutError`（定义在 `_lock.py` 而非 `errors.py`；等 10 秒拿不到锁时抛）。`EnvSyntaxError`、`YamlFlatRequiredError`、`TomlFlatRequiredError` 是 `ValueError` 子类，**不会**被 `except ConfError` 捕获 | ✅ |
| **日志与审计** —— 强制 `[Read]` / `[Write]` / `[Change]` / `[Error]` 事件流，外加进程结构三行 `[Start]` / `[Link]` / `[Send]`：去向可改、**不可关闭**；写全量（含 `op=skip`「想改没改」与 `op=noop`「本批声明已满足」），读按事务去重（`n=1000`）；每条写记录带调用点（`at=app/config.py:12`）、pid 与可选 `identity=`；终端列宽是**显示宽度**的弹性制表位（中文不偏列），文件形态保持紧凑且永不截断；`audit=True` 追加写 `<home>/audit.log`（`0600`、只追加、按大小轮转）。见 DESIGN §20 / §21 | ✅ |
| 测试 —— 每个模块一个测试文件，外加安全不变量 | ✅ 本地全绿；CI 在 ubuntu / windows / macos 上跑 |
| **命令行（头两条命令）** —— `onconf build` 按声明完整重建值文件与词表（`--path` 把整份重建写到新目录，原目录不动）；`onconf sync` 补缺并删除声明里没有的键（`--no-clean` 则一个键都不删）。声明靠**扫描项目里的 `conf(...)` 调用**、解读参数得到 —— 单函数 API 正是这件事的前提。两条命令都支持 `--dry-run`（一个字节都不写）与 `--json`；扫不动的调用会让 `sync` 拒绝删除任何键 | ✅ `build` / `sync`；其余七条命令尚未实现 |

## 路线图 —— 当前不可用

不要把计划建在这些之上，它们**尚未实现**：

| 能力 | 里程碑 |
|---|---|
| WAL（预写日志）—— **判定不做**：攒批窗口负责合并突发写、声明可从代码重新推导、专职写者负责串行、读改写 + 原子替换负责顺序（DESIGN §32.7） | 不计划 |
| C 加速器（未来）—— 做成 **extra**，不另开包名：`pip install onconf[c]` | — |
| 运行期的规则 1（清理未知键）—— 移出运行期、交给 `onconf sync` 已经定了（ISSUE-035），但尚未实现；写者的声明集不是持久状态，写者一换人基准就重置（DESIGN §32.4） | 随命令行 |
| 前缀分片锁 —— 当前是每个配置目录一把锁 | — |
| 把系统环境变量当作配置**来源**（`ONCONF_HOME` 只用来定位配置目录） | — |
| 按格式导出词表 | — |
| `.env` 的 `dict` / `list` 值 —— 由 `env_file_dict` / `env_file_list` 两个布尔开关开启（默认都关）；标量仍是字符串 | 2.2（计划） |
| 其余七条命令行 —— `check` / `format` / `diff` / `read` / `get` / `set` / `add` | M5 |
| 命令行按 `pyproject.toml` / `.gitignore` 收敛扫描范围（现在是固定跳过名单 + 整个项目） | — |

完整清单见 [`docs/roadmap.md`](docs/roadmap.md)。设计文档在 [`docs/design/`](docs/design/index.md)：
[`init_config.md`](docs/design/init_config.md) 与 [`file_support.md`](docs/design/file_support.md)
正在逐步替换 [`DESIGN.md`](docs/design/DESIGN.md)，旧稿随之一节一节退役。

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

- 默认路径**不开任何网络端口**、**不 spawn 子进程**（写者的端点只是 OS 命名空间里的一个
  同用户本地管道，而写者是个**线程**，不是子进程）
- YAML 配置只经 `yaml.safe_load` / `yaml.safe_load_all` 解析，绝不用 `yaml.load`（JSON 走 `json.loads`，TOML 走 `tomllib.loads`，`.env` 是纯文本逐行扫描）
- **外部字符串（值文件的名字、多文件键内嵌的路径）只经一道包含性校验到达文件系统** ——
  纯文件名或相对路径、无分隔符、无 `..`、非绝对路径，且解析后仍在 `<home>` 之内（`src/onconf/_paths.py`）
- 命令行**从不执行项目代码**：它用 `ast` 解析 `*.py`、读 `conf(...)` 的实参 —— 不 import、不 eval
- 不对配置内容做 `eval` / `exec` / `pickle`
- 审计文件只追加（`O_APPEND`）且按 `0600` 创建；日志可以改去向，但关不掉

### 已知限制

| 限制 | 后果 |
|---|---|
| **规则 1 需要写者长命** | 写者的声明集不是持久状态：写者进程起一个退一个时，`sync()` 只能拿**自己这一个进程**的声明去清理（DESIGN §32.4） |
| **写者是同伴，不是服务** | 它住在最先抢到该目录的那个进程里，请求在一把锁后面串行 —— 客户端要等自己的请求，还要等前面那个跑完。没有队列，也没有后台重试 |
| **兜底路径是进程内的** | 端点完全建不出来时，引擎退回「直接写 + OS 锁」：正确性在，但规则 1 的基准变成每进程各自一份 |
| **符号链接会被替换** | 写入走 `os.replace`：符号链接本身被替换成普通文件，链接目标一个字节都不会被写（链接就此断开） |
| **`ONCONF_HOME` 是可信输入** | 它决定配置目录，库不做目录包含性校验 |
| **审计行原样记值** | `data=` / `old=` / `new=` 里就是真实值。`audit=True` 会把它写进 `<home>/audit.log`（只追加、`0600`）—— 配置里全是密钥时打开它就是主动暴露（威胁模型 T12） |
| **审计跟着执行点走** | 客户端把请求交给专职写者，写者写审计文件、并往**它自己**的日志去向输出；客户端只补执行点**这一次真正输出出去的**记录。远端失败时发起方自己也会记一条 `[Error]`，但远端的**读**要等写者的下一个提交点 —— 所以它不一定出现在客户端自己的日志里，权威流是审计文件 |
| **审计文件假定「一个写者」** | 同一配置目录上第二个引擎也开 `audit=True` 时，它会把**自己本地的**记录追加进同一个 `<home>/audit.log`，而 `txn` 是按进程编号的 —— 文件里可能出现两个同号的批次，轮转也不再是单写者。客户端进程请别开 `audit`（默认就是关的） |
| **代码改不了已经存在的值** | 文件里的值与代码声明的不一致时，运行期尊重文件（记一条 `op=skip`）并返回文件里的值。要改是**人**的决定：`onconf sync` 同样不碰既存值（只补缺、只删未声明的键），`onconf build` 则按声明**完整重建**值文件（先备份，或用 `--path`） |
| **写者进程内自己的调用没和应答线程共用一把锁** | 写者自己线程上的 `conf()` 会和客户端请求并行：文件一致性由 OS 锁兜着（其中一边可能等满 `lock_timeout`），但引擎内存态在那个窗口里是可竞争的。这条没有回归测试守护（威胁模型 T4） |
| **写者按 `(home, file_name)` 选举，不按引擎配置** | 同一目录、同一文件名上的两个引擎共用一个写者 —— 即使它们的 `file_type` 或 `no_one_file` 不同。请求由**写者自己的**引擎执行，所以客户端的值会按写者的布局落盘。请让每个 `(home, file_name)` 只有一种值文件配置 |

完整分析（逐条威胁 + 代码依据）：[`docs/security/threat-model.md`](docs/security/threat-model.md)。

## 命令行

九条计划命令里已实现两条（`build` / `sync`）。它们靠**扫描项目里的 `conf(...)` 调用**
找到声明 —— 单函数 API 正是这件事的前提 —— 而且**从不 import 你的代码**：

```console
$ onconf build                # 按声明完整重建 <home>/settings.json 与词表
$ onconf build --path ./out   # 整份重建写到别处；原目录一个字节不动
$ onconf sync                 # 补缺，然后删掉声明里没有的键
$ onconf sync --no-clean      # 只补缺，一个键都不删
```

`--home` / `--file-name` / `--file-type` / `--no-one-file` 与 `AutoConf` 的参数一一对应；
`--dry-run` 一个字节都不写；`--json` 输出同一份数据的机器可读形态。
实参不是字面量（变量、循环、表达式）的调用扫不动：会被逐条列出来，此时 `sync`
**拒绝删除任何键**。

## 仓库结构

```text
src/onconf/
  __init__.py        # 两个面：AutoConf + conf
  _engine.py         # 引擎装配、目录约定、落盘
  _paths.py          # 外部字符串 → 路径的唯一入口（包含性校验）
  _core.py           # 对账：三集合算法
  _cli.py            # onconf 入口：build / sync（声明靠 AST 扫描）
  _vocab.py          # 词表 + JSON Schema
  _textscan.py       # 各后端共用的字节级扫描
  _lock.py           # 跨进程排他锁（OS 锁，兜底路径）
  _owner.py          # 专职写者：端点选举、IPC、写者循环
  _audit.py          # 强制日志 + append-only 审计（DESIGN §20 / §21）
  _json_backend.py   # JSON 值后端
  _yaml_backend.py   # YAML 值后端
  _env_backend.py    # .env 值后端
  _toml_backend.py   # TOML 值后端
  errors.py          # 异常族
tests/               # 每个模块一个测试文件 + 安全不变量
docs/                # 文档站源码（中文）
  design/init_config.md   # 两个面、引导层与值层、三种模式
  design/file_support.md  # 值文件选定、返回类型、后端、词表
  design/DESIGN.md        # 旧设计稿 —— 正在被逐节替换
```

模块会随后端增加而变多，以 `src/onconf/` 本身为准。

## 参与贡献

先读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。提交信息遵循
[约定式提交](https://www.conventionalcommits.org/)，**允许中文 subject**。
参与即表示你同意 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。

## 许可

[Apache-2.0](LICENSE) © 2026 HanYang06。第三方组件见
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
