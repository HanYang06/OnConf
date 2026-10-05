# D03 求值来源、键名与词表形态

| 项 | 值 |
|---|---|
| 类型 | 设计变更（breaking） |
| 优先级 | P1 |
| 状态 | 待决策（取最不确定成员）、ISSUE-009（部分已定）） |
| 成员状态 | 待决策 1 / 部分已定 1 —— 未定稿：ISSUE-007（待决策）、ISSUE-009（部分已定） |
| 前置 | D01 |
| 联动 | D02、D04 |
| 覆盖原编号 | ISSUE-007、ISSUE-009 |
| 影响面 | `src/onconf/_core.py`、`src/onconf/_engine.py`、`src/onconf/_env_backend.py`、`tests/`、`README.md`、`README.zh-CN.md`、`docs/roadmap.md`、`docs/security/threat-model.md`、`DESIGN.md` §3.1/§3.2/§4、`src/onconf/_vocab.py`、`tests/test_vocab.py`、`DESIGN.md` §3.1–§3.4/§27.1 |
| 标签 | `area:core`、`area:backend`、`breaking`、`area:vocab`、`breaking` |

## 0. 本决策的整体口径

求值链路有几层、键名在各载体上怎么落，是同一件事的两个方向。

- 设计稿承诺的第三层（系统环境变量）从未实现，也没有一处标注它被删除（原 ISSUE-007）；
- 键名映射（`.` ↔ `_`、大小写归一化）的用处取决于环境变量层是否补齐：补齐则有两个消费者，删除则只剩 `.env`（原 ISSUE-009）；
- 词表形态与「只输出一份 JSON Schema」的冲突一并在此收口（原 ISSUE-009）。

两条必须一起裁，否则键名映射会被迫改两次。

### 0.1 成员索引

| 原编号 | 本文件 | 一句话 |
|---|---|---|
| ISSUE-007 | §1 | 环境变量层删除还是补齐：删除则求值只有文件与词表两层，补齐则新增一个会盖过文件的默认来源（未定） |
| ISSUE-009 | §2 | 词表退化为「键 + 说明 + 默认值」；键名映射与按格式分档的取舍 |

> 本文档内的 `ISSUE-NNN` 是**原始编号**。同一 `D` 单元内的编号都在本文件里，完整编号映射见 `README.md`。

---

## 1. 环境变量层：删除还是补齐（原 ISSUE-007）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P1 / 待决策 |
| 原依赖 | ISSUE-009（键名映射与大小写归一化）、ISSUE-003（`EngineParams` 参数面） |
| 原影响面 | `src/onconf/_core.py`、`src/onconf/_engine.py`、`src/onconf/_env_backend.py`、`tests/`、`README.md`、`README.zh-CN.md`、`docs/roadmap.md`、`docs/security/threat-model.md`、`DESIGN.md` §3.1/§3.2/§4 |
| 原标签 | `area:core`、`area:backend`、`breaking` |

### 背景

- `DESIGN.md:95-102`（§4）把求值链路定为四层：词表 → 配置文件 → **环境变量（运行时覆盖，12-factor）** → 代码不参与；「无参数配置」的定义也写成「词表里有这个键，但文件与环境都没有」（`DESIGN.md:104`）。
- 实现只有两层：`src/onconf/_core.py:140-148` 命中事实就原样返回，否则取词表 `default`，没有第三个来源。
- `ONCONF_HOME` 只用于定位配置目录（`src/onconf/_engine.py:116,210-212`）；`.env` 后端读的是 `settings.env` 文件（`src/onconf/_env_backend.py:167-172`，后端分派见 `src/onconf/_engine.py:188-194`），从不读 `os.environ`。
- 状态声明按「未实现」登记：`README.md:182`、`docs/roadmap.md:52`。

不可接受之处：设计稿承诺的第三层从未实现，也没有一处标注它被删除；按设计稿设置环境变量覆盖值文件不会生效。

### 结论

1. **命名必须拆开**。「环境变量后端」在协作文档里是 `.env` 后端与系统环境变量后端的合称（`AGENTS.md:121`、`CONTRIBUTING.md:92`），设计稿也把「系统环境变量」列为一种后端格式（`DESIGN.md:26,49,84`），而 README 只把 `.env` 后端写成字符串后端（`README.md:158`）。两者是两件事：前者读 `settings.env`（`src/onconf/_env_backend.py:167-172`），后者读 `os.environ`，实现里不存在。
2. **层数只有一种表述**。`DESIGN.md:95-109`（§4）与 README 中的求值链路层数必须与 `src/onconf/_core.py:140-148` 的实际路径一致，不允许文档四层、实现两层并存。
3. **若补齐，读取 `os.environ` 必须是显式声明的开关**；键名映射（`.` ↔ `_`）与大小写归一化归 ISSUE-009，依据是 `DESIGN.md:56-60`（§3.2）与 `DESIGN.md:44-47`（§3.1 KeyCodec）。
4. `ONCONF_HOME` 的定位不变：它只决定配置目录，不是配置源（`src/onconf/_engine.py:116,210-212`）。
5. 源与值的优先级（环境变量与值文件谁覆盖谁）必须在定案时一并写死，不允许留成实现细节。

### 变更项

| 位置 | 改动 |
|---|---|
| `DESIGN.md:95-109`（§4） | 求值链路层数与「无参数配置」定义改为与最终取舍一致 |
| `src/onconf/_core.py:140-148` | 补齐分支：插入环境变量来源与优先级；删除分支：保持两层并在 docstring 写明「只有文件与词表两个来源」 |
| `src/onconf/_env_backend.py:3,167-172` | 模块 docstring 与名称表述改为「`.env` 文件后端」 |
| `src/onconf/_engine.py:116,210-212` | 补齐分支：新增环境变量源开关；删除分支：说明 `ONCONF_HOME` 只用于定位 |
| `README.md:158,182`、`README.zh-CN.md:175` | `.env` 后端说明与 Roadmap 行同步（两者是一对） |
| `docs/roadmap.md:52,63`、`docs/architecture/index.md:39`、`docs/index.md:63` | 同上 |
| `AGENTS.md:121`、`CONTRIBUTING.md:92` | 后端称谓拆分为「`.env` 文件后端」与「系统环境变量源」 |
| `docs/security/threat-model.md` | 补齐分支：环境变量值进入求值链路后的信任边界说明 |
| `tests/` | 两种走法各自都要有「环境变量存在但不生效 / 生效」的用例 |

### 验收标准

- [ ] `DESIGN.md` §4 的每一层都在 `src/onconf/_core.py` 的读取路径里有对应实现或明确标注「不做」
- [ ] 「环境变量后端」这一名称在 `src/`、`docs/`、`README.md`、`README.zh-CN.md` 中不再指代 `.env` 文件后端
- [ ] 删除分支：`DESIGN.md:104` 的「无参数配置」定义只提文件与词表；README 不再暗示环境变量覆盖
- [ ] 补齐分支：`os.environ` 读取有开关，未声明时不参与求值；大小写归一化与键名映射有测试
- [ ] `README.md` 与 `README.zh-CN.md` 同步

### 未决事项

#### 1. 该层是删除还是补齐

| 候选 | 规格后果 | 代价 |
|---|---|---|
| (a) 删除该层 | §4 的第三层从求值链路消失；「无参数配置」= 词表有键、文件没有值 | 容器 / CI 里用环境变量覆盖值文件的 12-factor 用法没有出口；「环境变量后端」这个误称要连带改名 |
| (b) 补齐该层 | 求值链路变成三层：值文件 → 环境变量 → 词表默认值 | 与「文件绝对优先、代码不权威」的定位（`README.md:44-45`）冲突 —— 环境变量会盖过文件；Windows 上环境变量大小写不敏感，必须归一化；新增一个默认生效的来源，除非它本身也是开关 |

#### 2. 补齐时的键名口径

| 候选 | 代价 |
|---|---|
| (a) 逻辑键与 `os.environ` 键同名，不做映射 | `app.server.port` 在环境里无法表示，实际只剩 `.env` 那一份可用 |
| (b) 按 `DESIGN.md:56-60` 的显式映射表 + 未声明键默认规则 | 映射表成为第二份键名权威，且与 ISSUE-009 的分档结论强耦合 |

---

## 2. 词表形态、键名映射、按格式分档（原 ISSUE-009）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P1 / 部分已定 |
| 原依赖 | ISSUE-003（`file_type` 与参数面）、ISSUE-027（类型声明移除）、ISSUE-007（环境变量层） |
| 原影响面 | `src/onconf/_vocab.py`、`src/onconf/_core.py`、`src/onconf/_env_backend.py`、`tests/test_vocab.py`、`README.md`、`README.zh-CN.md`、`docs/roadmap.md`、`DESIGN.md` §3.1–§3.4/§27.1 |
| 原标签 | `area:vocab`、`breaking` |

### 背景

- §3.3 设计的词表项含 `type / default / origin / physical / writable`（`DESIGN.md:64-74`）；实现只有 `key / type / doc / default`（`src/onconf/_core.py:82-90`），`origin` 只出现在读结果里（`_core.py:93-98`），`physical` / `writable` 不存在。
- §3.1 与 §3.2 要求每个后端有 KeyCodec 把统一键翻译成物理形态，并对不可逆映射保存显式映射表（`DESIGN.md:44-47,56-60`）；实现里 `.env` 后端按字面精确匹配（`src/onconf/_env_backend.py:20-21,155-159`）：`pack.max.byte=1` 与 `PACK_MAX_BYTE=1` 是两个不同的键，README 把「不做键名转换」写成了既有能力（`README.md:158`）。
- §3.4 要求词表按格式分档（`.env` 只给扁平键清单，`DESIGN.md:76-86`）；实现只产出一份 JSON Schema（`src/onconf/_vocab.py:151-174`），状态登记为未实现（`README.md:183`、`docs/roadmap.md:53`），§27.1 又定「永远只输出一份 JSON Schema」（`DESIGN.md:1680`）。

不可接受之处：同一件事在 §3.3 / §3.4 与 §27.1 有两套表述；键名映射这一层在文档与实现里都不存在，`.env` 键名与系统环境变量键名之间没有可互通的口径。

### 结论

1. 词表是锁死的核心数据结构，不是可关的能力开关（`DESIGN.md:38`）；「关掉词表」这个选项不存在。
2. 类型字段随 ISSUE-027 移除：`VocabEntry.type`（`src/onconf/_core.py:88`）、JSON Schema 的 `type` 字段与 `x-onconf-py`（`src/onconf/_vocab.py:36,151-174`）一并作废，形态收敛为「**键 + 说明 + 默认值**」。
3. 跨后端类型差异不写进词表（ISSUE-002 §3），只由 README 说明。
4. 词表落点与值文件绑定：`<home>/schema/<name>.json`（`src/onconf/_engine.py:259`）；值文件类型由 `file_type` 决定（ISSUE-003）。
5. `origin` 保留在读结果与日志里（`src/onconf/_core.py:93-98`），词表条目本身不记录它。
6. 词表永远产出，写入是提交点的一部分（`src/onconf/_engine.py:856-861`），没有「不生成词表」的配置。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_core.py:83-90` | `VocabEntry` 删 `type`，形态为 `key / doc / default` |
| `src/onconf/_vocab.py:36,63-79,155-165` | 删类型映射与 `x-onconf-py`；`to_schema` 只写 `description` / `default` |
| `src/onconf/_vocab.py:176-188` | `from_schema` 只读 `description` / `default` |
| `src/onconf/_env_backend.py:20-21,155-159` | 按未决事项的取舍，保留字面匹配或接入键名映射 |
| `DESIGN.md:44-47,56-60,62-74,76-86` | §3.1–§3.4 改写为最终形态 |
| `DESIGN.md:1680`（§27.1） | 与 §3.4 合并为一条表述 |
| `README.md:158,160,183`、`README.zh-CN.md` | `.env` 键名规则、词表说明、Roadmap 行同步 |
| `docs/roadmap.md:53` | 词表分档的当前状态改写 |
| `tests/test_vocab.py` | 形态与（若采纳）映射表的回归；Schema 往返断言更新 |

### 验收标准

- [ ] 词表条目的字段集合与 `VocabEntry` 定义逐项一致，Schema 往返后逐项相等
- [ ] `DESIGN.md` §3.1–§3.4 与 §27.1 对词表产物只有一种表述
- [ ] `.env` 键名规则在 README 与 `src/onconf/_env_backend.py` 的 docstring 中一致
- [ ] 若采用映射表：`.env` 中已声明键走映射、未声明键走默认规则，各有测试
- [ ] `README.md` 与 `README.zh-CN.md` 同步

### 未决事项

#### 1. 键名映射

| 候选 | 代价 |
|---|---|
| (a) 不做映射，物理键名 = 逻辑键名（`src/onconf/_env_backend.py:20-21`） | `.env` 里只能用带点的键名，与 12-factor 的 `PACK_MAX_BYTE` 风格不通；Windows 上大小写不敏感没有归一化交代，同一个键可能出现两个名字 |
| (b) 恢复 §3.2 的显式映射表 + 未声明键默认规则 + 大小写归一化 | 词表结构扩一次，映射表成为第二份键名权威；必须与 ISSUE-007 的取舍联动 —— 环境变量层若不存在，`physical` 的用处只剩 `.env` 文件 |

#### 2. 按格式分档

| 候选 | 代价 |
|---|---|
| (a) 只输出一份 JSON Schema（`DESIGN.md:1680`） | `.env` 与 TOML 用户没有可指向的词表文件，§3.4 的档位落空 |
| (b) 恢复分档，`.env` 给扁平键清单 | 多套导出格式与多份产物，与 §27.1 冲突；`.env` 放不下 `$schema` 成员（`src/onconf/_engine.py:196-199`），指针无处可写 |

#### 3. 词表是否记录 `origin`

| 候选 | 代价 |
|---|---|
| (a) 不记录（现状，`src/onconf/_core.py:93-98`） | 词表不具自描述性，审计与调试只能靠日志 |
| (b) 记录进词表条目 | 读路径要回写词表，读从只读变成写，与「读不落盘」的现状冲突 |

