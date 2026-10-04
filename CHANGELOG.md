# 变更日志

本文件记录 onconf 的所有重要变更。

格式遵循 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

本文件自 v0.1.0 起**人工维护**；v0.1.0 的历史条目由真实 git 提交整理
（`git log --oneline --no-merges`，整理范围至 `988d5df`），每一条都对应一个真实提交，
不是事后补写的愿景。尚未发布的能力与进度见 [docs/roadmap.md](docs/roadmap.md)。

## [Unreleased]

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
  [docs/roadmap.md](docs/roadmap.md)。
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

[Unreleased]: https://github.com/HanYang06/OnConf/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/HanYang06/OnConf/compare/3ef3f4f...v1.0.0
[0.1.0]: https://github.com/HanYang06/OnConf/compare/3ef3f4f...d166050

`v0.1.0` **从未打过 tag、也从未发布**，所以它只能按提交区间比对（`3ef3f4f...d166050`）；
`v1.0.0` 的对比基准因此也退回同一个起点。详见 `CONTRIBUTING.md` §4.4 的版本闸门。

未发布能力见 [docs/roadmap.md](docs/roadmap.md)。
