# D09 命令细则：`format` / `add` / `remove` / `check`

| 项 | 值 |
|---|---|
| 类型 | 设计变更 / 任务 |
| 优先级 | P1 / P2 |
| 状态 | 待决策（取最不确定成员） |
| 成员状态 | 部分已定 3 / 待决策 1 —— 未定稿：ISSUE-045（部分已定）、ISSUE-046（待决策）、ISSUE-047（部分已定）、ISSUE-049（部分已定） |
| 前置 | D08 |
| 联动 | D05、D06 |
| 覆盖原编号 | ISSUE-045、ISSUE-046、ISSUE-047、ISSUE-049 |
| 影响面 | `src/onconf/_json_backend.py`、新增整文件重排路径、CLI `format`、`tests/`、`README.md`、`README.zh-CN.md`、`DESIGN.md` §8 / §11.4、新增代码生成路径、`src/onconf/__init__.py`、`docs/getting-started.md`、新增 CLI `remove`、四个后端的 `delete_key`、新增只读路径、`src/onconf/_engine.py`、`src/onconf/_audit.py`、`src/onconf/_lock.py`、README 一对 |
| 标签 | `area:cli`、`area:format`、`area:cli`、`area:codegen`、`area:cli`、`breaking`、`area:cli`、`area:audit`、`breaking` |

## 0. 本决策的整体口径

四个命令各自的行为边界，是 D08 命令表的下钻。放在一起才能看到那条横切线：**哪些命令写字节、哪些一个字节都不写**。

- `format` 只对 JSON 值文件生效，YAML / TOML / `.env` 一律不提供且不写字节（原 ISSUE-045）；
- `add` 生成 `conf.py`：已存在时的行为、幂等判据与头注释（原 ISSUE-046，未定）；
- `remove` 只改值文件，代码侧一律不碰；`--dry-run` 不写任何字节（原 ISSUE-047）；
- `check` 必须一个字节都不写，需要一条专门的只读路径（原 ISSUE-049）。

### 0.1 成员索引

| 原编号 | 本文件 | 一句话 |
|---|---|---|
| ISSUE-045 | §1 | `format` 只支持 JSON：其余后端缩进即语法或有注释负担 |
| ISSUE-046 | §2 | `add` 的幂等、落点与头注释；生成物不被 import 就不生效（未定） |
| ISSUE-047 | §3 | 单键删除只动文件；若键仍在代码里声明，下次 `build` 会写回来 |
| ISSUE-049 | §4 | `check` 走只读路径：不建目录、不写 audit.log、不重写词表 |

> 本文档内的 `ISSUE-NNN` 是**原始编号**。同一 `D` 单元内的编号都在本文件里，完整编号映射见 `README.md`。

---

## 1. `format` 只支持 JSON（原 ISSUE-045）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P1 / 部分已定 |
| 原依赖 | ISSUE-031（`format` 的命令形态与统一约定） |
| 原影响面 | `src/onconf/_json_backend.py`、新增整文件重排路径、CLI `format`、`tests/`、`README.md`、`README.zh-CN.md`、`DESIGN.md` §8 / §11.4 |
| 原标签 | `area:cli`、`area:format` |

### 背景

- `format` 需要「整文件重排」，而这个库的四个后端全是字节级外科手术，没有整文件重写这条路：`src/onconf/_json_backend.py:3-13`、`src/onconf/_yaml_backend.py:5-6`、`src/onconf/_env_backend.py:3`、`src/onconf/_toml_backend.py:3`。唯一使用 `yaml.safe_dump` 的地方是把**单个值**渲染成一行（`src/onconf/_yaml_backend.py:157-172`）。
- YAML 的缩进是**语法**而不是视觉：`DESIGN.md` §27.2（`:1682-1690`）与 §27.3（`:1692-1699`）说明 YAML 的 schema 指针活在注释里、层级靠缩进表达，丢注释等于破坏用户的编辑器补全。
- TOML 有行尾注释且写回必须保留它们（`src/onconf/_toml_backend.py:220,228`），而标准库 `tomllib` 只读、没有写回库（`src/onconf/_toml_backend.py:17-21,35`）。
- `.env` 后端是扁平且字符串化的（`src/onconf/_env_backend.py:5-13`），注释只认整行（`:17-19`），重排缩进没有可作用的结构。
- JSON 不支持注释（`DESIGN.md:371-375`），因此缩进重排不丢任何东西。

### 结论

1. `format` 只对 JSON 值文件生效；YAML / TOML / `.env` 一律不提供格式化。
2. 不带格式化参数时 `format` 不修改任何字节：默认状态是「能塞就塞」，命令不得顺手重排。
3. JSON 无注释，格式化等于**纯缩进重排**，零风险：既不丢注释，也不改变值的语义。
4. YAML 不支持：缩进决定层级，格式化是伪命题；其 schema 指针与用户注释必须逐字保留，而整文件重排正是唯一会碰它们的手段。
5. TOML 不支持：注释必须保留，而标准库只有读侧；自写写回等于新造一个 TOML CST，成本高于收益。
6. `.env` 不支持：结构扁平，格式化没有可表达的目标。
7. 连带不引入 `ruamel.yaml`，也不新造 CST：运行时依赖闭包维持 `pyyaml` + `rich`（`pyproject.toml:48-54`、`DESIGN.md:1346`）。
8. 实现是一条与外科手术式回写**并列**的独立路径：解析 → 重排缩进 → 写回，仅对 JSON 开放；四个后端现有的 `set_value` / `append_key` / `delete_key` 不变量不受影响。
9. 重排后必须保留 JSON 的 `$schema` 数据成员（`src/onconf/_engine.py:864-877`）与键序。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_json_backend.py` | 新增整文件重排路径（解析 → 缩进重排 → 写回），与现有字节区间替换分开 |
| 新增 CLI `format` | 只接受 JSON 值文件；其余后端以非 0 退出并说明原因 |
| `tests/` | JSON 重排后键集合、键序、值与 `$schema` 成员不变；其余后端不写字节 |
| `README.md` / `README.zh-CN.md` | 参数与命令说明标注「`format` 只支持 JSON」（两者是一对） |
| `docs/getting-started.md` | 命令说明 |
| `DESIGN.md` §8（`:263-270`）、§11.4（`:367-384`） | 依赖立场与注释能力的表述与本项一致 |
| `pyproject.toml:48-54` | 依赖清单不变（不新增 `ruamel.yaml`） |

### 验收标准

- [ ] JSON 值文件格式化后，键集合、键序、每个值的语义与 `$schema` 成员逐字等价，只有空白与缩进变化
- [ ] 不带格式化参数时 `format` 不打开写句柄，文件 mtime 与内容不变
- [ ] YAML / TOML / `.env` 值文件的 `format` 以非 0 退出，且不写任何字节
- [ ] 注释敏感的后端有回归：`format` 之后 YAML 的 schema 指针注释、TOML 的行尾注释仍在文件里
- [ ] 运行时依赖仍只有 `pyyaml` + `rich`
- [ ] 行为变更带测试；回写类改动另断言未触及字节逐字不变
- [ ] 文档同步（`docs/` 未同步视为未完成）

### 未决事项

1. 缩进宽度是否可配：候选 (a) 固定 2 空格；(b) 提供 `--indent N`。代价：(a) 少一个旋钮，但与用户既有缩进风格不同的文件会被改成 2 空格；(b) 多一个参数面，默认值仍要定。

---

## 2. `add` 生成 `conf.py`：已存在时的行为、幂等与头注释（原 ISSUE-046）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P2 / 待决策 |
| 原依赖 | ISSUE-031（`add` 的命令形态与统一约定） |
| 原影响面 | 新增代码生成路径、`src/onconf/__init__.py`、`tests/`、`README.md`、`README.zh-CN.md`、`docs/getting-started.md` |
| 原标签 | `area:cli`、`area:codegen` |

### 背景

- 仓库里没有任何代码生成路径：`src/onconf/` 不写 `.py` 文件，也没有 `conf.py` / `argparse` / `sys.argv` 的匹配。`add` 的「生成一个函数」是全新能力。
- `conf()` 的声明副作用发生在 import 期：`conf()` 经 `AutoConf(**engine)` 建立引擎并写盘（`src/onconf/__init__.py:130-133`、`src/onconf/_engine.py:353-395`），所以生成的 `conf.py` 一旦被 import 就会写盘。
- 生成的样板在不被 import 时完全不生效：仓库既有用法都要求显式 import（`README.md:84`、`README.zh-CN.md:80`）。
- ISSUE-031 已定：`add` 是**生成**新文件，不改写任何既有文件。本项收口生成物的三条行为与一条提示。

### 结论

1. `add` 的动作集合 = 新增键 + 登记词表 + 生成声明代码；生成物是新文件，不修改任何既有文件。
2. 生成物落点由 `--code-file PATH` 指定，缺省文件名为 `conf.py`。
3. 生成的函数只填入键、值与 `doc`，不含其它逻辑；是否生效取决于用户在自己的项目里 import 它，生成动作不作任何保证。
4. 生成文件的头注释必须写明副作用：import 该文件即写盘。依据是 `conf()` 在调用时建立引擎并落盘（`src/onconf/__init__.py:130-133`）。
5. 命令输出必须明确提示「该文件需要被 import 才会执行，不被 import 就不生效」，避免配置静默不生效。
6. 生成物不替用户做任何接入动作：不写 import 语句到别的文件，不改 `pyproject.toml`，不扫工作区。

### 变更项

| 位置 | 改动 |
|---|---|
| 新增代码生成路径 | 按模板生成 `conf.py`：一个函数 + 头注释 |
| 新增 CLI `add` | `--code-file` 指定落点；输出含不生效提示 |
| `tests/` | 生成物结构、头注释内容、重复调用的结果各有用例（`tmp_path`） |
| `README.md` / `README.zh-CN.md` | `add` 的用法与「不 import 不生效」（两者是一对） |
| `docs/getting-started.md` | `add` 的一段用法 |

### 验收标准

- [ ] `add` 只创建指定落点的新文件，既有文件的内容与 mtime 不变
- [ ] 生成文件的头注释含两句：import 才会执行、import 即写盘
- [ ] 命令输出含「不被 import 就不生效」的提示
- [ ] 生成的 `conf.py` 在 `tmp_path` 下可被直接执行，并写出预期的键与值
- [ ] 重复 `add` 同一键的结果与既定幂等判据一致，且有回归测试
- [ ] 行为变更带测试；生成物用例不依赖 CWD
- [ ] 文档同步（`docs/` 未同步视为未完成）

### 未决事项

1. `conf.py` 已存在时的行为：候选 (a) 报错并要求指定别的落点；(b) 追加一个函数；(c) 整篇重写。代价：(a) 最保守，但打断重复生成的流程；(b) 等于「改写既有代码」，模板合并与语法错误风险随之回来；(c) 会覆盖用户写的代码。
2. 缺省落点目录：候选 (a) 当前工作目录；(b) 配置目录 `home`；(c) 由 `--code-file` 必填。代价：(a) 命令不指定路径时落点随 CWD 变化；(b) 生成物落进配置目录，与实际项目代码分离；(c) 失去缺省便利。
3. 幂等判据：候选 (a) 按函数名去重；(b) 按键集合去重；(c) 不做幂等。代价：(a) 函数名冲突时判定不准；(b) 同一函数内的多个键要一并比较；(c) 重复调用在文件里留下多份声明。
4. 一次 `add` 生成一个函数还是每个键一个函数，以及函数命名规则。

---

## 3. 单键删除 `remove`：只动文件，不碰代码（原 ISSUE-047）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 设计变更 / P1 / 部分已定 |
| 原依赖 | ISSUE-031（命令形态与统一约定）、ISSUE-035（规则 1 移除，删除能力转入 CLI） |
| 原影响面 | 新增 CLI `remove`、四个后端的 `delete_key`、`tests/`、`README.md`、`README.zh-CN.md`、`docs/getting-started.md` |
| 原标签 | `area:cli`、`breaking` |

### 背景

- 进程内的删除按 ISSUE-035 移除：引擎不再删除任何未被代码声明的键。现状代码里唯一的删除动作由 `clean` 分支产生（`src/onconf/_engine.py:846-849`），它只由完整提交点 `sync()` 触发（`src/onconf/_engine.py:404-407`）。
- 命令面只有批量出口：`sync` 删除代码未声明的键，单个键没有出口。
- 后端本身已具备单键删除能力，四个后端各有一个 `delete_key`：`src/onconf/_json_backend.py:225-245`、`src/onconf/_yaml_backend.py:218`、`src/onconf/_env_backend.py:200`、`src/onconf/_toml_backend.py:227`。缺的只是命令面。
- 代码侧定位「声明处」不可行：键可能是常量的值、可能来自元组循环、实参可能是 `Name` 而不是字面量；引擎只在运行期要求键是字符串（`src/onconf/_engine.py:321-325`），无法回溯声明位置。`DESIGN.md` §28.3（`:1756-1758`）区分了「值引用值」与「键用表达式算」，后者对静态扫描不可见。

### 结论

1. `remove` 只改值文件：把指定键从值文件里删掉（连同该带走的逗号或整行），代码侧一律不碰。
2. 代码侧不碰的两条理由成立：会引入更繁杂的工程问题；使用约定管的是「怎么写」，不由引擎替用户改代码。
3. `remove` 与 `sync` 是单键版与批量版的关系：`remove` 删一个键，`sync` 删所有代码未声明的键。
4. 输出必须写明写回风险：若该键仍在代码里被声明，下次 `build` 会把它写回来。该句是命令输出的固定内容。
5. `remove` 属于破坏性命令，一律支持 `--dry-run`（ISSUE-031 §4）：`--dry-run` 下不写任何字节。
6. 定位方式与 `get` / `set` 同构：`--file` 限定文件，缺省全局查找；多命中时逐条列出并要求指定文件。
7. 删除是外科手术式的：未被触及的字节逐字不变（四个后端 `delete_key` 的既有不变量）。

### 变更项

| 位置 | 改动 |
|---|---|
| 新增 CLI `remove` | 单键删除；`--file` / `--dry-run` / 写回提示 / 非 TTY 守卫 |
| `src/onconf/_json_backend.py:225-245` 等四个后端的 `delete_key` | 经命令面暴露；不改变既有不变量 |
| `tests/` | 删除后其余字节逐字不变；多命中与非 TTY 行为；`--dry-run` 不写字节 |
| `README.md` / `README.zh-CN.md` | 命令说明与「代码侧不碰、下次 `build` 会写回」（两者是一对） |
| `docs/getting-started.md` | 命令说明 |
| ISSUE-035 的正文口径 | 删除能力的出口登记为 `remove`（单键）与 `sync`（批量） |

### 验收标准

- [ ] `remove` 跑完，值文件里该键消失，其余字节逐字不变（注释、缩进、键序）
- [ ] 不给 `--file` 时按全局查找；多命中逐条列出 `key`、值、文件路径
- [ ] 非 TTY 下多命中不进入交互，直接以非 0 退出
- [ ] `--dry-run` 不写任何字节
- [ ] 输出含「若该键仍在代码里被声明，下次 `onconf build` 会把它写回来」
- [ ] 跑完 `remove` 后仓库内 `.py` 文件的 mtime 与内容不变
- [ ] 行为变更带测试；回写类改动另断言未触及字节逐字不变
- [ ] 文档同步（`docs/` 未同步视为未完成）

### 未决事项

1. 命令名：候选 (a) `remove`；(b) `unset`。代价：(a) 与 `add` 配对；(b) 与 `set` 配对。
2. 词表与 `$schema` 指针是否随之更新：候选 (a) 只改值文件，词表条目保留；(b) 同时删词表条目。代价：(a) 该键此后「有登记无值」，读取会抛 `KeyHasNoValueError`（`src/onconf/errors.py:20-21`）；(b) 引擎替代码侧做了判断，且下次 `build` 会重新登记。
3. 多文件模式下的定位方式（`--file` 与键内嵌路径的等价关系，ISSUE-008）是否与 `get` / `set` 完全一致。
4. 键不存在时的退出码：候选 (a) 非 0 报错；(b) 0 且静默成功。代价：(a) 幂等脚本要自己忽略该错误；(b) 与 `set` 的失败语义不一致。

---

## 4. `check` 必须一个字节都不写（原 ISSUE-049）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 任务 / P1 / 部分已定 |
| 原依赖 | ISSUE-031（`check` 是 CI 入口）、ISSUE-005（文件通道强制，引擎一动就产生落盘） |
| 原影响面 | 新增只读路径、`src/onconf/_engine.py`、`src/onconf/_audit.py`、`src/onconf/_lock.py`、`tests/`、README 一对、`docs/getting-started.md` |
| 原标签 | `area:cli`、`area:audit`、`breaking` |

### 背景

- `check` 的定位是 CI 入口（ISSUE-031），CI 会在只读环境或干净工作区里运行它。
- 现状任何写路径都会创建目录与文件：`exclusive()` 先建父目录再以 `O_CREAT` 打开锁文件（`src/onconf/_lock.py:82-83`），锁落在 `schema/` 下（`src/onconf/_engine.py:260`）。
- 引擎第一次被用到就写一条 `[Start]` 记录并收口（`src/onconf/_engine.py:492-504`）；落盘时词表整篇重写（`src/onconf/_engine.py:855-861`）。
- ISSUE-005 把文件通道改为强制之后，`<home>/audit.log` 恒产生（`src/onconf/_engine.py:266-271`、`src/onconf/_audit.py:95-99`），因此「启动一次引擎」本身就等于一次写盘。
- 在只读环境里，上述任何一步都只会以权限错误结束，检查结果根本到不了 CI。

### 结论

1. `check` 走一条专门的只读路径：不创建 `schema/`、不产生 `audit.log`、不改值文件、不留其它写句柄。
2. 只读不等于不读：`check` 仍读取值文件与词表，检查词表与值文件的一致性、`$schema` 指针、后端可解析性、以及使用约定（ISSUE-053）。
3. 只读路径不得调用任何创建或改写文件的动作；若需要与并发写者互斥，只允许使用不创建文件的读锁（实现方式见未决事项）。
4. 检查结果只经 stdout 与退出码表达；只读路径下日志与审计不落盘。
5. 只读性是硬约束，写成回归断言：跑完 `check` 后，工作区内所有既有文件的 mtime 与内容都不变，且不新增任何文件与目录。
6. 后端解析失败、词表缺失、指针缺失等检查结论按退出码分类表达，不影响只读性。

### 变更项

| 位置 | 改动 |
|---|---|
| 新增只读路径 | `check` 专用：不建目录、不写文件、不取写锁 |
| `src/onconf/_engine.py:492-504` | 只读路径下不写 `[Start]` 记录 |
| `src/onconf/_engine.py:855-861` | 只读路径下不重写词表 |
| `src/onconf/_lock.py:82-83` | 如采用读锁，增补不创建文件的共享锁路径 |
| `src/onconf/_audit.py:95-99` | 只读路径下不产生 `audit.log` |
| `tests/` | 只读回归：跑完 `check` 后工作区指纹不变、无新增文件 |
| `README.md` / `README.zh-CN.md` | `check` 的只读保证（两者是一对） |
| `docs/getting-started.md` | CI 用法 |

### 验收标准

- [ ] 干净工作区跑 `check`：不新增文件、不创建目录
- [ ] 既有文件 mtime 与内容逐文件不变（含 `schema/` 下的文件）
- [ ] 只读挂载或只读权限下 `check` 仍能完成并给出结果
- [ ] 检查结论经退出码表达：0 通过，非 0 按类别区分
- [ ] 回归测试断言「跑完 `check` 后工作区指纹不变」
- [ ] 词表与 `$schema` 指针的检查项各有用例，且不修改被检查的文件
- [ ] 文档同步（`docs/` 未同步视为未完成）

### 未决事项

1. 只读互斥的实现：候选 (a) 完全不取锁（写入是原子替换，读到的只会是替换前或替换后的完整文件）；(b) 增补一个不创建文件的读锁。代价：(a) 零新增机制，但与写者并发时可能读到替换前后的两种状态；(b) 需要 `src/onconf/_lock.py` 新增共享锁路径，Windows 与 POSIX 的语义各写一遍。
2. 只读路径下「词表缺失或过期」的报告级别：候选 (a) 报错（非 0）；(b) 报 warning 且通过。代价：(a) 干净工作区里 `check` 必然失败；(b) 词表缺失这一项会被 CI 放过。
3. 词表是锁死的默认产物（ISSUE-003），只读路径是否需要一条「检查但不产生」的显式声明。

