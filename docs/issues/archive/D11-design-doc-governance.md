# D11 文档治理：规格与决策日志分离

| 项 | 值 |
|---|---|
| 类型 | 任务 / 文档 |
| 优先级 | P1 / P2 |
| 状态 | 部分已定（取最不确定成员） |
| 成员状态 | 部分已定 2 / 已定稿，待实现 1 —— 未定稿：ISSUE-011（部分已定）、ISSUE-013（部分已定） |
| 前置 | 无 |
| 联动 | 无 |
| 覆盖原编号 | ISSUE-011、ISSUE-012、ISSUE-013 |
| 影响面 | `docs/design/DESIGN.md`、新增决策日志、`docs/design/index.md`、`AGENTS.md`、`CONTRIBUTING.md`、`README.md`、`mkdocs.yml`、`docs/api/index.md`、`docs/architecture/index.md`、`README.zh-CN.md`、`src/onconf/_engine.py`、`AGENTS.md` §3.4、新增 `scripts/check_design_marks.py`、`.pre-commit-config.yaml`、`.github/workflows/ci.yml` |
| 标签 | `area:docs`、`area:process`、`area:docs`、`area:process`、`area:docs` |

## 0. 本决策的整体口径

`DESIGN.md` 从「规格 + 日志」的混合物拆成两份文档，随之而来的是行级陈旧声明清理与机器可检的护栏。

- 规格只描述现在，作废靠改写不靠追加，双向可回溯，且可机械检查（原 ISSUE-011）；
- 陈旧状态声明批量修正，以仓库实际状态为准，不改任何行为（原 ISSUE-012）；
- 口径变更护栏从纸上约定变成 CI 可拦截的检查（原 ISSUE-013）；
- 本单元不触及任何运行时行为，可与其余单元并行推进。

### 0.1 成员索引

| 原编号 | 本文件 | 一句话 |
|---|---|---|
| ISSUE-011 | §1 | §11–§32 迁入决策日志，规格只留现在成立的陈述 |
| ISSUE-012 | §2 | 陈旧的文档与源码注释逐条修正（含 `_engine.py:70-71` 旧级别名） |
| ISSUE-013 | §3 | `scripts/check_design_marks.py` + pre-commit + CI lint 三步接线 |

> 本文档内的 `ISSUE-NNN` 是**原始编号**。同一 `D` 单元内的编号都在本文件里，完整编号映射见 `README.md`。

---

## 1. `DESIGN.md` 结构治理：规格与决策日志分离（原 ISSUE-011）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 任务 / P1 / 部分已定 |
| 原依赖 | 无 |
| 原影响面 | `docs/design/DESIGN.md`、新增决策日志、`docs/design/index.md`、`AGENTS.md`、`CONTRIBUTING.md`、`README.md`、`mkdocs.yml` |
| 原标签 | `area:docs`、`area:process` |

### 背景

- `docs/design/DESIGN.md` 共 2133 行。从 `7a78a4e` 到 `8d38b36` 该文件是 `+501 / −25`，其中动过它的提交共 14 个；而前 301 行（标题块 + §1–§10，`DESIGN.md:8-301`）只有 4 行被改动，且全部是改名（`auto_conf` → `onconf`、`AUTO_CONF_HOME` → `ONCONF_HOME`）。
- 推翻一律靠文末追加：文末有一次 `+294` 行的纯追加，新增章节 §27–§32 落在 `DESIGN.md:1669-2133`。
- 后果是失效条款仍以现行规格的口吻留在原位：WAL 已判定不做（§32.7），而 `DESIGN.md:1606`、`:1632`、`:1644-1649` 仍称默认路径为「文件锁 + WAL」、目录树仍画 `app.yaml.wal`。
- 文档自己承认这一点：`docs/design/index.md:11-12` 写着正文里「也有被后续小节明确推翻的前期结论」。
- 为什么不可接受：读者读到 §5.2 会把它当成现行规格；「当前真相在编号最大的那一节」这个约定文档里从未写明。

### 结论

#### 1. 拆成两份文档

| 文档 | 只写什么 |
|---|---|
| `docs/design/DESIGN.md`（规格） | 现在成立的形态、默认值、边界条件 |
| 决策日志（新文件） | 当时的决定、理由、被谁取代 |

现有 §11–§32（`DESIGN.md:302-2133`）的内容整段迁入决策日志，按时间编号。

#### 2. 规则一：规格只描述现在

出现在规格里的每一句都必须是当前成立的陈述。任何「为什么当初这么定」的文字一律进决策日志。

#### 3. 规则二：作废靠改写，不靠追加

一个条款失效时，就地改写或删除该条款本身，并在决策日志登记一条；不允许只在文末新增一节来推翻它。

#### 4. 规则三：双向可回溯

规格小节若由某条决策产生，就地写「见决策日志 NNN」；决策日志每条写清它改写了哪些规格小节号。

#### 5. 规则四：可机械检查

规格里不得出现「已推翻」「已被 §X 取代」「作废」这类历史标记，`grep -n '已推翻\|取代\|作废' docs/design/DESIGN.md` 必须为空。状态标记只允许出现在决策日志里。

#### 6. 存量清理范围

§1–§10 里已被推翻的条款（如 §5.2 的 WAL、§4 的环境变量层、§2 的多文件层叠）按规则二改写；逐行级的陈旧状态声明修正见 ISSUE-012。

#### 7. 引用同步

`AGENTS.md:90`、`CONTRIBUTING.md:450-451`、`README.md:187`、`docs/design/index.md:10-14`、`docs/architecture/index.md:5-7`、`mkdocs.yml:111` 对「设计稿」的分工说明同步为「规格 + 决策日志」。

### 变更项

| 位置 | 改动 |
|---|---|
| `docs/design/DESIGN.md:302-2133`（§11–§32） | 迁入决策日志，按时间编号 |
| `docs/design/DESIGN.md:8-301`（§1–§10） | 失效条款就地改写或删除 |
| `docs/design/DESIGN.md` 文首 | 增加两份文档的分工说明与阅读顺序 |
| 新增决策日志 | 每条含：编号 / 日期 / 决定 / 理由 / 改写的规格小节号 / 被谁取代 |
| `docs/design/index.md:10-14` | 改为描述两份文档及其读法 |
| `AGENTS.md:87-92`（§3.4）、`CONTRIBUTING.md:450-451` | 指向规格那一份；`§` 引用习惯不变 |
| `docs/architecture/index.md:5-7` | 「权威来源是设计稿」改为指向规格那一份 |
| `README.md:187`、`README.zh-CN.md` | 设计稿的链接与描述同步 |
| `mkdocs.yml:111` | 导航随两份文档更新 |

### 验收标准

- [ ] `docs/design/DESIGN.md` 中不存在任何已失效的陈述，且规则四的 `grep` 为空
- [ ] §11–§32 的全部内容在决策日志里逐条可寻，`DESIGN.md:345-363` 一类实测数据未丢失
- [ ] 规格的每个小节都能回答「现在的形态是什么」；决策日志的每条都能回答「为什么、何时、被谁取代」
- [ ] 决策日志引用的规格小节号在规格中真实存在（可用脚本核对）
- [ ] `uv run mkdocs build --strict` 通过，`AGENTS.md` / `CONTRIBUTING.md` / README 的链接不失效

### 未决事项

1. **决策日志的文件名**：候选 `docs/design/DESIGN-HISTORY.md`（代价：与 `docs/issues/DECISIONS.md` 名字相近，易混）；候选 `docs/design/DECISION-LOG.md`（代价：与规格不在同一命名族）；候选 `CHANGELOG-design.md`（代价：与 `docs/community/changelog.md` 语义重叠，需写明分工）。
2. **历史内容的迁移粒度**：候选全量迁入，含全部实测数字与落选方案（代价：迁移量大，决策日志会长于规格）；候选只迁结论与理由（代价：`DESIGN.md:345-363` 一类实测数据失去归属）。
3. **两份文档的版本对应**：候选在决策日志每条标注它生效的规格快照（代价：需要额外维护快照号）；候选不标（代价：无法回答「某个历史版本对应哪份规格」）。

---

## 2. 陈旧状态声明批量修正（原 ISSUE-012）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 文档 / P1 / 已定稿，待实现 |
| 原依赖 | ISSUE-011（`DESIGN.md` 的行级修正以拆分为前提） |
| 原影响面 | `AGENTS.md`、`docs/design/DESIGN.md`、`docs/api/index.md`、`docs/architecture/index.md`、`README.md`、`README.zh-CN.md`、`src/onconf/_engine.py` |
| 原标签 | `area:docs` |

### 背景

- 多处状态声明与仓库实际不符：`AGENTS.md:90` 称 `docs/design/DESIGN.md` 为「1136 行」，实际 2133 行；`README.md:187` 称设计稿「still under review」，与同页已发布的 1.0.0 并存。
- 源码注释停在旧口径：`src/onconf/_engine.py:70-71` 写「四个级别 `[R]/[W]/[C]/[E]`」，实现是完整词 `[Read]` / `[Write]` / `[Change]` / `[Error]`（`src/onconf/_audit.py:85-93`）；同一段 `:79` 也写 `[E]`。
- 文档里留着一整套被推翻的默认路径：`docs/design/DESIGN.md:1606`、`:1632`、`:1644-1649` 仍称「文件锁 + WAL」，而 WAL 已判定不做（`DESIGN.md:2040-2051`，§32.7）。
- 指引本身会误导：`docs/api/index.md:28` 让读者以带 `U+2753` 标记的小节为准，而该标记既不完整（§5.3 仍在）也不过期（§11 / §15 已定却无标记）。
- 为什么不可接受：同一仓库里对同一件事有两种陈述，读者无法判断该信哪一条。

### 结论

1. 按下表逐条修正，以仓库实际状态为准，不改任何行为。
2. `src/onconf/_engine.py:70-71,79` 的旧级别名注释一并修正，见变更项。
3. 涉及 `docs/design/DESIGN.md` 的行级修正先完成 ISSUE-011 的拆分，再落在规格那一份上。
4. 下表行号以 `8d38b36` 的 `docs/design/DESIGN.md` 为准；ISSUE-011 落地后按小节号定位。
5. `README.md` 与 `README.zh-CN.md` 成对同步。

### 变更项

| 位置 | 现文 | 应为 |
|---|---|---|
| `AGENTS.md:90` | 「`docs/design/DESIGN.md`（1136 行中文，意图的权威）」 | 行数与 `DESIGN.md` 实际一致，并按 ISSUE-011 说明它是规格那一份 |
| `docs/design/DESIGN.md:3` | 「状态：待评审」 | 已发布 1.0.0；文档性质由 ISSUE-011 的两份文档定义 |
| `docs/api/index.md:28` | 以带 `U+2753` 标记的小节为准 | 该指引失效（标记既不完整也不过期）；改为指向规格那一份 |
| `docs/architecture/index.md:39` | 把「审计报告与审计事件流（§20 / §21）」列为下一阶段未定稿 | §20 / §21 已交付（`README.md:169`、`docs/roadmap.md:32`）；未交付的只有 `report()`，且判定不做（ISSUE-006） |
| `README.md:187` | 「design draft (Chinese, still under review)」 | 与 1.0.0 的现状一致；`README.zh-CN.md` 同步 |
| `src/onconf/_engine.py:70-71` | 「四个级别 `[R]/[W]/[C]/[E]`」 | `[Read]` / `[Write]` / `[Change]` / `[Error]` |
| `src/onconf/_engine.py:79` | 「记一条 `[E]`」 | `[Error]` |
| `docs/design/DESIGN.md:1606` | 「默认路径（WAL + 文件锁）根本不需要 IPC」 | 默认路径是专职写者 + OS 锁兜底（§31 / §32） |
| `docs/design/DESIGN.md:1632` | 表格行「文件锁 / WAL」 | 同上 |
| `docs/design/DESIGN.md:1644-1649` | 目录树画 `app.yaml.wal` / `app.yaml.lock`，正文称「默认：文件锁 + WAL」 | 实际产物见 `src/onconf/_engine.py:55-63` |

### 验收标准

- [ ] 上表每一行都有对应改动，且现文在仓库中 `grep` 不到
- [ ] `AGENTS.md:90` 声明的行数与 `docs/design/DESIGN.md` 的实际行数一致
- [ ] `src/onconf/_engine.py` 中不再出现 `[R]` / `[W]` / `[C]` / `[E]` 形式的级别名
- [ ] `docs/design/DESIGN.md` 中不再出现 `app.yaml.wal` / `app.yaml.lock` / 「文件锁 + WAL」
- [ ] `README.md` 与 `README.zh-CN.md` 同步
- [ ] 纯文档与注释改动：`uv run pytest`、`uv run mypy`、`uv run ruff check .` 结果不变

---

## 3. 口径变更护栏：从纸上约定变成 CI 可拦截（原 ISSUE-013）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 任务 / P2 / 部分已定 |
| 原依赖 | ISSUE-011（拆成规格与决策日志之后，检查才有明确对象） |
| 原影响面 | `AGENTS.md` §3.4、`CONTRIBUTING.md`、`docs/design/DESIGN.md`、新增 `scripts/check_design_marks.py`、`.pre-commit-config.yaml`、`.github/workflows/ci.yml` |
| 原标签 | `area:process`、`area:docs` |

### 背景

- 现行护栏只是文字：`AGENTS.md:92` 与 `CONTRIBUTING.md:450-451` 要求「改动 `DESIGN.md` 必须在 PR 里单独说明理由」，没有任何机器检查。
- 实测不成立：动过 `DESIGN.md` 的 14 个提交里 9 个同时改了 `src/` 与 `tests/`，口径变更随 `feat(...)` / `fix(...)` 类提交一并进入主干（`docs/issues/DESIGN-DRIFT-AUDIT.md:98-112`）。
- 文档内的状态标记没有登记处：`docs/design/DESIGN.md:90`（§4）、`:813`（§17.2）、`:1884`（§30）、`:1943`（§32）四个小节标题带「已修正 / 实现后修正 / 已交付」，文首没有任何汇总表。
- 为什么不可接受：口径变更在 review 里不会被当作一次设计决策看待，护栏存在于文档而不在流程里。

### 结论

#### 1. 护栏必须落在机器上

「改动 `DESIGN.md` 请单独说明理由」这条约定升级为 CI 可拦截的检查；线下自觉不再是唯一保障。具体拦截形态见未决事项。

#### 2. 带状态标记的小节标题必须登记

受管文档（规格与决策日志，见 ISSUE-011）的文首必须有且仅有一张变更登记表，列固定为：小节号 / 标题 / 状态词 / 变更内容。规则三条：

- 正文中任何小节标题含「（已修正）」「（实现后修正）」「（已交付）」或等价状态词的，必须在表中有且仅有一行；
- 表内小节号必须在正文中真实存在；
- 两个集合必须相等，既不漏登记，也不留死行。

#### 3. 检查方式：脚本 + 两处接线

新增 `scripts/check_design_marks.py`，`--check` 模式提取正文标题里的状态标记小节号集合 A 与文首登记表的小节号集合 B，`A != B` 时打印差集并以退出码 1 结束。接线两处：

- 本地钩子：`.pre-commit-config.yaml:107-166` 的 `repo: local` 段新增一条，与 `ruff-check` 同级；
- CI：`.github/workflows/ci.yml:34-104` 的 `lint` job 新增一个阻塞步骤，与 `:83-84` 的第三方声明检查同级。

#### 4. 落地时登记表不是空的

登记表当前不存在，正文中带标记的小节号为 {§4、§17.2、§30、§32}。本项落地时必须同时补齐这四行，检查才会绿。

#### 5. 与 ISSUE-011 的关系

拆分落地后带状态标记的章节迁入决策日志，因此上文第 2 节的登记要求作用于决策日志；若规格里仍有带标记的小节，同一张登记表也适用于规格。

### 变更项

| 位置 | 改动 |
|---|---|
| `AGENTS.md:87-92`（§3.4） | 约定改写为可执行的提交与 CI 规则 |
| `CONTRIBUTING.md:450-451` | 同步该规则，补「违规由哪个 job 拦截」 |
| 受管文档的文首（ISSUE-011 落地后为决策日志） | 新增变更登记表（§4 / §17.2 / §30 / §32 四行） |
| 新增 `scripts/check_design_marks.py` | `--check` 模式；`A != B` 时退出码 1 并打印差集 |
| `.pre-commit-config.yaml:107-166` | `repo: local` 新增一条 hook |
| `.github/workflows/ci.yml:83-104` | `lint` job 新增阻塞步骤 |
| `tests/` 新增脚本用例 | 合规 / 漏登记 / 表内死行三组；按 `AGENTS.md` §5 坑 2 登记进 `pyproject.toml` 的 mypy override 名单 |

### 验收标准

- [ ] 正文带状态标记的小节号集合与文首登记表的小节号集合相等；缺一即 CI 红
- [ ] `uv run pre-commit run --all-files` 能在本地捕获同一违规
- [ ] 脚本用例覆盖「漏登记」与「表内死行」两种失败
- [ ] `AGENTS.md` §3.4 与 `CONTRIBUTING.md` 的表述与实际拦截点一致
- [ ] 混合提交的拦截形态按未决事项选定后，有至少一个反例测试（`src/` 与 `DESIGN.md` 同提交）

### 未决事项

1. **拦截形态**：候选一是 CI 检测「同一提交同时修改 `src/` 与 `docs/design/DESIGN.md`」即失败，要求 PR 里逐条说明理由（代价：CI 需读 PR 描述，或退化为要求提交信息携带固定 trailer，两者都要新约定）；候选二是只允许 `DESIGN.md` 的改动单独成提交，检查 `git diff --name-only` 的混合情况（代价：一次口径变更拆成两个提交，bisect 与 revert 的粒度变粗）。
2. **说明理由的存放位置**：候选是 PR 描述（代价：不进 git 历史，仓库克隆者看不到）；候选是提交 trailer `Design-Change: <理由>`（代价：需要固定 trailer 名，且在 `conventional-pre-commit` 之外再加一层校验）。
3. **状态词表**：候选是锁定「（已修正）」「（实现后修正）」「（已交付）」三个词面（代价：新写法会被漏检）；候选是按词根正则匹配 修正 / 交付 / 作废（代价：正文里的普通用词可能误报）。

