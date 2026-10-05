# D07 数据交付边界：sink、密钥与取数

| 项 | 值 |
|---|---|
| 类型 | 设计变更（breaking） |
| 优先级 | P1 |
| 状态 | 部分已定（取最不确定成员） |
| 成员状态 | 已定稿，待实现 1 / 部分已定 2 —— 未定稿：ISSUE-041（部分已定）、ISSUE-044（部分已定） |
| 前置 | D06 |
| 联动 | D10 |
| 覆盖原编号 | ISSUE-043、ISSUE-041、ISSUE-044 |
| 影响面 | 新增落盘 sink 层、`src/onconf/__init__.py`、`src/onconf/_audit.py`、`tests/test_audit.py`、`tests/test_security_invariants.py`、`README.md`、`README.zh-CN.md`、`src/onconf/errors.py`、`src/onconf/_engine.py`、`tests/` |
| 标签 | `area:audit`、`area:security`、`breaking`、`area:audit`、`area:security`、`area:audit` |

## 0. 本决策的整体口径

库「只产出数据、不发送、不回调」这条边界的三面。

- sink 的形态是参数而不是回调，用途限定为「选模式」与「填密钥」（原 ISSUE-043）；
- 加密密钥由调用方提供，缺失且必需时在写出任何记录之前抛专用异常；库不生成、不推导、不保管、不评价强度（原 ISSUE-041）；
- 调用方要自行发送时怎么拿到数据，三条候选未定（原 ISSUE-044）；
- 三者共同受一条硬约束：引擎参数必须可序列化 —— 执行点可能不是发起方进程，回调与文件句柄过不去 IPC。

### 0.1 成员索引

| 原编号 | 本文件 | 一句话 |
|---|---|---|
| ISSUE-043 | §1 | sink 只接受参数，不接受函数；库不发起任何网络请求 |
| ISSUE-041 | §2 | 密钥由调用方提供、缺失且必需时报异常；新增异常类与既有四类并列 |
| ISSUE-044 | §3 | 调用方自行发送时的取数形式：读文件 / 写进给定流 / 库暴露流接口（未定） |

> 本文档内的 `ISSUE-NNN` 是**原始编号**。同一 `D` 单元内的编号都在本文件里，完整编号映射见 `README.md`。

---

## 1. sink 只接受参数，不接收函数（原 ISSUE-043）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P1 / 已定稿，待实现 |
| 原依赖 | ISSUE-005（库只产出数据、不发送、不回调） |
| 原影响面 | 新增落盘 sink 层、`src/onconf/__init__.py`、`src/onconf/_audit.py`、`tests/test_audit.py`、`tests/test_security_invariants.py`、`README.md`、`README.zh-CN.md` |
| 原标签 | `area:audit`、`area:security`、`breaking` |

### 背景

现状最接近 sink 的参数是日志去向，它的形态是字符串二选一：`EngineParams.log` 注解为 `str`（`src/onconf/__init__.py:54`），`AuditLog` 接收 `str | os.PathLike[str]`（`src/onconf/_audit.py:439`），分派逻辑只精确匹配 `"stderr"` / `"stdout"`，其余任何值都当文件路径（`src/onconf/_audit.py:659-666`），参数只校验名字不校验值（`src/onconf/__init__.py:82-87`）。落盘侧没有独立的参数面。

若 sink 接受函数，调用方就能把发送逻辑塞进库里执行，网络边界便只由调用方自觉维持。当前这条边界是靠静态断言守住的：源码禁止出现 `socket` / `socketserver` 等模块（`tests/test_security_invariants.py:34-37`），运行时依赖只有 `pyyaml` 与 `rich`（`pyproject.toml:48-54`）。函数式 sink 会让这种守护失效——被执行的发送代码不在 `src/onconf/` 里，检索不到。引擎参数还必须可序列化（`DESIGN.md:710-711`：传 `Path` / 回调 / 文件句柄会在 IPC 处炸掉），回调本身就不可能随事务传给执行点。

### 结论

#### 1. sink 只接受参数

- sink 的形态是参数，不是回调。
- 参数用途限定为两类：**选模式**、**填密钥**。
- 函数式 sink 取消：不接受 callable、不接受可调用对象、不接受事件钩子。

#### 2. 库不发起网络请求

- 「库支持网络去向」不再成立：库不发起任何网络请求，不引入 HTTP / HTTPS 等协议库。
- 库的职责到「产出数据」为止；数据发往哪里、如何发送由调用方自行实现。
- 静态断言继续守护：`tests/test_security_invariants.py:34-37` 的禁 import 集合与 `pyproject.toml:48-54` 的运行时依赖不变。

#### 3. 与数据交付的关系

「产出数据」的具体交付形式见 ISSUE-044；本项只钉死 sink 的形态是参数。

### 变更项

| 位置 | 改动 |
|---|---|
| 新增落盘 sink 层 | 参数面只有「模式」与「密钥」两类；不出现 callable 注解 |
| `src/onconf/__init__.py:44-55` | `EngineParams` 增加 sink 的模式参数与密钥参数 |
| `src/onconf/__init__.py:82-87` | 参数值校验补齐：未知模式与缺失密钥都要报错，不停留在只校验参数名 |
| `src/onconf/_audit.py:439,659-666` | 删除「其余值一律当文件路径」的兜底分派 |
| `tests/test_security_invariants.py:34-41` | 断言不变；补充「sink 参数不含 callable」的守护 |
| `tests/test_audit.py` | sink 模式选择的参数化测试；传入 callable 在校验阶段被拒 |
| `README.md:127,169`、`README.zh-CN.md` | 参数说明改写为模式与密钥，去掉「去向」措辞 |

### 验收标准

- [ ] `EngineParams` 中不存在 callable 类型的参数，sink 参数注解全部是可序列化的纯数据
- [ ] 传入 callable 时在参数校验阶段报错，且不进入任何落盘路径
- [ ] 未知模式值不再被当成文件路径处理
- [ ] `tests/test_security_invariants.py:35-37` 的禁 import 断言不变且通过
- [ ] `src/onconf/` 中无网络模块 import，`pyproject.toml` 运行时依赖仍为 `pyyaml` + `rich`
- [ ] 行为变更带测试；`README.md` 与 `README.zh-CN.md` 同步

---

## 2. 加密密钥由调用方提供，缺失且必需时报异常（原 ISSUE-041）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P1 / 部分已定 |
| 原依赖 | ISSUE-005（加密落盘形式与 sink 参数模型）、ISSUE-043（sink 只接受参数） |
| 原影响面 | `src/onconf/errors.py`、`src/onconf/__init__.py`、新增落盘 sink 层、`tests/test_audit.py`、`README.md`、`README.zh-CN.md` |
| 原标签 | `area:audit`、`area:security` |

### 背景

`src/onconf/` 中没有任何加密符号：检索 `encrypt` / `cipher` / `hmac` / `secret` 零匹配，`hashlib` 只用于路径与内容摘要（`src/onconf/_owner.py:174,204`、`src/onconf/_core.py:300`）。因此「加密落盘需要密钥」目前在代码里没有落点，写入路径也不带任何密钥校验（`src/onconf/_audit.py:408-426`、`:668-675`）。

异常族是封闭的五类：`ConfError` 及其四个子类（`src/onconf/errors.py:12-29`），统一从顶层导出（`src/onconf/__init__.py:31-41`）。引擎参数只校验名字，不校验值（`src/onconf/__init__.py:82-87`）。缺密钥若只能抛 `ConfError` 基类，调用方无法用 `except` 区分「漏配密钥」与其它写入失败。

### 结论

#### 1. 密钥来源与库的边界

| 项 | 规则 |
|---|---|
| 提供方 | 调用方 |
| 库的职责 | 不生成、不推导、不保管、不评价强度 |
| 加密算法 | 由调用方指定 |

#### 2. 缺失且必需时报异常

- 触发条件：选中的落盘形式要求密钥（纯二进制加密 / 明文加密，见 ISSUE-005 §4 的四形式表），而调用方没有提供。
- 抛出时机：在写出任何记录之前，不产生半份加密文件。
- 异常类：新增一类，继承 `ConfError`，与既有四类并列（`src/onconf/errors.py:12-29`），并从顶层导出（`src/onconf/__init__.py:31-41`）。

#### 3. 传递路径

- 密钥经 sink 参数传入，属于「填密钥」那一类参数（ISSUE-043）。
- 命令行读取加密形式时密钥的入参属于 ISSUE-031；命令行必须能读出加密内容（ISSUE-042）。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/errors.py:12-29` | 新增密钥缺失异常类，继承 `ConfError` |
| `src/onconf/__init__.py:31-41` | 新异常加入 `__all__` |
| 新增落盘 sink 层 | 加密形式在写入前校验密钥；算法名与密钥均来自参数 |
| `src/onconf/_audit.py:668-675` | 审计写入接入加密 sink，失败沿用既有 `ConfError` 抛出通道 |
| `tests/test_audit.py` | 覆盖缺密钥、密钥可用、加密后往返三类 |
| `README.md:127,169`、`README.zh-CN.md` | 参数说明与日志审计章节补密钥来源与异常 |

### 验收标准

- [ ] 选择加密形式且未提供密钥时，在写入前抛出可 `except` 的新异常类，且该异常不是裸 `ConfError`
- [ ] 新异常类可从 `onconf` 顶层导入，并出现在 `__all__` 中
- [ ] 加密写入与读取往返后，记录的语义与明文形式一致
- [ ] 密钥不出现在任何记录、日志、异常消息与落盘字节中
- [ ] `src/onconf/` 中不存在密钥的持久化写入路径
- [ ] 行为变更带测试；`README.md` 与 `README.zh-CN.md` 同步

### 未决事项

缺密钥之外的两种失败是否复用同一个异常类，尚无裁定：

| 失败情形 | 候选 | 代价 |
|---|---|---|
| 算法名不可用（拼写错误、环境不支持） | (a) 复用密钥缺失异常；(b) 单列一类 | (a) 异常类少，但调用方无法区分「漏配密钥」与「算法不可用」；(b) 区分清楚，异常族再扩一格 |
| 密钥形态与算法不匹配（长度、编码不符） | (a) 复用密钥缺失异常；(b) 单列一类；(c) 由算法实现抛 `ValueError` | (c) 与 `errors.py` 现有分类不一致，调用方只能捕裸 `ValueError` |

三种情形都需要在写入任何记录之前抛出，不产生半份加密文件。

---

## 3. 调用方自行发送数据时的取数形式（原 ISSUE-044）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P1 / 部分已定 |
| 原依赖 | ISSUE-005（库只产出数据）、ISSUE-043（sink 只接受参数） |
| 原影响面 | `src/onconf/_audit.py`、`src/onconf/_engine.py`、`src/onconf/__init__.py`、`tests/`、`README.md`、`README.zh-CN.md` |
| 原标签 | `area:audit` |

### 背景

记录已经是可传输的纯数据：`Record` 的文档串自述「纯数据，可以直接过 IPC 回传给发起方」（`src/onconf/_audit.py:176-183`），远端应答里的记录确实回传并在发起方渲染（`src/onconf/_engine.py:594`）。但发送职责目前归库：`_emit_log` 自己写 `sys.stderr` / `sys.stdout` 或一个文件路径（`src/onconf/_audit.py:651-666`），审计文件也由库自己追加（`src/onconf/_audit.py:668-675`）。

库不发起网络请求、不接收函数之后（ISSUE-005 §5、ISSUE-043），「调用方要把数据发到别处」与「库产出的数据」之间必须有一个交付接口，否则调用方只能逆向解析库自己的落盘格式。引擎参数被要求是可序列化的纯数据（`DESIGN.md:710-711`），这条规则直接约束哪些交付形态可行。

### 结论

#### 1. 边界

- 库的职责到「产出数据」为止；数据发往哪里、如何发送由调用方自行实现。
- 库不发起网络请求，不接收函数（ISSUE-043）。
- 产出单位是记录而不是渲染文本：`Record` 的可序列化性由自身保证（`src/onconf/_audit.py:176-183`）。

#### 2. 对候选形式同时成立的约束

- 交付形态不得破坏「引擎参数是可序列化的纯数据」（`DESIGN.md:710-711`）。
- 执行点可能不是调用方进程：记录要跨 IPC 回到发起方（`src/onconf/_engine.py:594`），无法序列化的东西过不去。
- 无论选哪种交付形式，落盘那一份仍然恒写、全量（ISSUE-005 §1、§2）。

#### 3. 产出形式

产出形式不在本项内指定，候选与代价见「未决事项」。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_audit.py:651-666` | `_emit_log` 的发送职责按选定形式拆出 |
| `src/onconf/_audit.py:176-183` | `Record` 作为交付单位，字段与序列化保持不变 |
| `src/onconf/_engine.py:594` | 远端记录的交付沿用同一条路径 |
| `src/onconf/__init__.py:44-55` | 交付形式相关的参数位 |
| `tests/` | 交付形式的端到端测试；跨进程场景必须真起多进程 |
| `README.md:169`、`README.zh-CN.md` | 说明调用方如何取得记录 |

### 验收标准

- [ ] 选定的交付形式有端到端测试：调用方拿到的记录与库落盘的记录语义一致
- [ ] 交付过程不引入网络模块，`tests/test_security_invariants.py:35-37` 的断言不变且通过
- [ ] 交付形态不要求引擎参数携带不可序列化对象（`DESIGN.md:710-711`）
- [ ] 执行点在另一个进程时交付路径仍然成立，且用真进程验证
- [ ] 落盘那一份不受交付形式影响，仍然恒写、全量（ISSUE-005）
- [ ] `README.md` 与 `README.zh-CN.md` 同步

### 未决事项

产出形式。

| 候选 | 代价 |
|---|---|
| (a) 写到文件，由调用方读取 | 交付面最简单，库不需要新 API；调用方要自己解析落盘格式，还要处理轮转分片（ISSUE-039）；格式演化时读取方跟着改 |
| (b) 写进调用方给的流对象或 fd | 调用方不需要解析格式；但流对象与文件句柄不可序列化，与 `DESIGN.md:710-711` 冲突，执行点在别的进程时该 fd 也过不去 IPC |
| (c) 库暴露流接口 | 调用方按迭代取记录，格式与轮转都归库；需要新增公共 API 面，并要回答接口返回记录还是字节、以及它和落盘那一份是否同源 |

