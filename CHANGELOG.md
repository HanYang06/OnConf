# 变更日志

本文件记录 auto-conf 的所有重要变更。

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

### Changed

- 暂无可并入的条目。

### Fixed

- 暂无可并入的条目。

## [0.1.0] - 2026-10-04

首个版本。公开 API 收敛为两个面（`AutoConf` / `conf`），JSON 与 YAML 两个值后端可用，
提交点是「立即落盘 + `atexit` 收口」。开发状态为 Pre-Alpha。

### Added

- 仓库骨架：`pyproject.toml`、`uv.lock`、包入口、`.python-version`（`3ef3f4f`）。
- 纯内存核心：对账四条规则、读取五步、类型推断与转换、声明集哈希（`b6f8433`）。
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

[Unreleased]: https://github.com/HanYang06/auto-conf/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/HanYang06/auto-conf/compare/3ef3f4f...v0.1.0

未发布能力见 [docs/roadmap.md](docs/roadmap.md)。
