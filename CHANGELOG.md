# 变更日志

本文件记录 onconf 的所有重要变更。

格式遵循 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

本文件自 v0.1.0 起**人工维护**；v0.1.0 的历史条目由真实 git 提交整理
（`git log --oneline --no-merges`，整理范围至 `988d5df`），每一条都对应一个真实提交，
不是事后补写的愿景。尚未发布的能力与进度见[路线图](docs/roadmap/index.md)。

## [Unreleased]

### Added

- **命令行的人读输出有了色彩**（[路线图 2-078](docs/roadmap/2.x.md)）：新增 `--color=auto|always|never`
  这一处闸门，只给**语义**上色 —— `check` 的 finding 类别、`OK` / `Error:`、计划里的删除与新增
  动词；键名、路径、值与列宽一个都不动。
  - 缺省 `auto`：非终端就是纯文本，且与上色前**逐字相同**；判定顺序 `NO_COLOR` →
    `TERM=dumb` → `FORCE_COLOR` → 是不是终端 → Windows 上控制台支不支持 VT，
    **「关」排在「开」前面**。
  - `--json` 与一切落盘字节**永不经过**渲染层；`--help` 的着色仍归 `argparse`。

## [2.0.0] - 2026-10-07

### Changed

- **`EngineParams` 新增 `file_name` / `no_one_file`，`file_type` 的缺省值改为字面 `"json"`**
  （破坏性）：值文件路径变成 `<home>/<file_name><ext>`，两者都经**包含性校验**
  （纯文件名、无分隔符、无 `..`、非绝对、解析后仍在 `<home>` 之内）。空串不再是
  `file_type` 的合法取值 —— 默认值只有一个来源。
- **多文件寻址**：`no_one_file=True` 后，键里第一个 `:` 的左边是相对路径、右边是文件内
  键名（`conf("app/conf/net:net.id.post", 8080)` → `<home>/app/conf/net.json`）；没有前缀
  的键仍落默认文件。词表只有一份，每个值文件的 `$schema` 指针按自己的层级算相对路径；
  未被声明引用的值文件不会被加载、也不会被清理。多文件**关闭**时 `:` 不参与解析，
  行为与之前完全一致。
- **使用口 `conf` 收敛为三种模式**（破坏性）：签名变成 `conf(key, value=MISSING, doc=None)`，
  判据只看 `value` 位填没填。`doc` 从 keyword-only 变成第三个**位置**参数；参数面自此封闭。
- **`type=` 移除**（破坏性）：值类型不再声明、不再校验、不再进词表，`TypeConflictError`
  一并作废；JSON Schema 不再输出 `type` 与 `x-onconf-py`。要转换请在调用点显式
  `int(conf("PORT"))`。
- **`force=` 移除，运行期不再覆盖已存在的值**（破坏性）：文件里的值与声明不一致时尊重文件，
  只记一条 `op=skip`，值文件逐字不动。覆盖既存值是人的决定，归命令行的 `build` / `sync`。
  `Action("overwrite")`、`reconcile(force_keys=…)` 与 IPC 请求里的 `forced` 字段一并移除。
- **`conf(..., **engine)` 摘除**（破坏性）：使用口不得配置引擎，`conf(..., home=…)` 现在是
  `TypeError`。「一个配置口、一个使用口」不再依赖「引擎是否已经起来」这一时序条件。
- **值文件选定改为 `file_name` + `file_type`**：「按存在性从候选名里挑第一个」的隐式行为退役。
- **`home` 的缺省从「当前目录」改为 `./conf`**。
- 修复：新建**非 JSON** 值文件时，引擎用写死的 `"{}"` 当种子，TOML / YAML 后端会把它当内容
  解析而报错。现在每种后端各自提供 `EMPTY_TEXT` 种子（JSON 是 `{}`，其余三种是空文本）。
- **命令行输出统一英文**：命令自己写的文本（标签、计划、摘要、参数帮助、扫描报告）一律英文，
  不再混中文。库产出的文本（`ConfError` 消息、计划里的 `reason=`）原样透传 —— 后者还要落进
  审计文件，属于数据而不是 CLI 文案。
- **本地 pre-commit 钩子精简到「秒级 + 能自动修」**：`git commit` 时只跑行尾 / 空白 /
  冲突标记与 `ruff check --fix`，外加 `commit-msg` 的约定式提交校验。mypy、pytest、
  codespell、markdownlint、bandit、pip-audit、zizmor 与各类语法检查一概交给 CI ——
  本地再跑一遍只会让提交变慢、把贡献者劝退。

### Added

- **命令行 `onconf build` / `onconf sync`**（[路线图 §4](docs/roadmap/2.0.x/roadmap.md) 的头两条命令）：声明靠**静态扫描项目里的
  `conf(...)` 调用**得到（`ast.parse`，不 import、不执行用户代码），按 `key` / `value` / `doc`
  的参数形态解读。`build` 按声明完整重建值文件与词表（`--path` 把整份重建写到新目录）；
  `sync` 补缺并删除声明里没有的键（`--no-clean` 只补缺）。两者都支持 `--dry-run`（一个字节
  都不写）与 `--json`；扫不动的调用会被逐条列出，此时 `sync` **拒绝删除任何键**。
  控制台入口从「只打印配置目录」的占位改为 `onconf._cli:main`。
- **命令行 `onconf check`**：一个字节都不写地对比**三个口径** —— 代码里扫到的声明、词表、
  值文件 —— 报六类差异（`missing` / `stale` / `default` / `doc` / `unfilled` / `undeclared`），
  按 `key` 的码位序排。缺省只给 CI 状态（通过回一行、不通过逐条报），`--verbose` 补上落点
  文件，`--strict` 把 warning 也算作失败；发现问题时以退出码 5 结束。它**不带 `--fix`**：
  不通过时末行推荐 `onconf sync`。值文件读不出来时以退出码 3 报错，不再抛栈。
- **命令行 `get` / `set` / `diff` / `format`**：取值（四列 `key` / `value` / `path` / `doc`，
  同名的键有多少刷多少）、改值（`set` 只改**已有**键，`set --default` 改词表里的默认值并去
  追踪声明点）、变更历史（`diff` 扫审计日志里全部 `[Change]`，**不读哈希、不建索引**）、
  重排缩进（`format` 只做 JSON，`--indent` 是唯一触发参数，不给就一个字节都不写）。
  `--file` 只在多文件模式下有意义：关闭时给它是用法错误（退出码 2），不静默忽略。
  `set` 的多命中不再交给交互选择：列出编号候选并要求显式给出落点。
- 新增 `src/onconf/_paths.py`：外部字符串 → 路径的**唯一入口**（五条包含性规则）。
- `EngineParams` 补上 `lock_timeout` —— 它以前对公开 API 完全不可达（传了会抛
  `UnknownEngineParamError`）。
- `EngineParams` 补上 `file_name` / `file_type` / `no_one_file`；`EngineParams` 的注解与
  `Engine.__init__` 的形参一一对应，有回归守着。

### Fixed

- 清掉三处已被移除机制的陈旧引用：`_core.read_value` docstring 里的「声明期 `type=` 校验」、
  `_audit` 模块 docstring 的 `op=overwrite`、`Engine._log_failure` 那个只为「类型冲突」而存在
  且无人使用的 `message` 形参。
- 命令行扫描对齐 CPython：带 UTF-8 BOM 的源文件不再被当成语法错误（改用 `utf-8-sig` 读取）。
- 命令行扫描不再把**变量键的读取**（`conf(APP)`）当成问题：问题清单是给「期望集完不完整」
  用的，而期望集只由**声明形态**构成 —— 读取不产生持久状态，它的键是不是字面量与期望集无关
  （[初始化配置](docs/design/init_config.md) §8）。连带修掉一处误伤：项目里只要有一处变量键的
  读取，问题清单就非空，`sync` 因此拒绝清理任何键。

### Docs

- 路线图的「未实现」段按**批次**重排（下一批 / 未来 / 不计划 / 已定不动），并把批次写进
  [`docs/design/log.md`](docs/design/log.md)、[`docs/design/init_config.md`](docs/design/init_config.md)、
  [`docs/design/file_support.md`](docs/design/file_support.md)：**下一批** = 日志两通道与
  `audit` 口径（[路线图 §3](docs/roadmap/2.0.x/roadmap.md)）、运行期规则 1 的移除；
  **未来** = 落盘形式与加密/轮转（[路线图 §5](docs/roadmap/2.0.x/roadmap.md)）、
  `.env` 结构开关（2.2）、其余命令；**已定不动** = `$schema` 指针按载体能力、不新增参数。
- README 一对与 [`docs/api/index.md`](docs/api/index.md) 补**主 / 辅后端**标注
  （JSON 是主后端：缺省值、能力最完整、`$schema` 指针的落点；YAML / TOML / `.env` 为可选后端）。
- 新增「使用范式」一节（README 一对、[`docs/getting-started.md`](docs/getting-started.md)、
  [`docs/design/init_config.md`](docs/design/init_config.md) §8）：**声明处必须字面量** ——
  键、值、说明都写在调用点上；读取不受限（常量、拼接都行）。定性是**合法但不合理**
  （error 的分界是「不合法」，这一条只到 warning），因此**不设门禁**，只写清代价：
  命令行看不见它（`sync` 因此拒绝删除任何键）、静态复核与未来的 `check` 覆盖不到它、
  声明点不再自证。
- 新增设计文档 [`docs/design/init_config.md`](docs/design/init_config.md)（初始化配置：
  两个面、引导层与值层、三种模式、运行期写路径）与
  [`docs/design/file_support.md`](docs/design/file_support.md)（值文件选定、返回值口径、
  四个后端、词表、外科手术式回写）。两者开始**逐节替换**旧稿 `DESIGN.md`，
  并补齐 §11.1 / §17.7 / §18.1 情形 4 的认领。
- 威胁模型 **T1 由「白名单 → 不适用」改为「包含性校验」**，新增 **T13**（命令行静态扫描与
  删除动作）；不变量表与边界判定表同步。
- README 一对、`docs/api/index.md`、`docs/design/*`、[路线图](docs/roadmap/2.0.x/roadmap.md)
  同步；路线图把多文件与
  `build` / `sync` 从「未实现」移到「已实现」，`.env` 的 `dict` / `list` 仍预计 2.2。
- 修掉三页用户文档里的陈旧陈述（`docs/index.md`、`docs/getting-started.md`、
  `docs/architecture/index.md`）：`type=` / `TypeConflictError` / 按存在性挑值文件 /
  `__all__` 符号数 / `op=overwrite` / 词表记类型。
- **路线图重做**：[`docs/roadmap/`](docs/roadmap/index.md) 按版本分开 ——
  [1.0.x](docs/roadmap/1.0.x/roadmap.md) 记 v1.0.0 实际交付的能力、
  [2.0.x](docs/roadmap/2.0.x/roadmap.md) 记下一版收什么；每条固定「标题 / 正文 / 状态 /
  引用设计文稿」四段，不用表格。旧的 `docs/roadmap.md` 与嵌套的 `docs/issues/` 删除，
  文档里指向它们的 D0N / ISSUE-NNN 引用一并清掉；`mkdocs.yml` 导航同步；
  README 一对补一条版本口径 —— **1.0 与 2.0 都是破坏性变更版本，后续以 2.0 为准**。
- **文档口径统一为「只写现代」**：正文里不再出现「以前是…、改成了…、为什么改」这类
  变更叙述，作废 / 已替换 / 曾考虑之类的标记一并去掉（沿革看 git 与本文件）；
  `CONTRIBUTING.md` §8 与 `AGENTS.md` §6 记下这条约定；威胁模型的「修订记录」一节删除。
- **旧设计稿 `docs/design/DESIGN.md` 退役删除**：现役口径就是
  [设计稿索引](docs/design/index.md) 下的三份。源码与测试里指向它的节号引用全部清掉
  （不留悬空编号），`AGENTS.md` §3.4 改成「引用现役设计稿的文件名 + 小节」；
  `mkdocs.yml` 导航、codespell / markdownlint 的排除项、PR 与 issue 模板同步。
- 新增[命令行设计页](docs/design/cli.md)：把命令行矩阵从退役归档按**现行口径**重裁 ——
  九条命令的语义与分工、统一约定（`--dry-run` 零字节、退出码、`--json` 同源、不做交互选择）、
  破坏性操作的形态，以及它与运行中进程的关系。路线图命令行条目的「设计关联文件」不再指向
  「还没落地的部分」清单。

## [1.0.0] - 2026-10-04

首个稳定版，也是首个发布到 PyPI 的版本（发布名 `OnConf`）。相对 0.1.0 的工作区状态，这一版
把定位句的两个半句都落成了机制：「不丢一个字节」依旧是外科手术式回写；「不丢一次更新」交给
**专职写者**。落盘变成原子的，日志与审计成为强制面，值后端补齐了 TOML 与 `.env`。

**注意：这一版的包元数据与 README 正文是发布前打包进去的快照** —— PyPI 上 1.0.0 的
classifier 仍是 `Development Status :: 2 - Pre-Alpha`，页面正文也还写着「Pre-Alpha（`0.1.0`）
—— 只可用于评估，不要上生产」与「尚未发布到 PyPI」。PyPI 不允许修改已发布版本的元数据，
这些修正会随下一个版本生效。

### Added

- `.env` 字符串后端：值只能是字符串，不做键名映射，不认行内注释（`#` 出现在值里时就是值的
  一部分）；非字符串值当场拒绝并指路 JSON / YAML（`0820359`）。
- 协议与文档周边：`mkdocs.yml`、`docs/` 站点骨架、`CHANGELOG.md`、
  `THIRD_PARTY_NOTICES.md` 及其生成脚本 `scripts/gen_third_party_notices.py`。
- TOML 值后端；词表的 JSON Schema 往返与声明集哈希短路。
- 跨进程排他锁：操作系统级锁（Windows `msvcrt.locking`、其它 `fcntl.flock`），进程崩溃由
  OS 释放，不留死锁文件（`bbab1a8`）。
- 可选攒批窗口 `flush_window`；**默认 `0`**，即当场落盘，窗口按需开启（`bbab1a8`）。
- **专职写者**：谁先抢绑到配置目录的端点，谁就是唯一的读写者，其余进程经
  `multiprocessing.connection` 发请求。**抢绑本身就是选举**，所以不涉及锁文件
  （`62f46db`、`20f47b5`）。
- **原子写**：同目录临时文件 → `fsync` → `os.replace`（POSIX 再加父目录 `fsync`），并沿用
  文件原本的行尾与权限位；新建文件是 `0600`（`20f47b5`）。
- **日志与审计**（DESIGN §20 / §21）：强制 `[Read]` / `[Write]` / `[Change]` / `[Error]`
  事件流，外加进程结构三行 `[Start]`（引擎起来）/ `[Link]`（`op=bind` 成了写者 /
  `op=connect` 连上写者 / `op=fallback` 就地执行）/ `[Send]`（一次请求真的过了 IPC）；
  去向可改（`log="stderr"` 默认 / `"stdout"` / 文件路径）、**不可关闭**；写全量（含
  `op=skip`「想改没改」与 `op=noop`「本批声明已满足」）、读按事务去重（`n=<次数>`）；
  写记录带**调用点** `at=app/config.py:12`、pid 与可选 `identity=`；终端按**显示宽度**
  做弹性制表位对齐（中文不偏列），文件形态紧凑且**永不截断**；`audit=True` 追加写
  append-only 的 `<home>/audit.log`（`0600`、按大小轮转）。

### Changed

- 引擎参数增加 `log`（日志去向）与 `identity`（写进每行的 `服务@主机` 标记）；
  `audit=` 不再是「被接受但不产生行为」的参数 —— 它现在真的会写审计文件。
- **破坏性变更**：日志级别名从单字母改成完整词（`[R]`→`[Read]`、`[W]`→`[Write]`、
  `[C]`→`[Change]`、`[E]`→`[Error]`），并新增 `[Start]` / `[Link]` / `[Send]`。
  解析日志的脚本要跟着改；`[Start]` / `[Link]` / `[Send]` 的 `txn=0` 表示
  「不属于任何配置事务」（客户端与写者各数各的 txn，混在一起会撞号）。
- 版本号的唯一来源定为 `pyproject.toml`，改动一律走 `uv version`（它同时改 `uv.lock`）；
  `release.yml` 新增版本闸门：tag 必须等于 `v<pyproject 版本>`，构建产物也必须带着它。
  发版 runbook 见 `CONTRIBUTING.md` §4.4。
- **发布的触发条件收紧成一条路**：只有推 `v*` tag 才会 build + publish，而且 tag 指向的
  提交必须在 `main` 上 —— 以前只强制 `tag == 版本号`，「在没合并进主分支的提交上打个 tag」
  同样能把包发出去，而 PyPI 上的版本号不可撤回。`workflow_dispatch` 同时从「可以关掉
  dry-run 真发版」改成**只构建**的验证入口：手动触发再也绕不过那三道闸门。
- **项目改名**：`auto-conf` → **OnConf**；仓库、PyPI 发布名、import 名与 CLI 入口统一为
  `onconf`。历史提交信息里的旧名保留不动 —— 改它只能重写历史，收益不抵风险。
- 仓库与文档站地址统一成**真实大小写**：`github.com/HanYang06/OnConf`、
  `hanyang06.github.io/OnConf/`。OpenSSF Scorecard 的接口**大小写敏感**（实测
  `/OnConf` 返回 200、`/onconf` 返回 404），README 上那枚徽章原本是坏的；Pages 的
  `site_url` 写错大小写则会让站点产出的规范链接与 sitemap 指到 404（Pages 已确认是
  `build_type: workflow`、`html_url: https://hanyang06.github.io/OnConf/`）。
- **破坏性变更**：词表字段 `x-auto-conf-hash` → `x-onconf-hash`（**磁盘格式变更**，
  旧字段名不再被识别，会在下次落盘时按新名重写）。
- **破坏性变更**：环境变量 `AUTO_CONF_HOME` → `ONCONF_HOME`（旧变量不再生效）。
- 攒批窗口的默认值**反过来**：「攒批」改成「当场落盘」（`bbab1a8`，理由见 DESIGN §30）。
- 攒批窗口挂在**客户端**侧，不搬到写者身上 —— 窗口挪到写者的话，客户端显式配的
  `flush_window` 会被静默忽略（`20f47b5`）。
- 写者的认证从 `multiprocessing` 的 `authkey=` 搬到应用层：`authkey=` 的挑战应答**没有
  超时**，端点上「有人听、没人答」时 `conf()` 会挂死（`62f46db`）。
- 定位句定稿（`8df316b`）；`README` 拆成英文 / 中文两份（`97267f5`）；跨进程锁交付后的
  威胁模型翻案（`21ce60d`）。

### Fixed

- 指令键（`$` 开头）豁免对账，`$schema` 不会被规则 1 清掉（`787360e`）。
- 三态哨兵补 `__reduce__`：没有它，`MISSING` 过 IPC 会被 pickle 重建成**另一个对象**，
  `is MISSING` 恒为假 —— 「只登记不给值」会静默变成「给了一个哨兵当值」（`62f46db`）。
- `Listener.close()` 关不掉正在 `accept()` 的那个 handle，端点名因此不消失、下一个进程
  永远抢绑不到。顺序改为「举旗 → 关会话连接 → 空连接叫醒 → join → **最后才** close」
  （`62f46db`）。
- 写者原本**串行服务**连接：客户端 A 的整条会话把端口堵死，客户端 B 连得上却没人跟它握手。
  改为一条连接一个会话线程（`20f47b5`）。
- `authkey_for` 先建后写留下空文件窗口，并发读者会读到空字符串、两把钥匙分叉。改用
  `os.link`（`62f46db`）。
- 日志与审计在对抗性复核后修掉的一批（都是「记录说的跟实际发生的不是一回事」）：
  审计文件写失败不再**盖住**原始异常（类型冲突 / 键不存在照原样抛）；
  远端失败会在**发起方**自己的日志里也留一条 `[Error]`（原来只有执行点那侧有）；
  客户端不再把同一次读补两遍（`n=1` 之后又 `n=2`），与审计文件的那一行一致；
  `OSError`（盘满、没权限）也会留痕；审计输出与日志输出**互不牵连**（日志去向坏掉
  不再毁掉审计那一批）；`identity` 不再被写者的服务名顶替；键名 / 身份里的换行
  不再能伪造审计行；`os.write` 的短写不再静默截断记录。
- macOS（以及任何路径偏深的 POSIX 环境）上专职写者**静默失效**：端点名是
  `<home>/schema/settings.sock`，一超过 `AF_UNIX` 的 `sun_path` 上限（104 字节）
  `ipc.Listener` 就抛错，而 `_attach` 是尽力而为的 —— 表现只是所有请求退到就地执行。
  现在超限就换短名字的临时端点（`<tmpdir>/onconf-<uid>/`，`0o700`），名字仍只由配置
  目录决定（DESIGN §32.9）。
- 清残留的探活原本是**打一次招呼**：写者一忙（正在做一轮读改写），那句问候就等到超时
  被读成「没人」，于是**活写者的端点被当成残骸删掉**，下一个进程绑上来就是两个写者写
  同一个目录。改成纯 `connect`（3.14 的 `Client(authkey=None)` 不做挑战应答）。
- 端点所在目录现在**显式创建**：`bind` 不会替你建 `<home>/schema`，`ENOENT` 会被
  `claim` 翻译成「抢不到」—— 而这一步以前靠 `claim` 顺手调 `authkey_for` 的 `mkdir`
  兜着（写者本来就会自己读钥匙，那个调用一挪走，Linux 上第一个写者都当不上、所有请求
  退到就地执行，16 条测试一起倒）。macOS 反而看不见：那边走了短端点。
- `release.yml` 的产物校验用了 `ls dist/ | grep -c`：shellcheck `SC2010`（文件名里有
  空格/换行时还会数错），改成逐个文件的 glob 计数。
- `Security` 作业没给 gitleaks-action v3 传 `GITHUB_TOKEN`，也没给作业级
  `pull-requests: read` —— PR 上一律以
  "GITHUB_TOKEN is now required to scan pull requests" 失败。

### Known issue

- 「跨进程规则 1」（清理未知键）只在写者**长命**时成立：写者的声明集不是持久状态，写者
  一换人基准就重置。进程起一个退一个的用法仍不安全 —— 相关取舍见 DESIGN §32.4 与
  [路线图](docs/roadmap/index.md)。
- 写者进程内**自己**的调用与它的应答线程没有共用同一把锁：文件一致性由 OS 锁兜着，
  但其中一边可能等满 `lock_timeout`，引擎内存态在那个窗口里可竞争。没有回归测试守护，
  见[威胁模型](docs/security/threat-model.md) T4 的残余风险与 DESIGN §32.8 的「已知边界」。
- 同一配置目录上若**第二个进程**也开 `audit=True`，它的本地记录会进同一个
  `<home>/audit.log`，而 `txn` 按进程编号 —— 文件里可能出现两个同号批次
  （DESIGN §32.8 的「已知边界」）。

## [0.1.0] - 2026-10-04

首个版本。公开 API 收敛为两个面（`AutoConf` / `conf`），JSON 与 YAML 两个值后端可用，
提交点是「立即落盘 + `atexit` 收口」。开发状态为 Pre-Alpha。

### Added

- 仓库骨架：`pyproject.toml`、`uv.lock`、包入口、`.python-version`（`3ef3f4f`）。
- 纯内存核心：对账四条规则、读取五步、声明集哈希（`b6f8433`）。
- 异常族 `ConfError` / `KeyNotRegistered` / `KeyHasNoValue` / `TypeConflict` /
  `UnknownEngineParam`：读取错误按「键名写错」与「部署漏配」分开，调用方可用 `except` 区分
  （`b6f8433`）。
- 词表：三态持久化 + JSON Schema 往返 + 哈希短路（`9a4dd3c`）。
- JSON 值后端：外科手术式回写，未触及的字节逐字不动（`3f49615`）。
- YAML 值后端：注释 / 缩进 / 键序逐字保留（`832b158`）。
- 引擎装配：`conf` / `AutoConf` 两个面接通，声明到读回端到端可用（`007af1e`）。
- 支持用值当键（间接寻址）；`$schema` 指针每次落盘都保证存在（`988d5df`）。
- `.editorconfig`（`19d4373`）。

### Changed

- 新增设计文档 `DESIGN.md`，随后移入 `docs/design/` 作为唯一归属（`7a78a4e`、`c05fc06`）。
- YAML 词表复用同一套 JSON Schema，差别只在「怎么指向」（`1986b90`）。

### Fixed

- 指令键（`$` 开头）豁免对账，`$schema` 不会被规则 1 清掉（`787360e`）。

[Unreleased]: https://github.com/HanYang06/OnConf/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/HanYang06/OnConf/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/HanYang06/OnConf/compare/3ef3f4f...v1.0.0
[0.1.0]: https://github.com/HanYang06/OnConf/compare/3ef3f4f...d166050

`v0.1.0` **从未打过 tag、也从未发布**，所以它只能按提交区间比对（`3ef3f4f...d166050`）；
`v1.0.0` 的对比基准因此也退回同一个起点。详见 `CONTRIBUTING.md` §4.4 的版本闸门。

未发布能力见 [2.0.x 路线图](docs/roadmap/2.0.x/roadmap.md)。
