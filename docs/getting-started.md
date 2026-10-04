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

!!! warning "尚未发布到 PyPI"

    0.1.0 还没有发布到 PyPI，所以下面第一种方式**当前会失败**。
    它写在这里，是为了发布之后可以直接照抄。现在请用第二种。

### 从 PyPI 安装（发布后可用）

```bash
uv add onconf
```

### 从源码安装（当前唯一可用的方式）

```bash
git clone https://github.com/HanYang06/onconf.git
cd onconf
uv sync --all-groups
uv run pytest
```

`uv sync` 默认只装 dev 依赖组；文档站所需的 docs 组要显式打开，
`--all-groups` 是「dev + docs 一起装」。跑完上面第四行应当全绿。

## 最小示例

```python
from onconf import AutoConf, conf

AutoConf(home="./conf")      # 可省略，走约定
conf("app.server.port", 8080)  # 声明 + 写，返回当前生效值
print(conf("app.server.port")) # 读
```

三条语义值得单独记住：

1. `conf(key)` 是读。读不到会抛异常，不会静默返回 `None`。
2. `conf(key, value)` 是**声明 + 写**，返回**当前生效值**——文件里已有的值优先，不是你刚传的默认值。
3. `type=` **只做声明期一致性校验**，不参与读取期转换：引擎对值是透明的，文件里写 `"8080"`
   读回来就是字符串，要整数请自己 `int(conf("app.server.port"))`。

## 配置目录约定

配置目录 `<home>` 的确定顺序（实现见
[`src/onconf/_engine.py`](https://github.com/HanYang06/onconf/blob/main/src/onconf/_engine.py)）：

1. `AutoConf(home=...)` 的显式参数；
2. 环境变量 `ONCONF_HOME`；
3. 当前工作目录。

目录布局：

```text
<home>/
  settings.json          # 值文件：用户手写，库只做外科手术式回写
  schema/
    settings.json        # 词表：库自己的资产，整篇重写
    settings.lock        # 跨进程锁的握手点（空文件）
    settings.key         # 专职写者的认证码（0600）
    settings.sock        # 专职写者的端点（仅 POSIX）
```

`schema/` 下另外三个文件是库自己的簿记，不是配置，不用手改。

值文件名按 `settings.yaml` → `settings.yml` → `settings.json` → `settings.toml` → `settings.env` 的顺序探测
（取第一个已存在的），都不存在时默认用 `settings.json`。能吃下成员的后端会在值文件里写入一条
`$schema` 指针，指向 `schema/settings.json`，供编辑器读取补全；`.env` 与 `.toml` 放不下成员，所以不写指针。

`.env` 后端是**纯字符串**后端：值只能是字符串，非字符串会直接被拒绝（错误信息会指路 JSON / YAML
值文件）；读回来也一律是字符串，不做类型推断——要整数请自己写 `int(conf("PORT"))`。

!!! note "引擎起来之后不能改配置"

    v1 只支持在**第一次调用之前**设置 `home` / `log` / `audit` / `identity` / `flush_window`。
    引擎已经启动后再带上参数调用 `AutoConf(...)` 会抛 `ConfError`。命名空间与「零全局状态」的
    取舍见 `docs/design/DESIGN.md` §26。

## 日志与审计去哪儿

日志是**强制**的：每一次读 / 写 / 登记都会留下一行，**只能改去向，不能关掉**（关掉它不是
「少看几行」，是缺失配置审计）。默认去 `stderr`：

```console
$ uv run python -c "from onconf import conf; conf('app.server.port', 8080)"
[W]-[05:12:34.568]-[txn=1 pid=4821]  item=app.server.port  file=settings.json  op=fill         data=8080  reason=事实里没有
[C]-[05:12:34.568]-[txn=1 pid=4821]  item=app.server.port  file=settings.json  old=-           new=8080   at=<string>:1
[W]-[05:12:34.568]-[txn=1 pid=4821]  item=app.server.port  file=settings.json  op=update_meta  data=8080  reason=登记元数据
```

（这是实测输出的形态，时间戳与 pid 因运行而异。第三行是词表登记：值与默认值一致时，
文件不动，但词表要补上「有这么一个键」。）

四个级别：`[R]` 读 / `[W]` 一次对账动作（`op=` 是 fill、overwrite、clean、register、
update_meta、**skip**「想改没改」或 **noop**「本批声明已满足」）/ `[C]` 值真的变了
（`old → new`）/ `[E]` 失败。同一事务里重复读同一个键会合并成一行 `n=<次数>`，
所以循环里读一万次不会刷一万行。

去向与开关在**第一次调用之前**一次性配好（引擎是单例，起来之后不能再改）：

```python
AutoConf(log="./onconf.log")            # 改去文件（文件形态带完整日期、不截断）
AutoConf(log="stdout")                  # 或者 stdout
AutoConf(audit=True)                    # 再加一份 append-only 的 <home>/audit.log（0600、按大小轮转）
AutoConf(identity="order-svc@host-3")   # 每行多一个 id=，回答「哪个部署改的」
```

写记录里的 `at=` 是**调用点**（`app/config.py:12`），它回答的是「哪段代码改的」——
配置语境下这比 pid 有用得多。审计文件**只由执行点写**（有专职写者时就是写者），
所以多进程下它不会交错。

## 常见问题：几个异常怎么区分

异常族的共同基类是 `ConfError`，定义在
[`src/onconf/errors.py`](https://github.com/HanYang06/onconf/blob/main/src/onconf/errors.py)；
`LockTimeoutError` 在 `_lock.py`，也是它的子类。但**读期**还有三个后端错误是 `ValueError`
的子类，`except ConfError` 接不住它们，「分开处理」按下表区分：

| 异常 | 触发时机 | 含义 | 责任方 |
|---|---|---|---|
| `KeyNotRegisteredError` | 读 | 词表里没有登记，代码也从没声明过 | 调用方（键名写错） |
| `KeyHasNoValueError` | 读 | 词表里有登记，但值文件里没有值，也没有默认值 | 部署（漏配必填项） |
| `TypeConflictError` | 声明 | 默认值与 `type=` 声明的类型不一致 | 调用方 |
| `UnknownEngineParamError` | 调用 `AutoConf` / `conf` | 透传给引擎的参数名不存在 | 调用方 |
| `LockTimeoutError` | 任意落盘 | 超时内没拿到跨进程锁（另一个进程正卡在写盘上） | 部署（进程长期持锁） |
| `EnvSyntaxError` | 读 `.env` 值文件 | `.env` 里有既不是空行、注释，也不是 `KEY=value` 的行 | 部署/使用者（`ValueError` 的子类，**不是** `ConfError`） |
| `YamlFlatRequiredError` | 读 YAML 值文件 | 文件用了 v1 不支持的构造（嵌套 / 块标量 / 跨行 / 多文档） | 部署/使用者（`ValueError` 的子类，**不是** `ConfError`） |
| `TomlFlatRequiredError` | 读 TOML 值文件 | 文件用了 v1 不支持的构造（表数组 `[[…]]` / 跨行值） | 部署/使用者（`ValueError` 的子类，**不是** `ConfError`） |
| `ConfError` | 任意 | `ConfError` 子类的共同基类（也用于「引擎已启动又改配置」这类情形） | —— |

「键名写错」与「部署漏配」被刻意分成两类，因为它们的**责任方不同**：
前者你改代码，后者你改配置。把两者混成一句「配置不存在」，会让线上排障多绕一圈。

!!! tip "读取期不做类型转换"

    `type=` 不参与读取，所以读到的类型不对**不会**抛 `TypeConflictError`。
    类型对不对由你自己在取用处显式转换与校验——这是引擎「对值透明」的直接后果。
