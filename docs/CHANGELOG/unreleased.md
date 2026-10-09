## [Unreleased]

下一版的条目写在这里：人维护，一个 `fix:` / `feat:` 一行。发版时整页收成
`docs/CHANGELOG/<版本>.md`（标题补日期），本页重新开一张 —— 一条命令做完：
`uv run python scripts/release_notes.py finalize <版本>`。口径见
[变更日志的维护口径](../community/changelog.md)。

### Added

### Changed

- **发布流程**：`v*` tag 推上去、PyPI 发布成功之后，会**自动建 GitHub Release** —— 正文取该
  版本的变更页（相对链接转成绝对链接），再接上 GitHub 原生的 PR / 作者 / 完整对比附录；同时
  多一道闸门：没有 `docs/CHANGELOG/<版本>.md` 的版本发不出去。CI 也新增死链检查：文档里的
  相对链接与指向本仓库的地址必须落到真实路径。

### Fixed

- **PyPI 页面上的变更日志链接**（`[project.urls]` 的 `Changelog`）指向了一个 404 地址，从本版
  起指向按版本分页的变更日志索引。
- **已发布版本引用过的 2.0.x 路线图页**恢复可达：此前线上是 404。

[Unreleased]: https://github.com/HanYang06/OnConf/compare/v2.1.0...HEAD
