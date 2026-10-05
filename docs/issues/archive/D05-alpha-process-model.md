# D05 进程模型：独立 Alpha

| 项 | 值 |
|---|---|
| 类型 | 设计变更（breaking） |
| 优先级 | P0 / P1 |
| 状态 | 部分已定（取最不确定成员）、ISSUE-033（部分已定）、ISSUE-034（部分已定）、ISSUE-035（部分已定）） |
| 成员状态 | 部分已定 4 —— 未定稿：ISSUE-004（部分已定）、ISSUE-033（部分已定）、ISSUE-034（部分已定）、ISSUE-035（部分已定） |
| 前置 | D01 |
| 联动 | D06、D08 |
| 覆盖原编号 | ISSUE-004、ISSUE-033、ISSUE-034、ISSUE-035 |
| 影响面 | `src/onconf/_owner.py`（整模块重写）、`src/onconf/_engine.py`、`src/onconf/__init__.py`、`tests/test_owner.py`、`tests/test_engine.py`、`tests/test_security_invariants.py`、`docs/security/threat-model.md`、`README.md`、`README.zh-CN.md`、`AGENTS.md`、`src/onconf/_owner.py`（自举路径）、新增 Alpha 入口模块、`SECURITY.md`、`src/onconf/_owner.py`、`src/onconf/_engine.py`（攒批窗口与指纹）、`src/onconf/_core.py`、`tests/test_core.py`、`docs/roadmap.md`、`docs/architecture/index.md`、`DESIGN.md` §18 / §29 / §32 |
| 标签 | `area:process-model`、`breaking`、`area:process-model`、`area:security`、`area:process-model`、`area:core`、`breaking` |

## 0. 本决策的整体口径

Alpha 的模型、拉起它的命令、拉起它的判据、以及它成立的前提（规则 1 移除）原本分在四份文件里，并且互相声明依赖成环。它们其实是同一个决策：一个按需拉起、批次结束即退出的独立进程，接管全部写请求。

- Alpha 不是客户进程内的线程，也不是客户之一；一个配置目录对应一个 Alpha（原 ISSUE-004）；
- 启动采关闭制，由入口对象自举，竞态由 OS 原子绑定裁决；不常驻，批次结束即退出（原 ISSUE-004）；
- 每个请求必须有上界，超时就地写；该回退无损的前提是规则 1 已移除（原 ISSUE-004 + 原 ISSUE-035）；
- 拉起命令的来源与「多个事务」的判据都未定，但必须各自是一个确定条件（原 ISSUE-033 / 原 ISSUE-034）；
- 规则 1 从执行路径整体移除，引擎不再删除任何未被代码声明的键，删除能力转入 CLI（原 ISSUE-035）。

### 0.1 成员索引

| 原编号 | 本文件 | 一句话 |
|---|---|---|
| ISSUE-004 | §1 | 独立 Alpha 进程：定义、生命周期、失败回退、读路由、日志归属、安全定位 |
| ISSUE-033 | §2 | 拉起 Alpha 的命令来源：库内置默认命令还是配置声明（未定） |
| ISSUE-034 | §3 | 「识别到有多个事务」的判据（未定） |
| ISSUE-035 | §4 | 移除进程内自动清理：引擎不删任何未声明的键，能力转入 CLI |

> 本文档内的 `ISSUE-NNN` 是**原始编号**。同一 `D` 单元内的编号都在本文件里，完整编号映射见 `README.md`。

---

## 1. 进程模型：独立 Alpha 进程（原 ISSUE-004）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P0 / 部分已定 |
| 原依赖 | ISSUE-003（`EngineParams` 承载 Alpha 的引导参数）、ISSUE-035（规则 1 移除是就地写无损的前提）、ISSUE-033 / ISSUE-034（启动命令与拉起判据） |
| 原影响面 | `src/onconf/_owner.py`（整模块重写）、`src/onconf/_engine.py`、`src/onconf/__init__.py`、`tests/test_owner.py`、`tests/test_engine.py`、`tests/test_security_invariants.py`、`docs/security/threat-model.md`、`README.md`、`README.zh-CN.md`、`AGENTS.md` |
| 原标签 | `area:process-model`、`breaking` |

### 背景

- 写者是守护线程 `onconf-owner`，住在碰巧先抢到端点的客户进程内部（`src/onconf/_owner.py:403-411`、`src/onconf/_owner.py:566-590`）；选主就是抢绑端点（`src/onconf/_owner.py:234-246`）。
- 全局声明集只在写者活着时成立：写者随客户进程退出而换人，并集重置，多进程规则 1 的误删无法从根上消除（`DESIGN.md:1056-1082`、`DESIGN.md:2002-2025`）。
- 握手之后是阻塞的 `send` / `recv`，没有超时（`src/onconf/_owner.py:616-617,670-671`）：Alpha 卡住时调用方永久挂起，回退路径走不到。
- 端点生命周期依附于「谁先绑、谁退出交还」：Windows 命名管道随进程消失（`src/onconf/_owner.py:317`），POSIX 靠探活清残留（`src/onconf/_owner.py:312-325`），没有心跳，也没有 PID 判活。
- 审计文件按「一个执行点」建模（`README.md:235`），而现状是每个开启 `audit` 的引擎都往同一份 `<home>/audit.log` 追加。

### 结论

#### 1. Alpha 的定义与启动

- Alpha 是独立于所有客户进程的进程：不是客户进程内的线程，也不是客户之一。它是该配置目录唯一的读写者，持有全局声明集与工作集；一个配置目录对应一个 Alpha。
- 启动采关闭制：默认每个进程都有资格启动 Alpha，可通过参数显式退出该资格；不指定具体由哪个进程启动。
- 自举由入口对象完成：`AutoConf` 实例是每个进程必然存在的入口（`src/onconf/__init__.py:58`），哪个进程的入口先发现 Alpha 不存在，就由它拉起。
- 启动竞态由操作系统的原子绑定裁决（`src/onconf/_owner.py:234-246`）：只有一个进程能绑上端点成为 Alpha，其余退让并连接，不报错。
- 传输沿用 `multiprocessing.connection`（Windows 命名管道 / POSIX AF_UNIX，`src/onconf/_owner.py:82,189-209`），不开网络端口。
- Alpha 的启动参数（`home`、`file_type`、落盘与日志参数、`identity`）必须经新的传递路径到达 Alpha —— 启动参数或握手；现有线上协议不携带任何引擎参数（`src/onconf/_owner.py:333-347`），而 `AutoConf` 起来之后不可重配（`src/onconf/__init__.py:99-104`）。启动命令来源见 ISSUE-033，拉起判据见 ISSUE-034。

#### 2. 生命周期

- Alpha 不常驻：多数时间不存在，仅在拉起判据成立时出现，那一批事务结束即退出。
- 端点生命周期语义重写，不再有「首次使用时抢绑、退出时交还」的节奏：Alpha 在则独占端点，退出即释放；残留端点只在确认无人应答时清理，`_endpoint_is_alive` 的裸 `connect` 探测保留（`src/onconf/_owner.py:292-309`），用途改为判定 Alpha 是否存在。
- 存活判断只依据探测结果，不引入心跳与 PID 判活。
- 客户端 `atexit` 只交出自己的声明并收口日志（`src/onconf/_engine.py:404-407`），不得关闭 Alpha、不得影响其存活；「放下写者身份」这一职责随模型消失（`src/onconf/__init__.py:61-71`）。
- Alpha 不向 `<home>` 写 PID 或状态文件；实现若确需新增运行态文件，必须同步 `tests/test_security_invariants.py:140-147` 的首层路径白名单断言。

#### 3. 失败与回退

- 每个请求必须有上界：握手沿用 `HELLO_TIMEOUT`（`src/onconf/_owner.py:136`），握手之后的 `send` / `recv` 同样加上界（现状无上界，见 `src/onconf/_owner.py:616-617,670-671`）。上界是本节其余条款的落地前提。
- 当前请求在上界内未获响应 ⇒ 就地写。该回退路径已存在（`src/onconf/_owner.py:632-641`），且因规则 1 移除而无损（ISSUE-035）；即使 Alpha 活着只是慢，正确性由 OS 锁 + 锁内重读保证（`src/onconf/_engine.py:691-692`）。
- 后续请求继续尝试连接，并在具备资格时重新拉起 Alpha；一次失败不导致永久放弃。
- `[Link]` 的 `bind` / `connect` / `fallback` 三态语义按新模型重定（`src/onconf/_engine.py:506-508`）。

#### 4. 读路由

- 写请求全部经 Alpha 收口；读请求分级：单次读量小由客户自行读文件，量大时转 Alpha 代取。
- 「量大」的判据必须是一个可声明的参数，不允许隐式阈值；参数口径见未决事项。
- 本地读走指纹检查 + 按需重读：`_disk_stamp` 比较值文件与词表的 mtime + size（`src/onconf/_engine.py:794-808`），不得命中陈旧内存缓存；无待写时允许早退（`src/onconf/_engine.py:679-680`）。
- 硬约束：Alpha 不得持有未落盘的待提交状态，收到 `OP_COMMIT` 即当场提交落盘（`src/onconf/_owner.py:146-147`、`src/onconf/_engine.py:648-661`）。写入是原子替换（`src/onconf/_engine.py:153-163`），本地读读到的是最后一次已提交的版本，对「文件绝对权威」的引擎而言那就是事实（`DESIGN.md:805-811`）。
- 「小读本地、大读转取」是纯性能选择，不承载正确性。

#### 5. 日志与审计归属

- 日志归属发起方，不归执行点：终端形态回传发起方，由发起方自己的 `log=` 决定落点（默认 `stderr`）；文件形态由执行点写进 `<home>/audit.log`。
- 回传复用现有机制：执行点把本次真正输出的记录随应答回传（`src/onconf/_audit.py:594-603`），发起方补到自己的终端上（`src/onconf/_engine.py:588-594`）。Alpha 没有终端，因此它的默认去向不是 `stderr`，而是回传。
- 「审计文件假定一个执行点」不再成立：Alpha 成为唯一执行点后，`<home>/audit.log` 只有一个写入者，按进程编号的事务号不再交叠。
- Alpha 不自行发起写操作（规则 1 已移除，见 ISSUE-035；线上协议只有读与提交两个 op，`src/onconf/_owner.py:146-147`），因此不存在「没有发起方」的记录场景。
- 远端失败时由发起方另记一条 `[Error]` 的现有行为保留（`src/onconf/_engine.py:596-607`）。

#### 6. 安全定位

- 安全陈述由「不 spawn 子进程、不开端口」（`README.md:217-218`）改写为：库会拉起一个本机的、只连同用户的 Alpha 进程；不开网络端口，不出机器。
- `tests/test_security_invariants.py:35-37` 的禁 import 名单必须显式重写，不允许在断言不变的情况下通过。现状有两处假绿：`multiprocessing` 不在名单里而 `src/onconf/_owner.py:82` 已在用；检查基于名字，`importlib` 可绕过（`src/onconf/_lock.py:46-49`）。
- 威胁模型逐条复核：T4 残余风险的成因是写者与客户同进程（`docs/security/threat-model.md:146-153`），随 Alpha 独立而消失；T10 的「没有网络调用」结论保持（`docs/security/threat-model.md:226-247`）；T1 与不变量表同步（`docs/security/threat-model.md:77-85,299-306`）。
- 认证码的定位不变：它不是密码学边界，真正的边界是配置目录的文件系统 ACL（`src/onconf/_owner.py:47-49`）。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_owner.py`（整模块） | 由「抢绑端点的写者线程」改为「独立 Alpha 进程 + 客户连接」；新增自举路径与启动竞态退让 |
| `src/onconf/_owner.py:333-347` | 线上协议增加引擎参数传递通道（Alpha 的 `home` / `file_type` / 日志参数 / `identity`） |
| `src/onconf/_owner.py:616-617,670-671` | 握手之后的 `send` / `recv` 加上界 |
| `src/onconf/_owner.py:292-325` | 探测与残留清理改为 Alpha 存在性探测；端点生命周期语义按结论 §2 重写 |
| `src/onconf/_engine.py:330-351,469-471` | 读路由分级：按可声明参数决定本地读或转取；`_is_writer()` 语义改写 |
| `src/onconf/_engine.py:588-594,596-607` | 日志回传与远端失败补记按「终端归发起方、文件归执行点」重定 |
| `src/onconf/__init__.py:61-71,90-105` | `atexit` 只 `sync()`；入口对象承担自举；自启动资格参数纳入 `EngineParams` |
| `tests/test_owner.py` | 按新模型重写：独立进程、启动竞态、存在性探测、退让连接、超时回退 |
| `tests/test_engine.py:562-578,599-643` | 跨进程写者覆盖按 Alpha 模型重定；长命写者用例升级为主用例 |
| `tests/test_security_invariants.py:35-72,140-147` | 禁 import 断言显式重写；运行态文件白名单同步 |
| `docs/security/threat-model.md` T4 / T10 / 不变量表 | 按独立 Alpha 重写 |
| `README.md:52-55,59,217-218,228-230,234-236`、`README.zh-CN.md:50-51,173,210-211,221-229` | 「无独立进程 / 无守护进程 / 不 spawn 子进程」的陈述改写 |
| `AGENTS.md:10,12`、`docs/index.md:16,47`、`docs/getting-started.md:71-72,133`、`docs/roadmap.md:30,50`、`docs/architecture/index.md:31,37-38` | 专职写者描述同步 |
| `DESIGN.md:1119-1124`（§19.2）、`:1184-1190`（§19.6）、`:1656-1665`（§26.3） | 独立进程的定性、读路由结论与身份论证一并改写 |

### 验收标准

- [ ] 独立 Alpha 进程可由任意一个有资格的客户入口拉起；同时启动的多个进程只有一个成为 Alpha，其余连上而非报错
- [ ] Alpha 在事务批次结束后退出；不存在心跳、PID 文件或常驻监督
- [ ] 客户端 `atexit` 后 Alpha 仍存活；Alpha 存活期间不因某个客户退出而换人
- [ ] 请求有上界：Alpha 无响应时调用方在上界内返回并就地写，且留 `[Link] op=fallback`
- [ ] 后续请求重新尝试连接与拉起，不因一次失败永久降级
- [ ] 本地读在值文件被其他进程改动后读到新值（指纹检查回归）
- [ ] 终端记录在发起方进程输出；审计文件由执行点写且只有一个写入者
- [ ] 行为变更带测试；`tests/test_owner.py` 覆盖独立进程与启动竞态，`tests/test_engine.py` 覆盖真进程并发
- [ ] `tests/test_security_invariants.py` 的改写显式列出放行项，不保留任何假绿断言
- [ ] `README.md` 与 `README.zh-CN.md` 同步；威胁模型 T4 / T10 / 不变量表与本项一致

### 未决事项

- **关闭了自启动资格的进程，在 Alpha 不存在时如何处置**：候选 (a) 等待到请求上界后就地写，(b) 直接报错要求由有资格的进程先拉起 Alpha。代价：(a) 把不可用性摊平为「慢一点」，但每个请求都要等满上界；(b) 状态明确，但无人拉起时该进程完全不可用。
- **请求上界与启动失败阈值的取值**：候选为「两者复用同一个值」或「各自独立」。代价：复用少一个参数，但启动失败与请求无响应的语义被绑在一起；独立更精确，参数面多一项。
- **读路由「量大」参数的口径**：候选 (a) 单次值序列化后的大小阈值，(b) 单位时间内的读次数阈值，(c) 显式批量读 API 一律转取。代价：(a)(b) 要求引擎维护比较或计数状态；(c) 不引入内部状态，但要求调用方改写调用点。

---

## 2. 拉起 Alpha 的命令来源（原 ISSUE-033）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P1 / 部分已定 |
| 原依赖 | ISSUE-004（Alpha 的定义与启动模型） |
| 原影响面 | `src/onconf/_owner.py`（自举路径）、新增 Alpha 入口模块、`src/onconf/__init__.py`、`tests/test_owner.py`、`docs/security/threat-model.md`、`SECURITY.md`、`README.md`、`README.zh-CN.md` |
| 原标签 | `area:process-model`、`area:security` |

### 背景

- 库负责启动 Alpha（ISSUE-004 结论 §1），而源码中没有任何启动进程的代码：`src/` 下 `subprocess` / `Popen` / `Process(` 零匹配，`multiprocessing` 只用于 `connection`（`src/onconf/_owner.py:82`）。
- 现有选主不启动任何东西：`Owner.claim` 直接在当前进程内绑端点（`src/onconf/_owner.py:397-401`），而这要求一个活的本地 `Engine` 对象（`src/onconf/_engine.py:473-488`）。
- 线上协议不携带引擎参数（`src/onconf/_owner.py:333-347`），`AutoConf` 起来之后不可重配（`src/onconf/__init__.py:99-104`），因此 Alpha 的启动参数必须另设传递路径。

### 结论

- 关闭制下由库负责拉起 Alpha（ISSUE-004 结论 §1），启动路径必须是库内的确定路径，不依赖部署系统或时序。
- Alpha 必须自行装配一个同 `home` 的引擎：`home` 及其余引导参数（`file_type`、落盘与日志参数、`identity`）经启动参数或握手传入。
- Alpha 的入口必须是包内可定位的模块，使 `python -m` 形式的启动在任何安装方式下都成立。
- 命令来源本身见未决事项：库内置默认命令与配置声明命令二者只能取一，未定之前该项不落地。

### 变更项

| 位置 | 改动 |
|---|---|
| 新增 Alpha 入口模块（例如 `onconf.alpha`） | 独立进程入口：解析引导参数、装配引擎、绑端点、服务请求、批次结束退出 |
| `src/onconf/_owner.py:397-401` | 自举路径：由「当前进程抢绑」改为「探测 → 连接或启动 Alpha」 |
| `src/onconf/_owner.py:333-347` | 以启动参数或握手传递 Alpha 的引擎参数 |
| `src/onconf/__init__.py:90-105` | 自启动资格参数进入 `EngineParams` |
| `tests/test_owner.py` | 启动路径的回归：参数传递、启动失败、竞态退让 |
| `docs/security/threat-model.md` | 若采配置声明命令，新增「配置可执行任意命令」的信任边界条目 |
| `SECURITY.md`、`README.md:52-55,59`、`README.zh-CN.md` | 启动模型与信任边界说明 |

### 验收标准

- [ ] Alpha 由库拉起，不需要外部运维或部署系统参与
- [ ] 拉起时 Alpha 使用与客户相同的 `home` 与引导参数
- [ ] 启动失败有明确异常与上界，不静默降级成「Alpha 永远不存在」
- [ ] 打包、虚拟环境、冻结分发三种安装方式各有一组启动验证
- [ ] 若采配置声明命令，威胁模型有对应信任边界条目，且默认不允许任意命令
- [ ] `README.md` 与 `README.zh-CN.md` 同步

### 未决事项

- **库内置默认命令**：以 `sys.executable -m onconf.alpha` 之类从 `home` 派生参数。代价：对使用者零侵入；打包、虚拟环境、冻结分发等场景下 `sys.executable` 与模块定位可能对不上，需要逐场景验证。
- **配置声明命令**：由配置给出完整命令行。代价：灵活，且能适配非标准安装；但等于允许配置执行任意命令，与现有安全定位正面冲突，必须配套信任边界说明并在威胁模型新增条目。

---

## 3. 「识别到有多个事务」的判据（原 ISSUE-034）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P1 / 部分已定 |
| 原依赖 | ISSUE-004（Alpha 的按需拉起与退出）、ISSUE-035（规则 1 移除后 Alpha 无需为声明集长命） |
| 原影响面 | `src/onconf/_owner.py`、`src/onconf/_engine.py`（攒批窗口与指纹）、`tests/test_owner.py`、`tests/test_engine.py`、`README.md`、`README.zh-CN.md` |
| 原标签 | `area:process-model` |

### 背景

- Alpha 只在「识别到多个事务」时拉起，那一批结束即退出（ISSUE-004 结论 §2），因此该判据是拉起动作的唯一触发条件。
- 现状没有任何可用的判据基础：成员计数与成员发现在设计上被砍掉（`DESIGN.md:1119-1124`），实现里既无连接者计数，也无并发写者探测。
- 冷启动一个 Python 进程实测约 65 ms（`DESIGN.md:347`）；短命模型下每一次突发都要付这笔钱（`DESIGN.md:1145-1153`）。
- 现有唯一的时间维度是每个引擎自己的攒批窗口，默认 0 秒即每次声明当场落盘（`src/onconf/_engine.py:122-124`）。

### 结论

- 拉起 Alpha 的判据必须是一个确定性条件，不由时序运气决定；判据成立前 Alpha 不存在，判据消失后 Alpha 退出。
- 判据必须在客户进程侧可判定，且不要求 Alpha 先存在，否则自举循环。
- 判据必须能区分「一个进程连续多次声明」与「多个进程各自在写」。
- 具体口径见未决事项；口径确定前该判据不落地。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_owner.py` | 新增触发判定与去抖；判定成立才启动 Alpha |
| `src/onconf/_engine.py:122-124,390-395` | 攒批窗口与触发判据的关系落定（窗口到期是否等同「攒够一批」） |
| `src/onconf/_engine.py:794-808` | 若采指纹判据，复用 `_disk_stamp` 的 mtime + size 比较并加时间窗 |
| `tests/test_owner.py` | 触发判据的边界测试：单事务不拉起、判据成立拉起、判据消失退出 |
| `tests/test_engine.py` | 真进程并发下的触发与退出回归 |
| `README.md` / `README.zh-CN.md` | 拉起条件的说明 |

### 验收标准

- [ ] 单进程单事务场景下 Alpha 不被拉起
- [ ] 判据成立后 Alpha 出现，批次结束后退出
- [ ] 触发判定不依赖 Alpha 已存在，不产生自举死锁
- [ ] 判据的边界条件有测试：恰好达到与恰好未达到
- [ ] 拉起的冷启动成本有实测记录（约 65 ms/次，`DESIGN.md:347`）
- [ ] `README.md` 与 `README.zh-CN.md` 同步

### 未决事项

- **本进程攒够一批**（`flush_window` 到期或一次批量声明）：候选口径之一。代价：不引入新状态；但判据只看本进程，单进程的连续突发会反复拉起又退出，每次付一份冷启动成本。
- **端点上出现多个连接者**：候选口径之一。代价：判据直接对应「多个事务」的语义，最贴近模型；但需要连接者计数，而成员计数刚在设计上被砍掉（`DESIGN.md:1119-1124`），且要求 Alpha 不存在时也能计数，需要额外的共享状态。
- **值文件指纹短时间反复变化**：候选口径之一。代价：不需要成员信息，只依赖文件系统（`src/onconf/_engine.py:794-808` 已有指纹）；但需要轮询与时间窗，判据有延迟，且难以区分单个进程的连续写，容易误触发。

---

## 4. 移除进程内自动清理（规则 1）（原 ISSUE-035）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P1 / 部分已定 |
| 原依赖 | ISSUE-004（就地写无损的前提）、ISSUE-047 / ISSUE-031（清理能力的 CLI 落点） |
| 原影响面 | `src/onconf/_core.py`、`src/onconf/_engine.py`、`src/onconf/__init__.py`、`tests/test_core.py`、`tests/test_engine.py`、`README.md`、`README.zh-CN.md`、`docs/roadmap.md`、`docs/architecture/index.md`、`DESIGN.md` §18 / §29 / §32 |
| 原标签 | `area:core`、`breaking` |

### 背景

- 规则 1（删除代码未声明的键）现在是执行路径的一部分：`reconcile` 的 `clean_unknown` 开关（`src/onconf/_core.py:181-187`）产出 `Action("clean")`（`src/onconf/_core.py:101-104,220-224`）。
- `sync()` 与 `flush()` 的差别只剩这一个开关（`src/onconf/_engine.py:399-407`），进程退出经 `atexit` 调用 `sync()`（`src/onconf/__init__.py:61-68`）。
- 该行为在多进程下必然误删：写者一换人声明集重置，新写者按自己那一份清理（`DESIGN.md:2002-2025`；风险 A 见 `DESIGN.md:1056-1082`）。
- 提交路径按 `clean` 动作产出删除记录并计入变更事项（`src/onconf/_engine.py:668-713,752-761`）。
- 文档把它登记为未定问题：`README.md:180,228,230`、`README.zh-CN.md:173,221,223`、`docs/roadmap.md:50`、`docs/architecture/index.md:38`。

### 结论

- 规则 1 从执行路径整体移除：引擎不再删除任何未被代码声明的键。
- `reconcile` 不再接受清理开关；`Action("clean")` 这一动作类型取消（`src/onconf/_core.py:101-104`）。
- 提交点只做补充、覆盖与元数据更新，不做删除。
- 接受后果：值文件随时间积累不再声明的键。`README.md` / `README.zh-CN.md` 的 Known limitations 必须新增这一条，并撤掉「规则 1 需要写者长命」的旧表述（`README.md:180,228`、`README.zh-CN.md:173,221`）。
- 清理能力转移到命令行：单键删除见 ISSUE-047，批量同步删除见 ISSUE-031 的 `sync`。CLI 离线执行、可以删除，因为它不经过多进程执行路径。
- 连带消掉：§18.4 风险 A（`DESIGN.md:1056-1082`）、§32.4（`DESIGN.md:2002-2025`）、§29.1 的「期望集完整」前提（`DESIGN.md:1830-1851`）、`clean_unknown` 参数、`Action("clean")`，以及「写者必须长命」这条限制。
- 该项同时是 ISSUE-004 回退无损的前提：就地写不再有误删风险。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_core.py:101-104` | `Action` 的合法 `kind` 去掉 `clean` |
| `src/onconf/_core.py:181-224` | `reconcile` 去掉 `clean_unknown` 参数与清理分支 |
| `src/onconf/_engine.py:399-407` | `flush()` / `sync()` 的语义分裂消失（命名去留见未决事项） |
| `src/onconf/_engine.py:648-661,668-713` | 提交路径去掉 `clean` 分支及相关记录判定 |
| `src/onconf/_engine.py:752-761` | 变更事项判定去掉 `clean` |
| `src/onconf/__init__.py:61-68` | `atexit` 提交点按新语义改写 |
| `tests/test_core.py`、`tests/test_engine.py` | 删除清理用例；新增「未声明的键保留」回归 |
| `README.md:180,228,230`、`README.zh-CN.md:173,221,223` | Known limitations 新增「引擎不清理未声明的键」；撤掉旧表述 |
| `docs/roadmap.md:50,65`、`docs/architecture/index.md:38` | 「短命进程之间的规则 1」条目改写或删除 |
| `DESIGN.md:1054-1090`（§18.4）、`:1830-1851`（§29.1）、`:2002-2025`（§32.4） | 规则 1 的执行语义移除，登记为 CLI 能力 |

### 验收标准

- [ ] 任何配置组合下，事实里存在而代码未声明的键在提交后仍然存在
- [ ] `reconcile` 的签名不含清理开关；`Action` 不再有 `clean`
- [ ] `conf()`、提交点、进程退出三条路径都不触发删除
- [ ] 未声明键的保留有回归测试，且覆盖真进程并发
- [ ] 被移除的行为不再有任何测试依赖它
- [ ] README 的 Known limitations 新增条目；`README.md` 与 `README.zh-CN.md` 同步
- [ ] ISSUE-047 / ISSUE-031 的 CLI 清理入口已登记，且与进程内执行路径无关

### 未决事项

- **`sync()` 与 `flush()` 只剩一个语义后的命名**：候选 (a) 两个名字保留，互为别名；(b) 撤掉一个，只留 `flush()`。代价：(a) 不破坏现有调用点，但公开面留下两个同义动词；(b) 公开 API 收缩，需要同步改动调用点与文档。

