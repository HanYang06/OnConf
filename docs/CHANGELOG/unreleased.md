## [Unreleased]

下一版的条目写在这里：人维护，一个 `fix:` / `feat:` 一行。发版时整页收成
`docs/CHANGELOG/<版本>.md`（标题补日期），本页重新开一张 —— 一条命令做完：
`uv run python scripts/release_notes.py finalize <版本>`。口径见
[变更日志的维护口径](../community/changelog.md)。

### Added

### Changed

### Fixed

- **首页与 README 把「当前版本」写成了一个具体的版本号**：这类声明每逢发版就要手改一遍，
  漏一次就把读者钉在旧版本上（2.1.1 之前它们还停在 `1.0.0`）。现在这些地方一律指向 PyPI
  与变更日志，不再自带版本号；版本号只由 `pyproject.toml` 与发布记录承担。
[Unreleased]: https://github.com/HanYang06/OnConf/compare/v2.1.1...HEAD
