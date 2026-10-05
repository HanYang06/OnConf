# 贡献指南

感谢你愿意为 onconf 花时间。本文说明本项目的协作方式、开发环境、检查流程与提交规范。

参与本项目之前，请先阅读 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)（Contributor Covenant 2.1 简体中文译本）。
提交 Issue、参与讨论、提交 Pull Request，都视为你已同意遵守该行为准则。

---

## 1. 项目速览

onconf 是一个**基于本地文件的、进程内使用的配置引擎**，对外只暴露一个入口。

- 不是服务，不是配置中心，**不走网络**；
- 单机运行，但**多进程 / 多实例同时读写安全**（不丢更新）；
- 核心语义是「**文件绝对优先**」：代码不权威，代码只是发出写请求；
- 回写采用**外科手术式**方式：未被触及的字节逐字不动，用户的注释、缩进、键序都要保住。

一些必须先建立的预期：

| 项 | 值 |
|---|---|
| 发布名（PyPI） | `onconf` |
| import 名 | `onconf` |
| CLI 入口 | `onconf` |
| Python 版本 | `>=3.14` |
| 构建后端 | `uv_build` |
| 包与虚拟环境管理 | `uv`（`uv.lock` 已提交） |
| 开源协议 | Apache-2.0（见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)） |
| 文档站 | <https://hanyang06.github.io/OnConf/> |
| 仓库 | <https://github.com/HanYang06/OnConf> |

> 展示名写作 **OnConf**（概念与项目身份）；仓库名、PyPI 发布名、import 名与 CLI 入口
> 统一为 `onconf`。历史提交里出现的 `auto-conf` / `auto_conf` 是改名前的旧名，不再使用。

---

## 2. 开发环境搭建

### 2.1 安装 uv

本项目的依赖、虚拟环境、构建全部由 `uv` 管理。请先按官方方式安装 `uv`：

#### Windows（PowerShell）

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

#### macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装完成后确认：

```bash
uv --version
```

### 2.2 克隆与安装

```bash
git clone https://github.com/HanYang06/OnConf.git
cd onconf
uv sync --all-groups
```

`uv sync --all-groups` 会安装**全部依赖**（含 `dev` 与 `docs` 组）。

Python 版本由仓库根目录的 `.python-version` 钉死为 `3.14`。如果你本机没有这个解释器，
让 uv 自己装一个即可：

```bash
uv python install 3.14
```

`requires-python = ">=3.14"`。请不要为了兼容更低的 Python 版本而写兼容分支：
本项目**只支持 3.14 及以上**。

### 2.3 三个平台各自的注意事项

#### Windows

- 本机常见配置是 `core.autocrlf=true`，但本仓库**统一 LF 行尾**。
  `.gitattributes` 里的 `* text=auto eol=lf` 优先级高于 `core.autocrlf`，
  `.editorconfig` 里也固化了 `end_of_line = lf`。**不要提交 CRLF 文件**，
  也不要把编辑器改成 CRLF。
- 配置文件必须放在**本地普通目录**：文件锁与杀毒软件、OneDrive / 网盘同步目录会打架。
  并发相关的测试尤其不要把工作目录设在被同步的目录里。
- Windows 上**环境变量大小写不敏感**。涉及 `.env` 或系统环境变量后端时，
  请用测试覆盖大小写归一化，不要依赖大小写区分两个键。

#### macOS

- 默认文件系统大小写不敏感，文件名大小写相关的用例要显式小心中毒。
- 并发测试请在本地磁盘（`/tmp` 或仓库内临时目录）进行，不要放在网络挂载卷上。

#### Linux

- 关注权限位：只有写者的认证码文件 `schema/settings.key` 被显式收紧到 `0600`
  （`_owner.authkey_for` 在 `os.link` 之前 `chmod`，硬链接共享 inode）。
  端点本身是 `ipc.Listener`（Windows 命名管道 / POSIX 下 `schema/` 里的 socket 文件），
  库没有给它设权限位。
- CI 使用 `ubuntu-latest`，本地能过、CI 不能过时，优先看时区、语言环境（`LC_ALL`）
  与文件系统大小写差异。

三个平台的组合在 CI 中都会被覆盖：

| 平台 | Python |
|---|---|
| `ubuntu-latest` | 3.14 |
| `windows-latest` | 3.14 |
| `macos-latest` | 3.14 |

---

## 3. Git hooks

本项目使用 **pre-commit 框架**管理 Git hooks。

### 3.1 安装

```bash
uv run pre-commit install --install-hooks
```

`--install-hooks` 会顺带把 hook 环境装好，避免你第一次提交时现场下载。

### 3.2 提交前会发生什么

执行 `git commit` 时，pre-commit 会依次跑这些钩子（多数只看**本次改动的文件**）：

- 行尾与空白字符检查 —— 确认文件是 UTF-8、LF 行尾、文件末尾有且只有一个换行；
- 文件完整性检查 —— 大文件、私钥、冲突标记、YAML / TOML / JSON 语法；
- `ruff check` —— lint（含自动修复）；
- `mypy` —— 严格类型检查（`--strict`，配置见 `pyproject.toml`）；
- `codespell` —— 拼写检查；
- `bandit` —— `src/` 安全静态扫描；
- `zizmor` —— GitHub Actions 安全审计。

还有几个钩子挂在**别的阶段**，不在 `git commit` 的主流程里：

- `conventional-pre-commit` —— 挂在 `commit-msg` 阶段，校验提交信息符合 Conventional Commits；
- `ruff format` —— **只在 manual 阶段**（`.pre-commit-config.yaml` 里写死 `stages: [manual]`）：
  团队约定暂不重排既有排版，要跑得显式调
  `uv run pre-commit run ruff-format --hook-stage manual --all-files`；
- `pip-audit` 与 `mkdocs-build` —— 同样是 manual 阶段；`pytest` 挂在 `pre-push`。

任何一项失败，提交就会被拦下。这是**预期行为**，不是环境坏了：

- hook 自动改了文件（`ruff check --fix` / 行尾修正）⇒ 改动留在工作区，
  你确认后再 `git add` 一次、重新提交即可；
- hook 报了无法自动修的问题 ⇒ 按提示改代码，然后重新提交。

**不要用 `git commit --no-verify` 绕过 hooks。** CI 会再跑一遍同样的检查，
绕过去只会把问题推迟到 PR 上。

### 3.3 手动跑

```bash
uv run pre-commit run --all-files
```

---

## 4. 常用命令

以下命令是项目的**确切开发命令**，请原样使用。

### 4.1 日常

```bash
uv sync --all-groups                          # 安装全部依赖（含 dev 与 docs 组）
uv run pytest                                 # 单元测试
uv run ruff check --fix .                     # lint 并自动修复
uv run ruff format .                          # 格式化
uv run mypy src tests                         # 严格类型检查
uv run mkdocs serve                           # 本地预览文档站
```

### 4.2 提交前

```bash
uv run pre-commit install --install-hooks     # 安装 git hooks
uv run pre-commit run --all-files             # 手动跑全部检查
uv run pytest --cov --cov-report=term-missing # 带覆盖率
```

### 4.3 发版前

```bash
uv run bandit -c pyproject.toml -r src        # 安全静态扫描
uv run pip-audit                              # 依赖漏洞审计
uv run zizmor .github/workflows               # GitHub Actions 安全审计
uv build                                      # 构建 sdist/wheel
```

### 4.4 版本号：唯一来源是 `pyproject.toml`，改动一律走 `uv version`

**版本号只有一个来源**：`pyproject.toml` 里 `[project] version`（因此它必须保持**静态**，
不能改成 `dynamic`）。改动走 `uv version` —— 它按语义化版本自增，并且会**同时**改好
`pyproject.toml` 与 `uv.lock` 里本项目的版本，两处必须进同一个提交（否则 CI 的
`--frozen` 会直接失败）。

```bash
uv version --short --frozen        # 现在是哪个版本（只读，不动 lock、不建虚拟环境）
uv version --bump patch --dry-run  # 先看会变成什么
uv version --bump patch            # 0.1.0 → 0.1.1（minor / major 同理）
uv version 0.2.0rc1                # 进预发布：显式写全（RC/beta/alpha 都这么写）
uv version --bump rc               # 预发布内部自增：0.2.0rc1 → 0.2.0rc2
uv version --bump stable           # 转正：0.2.0rc2 → 0.2.0
uv version --output-format json    # 给脚本读：{package_name, version, commit_info}
```

!!! warning "`uv version` 不会打 git tag"

    它只管版本号。tag 是紧接着的手工动作，而且 CI 会**强制两者一致**：

```bash
uv version --bump minor                          # 1) 改版本（pyproject + uv.lock）
git add pyproject.toml uv.lock CHANGELOG.md      # 2) CHANGELOG 的 [Unreleased] 收成新版本
git commit -m "chore(release): 0.2.0"
git tag -a v0.2.0 -m "0.2.0"                     # 3) tag 必须等于 uv version --short
git push origin main --follow-tags               # 4) 推 tag 触发 release.yml
```

`release.yml` 的 `version` job 有三道闸门，任一不过则 build 与 publish 都不跑：

| 闸门 | 要求 |
|---|---|
| tag 与版本号 | tag 必须正是 `v<pyproject.toml 里的版本>`（`uv version --short`） |
| tag 落在哪 | tag 指向的提交必须在 `main` 上 —— **先合并到主分支，再在 main 的提交上打标签** |
| 产物命名 | 构建后 `dist/` 里必须同时有带着该版本号的 sdist 与 wheel |

这样「tag 是 v0.2.0、包里其实还是 0.1.0」和「在没合并的分支上打个 tag 就发版」两种发布
都出不了门 —— PyPI 上的版本号是不可撤回的。

**发布只有一个入口：推 `v*` tag。** `workflow_dispatch` 是**只构建**的验证入口
（版本解析 → 构建 → 产物校验 → 来源证明），它没有任何「发布」模式 —— 手动点什么都不会
发版，这样手动入口就不可能把上面三道闸门绕过去。仓库侧还可以给 `pypi` environment 加一条
「只允许 `main` 部署」的分支保护规则当第二道锁。

发版时还要把 `CHANGELOG.md` 的 `[Unreleased]` 收成 `## [x.y.z] - YYYY-MM-DD`，
并在文件末尾补上对应的对比链接。

#### PyPI 侧：Trusted Publisher 要注册什么

`publish` job 用 OIDC（trusted publishing）换一次性上传凭据，**PyPI 上没有对应记录就直接
拒绝**，报 `invalid-publisher: valid token, but no corresponding publisher`。要登记的值
必须与 OIDC token 里的 claims 对齐：

| PyPI 字段 | 填什么 | 说明 |
|---|---|---|
| PyPI Project Name | `onconf` | 项目名；**项目还不存在时只能用 pending publisher**，由第一次成功上传创建 |
| Owner | `HanYang06` | claim 里的 `repository_owner`；PyPI 对它是**大小写敏感**的 `str.__eq__` |
| Repository name | `OnConf` | claim 里的 `repository`（`HanYang06/OnConf`）；这一项 PyPI 折叠大小写 |
| Workflow name | `release.yml` | **只填文件名**，不要带 `.github/workflows/` 路径 |
| Environment name | `pypi` | 与 `publish` job 的 `environment:` 一致；PyPI 折叠大小写 |

登记入口：已有项目走 project → Settings → Publishing；**首次发布走
<https://pypi.org/manage/account/publishing/> 的 pending publisher**。

踩过的两个坑，记在这里省得再查一次：

- 仓库改名（`onconf` → `OnConf`）之后 PyPI 侧还留着旧配置 —— PyPI 自己的
  [troubleshooting 文档](https://docs.pypi.org/trusted-publishers/troubleshooting/)
  把「repository 被改名」列为 `invalid-publisher` 的典型原因；
- 修好配置后**不需要重新打 tag**：在原运行上点 **Re-run failed jobs** 就行（`ref` 与
  artifact 都没变，claims 因此完全一致）。

---

## 5. 分支、提交与 PR

### 5.1 分支命名

从 `main` 切出，分支名用「类型 / 短横线描述」的小写形式：

| 前缀 | 用途 | 示例 |
|---|---|---|
| `feat/` | 新功能 | `feat/env-backend` |
| `fix/` | 缺陷修复 | `fix/wal-replay-order` |
| `docs/` | 文档 | `docs/contributing-guide` |
| `refactor/` | 重构（不改行为） | `refactor/engine-split` |
| `perf/` | 性能 | `perf/vocab-hash-shortcut` |
| `test/` | 测试 | `test/multiprocess-flush` |
| `build/` | 构建与依赖 | `build/bump-ruff` |
| `ci/` | CI 与自动化 | `ci/add-zizmor` |
| `chore/` | 杂项 | `chore/editorconfig` |

描述部分用英文短横线写法（因为它同时是 URL 的一部分）；分支名里不要用中文、空格或下划线。

### 5.2 提交信息：Conventional Commits

提交信息采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/) 规范，
**允许中文 subject**（现有历史提交就是中文 conventional 风格）。

格式：

```text
<类型>(<可选范围>): <subject>

<可选正文>

<可选脚注>
```

类型表：

| 类型 | 含义 | 示例 |
|---|---|---|
| `feat` | 新增功能 | `feat(env): .env 后端读写往返` |
| `fix` | 修复缺陷 | `fix(core): 指令键豁免对账` |
| `docs` | 只改文档 | `docs: 补充并发模型说明` |
| `style` | 只改格式（不影响语义） | `style: ruff format 全量重排` |
| `refactor` | 重构（既不修缺陷也不加功能） | `refactor(vocab): 抽出哈希短路` |
| `perf` | 性能优化 | `perf(engine): 惰性导入 rich` |
| `test` | 增删改测试 | `test(engine): 补齐多进程 flush 用例` |
| `build` | 构建系统或依赖 | `build: 升级 uv_build 约束` |
| `ci` | CI 配置与脚本 | `ci: 增加 CodeQL 工作流` |
| `chore` | 其他不改动源码与测试的杂项 | `chore: 加入 .editorconfig` |
| `revert` | 回滚此前的提交 | `revert: 回滚外科手术式回写改动` |

约定：

- **subject 用中文**，不要以句号结尾，不要写「修复了……的问题」这种流水账，直接写做了什么；
- 范围（scope）用英文小写，例如 `core` / `engine` / `vocab` / `yaml` / `json` / `env` / `ci` / `docs`；
- **破坏性变更**：在类型后加 `!`（例如 `feat(core)!: 移除旧的对账开关`），
  并在脚注里以 `BREAKING CHANGE:` 开头写清破坏了什么、用户该怎么迁移；
- 一个提交只做一件事。顺手做的格式化、重命名请单独成一个提交。

示例：

```text
fix(core): 指令键豁免对账

$schema 这类以 $ 开头的指令键不参与「清理未知数据」，
否则每次启动都会把 schema 指针删掉。
```

### 5.3 Pull Request 流程

1. 先搜一遍 [Issue 列表](https://github.com/HanYang06/OnConf/issues) 与
   [Discussions](https://github.com/HanYang06/OnConf/discussions)，确认不是重复工作；
   较大的改动（新后端、公开 API 变更、磁盘格式变更）**请先开 Issue 对齐方案**再动手。
2. 从 `main` 切分支，按 §5.1 命名。
3. 写代码、补测试、补文档，按 §5.2 提交。
4. 推送并发起 Pull Request，使用仓库的 PR 模板填写（模板会自动出现在描述框里）。
5. 等待 CI 全绿。CI 的检查档位是**加强档**，包含：

   | 工作流 | job | 内容 |
   |---|---|---|
   | `.github/workflows/ci.yml` | `lint` | ruff check + ruff format --check + codespell + 第三方许可清单校验（`scripts/gen_third_party_notices.py --check`）+ markdownlint |
   | `.github/workflows/ci.yml` | `typecheck` | mypy --strict |
   | `.github/workflows/ci.yml` | `test` | 三平台矩阵 + pytest + 覆盖率 |
   | `.github/workflows/ci.yml` | `security` | bandit + pip-audit + zizmor |
   | `.github/workflows/codeql.yml` | `analyze` | CodeQL |
   | `.github/workflows/dependency-review.yml` | `dependency-review` | 依赖变更审查 |
   | `.github/workflows/docs.yml` | `deploy` | MkDocs → GitHub Pages |
   | `.github/workflows/release.yml` | `build` / `publish` | 构建与 PyPI trusted publishing（**只有 tag 推送会发布**；手动触发只构建） |
   | `.github/workflows/scorecard.yml` | `analysis` | OpenSSF Scorecard |

   检查档位里还包含 **gitleaks**（密钥泄漏扫描）与 **actionlint**（工作流语法检查），
   依赖更新由 **Dependabot** 负责。

6. 至少一位维护者 review 通过后合并。**合并方式只有一种：merge commit**
   （GitHub 上的 “Create a merge commit”）；仓库设置里 squash 与 rebase 都已关闭，
   所以平台层面选不错。理由是**历史要看得见分支**：merge commit 在提交图上留下
   「这个 PR 是从分支进来的」这条事实，`git log --first-parent` 因此是一条干净的
   PR 级时间线；squash 与 rebase 都会把分支抹平，事后分不清一次改动是走 PR 进来的
   还是直接推上去的。**不要**用 `git merge --ff-only` 或 `git rebase` 自己把分支推平
   再推 main（服务端 ruleset 也会拒绝直推）。
   PR 标题仍须是一条合法的 Conventional Commit —— release-drafter 是按 **PR 标题 +
   标签**生成发布说明的，与提交图长什么样无关。

---

## 6. 代码风格约定

### 6.1 类型注解与静态检查

- **所有函数（含私有函数）必须写完整类型注解**，参数与返回值都不能省；
- 类型检查以 **mypy `--strict`** 为准：

  ```bash
  uv run mypy src tests
  ```

- 不要用 `# type: ignore` 掩盖问题。确实无法避免时，必须写成带错误码的窄化形式
  （例如 `# type: ignore[no-any-return]`），并在同一行或上一行说明原因；
- 不要用 `Any` 图省事。公共 API 上出现 `Any` 需要能说清理由。

### 6.2 文档字符串

- **公共 API 必须有 docstring**（模块、公开类、公开函数）；
- docstring 用中文，说明「做什么、返回什么、抛什么异常」，不要复述函数名；
- 内部实现的 docstring 可选，但涉及不变量、并发假设、边界条件时必须写。

### 6.3 行尾与格式

- **全仓统一 LF 行尾**。`.gitattributes` 与 `.editorconfig` 已固化这条规则，
  本机即使 `core.autocrlf=true` 也不要提交 CRLF；
- 文件编码 UTF-8（无 BOM），文件末尾保留且仅保留一个换行；
- 格式化交给 `ruff format`，不要手工调对齐；
- 行宽以 `ruff format` 的实际输出为准（`.editorconfig` 中记录了 `max_line_length = 100`）；
- 不要手工排序 import，交给 `ruff check --fix`。

### 6.4 许可头

**每个新增的源码文件**（Python 文件）必须在**文件最顶部**写下面两行，逐字照抄，
紧接着就是模块 docstring（中间不空行）：

```python
# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
```

- 顺序不能颠倒，`#` 后有一个空格，年份写 `2026`；
- 不要改写署名；
- 新建的文件如果漏了这两行，请在同一个 PR 里补上。

第三方代码的许可与归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，
不要直接把外部代码粘进 `src/`。

---

## 7. 测试要求

- **新增或修改行为必须带测试。** 没有测试的行为变更不会被合并；
- 测试放在 `tests/`，用 pytest 编写；测试文件命名 `test_*.py`，用例命名 `test_*`；
- 涉及文件系统与并发的用例，必须使用临时目录（`tmp_path`），
  不要污染仓库根目录，也不要依赖当前工作目录；
- 涉及多进程 / 多实例的用例，要真的起多个进程去验证「不丢更新」，
  而不是只在单进程里模拟；
- 涉及回写的用例，请断言**未被触及的字节逐字不变**（注释、缩进、键序），
  这是本项目的核心语义，不能只断言最终值相等；
- 本地自查：

  ```bash
  uv run pytest
  uv run pytest --cov --cov-report=term-missing
  ```

- **覆盖率门槛由 CI 强制**：`test` job 在三个平台 × Python 3.14 上跑测试并校验覆盖率，
  低于门槛直接失败。不要通过排除文件或加 `# pragma: no cover` 来凑数。

---

## 8. 文档要求

- **用户可见的行为变化必须同步 `docs/`**。代码改了、文档没改，PR 视为未完成；
- 文档语言**以中文为主**；README 是两份：[`README.md`](README.md)（英文）与
  [`README.zh-CN.md`](README.zh-CN.md)（中文），**改一份必须同步改另一份**；
- 设计层面的取舍记录在 [`docs/design/DESIGN.md`](docs/design/DESIGN.md)：
  它是设计草案与决策记录，**改动它请在 PR 里单独说明理由**，
  不要把它当成随手可改的说明文档；
- 文档站是 MkDocs Material，本地预览：

  ```bash
  uv run mkdocs serve
  ```

- 合并到 `main` 后由 `.github/workflows/docs.yml` 的 `deploy` job 发布到 GitHub Pages；
- Markdown 由 markdownlint 检查：标题层级不要跳级，代码块必须标语言，
  列表缩进保持一致。

---

## 9. 不要提交什么

以下内容**绝对不能进仓库**（`.gitignore` 已尽量兜底，但它不是保险）：

- **任何密钥与凭据**：token、私钥（`*.pem` / `*.key`）、keystore、云厂商 AK/SK；
- **`.env` 及其变体**（`.gitignore` 里只有 `.env`、`.env.*`，并放行 `!.env.example`）。
  注意引擎自己的 env 值文件叫 `settings.env`，**不匹配**上面任何一条模式
  （默认布局下靠 `/conf/` 兜底）。示例请写成不含真实值的样例文件；
- **运行时产物**：`/conf/` 目录、`*.wal` 预写日志、`audit.log` / `audit-*.log` 审计日志；
  这些是本项目自己的运行痕迹，属于产物而非源码；
- **构建与缓存产物**：`dist/`、`build/`、`site/`、各类 `*_cache/`、`*.egg-info/`；
- **与本 PR 无关的大文件、二进制与生成物**。

提交前请自查一次暂存区：

```bash
git status
git diff --cached
```

gitleaks 会在 CI 里再拦一道，但**已经被推到公开仓库的密钥只能作废**，
所以第一道防线始终是你自己。

---

## 10. 报告安全问题

**安全漏洞不要开公开 Issue**，也不要在 Discussions 里贴细节、PoC 或受影响版本的具体利用方式。

请走 [SECURITY.md](SECURITY.md) 描述的私密渠道报告。维护者会先私下确认与修复，
再协调公开披露。普通缺陷请走 [Bug 模板](https://github.com/HanYang06/OnConf/issues/new/choose)，
用法问题请走 [Discussions](https://github.com/HanYang06/OnConf/discussions) ——
具体分工见 [SUPPORT.md](SUPPORT.md)。

---

## 11. 许可

向本项目提交贡献，即表示你同意以 **Apache-2.0** 协议授权你的贡献
（见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)）。请确认你有权提交这些代码。
