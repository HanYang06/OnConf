# D01 接口面：使用口 `conf` 与配置口 `AutoConf`

| 项 | 值 |
|---|---|
| 类型 | 设计变更（breaking） |
| 优先级 | P0 / P1 / P2 |
| 状态 | 待决策（取最不确定成员）、ISSUE-054（待决策）） |
| 成员状态 | 已定稿，待实现 3 / 部分已定 1 / 待决策 1 —— 未定稿：ISSUE-003（部分已定）、ISSUE-054（待决策） |
| 前置 | 无 |
| 联动 | D02、D03、D04、D06 |
| 覆盖原编号 | ISSUE-001、ISSUE-002、ISSUE-003、ISSUE-027、ISSUE-054 |
| 影响面 | `src/onconf/__init__.py`、`src/onconf/_engine.py`、`src/onconf/_core.py`、`tests/`、`README.md`、`README.zh-CN.md`、`docs/api/index.md`、`DESIGN.md` §11.1/§15.1/§17.5–§17.7、`src/onconf/_env_backend.py`、四个后端、`DESIGN.md` §10/§15.4/§18.2/§18.3、`src/onconf/_audit.py`、`src/onconf/_vocab.py`、`tests/test_security_invariants.py`、`docs/security/threat-model.md`、`docs/roadmap.md`、`.gitignore`、`DESIGN.md` §9.1/§15.3、`src/onconf/errors.py`、`tests/test_vocab.py`、`src/onconf/_engine.py:201-220`、`src/onconf/__init__.py:44-55` |
| 标签 | `area:api`、`breaking`、`area:api`、`area:backend`、`breaking`、`area:api`、`area:security`、`breaking`、`area:api`、`area:vocab`、`breaking`、`area:engine`、`area:docs` |

## 0. 本决策的整体口径

使用口与配置口是同一次接口收敛的两面，必须一起冻结：使用口决定「怎么问」，配置口决定「能问什么」。

- 使用口收敛为三种模式，判据只看 `value` 位是否填写（原 ISSUE-001）；
- 返回值取载体原生类型，引擎不猜类型、不做向声明类型的转换（原 ISSUE-002）；
- `type=` 删除后类型退出一切持久状态 —— 词表、JSON Schema、声明哈希、异常族（原 ISSUE-027）；
- 配置口的参数面按性质分四组，总原则是「凡是引擎的默认行为，都必须能显式声明、覆盖或关闭」（原 ISSUE-003）；
- 值文件类型由单值参数 `file_type` 决定，其缺省值与「以 JSON 为主」的定位绑定（原 ISSUE-054）。

本单元是其余所有单元的冻结点：它定完之前，任何涉及参数面、路径、日志、CLI 的改动都要返工。

### 0.1 成员索引

| 原编号 | 本文件 | 一句话 |
|---|---|---|
| ISSUE-001 | §1 | 签名收敛为 `conf(key, value=MISSING, doc=None)`，判据只看 `value` 位；`type=` / `force=` / `**engine` 出局 |
| ISSUE-002 | §2 | 返回值 = 载体原生类型；引擎不猜类型、不转换、不为缺失的载体能力兜底 |
| ISSUE-003 | §3 | 配置口参数面按 A / B·C / D 四组重构；引导层不可运行中改；默认行为一律可声明 |
| ISSUE-027 | §4 | `type=` 删除后的连带清理：词表形态、Schema 输出、声明哈希、`TypeConflictError` |
| ISSUE-054 | §5 | `file_type` 缺省值与「以 JSON 为主」的主 / 辅后端标注（未定） |

> 本文档内的 `ISSUE-NNN` 是**原始编号**。同一 `D` 单元内的编号都在本文件里，完整编号映射见 `README.md`。

---

## 1. 使用口 `conf` 参数面收敛为三种模式（原 ISSUE-001）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P0 / 已定稿，待实现 |
| 原依赖 | ISSUE-027（`type=` 移除）、ISSUE-003（覆盖出口归配置口、引擎参数分组）、ISSUE-008（键内嵌路径） |
| 原影响面 | `src/onconf/__init__.py`、`src/onconf/_engine.py`、`src/onconf/_core.py`、`tests/`、`README.md`、`README.zh-CN.md`、`docs/api/index.md`、`DESIGN.md` §11.1/§15.1/§17.5–§17.7 |
| 原标签 | `area:api`、`breaking` |

### 背景

现状签名是 `conf(key, value=MISSING, *, doc=None, type=None, force=False, **engine)`（`src/onconf/__init__.py:108-116`），读写判据由三个条件合取而成：`value is MISSING and doc is None and type is None` 则读（`src/onconf/_engine.py:326-328`）。

- 每新增一个参数就要往判据里追加一个合取项，参数面无法封闭；`conf(key, type=int)` 由此成为可达的第四种形态（`_engine.py:326`）。
- `force` 不进判据，`conf(key, force=True)` 被静默降级成读（`_engine.py:326`、`_engine.py:387-388`）：调用方以为在覆盖，实际没有任何写入发生。
- `doc` 是 keyword-only（`__init__.py:112`）；`**engine` 让使用口也能配置引擎，`conf("a.b", 1, home="/x")` 是合法调用（`__init__.py:115,130`）。

不可接受之处：三模式矩阵之外仍有可达形态，其中一种把写意图静默当成读，且参数面每加一项都要改判据。

### 结论

#### 1. 签名与判据

```python
conf(key: str, value: Any = MISSING, doc: str | None = None) -> Any
```

写法与模式一一对应，不做任何推断：

```text
conf(key)                    → 模式 3：读
conf(key, value)             → 模式 1：声明 + 写
conf(key, value, doc)        → 模式 1：声明 + 写，同时登记说明
conf(key, doc=…)             → 模式 2：只登记（空结构）
conf(key, value, doc=…)      → 模式 1
```

- 判据只看 `value` 位是否填写。`None` / `""` / `0` 都是合法值，一律算填写；`MISSING` 是唯一哨兵（`src/onconf/_core.py:58-59`）。
- 第 2 位置恒属 `value`，因此 `conf(key, x)` 永远是模式 1；模式 2 只能由 `doc=` 关键字触发，没有位置写法。
- 判据里不再出现 `doc` / `type` / `force`，参数面自此封闭：以后新增参数不需要改判据。
- `type` 见 ISSUE-027，`force` 见第 2 节，`**engine` 摘除。

| 模式 | 调用形态 | 判据 | 语义 | 返回值 |
|---|---|---|---|---|
| 1 | `conf(key, value)`、`conf(key, value, doc)` | `value` 位填写 | 声明 + 写 | 当前生效值 |
| 2 | `conf(key, doc=…)` | `value` 位空、`doc` 给出 | 只登记（空结构），随即按读取规则取值 | 事实里的值；没有就报错 |
| 3 | `conf(key)` | `value` 位空、`doc` 未给出 | 读 | 事实里的值或词表默认值 |

模式 1 的两种写法等价，只在是否同时登记说明上有差别：`doc` 位置给了就写进词表，不给就只声明值与默认值。

#### 2. 「创建」与「覆盖」不再由 `conf` 区分

`force=` 从 `conf` 移除。模式 1 遇到事实里已有不同值时按「尊重文件」处理（`src/onconf/_core.py:246-256`）。覆盖既存值是配置口动词面的职责（`DESIGN.md:848-874` §17.5/§17.6），动词名称与形态见 ISSUE-003。

#### 3. 报错与返回值口径

| 情形 | 结果 |
|---|---|
| 读未登记的键 | `KeyNotRegisteredError` |
| 已登记但事实里没有值 | `KeyHasNoValueError`（`src/onconf/_core.py:140-148`） |
| 模式 1 的返回值 | 事实里的值，不是传入的默认值（`src/onconf/_engine.py:769-784`） |
| `key` 不是字符串 | `TypeError`（`src/onconf/_engine.py:321-325`） |

#### 4. 使用口不得配置引擎

`**engine` 从 `conf` 摘除（`src/onconf/__init__.py:115,130`），引擎参数只走配置口；「一个配置口、一个使用口」在实现上成立，不再依赖「引擎是否已经起来」这一时序条件。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/__init__.py:108-116` | 签名收敛为 `conf(key, value=MISSING, doc=None)`；删 `type` / `force` / `**engine` |
| `src/onconf/__init__.py:130` | 删除 `AutoConf(**engine) if engine else _engine` 分派，直接取单例 |
| `src/onconf/_engine.py:301-328` | `Engine.__call__` 判据改为只看 `value`；`doc` 位置参数化 |
| `src/onconf/_engine.py:330-395` | `read` / `declare` 的 `type` / `force` 形参随 ISSUE-027 与配置口动词面移除 |
| `src/onconf/_engine.py:769-784` | `_effective` 去掉 `force` 分支 |
| `src/onconf/_core.py:71-80,280-300` | `Decl.type` 与声明集哈希里的类型编码随 ISSUE-027 移除 |
| `docs/api/index.md:12,16-21` | 签名与「三条语义」改写为三模式 |
| `README.md:128,130-137`、`README.zh-CN.md` | 两个面表格的 `conf` 签名与四条调用示例 |
| `DESIGN.md:311`（§11.1）、`:648-659`（§15.1）、`:876-905`（§17.7） | 统一为单一签名与三模式口径 |
| `tests/` | 按参数形态分派的用例改为三模式；补「`force=True` 不再被当成读」的回归 |

### 验收标准

- [ ] 五种写法与模式的对应逐个有用例：`conf(key)` / `conf(key, value)` / `conf(key, value, doc)` / `conf(key, doc=…)` / `conf(key, value, doc=…)`
- [ ] `conf(key, value, doc)` 第 3 位置写法可用，且 `doc` 写进词表；`conf(key, doc=…)` 不因其位置形态被误判为模式 1
- [ ] 模式 2 在事实无值时抛 `KeyHasNoValueError`，事实有值时返回该值
- [ ] 传入 `force=` / `home=` 等已摘除参数抛 `TypeError`，不再静默降级
- [ ] 模式 1 的返回值等于值文件里的既存值（值文件优先）
- [ ] `README.md` 与 `README.zh-CN.md` 同步；`docs/api/index.md` 的签名与判据同源

---

## 2. 使用口 `conf` 返回值口径与类型推断取消（原 ISSUE-002）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P0 / 已定稿，待实现 |
| 原依赖 | ISSUE-027（类型声明移除）、ISSUE-028（`.env` 编解码格式）、ISSUE-003（`env_file_dict` / `env_file_list` 参数位） |
| 原影响面 | `src/onconf/_core.py`、`src/onconf/_engine.py`、`src/onconf/_env_backend.py`、四个后端、`tests/`、`README.md`、`README.zh-CN.md`、`docs/api/index.md`、`DESIGN.md` §10/§15.4/§18.2/§18.3 |
| 原标签 | `area:api`、`area:backend`、`breaking` |

### 背景

设计稿要求读取时把值向声明类型收敛：`DESIGN.md:1026-1052`（§18.3）给出「推断类型 != 声明类型 ⇒ 尝试转换」，同一要求另见 §18.2 第 ④ 步（`DESIGN.md:1015`）、§15.4 引用（`DESIGN.md:1050`）与 §10/M1（`DESIGN.md:1179`）。

实现没有推断也没有转换：`src/onconf/_core.py:140-148` 只有「命中事实原样返回」与「取词表 `default`」两条路径，`_core.py:131-136` 明写引擎对值透明。README 与 API 文档站在实现一边（`README.md:141-143`、`docs/api/index.md:18-19`），而 `src/onconf/_core.py:11` 的模块 docstring 仍把 §18.3 的转换条目列为遵循的规格。

后端表达能力确实不同：`.env` 物理上只存字符串，`render()` 对非 `str` 直接报错（`src/onconf/_env_backend.py:5-13,104-110`）；TOML 没有 `null`（`src/onconf/_toml_backend.py:27,190-191`）。

不可接受之处：同一件事有三份互不相同的表述（设计稿要求转换、实现不转换、README 与 API 文档各写一套），且没有一处标注废弃。

### 结论

#### 1. 返回值 = 载体原生类型

「可直推」的准确含义是**载体自己带着类型信息**：载体能表达就返回，不能表达时按字符串。引擎只把解析结果原样交出。

| 后端 | 载体能表达 | 读回来 |
|---|---|---|
| JSON | string / number / boolean / null / array / object | 对应 Python 类型；dict / list 正常返回 |
| YAML | 同 JSON（YAML 1.2 是 JSON 超集） | 同上 |
| TOML | string / integer / float / boolean / array / table / datetime | 同上；`None` 表达不了 |
| `.env` | 只有字符串 | 一律 `str` |

#### 2. 引擎的三个「不做」

1. 不从内容猜类型：`PORT=8080` 在 `.env` 上读回 `"8080"`，不变成 `int`；
2. 不做向声明类型的转换：要 `int` 就在使用处写 `int(conf("PORT"))`；
3. 不为缺失的载体能力兜底：`.env` 里的复杂结构就是字符串。

#### 3. 跨后端类型差异不承诺可移植

同一个键在不同后端读回的类型可以不同，这条差异**不进词表**，由 README 写成跨后端不可移植的类型差异（与 `DESIGN.md:1680` §27.1「只输出一份 JSON Schema」一致）。

```python
conf("app.tags")   # JSON 后端 → ["a", "b"]
conf("app.tags")   # .env 后端 → "['a', 'b']"
```

#### 4. 载体的显式类型标签被尊重

YAML 的 `!!str "8080"` 读回字符串 `"8080"`：标签由 `yaml.safe_load_all` 解析（`src/onconf/_yaml_backend.py:144-154`），引擎原样交出。词表侧不再输出 `type`（ISSUE-027），两处不冲突。

#### 5. `.env` 的 dict / list 由两个布尔开关显式开启

| 方向 | 行为 |
|---|---|
| 开关默认 | `env_file_dict` / `env_file_list` 默认 `False`，即默认不支持 |
| 写 | dict / list 序列化成字符串写进 `.env`（`render()` 现只接受 `str`，`src/onconf/_env_backend.py:104-110`） |
| 读 | 只有值形如 `{...}` / `[...]` 才尝试解回，且只有解出 `dict` / `list` 才采用 |
| 解不回 | 返回原字符串，不报错 |

解回范围限定在 `dict` / `list` 两种结构：`PORT=8080` 仍是 `"8080"`，`FLAG=true` 仍是 `"true"`，`NAME=null` 仍是 `"null"`。编码方式与转义边界见 ISSUE-028。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_core.py:130-148` | 读取路径现状即目标行为，保留；docstring 的引用改为实际行为 |
| `src/onconf/_core.py:11` | 模块 docstring 删掉 §18.3「推断 → 比对 → 转换」条目 |
| `src/onconf/__init__.py:44-55` | `EngineParams` 新增 `env_file_dict` / `env_file_list`（`bool`，默认 `False`），见 ISSUE-003 |
| `src/onconf/_env_backend.py:104-110` | `render()` 在开关开启时接受 `dict` / `list` 并序列化成字符串 |
| `src/onconf/_env_backend.py:167-172` | `loads()` 在开关开启时对 `{...}` / `[...]` 形态尝试解回，只采用 `dict` / `list` |
| `src/onconf/_engine.py:273-276` | 后端分派把开关传给 `.env` 后端 |
| `DESIGN.md:1015,1050,1026-1052,1179` | §18.2 ④、§15.4 引用、§18.3 整节、§10/M1 改为「引擎不转换」 |
| `README.md:141-143`、`README.zh-CN.md` | 补跨后端类型差异与 `.env` 结构开关的后果 |
| `docs/api/index.md:18-19` | 第 2 条语义改写为「返回值取载体原生类型」 |
| `tests/` | 补「跨后端同键不同类型」与「`.env` 结构开关往返 / 解不回回落字符串」的回归 |

### 验收标准

- [ ] 四个后端各有一组往返测试，断言返回值等于载体原生类型
- [ ] `.env` 开关关闭时 `PORT=8080` 读回 `"8080"`，不变成 `int`
- [ ] 开关开启后 dict / list 往返成功；解不回时返回原字符串且不报错
- [ ] 标量不被解回：`8080` / `true` / `null` 在开关开启时仍是字符串
- [ ] 同一键在 JSON 与 `.env` 上读回不同类型，有显式用例并在 README 写明
- [ ] YAML `!!str "8080"` 读回字符串，有回归测试
- [ ] `README.md` 与 `README.zh-CN.md` 同步

---

## 3. 配置口 `AutoConf` 重新设计（原 ISSUE-003）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P0 / 部分已定 |
| 原依赖 | ISSUE-001 / ISSUE-002（使用口形态）、ISSUE-005（日志两通道、审计开关取消）、ISSUE-008（多文件）、ISSUE-026（开关产物处置）、ISSUE-027（类型声明移除） |
| 原影响面 | `src/onconf/__init__.py`、`src/onconf/_engine.py`、`src/onconf/_audit.py`、`src/onconf/_vocab.py`、`tests/test_security_invariants.py`、`docs/security/threat-model.md`、`README.md`、`README.zh-CN.md`、`docs/api/index.md`、`docs/roadmap.md`、`.gitignore`、`DESIGN.md` §9.1/§15.3 |
| 原标签 | `area:api`、`area:security`、`breaking` |

### 背景

- `EngineParams` 只有五个字段（`src/onconf/__init__.py:44-55`），而 `Engine.__init__` 还接受 `lock_timeout`（`src/onconf/_engine.py:247-256`）；运行时校验按 `EngineParams.__annotations__` 做（`__init__.py:82-87`），于是 `AutoConf(lock_timeout=30)` 抛 `UnknownEngineParamError` —— 该参数对公开 API 完全不可达。
- 值文件按存在性从写死的五个候选名里挑第一个（`src/onconf/_engine.py:201-207,215-220`），文件名主干固定为 `settings`（`_engine.py:117`），类型由后缀反推且只认白名单里的后缀（`_engine.py:273-276`）：调用方无法指名用哪个文件。
- `home` 缺省落到当前目录（`_engine.py:210-212`），与 §9.1 的 `./conf` 不一致（`DESIGN.md:278-281`）。
- 引擎起来后带参调用 `AutoConf(...)` 抛 `ConfError`（`__init__.py:99-104`），而 §15.3 把运行中改配置定性为「单例可变的必需品」（`DESIGN.md:684-702`）。
- 「文件名可配置」与现有安全不变量正面冲突：测试断言值文件路径只来自固定白名单（`tests/test_security_invariants.py:14,42-45,113-119`）。

不可接受之处：用哪个文件、哪种类型、审计去哪个位置、日志刷哪些级别，全部由引擎按约定猜；这些默认行为一个都不能显式声明。

### 结论

总原则：**凡是引擎的默认行为，都必须是一个能显式声明、能覆盖、能关闭的参数。** `DESIGN.md:278-281`（§9.1）把「隐式约定」当作换取「轻」的取舍，该定性作废。参数面按性质分四组，取代当前混装的一串。

#### 1. A 组：能力开关

| 参数 | 默认 | 语义 |
|---|---|---|
| `env_file_dict` / `env_file_list` | `False` | `.env` 后端是否参与 dict / list 的写入与解回（ISSUE-002） |
| 终端日志开关 | 开 | 关闭只影响终端那份，文件通道强制（ISSUE-005） |

- 词表不在开关之列：它是锁死的核心数据结构（`DESIGN.md:38`），「关掉词表」这个选项不存在。
- `audit` 开关取消：审计文件恒写，路径改为独立参数、默认 `<home>/audit.log`（ISSUE-005 §3）。
- 开关关闭 = 该能力完全不参与；关闭后已有产物的处置见 ISSUE-026。

#### 2. B / C 组：文件与路径信息

声明粒度是**目录 + 名称 + 类型**，路径由三者派生；多文件用键内嵌路径表达（例：`conf("app/conf/net:net.id.post")`），不新增路径参数（ISSUE-008）。

```text
目录      <home>                  ← 参数
文件路径  <home>/<name><ext>      ← 派生
文件名称  <name>                  ← 参数（多文件时内嵌在键里）
文件类型  file_type = ""          ← 参数：单值，决定实际使用的配置文件
```

`file_type` 一次只有一个类型；`_pick_values_file` 的「按存在性挑第一个」退役（`src/onconf/_engine.py:215-220`）。

#### 3. D 组：日志、审计与落盘

| 组 | 可配内容 |
|---|---|
| 终端 | 开 / 关；按级别词筛选（只刷 `Change` / 只刷 `Write` / 全刷） |
| 文件 | 强制，不可关；永远全量 |
| 落盘形式 | 明文（默认）/ 纯二进制 / 二进制加密 / 明文加密 |
| 加密 | 是否加密、算法由调用方指定；密钥由调用方提供，缺失且必需时抛异常，引擎不生成、不推导、不保管 |
| 轮转 | 落盘规则 / 触发方式 / 轮转方式三组参数 |

库不发起网络请求、不收函数式 sink，职责到「产出数据」为止（ISSUE-005）。

#### 4. 引导层与值层分开

引导层（`home`、`file_type`、落盘形式、加密、`lock_timeout`）不可运行中改，改了必须重启；值层每次从文件重新读取。`DESIGN.md:684-702`（§15.3「必需品」）作废，`docs/roadmap.md:39` 改为判定不做；`src/onconf/__init__.py:99-104` 抛 `ConfError` 的行为保留，理由改为「按设计不支持」。

#### 5. 其余收敛

- `home` 缺省从 `.` 改为 `./conf`。
- `lock_timeout` 补进 `EngineParams`，行为不变。
- `conf(..., **engine)` 从使用口摘除（`src/onconf/__init__.py:115,130`，见 ISSUE-001）。
- `AutoConf()` 无参调用保留「取回单例」语义并写进文档；「两个面」的说法与 `__all__` 对齐（`src/onconf/__init__.py:31-41`，异常族保持从顶层可导入）。
- 安全手段替换：固定白名单 → 包含性校验，约束为纯文件名、无路径分隔符、无 `..`、拒绝绝对路径、解析后仍在 `<home>` 之内；`docs/security/threat-model.md` 的 T1 与 `tests/test_security_invariants.py:113-119,140-147` 同步改写。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/__init__.py:44-55` | `EngineParams` 按四组重构，新增 `file_type` / `env_file_dict` / `env_file_list` / 日志参数，补 `lock_timeout`，删 `audit` |
| `src/onconf/__init__.py:31-41,82-87` | `__all__` 与「两个面」对齐；校验集合与 `Engine.__init__` 形参集合逐项一致 |
| `src/onconf/__init__.py:99-105` | 引导层不可运行中改；`ConfError` 理由改写 |
| `src/onconf/__init__.py:108-116,130` | 摘掉 `conf` 的 `**engine` |
| `src/onconf/_engine.py:117,201-207,215-220,273-276` | 值文件选定改为 `file_type` + 名称显式声明；候选名单退役 |
| `src/onconf/_engine.py:210-212` | `home` 缺省改为 `./conf` |
| `src/onconf/_engine.py:253,267-271` | `lock_timeout` 可见性；`AuditLog` 构造改为恒定写 + 独立路径参数 |
| `tests/test_security_invariants.py:14,42-45,113-119,140-147` | 白名单断言 → 包含性校验，新增路径穿越回归 |
| `docs/security/threat-model.md` | T1 与不变量表同步（单独提交说明） |
| `README.md:123-150`、`README.zh-CN.md` | 两个面与参数说明改写（两者是一对） |
| `docs/api/index.md:11,25-28` | 参数表与公开符号自述 |
| `docs/roadmap.md:39`、`DESIGN.md:278-281,684-702` | 状态行与两处定性改写 |
| `.gitignore:80-90` | 按 `home` 新缺省收窄兜底 |

### 验收标准

- [ ] `AutoConf(lock_timeout=30)` 不再抛 `UnknownEngineParamError`；`EngineParams` 注解与 `Engine.__init__` 形参一一对应，有测试
- [ ] `file_type` 决定使用的后端；`_VALUES_CANDIDATES` 与 `_pick_values_file` 不再参与选定
- [ ] `home` 缺省为 `./conf`，有测试
- [ ] `conf(..., home=…)` 抛 `TypeError`，使用口无法配置引擎
- [ ] 引擎起来后带参调用 `AutoConf(...)` 抛 `ConfError`，文档理由为「引导层不可运行中改」
- [ ] 路径穿越回归：含分隔符、含 `..`、绝对路径、解析后越出 `<home>` 的文件名逐个被拒绝
- [ ] 安全不变量与威胁模型同步，且在提交里单独说明
- [ ] `README.md` 与 `README.zh-CN.md` 同步；`docs/api/index.md` 参数表与新签名一致

### 未决事项

| 未定项 | 候选 | 代价 |
|---|---|---|
| `file_type = ""` 空值的语义 | (a) 空串表示「按存在性从候选名挑第一个」，保持现状 | 文件选定仍是隐式行为，与本项总原则直接冲突 |
| 同上 | (b) 空串表示默认使用 JSON | 需在 `pyyaml` 与 `json` 之间指定主后端；TOML / `.env` 用户必须显式声明 `file_type`；与「以 JSON 为主」的定位陈述（`_engine.py:201-207` 把 YAML 排第一）联动，见 ISSUE-054 |
| `$schema` 指针注入是否随 `file_type` 参数化 | (a) 保持按载体能力：只有 `.json` / `.yaml` / `.yml` 能放成员（`src/onconf/_engine.py:196-199`） | `.toml` / `.env` 用户既拿不到编辑器指针，也无法声明要或不要 |
| 同上 | (b) 变成能声明、能关闭的参数 | `EngineParams` 再多一个开关，且在 `.env` / `.toml` 上打开它没有落脚点 |
| 覆盖既存值的出口（配置口动词面）的名称与形态 | (a) `AutoConf` 上的方法，如 `engine.overwrite(key, value)` | 方法名、返回值、与 `conf` 声明元数据的登记关系要逐个定义；`AutoConf` 从参数类型变成带状态的对象 |
| 同上 | (b) `conf` 上保留一个显式透传参数 | 与「`force=` 离开 `conf`」的裁定相反，温和面上再开一个洞 |
| 同上 | (c) 不给出口 | `DESIGN.md:862-874`（§17.6）列出的「程序想持久化一个值」场景被整类砍掉 |

---

## 4. `type=` 移除后「类型声明」的连带清理（原 ISSUE-027）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P1 / 已定稿，待实现 |
| 原依赖 | ISSUE-001（`conf` 参数面收敛）、ISSUE-002（返回值口径） |
| 原影响面 | `src/onconf/_core.py`、`src/onconf/_vocab.py`、`src/onconf/_engine.py`、`src/onconf/errors.py`、`src/onconf/__init__.py`、`tests/test_vocab.py`、`tests/`、`README.md`、`README.zh-CN.md`、`docs/api/index.md` |
| 原标签 | `area:api`、`area:vocab`、`breaking` |

### 背景

- `type=` 是 `conf` 的公开参数（`src/onconf/__init__.py:113`），当前只在声明期做一致性校验（`src/onconf/_engine.py:364-381`），读取期完全不参与。
- 类型同时被写进三处持久状态：`Decl.type`（`src/onconf/_core.py:76`）与 `VocabEntry.type`（`_core.py:88`）、JSON Schema 的 `type` 与 `x-onconf-py`（`src/onconf/_vocab.py:36,151-174`）、声明集哈希（`_core.py:276-277,290-300`）；`_meta_stale` 也比较类型（`_core.py:171-178`）。
- 使用口已经按「载体能表达什么就返回什么」定义返回值（ISSUE-002），而 `type=` 的存在暗示引擎会校验或转换；README 关于类型的两处（`README.md:44`、`README.md:141-146`）与 `docs/api/index.md:18-21` 表述互不一致。
- `type=` 与三模式矩阵无关：`conf(key, type=int)` 是判据里多出来的合取项所放行的形态（`src/onconf/_engine.py:326`）。

不可接受之处：类型声明只制造一份必须与文件内容保持同步的额外状态，而它在读写语义上没有任何作用。

### 结论

1. `type=` 彻底删除：`conf` 不再接受该参数（ISSUE-001），`Decl` 与 `VocabEntry` 不再有 `type` 字段。
2. 词表退化为「**键 + 说明 + 默认值**」；JSON Schema 输出不再写 `type`，`x-onconf-py` 扩展一并作废（`src/onconf/_vocab.py:36,155-165`）。
3. `TypeConflictError` 无家可归，随本项作废并从 `src/onconf/errors.py:24` 与 `src/onconf/__init__.py:26,38` 移除；其余异常族继续从顶层可导入。
4. 类型不再参与任何持久状态：声明集哈希不再编码类型（`src/onconf/_core.py:290-300`），`_meta_stale` 只比较说明与默认值（`_core.py:171-178`）。
5. 声明期校验整体消失：取值类型由载体决定（ISSUE-002），要转换在使用处显式写 `int(conf("PORT"))`。
6. 词表的跨后端类型差异字段不因此新增：词表本就不记录「这个键在 `.env` 上只可能是字符串」（ISSUE-002 §3）。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/__init__.py:108-116` | 签名删 `type=` |
| `src/onconf/__init__.py:26,38` | `__all__` 与导入里删 `TypeConflictError` |
| `src/onconf/errors.py:24` | 删除 `TypeConflictError` |
| `src/onconf/_core.py:71-90` | `Decl.type` 与 `VocabEntry.type` 字段删除 |
| `src/onconf/_core.py:171-178` | `_meta_stale` 只比 `doc` 与默认值 |
| `src/onconf/_core.py:276-277,290-300` | 删除 `_type_name`；哈希载荷不再含类型 |
| `src/onconf/_vocab.py:36,63-79,155-165,176-188` | 删除 `PY_TYPE_KEY`、`type_to_json` / `type_from_json` 与 `type` 映射表；Schema 往返只保留 `description` / `default` |
| `src/onconf/_engine.py:301-328,353-381` | `__call__` / `declare` 删 `type` 形参与类型校验分支；`_type_matches` 删除 |
| `docs/api/index.md:12,18-21` | 签名与第 2、3 条语义改写 |
| `README.md:44,141-146,168`、`README.zh-CN.md` | 删「declare keys and their types」与 `TypeConflictError` 的说明 |
| `tests/test_vocab.py:96-103` | `x-onconf-py` 用例删除，替换为「Schema 不含类型字段」的断言 |
| `tests/` | 类型冲突用例删除；补「`type=` 抛 `TypeError`」与「Schema 往返无类型字段」 |

### 验收标准

- [ ] `conf(key, type=int)` 抛 `TypeError`，有回归测试
- [ ] 词表输出的 JSON Schema 不含 `type` 与 `x-onconf-py` 字段
- [ ] 无类型字段的 Schema 往返（写出 → 读回）后词表逐项相等
- [ ] 同一声明两次调用的声明集哈希一致，且哈希不受类型影响
- [ ] `TypeConflictError` 不再从 `onconf` 导出；`README.md`、`docs/api/index.md` 不再提及
- [ ] `README.md` 与 `README.zh-CN.md` 同步

---

## 5. 「本质上以 JSON 为主」的定位连带（原 ISSUE-054）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P2 / 待决策 |
| 原依赖 | ISSUE-003（`file_type` 是单值参数，决定实际使用的配置文件类型） |
| 原影响面 | `src/onconf/_engine.py:201-220`、`src/onconf/__init__.py:44-55`、`README.md`、`README.zh-CN.md`、`docs/api/index.md`、四个后端 |
| 原标签 | `area:engine`、`area:docs` |

### 背景

- 「本质上以 JSON 为主」是一条定位陈述。现状与它不一致之处有三。
- `file_type` 尚不存在：`EngineParams` 只有 `home` / `audit` / `flush_window` / `log` / `identity`（`src/onconf/__init__.py:44-55`），实际使用的值文件类型由后缀与存在性决定。
- 值文件的选定是「按存在性挑第一个」，且 YAML 排在第一位：`_VALUES_CANDIDATES` 的顺序为 `settings.yaml` / `settings.yml` / `settings.json` / `settings.toml` / `settings.env`（`src/onconf/_engine.py:201-207`），`_pick_values_file` 取白名单里第一个存在的文件，全都不存在时才落到 `settings.json`（`src/onconf/_engine.py:215-220`）。
- 文档把四个后端并列为对等能力：README 的定位句与特性表都写「many backends」（`README.md:48-49`、`:156-159`），没有主 / 辅标注；README 中也没有 `file_type` 的匹配。
- ISSUE-003 已定：`file_type` 是单值参数，决定实际使用的配置文件类型，不能同时出现多个类型（ISSUE-008 §4.2 给出了后缀派生规则）。

### 结论

1. 定位陈述成文：引擎以 JSON 为主要值文件格式，其余后端是可选后端，不是并列默认。
2. `file_type` 是单值参数，取值决定实际使用的配置文件类型与后缀；缺省值要与「以 JSON 为主」这一定位一致（具体取值见未决事项）。
3. `_VALUES_CANDIDATES` 的「按存在性挑第一个」取消：它把「哪个文件生效」交给磁盘上恰好有什么，属于隐式约定（总原则见 ISSUE-003：凡是引擎的默认行为，都必须能显式声明、覆盖或关闭）。`_pick_values_file` 随之退役，与 ISSUE-008 的处置一致。
4. YAML 不再排在候选序列第一位；候选顺序不再参与判定。
5. 文档必须标注主 / 辅后端：README 一对的定位句与特性表、`docs/api/index.md` 的参数表都要写明 JSON 是主要格式，其余后端为可选。
6. 后端的能力差异不因定位而消失：`.env` 是字符串后端（`src/onconf/_env_backend.py:5-13`）、TOML 没有 `null`（`src/onconf/_toml_backend.py:27`）、`$schema` 指针只在能吃下成员的后端可用（`src/onconf/_engine.py:196-199`），这些差异继续逐条写在文档里。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/__init__.py:44-55` | `EngineParams` 新增 `file_type`，单值 |
| `src/onconf/_engine.py:201-220` | `_VALUES_CANDIDATES` 与 `_pick_values_file` 退役；值文件由 `file_type` 派生 |
| `README.md:48-49,156-159`、`README.zh-CN.md` | 定位句与特性表标注主 / 辅后端（两者是一对） |
| `docs/api/index.md` | 参数表补 `file_type` |
| `tests/` | 值文件选定由 `file_type` 决定；缺省值与文档声明一致 |
| `DESIGN.md` §28.4（`:1779-1784`） | 后端对等表述与本项定位一致 |

### 验收标准

- [ ] `EngineParams` 含 `file_type`，单值，取值与四个后端的后缀一一对应
- [ ] 值文件选定不再依赖「文件是否存在」，`_VALUES_CANDIDATES` 与 `_pick_values_file` 退役
- [ ] `file_type` 缺省时选中的文件与文档声明一致，且有用例覆盖既有 `settings.yaml` 存在的情形
- [ ] `README.md` 与 `README.zh-CN.md` 都标注主 / 辅后端并逐条对齐
- [ ] `docs/api/index.md` 补 `file_type` 条目
- [ ] 文档同步（`docs/` 未同步视为未完成）

### 未决事项

1. `file_type` 的缺省值：候选 (a) `"json"`；(b) 空串，由后缀白名单推导。代价：(a) 与定位一致，但改变既有行为（当前目录里只有 `settings.yaml` 时选中的是 YAML）；(b) 保留「按存在性挑第一个」的隐式行为，与总原则冲突。
2. 「以 JSON 为主」是否附带能力优先级：候选 (a) 仅作为缺省值与文档标注；(b) JSON 后端在文档与检查中具有主后端地位（例如 `$schema` 指针、注释能力的表述按主后端组织）。代价：(a) 改动最小，主 / 辅差别只在文档与缺省值；(b) 需要逐项定义「主」意味着什么。
3. 主 / 辅标注的措辞与落点：README 定位句、特性表、`docs/api/index.md` 三处如何分工，以及与多文件章节（ISSUE-008）的表述如何对齐。

