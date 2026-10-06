# 快速开始

本页覆盖：环境要求、两种安装方式、最小可跑示例、配置目录约定，以及异常怎么区分。
语义与算法层面的内容不在这里，见[设计稿索引](design/index.md)。

## 环境要求

| 项 | 要求 | 依据 |
|---|---|---|
| Python | 3.14 或更高 | `pyproject.toml` 的 `requires-python = ">=3.14"` |
| 包管理与构建 | uv（构建后端是 `uv_build`） | `pyproject.toml` 的 `[build-system]` |

项目只用 uv 管理依赖与构建，没有 pip 工作流。

## 安装

两种方式都可用：第一种装 PyPI 上已发布的 `1.0.0`，第二种拿的是 `main` 的最新状态。

### 从 PyPI 安装

```bash
uv add onconf
```

### 从源码安装

```bash
git clone https://github.com/HanYang06/OnConf.git
cd onconf
uv sync --all-groups
uv run pytest
```

`uv sync` 默认只装 dev 依赖组；文档站所需的 docs 组要显式打开，
`--all-groups` 是「dev + docs 一起装」。跑完上面第四行应当全绿。

## 最小示例

```python
from onconf import AutoConf, conf

AutoConf(home="./conf")  # 可省略，走约定
conf("app.server.port", 8080)  # 声明 + 写，返回当前生效值
print(conf("app.server.port"))  # 读
```

三条语义值得单独记住：

1. `conf(key)` 是读。读不到会抛异常，不会静默返回 `None`。
2. `conf(key, value)` 是**声明 + 写**，返回**当前生效值**——文件里已有的值优先，不是你刚传的默认值。
3. 引擎对值是**透明的**：文件里写 `"8080"` 读回来就是字符串，要整数请自己
   `int(conf("app.server.port"))`。引擎不接受类型声明，也不推断、不转换。

## 声明要写字面量

带上 `value` 的调用就是**规格**，所以键、值、说明都写成字面量：

```python
conf("app.server.port", 8080, "服务端口")   # ✅
conf("slot.max.byte.b", 512, "格长档位之一")  # ✅
```

```python
APP_PORT = "app.server.port"
conf(APP_PORT, 8080)          # ❌ 合法，但声明处不是字面量
for key, value in TABLE:
    conf(key, value)          # ❌ 同一件事，多绕了一层
```

**读取不受限**：`conf("app.server.port")` 与 `conf(APP_PORT)` 都行，常量写错了会当场报错。

这是**约定而不是强制检查**（合法但不合理），代价自己衡量：这样写的声明，命令行的
`onconf build` / `onconf sync` 看不见（`sync` 会把那个键当成「代码没声明」，并因此拒绝
删除任何键），`grep` 与未来的 `check` 也看不见。完整口径见
[初始化配置](design/init_config.md) §8。

## 配置目录约定

配置目录 `<home>` 的确定顺序（实现见
[`src/onconf/_engine.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/_engine.py)）：

1. `AutoConf(home=...)` 的显式参数；
2. 环境变量 `ONCONF_HOME`；
3. `./conf`（缺省）。

目录布局：

```text
<home>/
  settings.json          # 值文件：名字由 file_name、后缀由 file_type 决定；用户手写
  app/conf/net.json      # 多文件模式（no_one_file=True）下 `<路径>:` 键的落点
  schema/
    settings.json        # 词表：库自己的资产，整篇重写（多文件下也只有这一份）
```

`schema/` 下那个文件是库自己的簿记，不是配置，不用手改。

文件名主干由 `file_name` 给（缺省 `settings`，纯文件名），后缀由 `file_type` 给（缺省
**字面** `"json"`）——目录里恰好有别的类型文件**不会**被选中。名字与（多文件模式的）键内嵌
路径都要过包含性校验：纯文件名 / 相对路径、无分隔符、无 `..`、非绝对、解析后仍在 `<home>` 内。
能吃下成员的后端会在值文件里写入一条 `$schema` 指针，指向词表（多文件按各自层级算相对路径）；
`.env` 与 `.toml` 放不下成员，所以不写指针。

`.env` 后端是**纯字符串**后端：值只能是字符串，非字符串会直接被拒绝（错误信息会指路 JSON / YAML
值文件）；读回来也一律是字符串，不做类型推断——要整数请自己写 `int(conf("PORT"))`。

!!! note "引擎起来之后不能改配置"

    v1 只支持在**第一次调用之前**设置 `home` / `file_name` / `file_type` / `no_one_file` /
    `log` / `audit` / `identity` / `flush_window`。
    引擎已经启动后再带上参数调用 `AutoConf(...)` 会抛 `ConfError`。

!!! note "谁能写"

    创建引擎实例的进程是**属主**，读写、生成词表；从它派生出来的进程（`fork`，或者继承了
    `ONCONF_OWNER_PID` 的 `spawn` / `subprocess`）**只读**，第一次想写就抛 `ConfError`。
    同一时刻只有一个写者是部署责任 —— 口径见[并发模型](design/concurrency.md)。

## 日志与审计去哪儿

日志是**强制**的：每一次读 / 写 / 登记都会留下一行，**只能改去向，不能关掉**（关掉它不是
「少看几行」，是缺失配置审计）。默认去 `stderr`：

```console
$ uv run python -c "from onconf import conf; conf('app.server.port', 8080)"
[Start]-[05:12:34.500]-[txn=0 pid=4821]   item=-  file=settings.json
[Link]-[05:12:34.501]-[txn=0 pid=4821]    item=-  file=settings.json  op=bind
[Write]-[05:12:34.502]-[txn=1 pid=4821]   item=app.server.port  file=settings.json  op=fill         data=8080  reason=事实里没有
[Change]-[05:12:34.502]-[txn=1 pid=4821]  item=app.server.port  file=settings.json  old=-           new=8080   at=<string>:1
[Write]-[05:12:34.502]-[txn=1 pid=4821]   item=app.server.port  file=settings.json  op=update_meta  data=8080  reason=登记元数据
```

（这是实测输出的形态，时间戳与 pid 因运行而异。第三、五行都有：`fill` 是值落进文件，
`update_meta` 是词表登记 —— 值与默认值一致时文件不动，但词表要补上「有这么一个键」。）

**五个级别**，名字就是它干的事：

| 级别 | 意思 | 出现时机 |
|---|---|---|
| `[Start]` | 引擎起来了 | 第一次真正用到这个引擎 |
| `[Read]` | 读到一个值 | 带 `origin=`（file 或 vocab）与 `n=<次数>` |
| `[Write]` | 一次对账动作 | `op=` 取 fill / register / update_meta / **skip**「想改没改」/ **noop**「本批声明已满足」 |
| `[Change]` | 值真的变了 | `old → new` |
| `[Error]` | 失败 | 带 `err=` 与原因 |

`[Start]` 是**生命周期**那一行，带 `txn=0`（不属于任何配置事务）。
同一事务里重复读同一个键会合并成一行 `n=<次数>`，所以循环里读一万次不会刷一万行。

去向与开关在**第一次调用之前**一次性配好（引擎是单例，起来之后不能再改）：

```python
AutoConf(log="./onconf.log")  # 改去文件（文件形态带完整日期、不截断）
AutoConf(log="stdout")  # 或者 stdout
AutoConf(audit=True)  # 再加一份 append-only 的 <home>/audit.log（0600、按大小轮转）
AutoConf(identity="order-svc@host-3")  # 每行多一个 id=，回答「哪个部署改的」
```

写记录里的 `at=` 是**调用点**（`app/config.py:12`），它回答的是「哪段代码改的」——
配置语境下这比 pid 有用得多。**谁发起谁记账**：审计文件由发起操作的那个进程写，
多个进程同时用同一个目录时各行都带自己的 pid，读的人据此分辨。

## 常见问题：几个异常怎么区分

异常族的共同基类是 `ConfError`，定义在
[`src/onconf/errors.py`](https://github.com/HanYang06/OnConf/blob/main/src/onconf/errors.py)。
**读期**还有三个后端错误是 `ValueError`
的子类，`except ConfError` 接不住它们，「分开处理」按下表区分：

| 异常 | 触发时机 | 含义 | 责任方 |
|---|---|---|---|
| `KeyNotRegisteredError` | 读 | 词表里没有登记，代码也从没声明过 | 调用方（键名写错） |
| `KeyHasNoValueError` | 读 | 词表里有登记，但值文件里没有值，也没有默认值 | 部署（漏配必填项） |
| `UnknownEngineParamError` | 调用 `AutoConf` / `conf` | 透传给引擎的参数名不存在 | 调用方 |
| `EnvSyntaxError` | 读 `.env` 值文件 | `.env` 里有既不是空行、注释，也不是 `KEY=VALUE` 的行 | 部署/使用者（`ValueError` 的子类，**不是** `ConfError`） |
| `YamlFlatRequiredError` | 读 YAML 值文件 | 文件用了 v1 不支持的构造（嵌套 / 块标量 / 跨行 / 多文档） | 部署/使用者（`ValueError` 的子类，**不是** `ConfError`） |
| `TomlFlatRequiredError` | 读 TOML 值文件 | 文件用了 v1 不支持的构造（表数组 `[[…]]` / 跨行值） | 部署/使用者（`ValueError` 的子类，**不是** `ConfError`） |
| `ConfError` | 任意 | `ConfError` 子类的共同基类；也用于「引擎已启动又改配置」、值文件名或键内嵌路径不合法、以及**派生进程试图写**这类情形 | —— |

「键名写错」与「部署漏配」被刻意分成两类，因为它们的**责任方不同**：
前者你改代码，后者你改配置。把两者混成一句「配置不存在」，会让线上排障多绕一圈。

!!! tip "读取期不做类型转换"

    引擎对值是透明的，类型对不对由你自己在取用处显式转换与校验。
    同一个键在不同后端可以读回不同类型（JSON 上是列表、`.env` 上是字符串），
    这条差异**不承诺可移植**，也不进词表。

## 命令行

九条计划命令里已实现两条。它们靠**扫描项目里的 `conf(...)` 调用**找到声明
（只做语法分析，**不 import 你的代码**）：

```console
onconf build                # 按声明完整重建值文件与词表（先备份，或用 --path）
onconf build --path ./out   # 整份重建写到别处；原目录一个字节不动
onconf sync                 # 补缺，然后删掉声明里没有的键
onconf sync --no-clean      # 只补缺，一个键都不删
```

`--home` / `--file-name` / `--file-type` / `--no-one-file` 与 `AutoConf` 的参数一一对应；
`--dry-run` 一个字节都不写；`--json` 输出同一份数据的机器可读形态。实参不是字面量的调用
扫不动，会被逐条列出来——此时 `sync` **拒绝删除任何键**。
