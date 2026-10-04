# 变更日志

本文件记录 onconf 的所有重要变更。

格式遵循 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

本文件自 v0.1.0 起**人工维护**；v0.1.0 的历史条目由真实 git 提交整理
（`git log --oneline --no-merges`，整理范围至 `988d5df`），每一条都对应一个真实提交，
不是事后补写的愿景。尚未发布的能力与进度见 [docs/roadmap.md](docs/roadmap.md)。

## [Unreleased]

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
- **日志与审计**（DESIGN §20 / §21）：强制 `[R]` / `[W]` / `[C]` / `[E]` 事件流，去向可改
  （`log="stderr"` 默认 / `"stdout"` / 文件路径）、**不可关闭**；写全量（含 `op=skip`
  「想改没改」与 `op=noop`「本批声明已满足」）、读按事务去重（`n=<次数>`）；写记录带
  **调用点** `at=app/config.py:12`、pid 与可选 `identity=`；终端按**显示宽度**做弹性制表位
  对齐（中文不偏列），文件形态紧凑且**永不截断**；`audit=True` 追加写 append-only 的
  `<home>/audit.log`（`0600`、按大小轮转）。

### Changed

- 引擎参数增加 `log`（日志去向）与 `identity`（写进每行的 `服务@主机` 标记）；
  `audit=` 不再是「被接受但不产生行为」的参数 —— 它现在真的会写审计文件。
- **项目改名**：`auto-conf` → **OnConf**；仓库、PyPI 发布名、import 名与 CLI 入口统一为
  `onconf`。历史提交信息里的旧名保留不动 —— 改它只能重写历史，收益不抵风险。
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

### Known issue

- 「跨进程规则 1」（清理未知键）只在写者**长命**时成立：写者的声明集不是持久状态，写者
  一换人基准就重置。进程起一个退一个的用法仍不安全 —— 相关取舍见 DESIGN §32.4 与
  [docs/roadmap.md](docs/roadmap.md)。

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

[Unreleased]: https://github.com/HanYang06/onconf/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/HanYang06/onconf/compare/3ef3f4f...v0.1.0

未发布能力见 [docs/roadmap.md](docs/roadmap.md)。
