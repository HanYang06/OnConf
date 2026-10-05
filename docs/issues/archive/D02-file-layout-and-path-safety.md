# D02 值文件布局与路径安全

| 项 | 值 |
|---|---|
| 类型 | 设计变更（breaking） |
| 优先级 | P1 |
| 状态 | 部分已定（取最不确定成员）、ISSUE-024（部分已定）） |
| 成员状态 | 部分已定 2 —— 未定稿：ISSUE-008（部分已定）、ISSUE-024（部分已定） |
| 前置 | D01 |
| 联动 | D03、D05 |
| 覆盖原编号 | ISSUE-008、ISSUE-024 |
| 影响面 | `src/onconf/_engine.py`（值文件选定）、键解析层、`_json_backend.py` / `_yaml_backend.py` / `_env_backend.py` / `_toml_backend.py`、`tests/test_security_invariants.py`、`tests/test_engine.py`、`README.md`、`README.zh-CN.md`、`docs/api/index.md`、`DESIGN.md` §9 / §28、`src/onconf/_engine.py`、`docs/security/threat-model.md` T1 与不变量表 |
| 标签 | `area:files`、`area:security`、`breaking` |

## 0. 本决策的整体口径

多文件能力与安全不变量是同一次改动的两端，必须同提交落地。

- 键内嵌路径一旦允许（原 ISSUE-008），「值文件路径只来自固定白名单」这一手段就失效；
- 手段必须同时换成包含性校验：纯文件名、无分隔符、无 `..`、拒绝绝对路径、解析后仍在 `<home>` 之内（原 ISSUE-024）；
- 顺序颠倒就要改两遍安全断言与威胁模型 T1。

### 0.1 成员索引

| 原编号 | 本文件 | 一句话 |
|---|---|---|
| ISSUE-008 | §1 | `conf("app/conf/net:net.id.post")`，一个开关，后缀由 `file_type` 决定，关闭时键就是一个字节都不解析的字符串 |
| ISSUE-024 | §2 | 外部字符串到路径的唯一入口改为包含性校验；测试与威胁模型 T1 同步改写 |

> 本文档内的 `ISSUE-NNN` 是**原始编号**。同一 `D` 单元内的编号都在本文件里，完整编号映射见 `README.md`。

---

## 1. 多文件配置：键内嵌路径（原 ISSUE-008）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P1 / 部分已定 |
| 原依赖 | ISSUE-003（`file_type` 单值参数）、ISSUE-024（多文件开启时的包含性校验） |
| 原影响面 | `src/onconf/_engine.py`（值文件选定）、键解析层、`_json_backend.py` / `_yaml_backend.py` / `_env_backend.py` / `_toml_backend.py`、`tests/test_security_invariants.py`、`tests/test_engine.py`、`README.md`、`README.zh-CN.md`、`docs/api/index.md`、`DESIGN.md` §9 / §28 |
| 原标签 | `area:files` |

### 背景

- 一个引擎只有一个值文件，按固定白名单「取第一个存在的」（`src/onconf/_engine.py:201-207,215-220`）；文件名主干写死为 `settings`（`src/onconf/_engine.py:117`）。
- 没有多文件，也没有键内嵌路径的解析：值文件的顶层必须是单个映射，多文档被拒（`src/onconf/_yaml_backend.py:144-148`）。
- 键是扁平点分字面量，层级不进入键名（`DESIGN.md:1721-1731`，§28.1）；键名永不参与路径拼接（`tests/test_security_invariants.py:13`）。
- 「按存在性挑第一个」与「由后缀反推后端」都是隐式行为：调用方无法指名使用哪个文件、哪个类型（`src/onconf/_engine.py:215-220,273-276`）。

### 结论

#### 1. 语法

```text
conf("app/conf/net:net.id.post")

多文件 = 开启
├─ 文件： <home>/app/conf/net.<ext>
└─ 键：   net.id.post          （该文件内的扁平点分键）

多文件 = 关闭（默认）
└─ 键：   字符串 "app/conf/net:net.id.post"，一个字节都不解析
```

分隔符是 `:`：左侧是文件路径，右侧是该文件内的配置项。

#### 2. 判据只有一个开关

- 关闭（默认）⇒ 键就是字符串，`app/conf/net:net.id.post` 与任何普通键没有区别。
- 开启 ⇒ 才把左侧解析成文件路径。
- 这是纯增量能力：不开启时该特性不存在。

#### 3. 后缀由 `file_type` 决定

`file_type` 是单值参数，一次只有一个类型（见 ISSUE-003）；键里不写扩展名。

```text
file_type = "json"  ⇒  app/conf/net:net.id.post  ⇒  <home>/app/conf/net.json
file_type = "env"   ⇒  app/conf/net:net.id.post  ⇒  <home>/app/conf/net.env
```

同时只有一个类型，取代「按存在性挑第一个」的隐式行为（`src/onconf/_engine.py:215-220`）。

#### 4. 开启时必须做包含性校验

路径直接来自键字符串，`conf("../../etc/passwd:x")` 是直白的路径穿越；校验规则与实现落点见 ISSUE-024。关闭多文件时该规则不参与解析，键名穿越的行为级回归原样成立（`tests/test_security_invariants.py:122-150`）。

#### 5. 与「键永远扁平」的关系

层级发生在文件之间，文件内部的键仍扁平（`DESIGN.md:1721-1731`）。`.env` 后端同样可用：`:` 在解析阶段被吃掉，到达后端的是 `net.id.post`，落在 `.env` 键正则 `[A-Za-z_][A-Za-z0-9_.\-]*` 之内（`src/onconf/_env_backend.py:38-43`）。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_engine.py:201-220` | 值文件选定：白名单 + 存在性 → 单文件（默认）或多文件（开关 + 键内嵌路径解析） |
| `src/onconf/_engine.py:257-260` | 值文件、词表、锁的路径由所选文件派生 |
| 键解析层（`_core.py` 或新增模块） | `:` 切分 + 路径归一 + 包含性校验；多文件关闭时直通 |
| `src/onconf/_json_backend.py`、`_yaml_backend.py`、`_env_backend.py`、`_toml_backend.py` | 接收解析后的扁平键与已选定的文件 |
| `tests/test_security_invariants.py:113-150` | 多文件开启时走包含性校验；关闭时现有断言不变（与 ISSUE-024 合并） |
| `tests/test_engine.py` | 新增多文件寻址往返与未触及字节逐字不变的断言 |
| `DESIGN.md:282-286`（§9 第 6 问）、`:1721-1731`（§28.1） | 多文件同键优先级给出答案；补「层级发生在文件之间」 |
| `README.md` / `README.zh-CN.md`、`docs/api/index.md` | 语法与开关说明 |

### 验收标准

- [ ] 多文件关闭时，`conf("app/conf/net:net.id.post", v)` 与普通字符串键行为完全一致
- [ ] 多文件开启时，`conf("app/conf/net:net.id.post")` 读写 `<home>/app/conf/net.<ext>` 内的 `net.id.post`
- [ ] 回写后该文件未被触及的字节逐字不变（注释、缩进、键序）
- [ ] 多文件开启时含 `..` 的键与绝对路径键被拒绝，`<home>` 之外不产生任何文件
- [ ] `file_type` 为 `json` / `yaml` / `env` 时后缀与后端一致；一次只有一个类型
- [ ] `.env` 后端在多文件开启时可用
- [ ] `tests/test_security_invariants.py` 的路径穿越回归覆盖开启与关闭两种状态
- [ ] `README.md` 与 `README.zh-CN.md` 同步

### 未决事项

- **没有 `:` 的键在多文件开启时落到哪个文件**：候选 (a) 落到一个默认文件（名称待定），(b) 报错并要求多文件模式下键必须带路径，(c) 落到上次用过的文件。代价：(a) 决定多文件与单文件能否混用，需要固定默认文件名；(b) 语义最窄，但让「有键无路径」的既有调用全部不可用；(c) 引入跨调用状态。
- **Windows 的 `\` 是否认作分隔符**：候选 (a) 只认 `/`，`\` 是普通字符；(b) 两者都认。代价：(a) 跨平台不一致；(b) 行为一致，但需要在解析层统一折叠。现有回归同时覆盖两种写法（`tests/test_security_invariants.py:135`）。
- **多文件与单文件能否同时存在**：即开启多文件后，`<home>/settings.json` 是否仍在、还能否被寻址。
- **锁粒度**：候选「一目录一锁」与「一文件一锁」。前者最简单，后者并发更好但需要新的锁命名、清理与测试。
- **词表落点**：候选「一份总词表」与「每个值文件一份」。现状由值文件名主干派生（`src/onconf/_engine.py:259`），多文件之后该派生规则不再唯一。

---

## 2. 安全不变量：固定白名单 → 包含性校验（原 ISSUE-024）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更（breaking） / P1 / 部分已定 |
| 原依赖 | ISSUE-003（文件名与类型可配）、ISSUE-008（多文件键内嵌路径） |
| 原影响面 | `src/onconf/_engine.py`、键解析层、`tests/test_security_invariants.py`、`docs/security/threat-model.md` T1 与不变量表、`README.md`、`README.zh-CN.md` |
| 原标签 | `area:security`、`breaking` |

### 背景

- 现有手段是固定白名单：测试断言值文件名属于 5 个写死的名字、父目录等于 `home`、词表在 `schema/` 下（`tests/test_security_invariants.py:42-45,113-119`）。
- 该手段同时被声明为不变量本身（`tests/test_security_invariants.py:14`），并延伸到 `<home>` 首层路径白名单 `{"settings.json", "schema"}`（`tests/test_security_invariants.py:140-147`）。
- 威胁模型把 T1（键名路径穿越）判为「不适用」，依据就是值文件路径由白名单推导、键名不参与拼接（`docs/security/threat-model.md:77-85`）。
- 配置口要求文件名与类型可配（ISSUE-003），多文件要求路径内嵌在键字符串里（ISSUE-008）：两者都与白名单手段冲突。冲突的是手段，不是目的。

### 结论

#### 1. 目的与手段分离

目的是「键名不得把写入带出 `home` 之外」（威胁模型 T1，`docs/security/threat-model.md:77-85`）。手段不再是固定白名单，改为包含性校验。

#### 2. 新规则

任何由键或参数参与的文件名，必须同时满足：

1. 是纯文件名，不含目录分量；
2. 不含路径分隔符（`/` 与 `\`）；
3. 不含 `..`；
4. 不是绝对路径；
5. 解析后仍位于 `home` 之内。

#### 3. 适用范围

- 值文件的名称与类型（ISSUE-003 C 组）；
- 多文件开启时键内嵌路径的左侧（ISSUE-008）；
- 词表、锁与端点路径继续由值文件主干派生，不额外接受外部字符串（`src/onconf/_engine.py:259-260`）。

#### 4. 测试改写

`tests/test_security_invariants.py:113-119` 的白名单断言改为包含性校验回归；`:140-147` 的首层路径断言按解析结果重写；`:122-150` 的行为级穿越回归保留，并补多文件开启态。安全断言的每一次改动都要在提交说明中单独列出。

#### 5. 威胁模型同步

T1 的结论由「不适用（白名单）」改为「由包含性校验守护」（`docs/security/threat-model.md:77-85`）；不变量表与 README 的安全段同步（`docs/security/threat-model.md:299-306`、`README.md:214-222`）。

### 变更项

| 位置 | 改动 |
|---|---|
| 键解析 / 路径派生层 | 新增包含性校验，作为所有「外部字符串 → 路径」的唯一入口 |
| `src/onconf/_engine.py:257-260` | 值文件、词表、锁路径派生经过校验 |
| `tests/test_security_invariants.py:14` | 不变量陈述由「固定白名单」改为「包含性校验」 |
| `tests/test_security_invariants.py:42-45` | `_VALUES_WHITELIST` 退役 |
| `tests/test_security_invariants.py:113-119` | 改为包含性校验断言 |
| `tests/test_security_invariants.py:140-147` | 首层路径白名单按新规则重写 |
| `tests/test_security_invariants.py:122-150` | 行为级穿越回归保留，补多文件开启态 |
| `docs/security/threat-model.md:77-85,299-306` | T1 结论与不变量表改写 |
| `README.md:214-222`、`README.zh-CN.md` | 安全不变量清单同步 |

### 验收标准

- [ ] 纯文件名通过校验；含 `/`、含 `\`、含 `..`、绝对路径、解析后越出 `home` 的名称全部被拒绝
- [ ] 被拒绝时不产生任何文件，异常说明被拒原因
- [ ] 多文件关闭时键名穿越的行为级回归原样通过
- [ ] 多文件开启时同一回归按新校验通过
- [ ] `tests/test_security_invariants.py` 中不再有「值文件路径只来自固定白名单」这类陈述
- [ ] 威胁模型 T1 与本项结论一致；`README.md` 与 `README.zh-CN.md` 同步
- [ ] 安全断言的改动在提交说明中单独列出

### 未决事项

- **符号链接的处置**：候选 (a) 校验只做字符串与解析后包含性，不额外拒链；(b) 额外拒绝符号链接。代价：(a) 少一条检查，但链接指向 `home` 外时写入仍会落在外侧（现状是 `os.replace` 替换链接本身，见 `docs/security/threat-model.md:107-122`）；(b) 更严，但需要额外的 `lstat` 与对应回归。
- **已存在的非普通文件**（目录、设备文件等）是否一并拒绝：候选 (a) 只校验路径；(b) 同时要求目标不存在或是普通文件。代价：(b) 多一次 `stat`，并要定义「已存在但非普通」时的报错形态。

