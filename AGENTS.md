# AGENTS.md —— 给编码代理的项目须知

> 权威协作规范在 [CONTRIBUTING.md](CONTRIBUTING.md)。本文件是它的**可执行摘要**：
> 命令、硬性约定、以及最容易踩的坑。两者冲突时以 `CONTRIBUTING.md` 与仓库配置
> （`pyproject.toml` / `.pre-commit-config.yaml` / CI）为准。

## 1. 项目是什么

**OnConf**（发布名 / import 名 / CLI 入口统一为 `onconf`；本目录名 `auto_conf` 与历史
提交里的 `auto-conf` 是**改名前的旧名**，不要再用）是一个**基于本地文件的进程内配置引擎**。

- 不是服务、不走网络；单机运行，但多进程同时读写不丢更新；
- 核心语义是「**文件绝对优先**」：代码不权威，代码只发出写请求；
- 回写是**外科手术式**的：未被触及的字节（注释、缩进、键序、空行）逐字不动。

Python `>=3.14`，不做低版本兼容分支。构建后端 `uv_build`，依赖与虚拟环境一律用 `uv`。

**定位句是定稿的**（`README.md` 顶部）：

> Configuration has no verbs: one name reads and writes it, in both directions, without losing a byte or an update.

改它必须**同一提交内**同步 5 处：`README.md`、`README.zh-CN.md`、`pyproject.toml` 的
`description`、`mkdocs.yml` 的 `site_description`、`docs/index.md`。

## 2. 命令（原样使用，不要自行换工具链）

```bash
uv sync --all-groups                          # 安装全部依赖（dev + docs 组）
uv run pytest                                 # 单元测试
uv run pytest --cov --cov-report=term-missing # 带覆盖率（门槛 90%，见下）
uv run ruff check --fix .                     # lint 并自动修复
uv run mypy                                   # 严格类型检查（files = src, tests）
uv run ruff format .                          # 格式化（manual，见 §5 坑 1）
uv run pre-commit run --all-files             # 本地全量检查
uv run mkdocs serve                           # 文档站预览
uv version --short --frozen                   # 读版本号（只读，不动 lock/venv）
uv version --bump patch                       # 自增版本（同时改 pyproject + uv.lock）
```

发版前：`uv run bandit -c pyproject.toml -r src`、`uv run pip-audit`、
`uv run zizmor .github/workflows`、`uv build`。

**版本号只有一个来源**：`pyproject.toml` 的 `[project] version`，改动一律走 `uv version`
（`--bump patch|minor|major`、预发布写全 `0.2.0rc1`、`--bump rc`、`--bump stable`）。
它**不打 git tag** —— tag 手工打，且 CI 会强制 `tag == v<pyproject 版本>` **并且 tag 指向的
提交已在 `main` 上**；**只有推 tag 才会发布**（`workflow_dispatch` 是只构建的验证入口，
不会发版）。
完整 runbook 见 `CONTRIBUTING.md` §4.4。

本机已装 `uv`（`C:\Users\Hy06\.local\bin\uv.exe`）。**不要**用 `pip install`、不要绕过
`uv run` 去调 `.venv/Scripts/*.exe`——工具版本唯一来源是 `uv.lock`。

## 3. 硬性约定（新增/修改文件必读）

### 3.1 许可头 —— 漏了 CI 就红

**每个** Python 文件（含 `tests/` 与 `scripts/`）最顶部逐字写这两行，紧接着就是模块
docstring，中间不空行：

```python
# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
```

由 ruff 的 `CPY` 规则强制执行（`notice-rgx`，`min-file-size = 1`）。顺序、`#` 后空格、
年份 `2026` 都不能改。

### 3.2 类型与文档

- **所有函数（含私有函数）必须完整注解**，参数与返回值都不许省；测试文件的宽松豁免
  由 `pyproject.toml` 里的 per-module override 给出。
- mypy 是 `strict = true` + `warn_unreachable` + `extra_checks`。
  **不要用 `# type: ignore` 掩盖问题**；万不得已必须写成带错误码的窄形式
  （`# type: ignore[no-any-return]`）并就近说明原因。
- 公共 API 必须有中文 docstring（Google convention），写清「做什么、返回什么、抛什么」。
- `Any` 只允许出现在语义上真的任意的位置（配置 value 就是任意 JSON/YAML 值）。

### 3.3 行尾与格式

- **全仓 LF**，UTF-8 无 BOM，文件末尾有且仅有一个换行。
  即使本机 `core.autocrlf=true` 也不要提交 CRLF。
- 行宽 100；quote `double`；import 排序交给 `ruff check --fix`（`known-first-party = ["onconf"]`）。
- ruff lint 的 select 列表很长（A/ANN/BLE/C90/D/DTZ/EM/PERF/PL/PT/RUF/S/TRY/UP…）。
  `RUF001/002/003`（中文标点判为 ambiguous-unicode）与 `D400/D415`、`EM101/102`、
  `TRY003`、`ANN401`、`PLR0913` 是**有意豁免**的，不要"顺手修好"。

### 3.4 代码里的 `§` 引用

源码中约 76 处注释/文档串引用设计草案的节号（如 `（§32.4）`、`DESIGN §15.4`），
指向 [docs/design/DESIGN.md](docs/design/DESIGN.md)（1136 行中文，**意图的权威**，
不是状态的权威）。新增/改动涉及设计取舍的逻辑时，沿用这个引用习惯；
**改动 DESIGN.md 必须在 PR 里单独说明理由**。

## 4. 测试

- **行为变更必须带测试**，没有测试的行为变更不会被合并。
- 测试文件命名 `test_*.py`、用例 `test_*`，放 `tests/`；`tests/` **没有 `__init__.py`**
  （`--import-mode=importlib`）。
- `filterwarnings = ["error"]`：任何 `DeprecationWarning` / `ResourceWarning` 都当场变红。
  断言异常用 `pytest.raises(..., match=...)`（`PT011` 已豁免，不强制）。
- 涉及文件系统/并发的用例**必须用 `tmp_path`**，不要污染仓库根目录，也不要依赖 CWD；
  并发要**真的起多进程**验证"不丢更新"，不要在单进程里模拟。
- 涉及回写的用例，除了断言最终值，还要断言**未被触及的字节逐字不变**（注释、缩进、键序）。
- **覆盖率门槛 90% 由 CI 强制**（当前实测 93.95%）。不要靠排除文件或
  `# pragma: no cover` 凑数。

## 5. 最容易踩的坑

1. **`ruff format` 只在 manual 阶段。** 团队约定暂不重排既有文件；CI 的
   `ruff format --check` 是 `continue-on-error`。别在无关改动里全量格式化，
   也别忘了**新增代码仍应按 format 的风格写**。
2. **新增测试文件必须补 `pyproject.toml` 的 mypy override 名单。**
   `tests/` 没有 `__init__.py`，mypy 把它们当**顶层模块**（`test_core` 而非
   `tests.test_core`），所以 `"tests.*"` 匹配不到、`"test_*"` 这种部分通配 mypy 也不接受
   ——只能逐个列在 `[[tool.mypy.overrides]]` 的 `module = [...]` 里。漏了就是
   "unused section" 或严格模式报错。
3. **不要 `git commit --no-verify`。** CI 会重跑同一套检查，绕过去只是把问题推到 PR。
4. **`.env` 与运行时产物绝不入库。** 特别注意引擎自己的 env 值文件叫 `settings.env`
   （**不匹配** `.gitignore` 里的 `.env` / `.env.*` 模式）。
   另外 `/conf/`、`*.wal`、`audit.log` / `audit-*.log` 都是运行痕迹，不是源码。
5. **Windows 上环境变量大小写不敏感**；`.env` / 系统环境变量后端要覆盖大小写归一化，
   不要指望大小写区分两个键。文件锁与 OneDrive / 网盘同步目录会打架，并发测试别放那儿。
6. **`mkdocs.yml` 被 `check-yaml` 排除是必须的**，且不能用 `--unsafe` 解决
   （`pymdownx.superfences` 的自定义围栏标签会让安全加载器失败）。权威校验走
   `mkdocs build --strict`。
7. 依赖版本改动请走 `uv add` / `uv lock`，不要手写 `uv.lock`。

## 6. 文档同步（用户可见变更的硬要求）

- 行为变了、`docs/` 没变 ⇒ PR 视为**未完成**；
- `README.md`（英文）与 `README.zh-CN.md`（中文）是**一对，改一份必须同步另一份**；
- `README.md` 的「Currently implemented」与「Roadmap」表是**状态声明**，交付新能力或
  关闭/打开限制时同步更新；安全不变量变更还要同步
  [docs/security/threat-model.md](docs/security/threat-model.md)；
- Markdown 受 markdownlint 约束：标题层级不跳级、代码块标语言、列表缩进一致。

## 7. 结构速查

```text
src/onconf/
  __init__.py        # 对外仅两个面：AutoConf(**engine) 与 conf(key, value=…, doc=…)
  _engine.py         # 引擎装配、目录约定、回写
  _core.py           # 对账：三集合算法
  _vocab.py          # 词表 + JSON Schema
  _textscan.py       # 各后端共用的字节级扫描
  _lock.py           # 跨进程 OS 锁（兜底路径；LockTimeoutError 定义在这里）
  _owner.py          # 专职写者：端点选举、IPC、写循环
  _audit.py          # 强制日志 + append-only 审计（DESIGN §20 / §21）
  _json_backend.py / _yaml_backend.py / _env_backend.py / _toml_backend.py
  errors.py          # 错误分类（EnvSyntaxError 等是 ValueError 子类，不是 ConfError）
tests/               # 每模块一个文件 + test_security_invariants.py
scripts/gen_third_party_notices.py   # --check 模式在 CI lint job 里强制
docs/                # 文档站源（中文）
```

`src/onconf/` 本身是模块清单的权威；README 的布局树是派生视图。

## 8. 提交

Conventional Commits，**subject 用中文、不以句号结尾、一个提交只做一件事**；
范围用英文小写（`core` / `engine` / `vocab` / `yaml` / `json` / `env` / `owner` / `ci` / `docs`）。
破坏性变更加 `!` 并在脚注写 `BREAKING CHANGE:`。

分支规范见 `CONTRIBUTING.md` §5.1（从 `main` 切，形如 `feat/env-backend`）。**`main` 不能
直推**：服务端 ruleset `main` 禁止删除与强推，并且要求 CodeQL 对目标提交给出结果，而
CodeQL 只在「推 `main`」和「针对 `main` 的 PR」上跑 —— 直推因此必然被拒
（`GH013 … Code scanning is waiting for results from CodeQL`，实测踩过）。改动一律走
「推分支 → 开 PR → 等 CI / CodeQL → 合并」；`.pre-commit-config.yaml` 里没有
`no-commit-to-branch`，那只是本地钩子的取舍，**不代表允许直推**。

**合并方式固定为 merge commit**：仓库设置里 squash 与 rebase 都已关闭，`gh pr merge`
只可能走 `--merge`。不要用 `git merge --ff-only` / `git rebase` 自己把分支推平 ——
`merge commit` 是「这个 PR 从分支进来」这条事实的唯一载体，推平了历史就看不见分支状态。
口令：`gh pr merge <n> --merge --delete-branch`。
