# 1.0.x —— v1.0.0 交付了什么

> 本页是 **v1.0.0**（2026-10-04 发布到 PyPI，tag `v1.0.0`）的能力状态记录：只写
> 「1.0.0 发出去的是什么样」，不写计划，也不写后来在主线上升级成了什么。
> 下一版收什么见 [2.0.x](../2.x.md)，某一版具体改了什么见
> [变更日志](../../CHANGELOG/index.md)。
>
> 每条四段：**标题 / 正文 / 状态 / 引用设计文稿**。1.0.x 里的状态只有 `已实现`。
> 引用给的是「这套机制记在哪」；`docs/design/` 下的稿子只引机制没变的部分。
>
> **注意**：本页只描述 **v1.0.0** 的形态，不是当前用法 ——
> 当前用法看 [`init_config.md`](../../design/init_config.md)。

## 0. 它是什么

### 0.1 定位句

> **配置不再有动词：同一个名字读它、写它，两个方向都不丢——不丢一个字节，也不丢一次更新。**
>
> Configuration has no verbs: one name reads and writes it, in both directions, without
> losing a byte or an update.

中英同源，改一句必须同一次改完五处：`README.md`、`README.zh-CN.md`、`pyproject.toml` 的
`description`、`mkdocs.yml` 的 `site_description`、`docs/index.md`。

**状态**：`已实现` ｜ **引用设计文稿**：（定位句见仓库根 `README.md` 顶部）

### 0.2 四条铁律

1. **文件绝对优先** —— 代码不权威，代码只发出写请求；运行期对已存在的值一律只读。
2. **未触及的字节逐字不动** —— 回写是外科手术式的：注释、缩进、键序、空行、行尾都保留。
   词表是例外（它是库自己的资产，整篇重写合法）。
3. **不丢一次更新** —— 一个配置目录上只有一个执行点；锁内按需重读；落盘原子。
4. **不是服务、不走网络** —— 库跑在调用方进程里；默认路径不开端口、不 spawn 子进程
   （1.0 的写者是**线程**，不是子进程）。

**状态**：`已实现` ｜ **引用设计文稿**：[`init_config.md` §5](../../design/init_config.md)

### 0.3 两个面（公开 API 只有这两个）

```python
AutoConf(**engine)   # 配置引擎自己 —— 1.0 的引擎参数：home / audit / log / identity / flush_window
conf(...)            # 读 / 写 / 登记
```

`__all__` 共 9 个符号：`AutoConf`、`conf`、`Engine`、`EngineParams` 与五个异常
（`ConfError` / `KeyNotRegisteredError` / `KeyHasNoValueError` / `TypeConflictError` /
`UnknownEngineParamError`）。`LockTimeoutError` 定义在 `_lock.py`，不在 `__all__` 里；
各后端的语法错误是 `ValueError` 子类，**接不住 `except ConfError`**。

**状态**：`已实现` ｜ **引用设计文稿**：[`init_config.md` §1](../../design/init_config.md)

## 1. 使用口与配置口

### 1.1 `conf` 的签名与判据

`conf(key, value=MISSING, *, doc=None, type=None, force=False, **engine)`。
判据不是「`value` 位空没空」，而是**这一行在不在声明** —— 任何 `doc=` / `type=` 的出现
都让这一行变成声明。`conf(key)` 读；`conf(key, value)` 声明 + 写；
`conf(key, doc="…")` 只登记不给值（必填键），随即按读规则取值。

**状态**：`已实现` ｜ **引用设计文稿**：[`init_config.md` §4](../../design/init_config.md)

### 1.2 `type=` 只做声明期一致性校验

显式声明这一项的 Python 类型；默认值与声明不符时抛 `TypeConflictError`
（`bool` 是 `int` 的子类，单独挡掉）。它**不参与读取期转换** —— 引擎对值是透明的。

**状态**：`已实现` ｜ **引用设计文稿**：（v1.0.0 无对应设计文稿）

### 1.3 `force=` 逐项覆盖

`force=True` 时覆盖值文件里已有的值；没有全局开关，逐调用点决定。

**状态**：`已实现` ｜ **引用设计文稿**：[`init_config.md` §4](../../design/init_config.md)

### 1.4 使用口可以顺手配置引擎

`conf(..., home="…")` 这类 `**engine` 透传：引擎还没起来时顺手把它配置起来，
已经起来时再带参调用抛 `ConfError`。

**状态**：`已实现` ｜ **引用设计文稿**：[`init_config.md` §2](../../design/init_config.md)

### 1.5 报错与返回值口径

读未登记 ⇒ `KeyNotRegisteredError`；已登记但事实里没有值 ⇒ `KeyHasNoValueError`；
声明 + 写返回**当前生效值**（值文件优先，不是传入的默认值）；`key` 不是字符串 ⇒ `TypeError`。
两类读取错误的责任方不同：键名写错 vs 部署漏配。

**状态**：`已实现` ｜ **引用设计文稿**：[`init_config.md` §4](../../design/init_config.md)

### 1.6 `AutoConf` 无参调用取回单例

`AutoConf()` 把已经起来的引擎取回来；`AutoConf(**engine)` 只在第一次调用前合法。

**状态**：`已实现` ｜ **引用设计文稿**：[`init_config.md` §2](../../design/init_config.md)

## 2. 值文件与后端

### 2.1 四个值后端

JSON（外科手术式回写）、YAML（注释、锚点、键序逐字保留）、`.env`（纯字符串后端，
不认行内注释，不做键名映射）、TOML（表头归一成点分键）。每个后端一个模块，共用一套
字节级扫描。

**状态**：`已实现` ｜ **引用设计文稿**：[`file_support.md` §7 外科手术式回写](../../design/file_support.md)、
[§9 `.env` 是字符串后端](../../design/file_support.md)

### 2.2 值文件选定：按存在性挑第一个

`home` 缺省是**当前目录**。值文件从候选名单 `settings.yaml` → `settings.yml` →
`settings.json` → `settings.toml` → `settings.env` 里挑**第一个存在的**；一个都没有就
创建 `settings.json`。1.0 **没有** `file_name` / `file_type` 参数，后缀决定用哪个后端。

**状态**：`已实现` ｜ **引用设计文稿**：（v1.0.0 无对应设计文稿）

### 2.3 外科手术式回写

未被触及的字节逐字不动：注释、缩进、键序、空行、行尾都保留。实现上是字节级扫描后的
片段替换，不是「解析 → 序列化整篇」。

**状态**：`已实现` ｜ **引用设计文稿**：[`file_support.md` §7](../../design/file_support.md)

### 2.4 读回来的是载体原生类型

JSON / YAML 返回对应的 Python 类型（`dict` / `list` 正常返回），TOML 同（`None` 表达不了），
`.env` 一律 `str`。载体的显式类型标签被尊重（YAML 的 `!!str "8080"` 读回字符串）。
跨后端类型差异**不承诺可移植**。

**状态**：`已实现` ｜ **引用设计文稿**：[`file_support.md` §2–§4](../../design/file_support.md)

### 2.5 `$schema` 指针

每次落盘都保证值文件里有指向词表的 `$schema` 指针，按载体能力来 —— 只有能吃下成员的
后端才写（JSON / YAML）；`.env` 与 `.toml` 上没有落脚点，直接跳过。

**状态**：`已实现` ｜ **引用设计文稿**：[`file_support.md` §8](../../design/file_support.md)

### 2.6 用值当键（间接寻址）

`conf(conf("app.key_name"))`：先读出一个值，再拿它当键名读第二个。键永远扁平，值随便嵌套。

**状态**：`已实现` ｜ **引用设计文稿**：[`file_support.md` §1.1](../../design/file_support.md)

## 3. 词表

### 3.1 形态：键 + 类型 + 说明 + 默认值

词表是锁死的核心结构，**永远产出**，写入是提交点的一部分；落点 `<home>/schema/settings.json`。
三态不许塌陷：未登记 / 已登记无值（`default` 键缺失 ⇒ `KeyHasNoValueError`）/
值就是 `None`（`"default": null`）。产物是 JSON Schema 往返，逐键写 `type` 与 `x-onconf-py`。

**状态**：`已实现` ｜ **引用设计文稿**：[`file_support.md` §6](../../design/file_support.md)

### 3.2 声明集哈希：已算、已落盘、无消费者

词表里有 `x-onconf-hash`（声明集指纹），`Vocabulary.matches()` 也写了「指纹对得上就整体跳过」
的语义，但引擎里**没有调用点** —— 实际效果由词表逐项 diff 达到。

**状态**：`已实现`（作为现状描述成立）｜ **引用设计文稿**：[`file_support.md` §6](../../design/file_support.md)

## 4. 多进程

### 4.1 专职写者

谁先绑上配置目录的端点，谁就是唯一的读写者；其余进程经 `multiprocessing.connection`
（Windows 命名管道 / POSIX `AF_UNIX`）发请求。**抢绑本身就是选举**，不涉及锁文件；
认证在应用层。写者住在最先抢到该目录的那个**进程里**（是个线程，不是子进程），
客户端要等自己的请求，还要等前面那个跑完 —— 没有队列，也没有后台重试。

**状态**：`已实现` ｜ **引用设计文稿**：（v1.0.0 无对应设计文稿；2.0 的进程结构见[路线图 §2](../2.x.md)）

### 4.2 OS 锁兜底 + 锁内按需重读

跨进程排他锁是**操作系统级**的（Windows `msvcrt.locking`、其它 `fcntl.flock`），
进程崩溃也由 OS 释放；等 10 秒拿不到抛 `LockTimeoutError`（`lock_timeout` 在 1.0
还没有作为参数暴露）。锁内按需重读用指纹（`mtime` + 大小）**同时**看值文件与词表，
别人刚登记的键不会被挤掉。

**状态**：`已实现` ｜ **引用设计文稿**：（v1.0.0 无对应设计文稿）

### 4.3 原子写

同目录临时文件 → `fsync` → `os.replace`，POSIX 再加父目录 `fsync`；沿用文件原本的行尾与
权限位，新建文件是 `0600`。

**状态**：`已实现` ｜ **引用设计文稿**：（v1.0.0 无对应设计文稿）

### 4.4 可选攒批窗口

`flush_window`（缺省 `0`，当场落盘）。窗口挂在**客户端**侧，所以每个引擎的窗口归自己。

**状态**：`已实现` ｜ **引用设计文稿**：（v1.0.0 无对应设计文稿）

### 4.5 进程退出是一个提交点

`atexit` 里 `sync()` + `close()`：进程退出时期望集完整，规则 1（清理未声明的键）才允许执行；
顺手还回写者身份，端点早一点释放。

**状态**：`已实现` ｜ **引用设计文稿**：（v1.0.0 无对应设计文稿）

## 5. 日志与审计

### 5.1 强制事件流

四个级别 `[Read]` / `[Write]` / `[Change]` / `[Error]`，外加进程结构三行 `[Start]` /
`[Link]` / `[Send]`。去向可改（`log="stderr"` 默认 / `"stdout"` / 文件路径），
**不可关闭**。写全量（含 `op=skip`「想改没改」与 `op=noop`「本批声明已满足」），
读按事务去重（`n=`）。每条写记录带调用点（`at=app/config.py:12`）、pid 与可选 `identity=`。
终端列宽是**显示宽度**的弹性制表位（中文不偏列），文件形态紧凑且永不截断。

**状态**：`已实现` ｜ **引用设计文稿**：[`log.md`](../../design/log.md)

### 5.2 审计文件是开关控制的

`audit=True` 时才追加写 `<home>/audit.log`（`0600`、`O_APPEND`、按大小轮转）；
默认**不开**。

**状态**：`已实现` ｜ **引用设计文稿**：[`log.md`](../../design/log.md)

## 6. 安全

### 6.1 不变量

- 默认路径**不开任何网络端口**、**不 spawn 子进程**（写者的端点只是 OS 命名空间里的一个
  同用户本地管道，而写者是个线程）；
- YAML 只经 `yaml.safe_load` / `yaml.safe_load_all`，绝不用 `yaml.load`；
  JSON 走 `json.loads`，TOML 走 `tomllib.loads`，`.env` 是纯文本逐行扫描；
- 键名永不变成文件系统路径（1.0 的手段是**固定白名单**）；
- 不对配置内容做 `eval` / `exec` / `pickle`；
- 审计文件只追加（`O_APPEND`）且按 `0600` 创建；日志可以改去向，但关不掉。

以上每一条都有回归测试，见 `tests/test_security_invariants.py`。

**状态**：`已实现` ｜ **引用设计文稿**：[威胁模型](../../security/threat-model.md)

### 6.2 已知限制

- **规则 1 需要写者长命** —— 写者的声明集不是持久状态，写者一换人基准就重置：
  `sync()` 只能拿**自己这一个进程**的声明去清理。
- **写者是同伴，不是服务** —— 它住在最先抢到该目录的那个进程里，请求在一把锁后面串行。
- **兜底路径是进程内的** —— 端点完全建不出来时退回「直接写 + OS 锁」：正确性在，
  但规则 1 的基准变成每进程各自一份。
- **符号链接会被替换** —— 写入走 `os.replace`：链接本身被替换成普通文件，
  链接目标一个字节都不会被写（链接就此断开）。
- **`ONCONF_HOME` 是可信输入** —— 它决定配置目录，库不做目录包含性校验。
- **审计行原样记值** —— `data=` / `old=` / `new=` 里就是真实值；`audit=True` 会把它写进
  `<home>/audit.log`，配置里全是密钥时打开它就是主动暴露（威胁模型 T12）。
- **审计跟着执行点走** —— 客户端把请求交给写者，写者写审计、并往它**自己**的日志去向输出。
- **审计文件假定「一个写者」** —— 同一目录上第二个引擎也开 `audit=True` 时，
  `txn` 按进程编号，文件里可能出现两个同号的批次，轮转也不再是单写者。
- **写者自己线程上的 `conf()` 没和应答线程共用一把锁** —— 文件一致性由 OS 锁兜着，
  但引擎内存态在那个窗口里是可竞争的（威胁模型 T4），没有回归测试守护。

**状态**：`已实现`（作为现状描述成立）｜ **引用设计文稿**：[威胁模型](../../security/threat-model.md)

## 7. 异常族

`ConfError` 作基类，含 `KeyNotRegisteredError`、`KeyHasNoValueError`、`TypeConflictError`、
`UnknownEngineParamError`；`LockTimeoutError` 定义在 `_lock.py`。另有三个**读期**的
`ValueError` 子类 —— `EnvSyntaxError` / `YamlFlatRequiredError` / `TomlFlatRequiredError`
（定义在各后端）—— 它们**不是** `ConfError` 子类，接不住 `except ConfError`。

**状态**：`已实现` ｜ **引用设计文稿**：[`init_config.md` §4](../../design/init_config.md)

## 8. 工程质量

`pytest` 每个模块一个测试文件 + 安全不变量；`ruff check`、`mypy --strict`、
覆盖率门槛 90% 由 CI 强制；CI 在 ubuntu / windows / macos 三平台跑。

**状态**：`已实现` ｜ **引用设计文稿**：[`CONTRIBUTING.md`](https://github.com/HanYang06/OnConf/blob/main/CONTRIBUTING.md)

## 9. 1.0.0 没有的

真正的命令行（`onconf` 只打印配置目录就退出）；`file_name` / `file_type` 参数；
多文件寻址；日志两通道；独立 Alpha 进程；`.env` 的 `dict` / `list` 值；
前缀分片锁；把系统环境变量当作配置**来源**；WAL（已判定不做）。
逐条归属与状态见 [2.0.x](../2.x.md)。
