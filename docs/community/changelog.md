# 变更日志的维护口径

本页说明变更日志**放在哪儿、发版时怎么收口**。条目本身在[变更日志索引](../CHANGELOG/index.md)。

## 一版一页

- 唯一事实来源是 `docs/CHANGELOG/`：**一个已发布版本一页**（`0.1.0.md`、`1.0.0.md`、
  `2.0.0.md`、`2.1.0.md` …），文件名就是版本号，页面标题形如 `## [2.1.0] - 2026-10-09`；
- 开发期的条目落在 `docs/CHANGELOG/unreleased.md`。发版时整页收成该版本那一页（标题补
  `- YYYY-MM-DD` 日期），未发布页重新开一张：`uv run python scripts/release_notes.py finalize <版本>`
  一次做完；
- 索引页 `docs/CHANGELOG/index.md` 是**派生视图**：只列版本、日期与对比链接，不存条目正文。

## 发版时的三条硬约束

1. **该版本页必须存在** —— `.github/workflows/release.yml` 在 tag 推送时先查
   `docs/CHANGELOG/<版本>.md`，缺了就让整条发布链停下。没有变更记录的版本发不出去。
2. **Release 正文由该页生成** —— `uv run python scripts/release_notes.py body <版本>` 把相对
   链接转成绝对链接、补上站点版本页地址；GitHub 侧再自动附上 PR / 作者 / 完整对比。
3. **自动附录的分类靠标签** —— `.github/release.yml` 按 `feat` / `fix` / `docs` … 标签分类；
   PR 标题是合法 Conventional Commit 时，`.github/workflows/labeler.yml` 会自动打上对应标签。

## 格式

遵循 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循
[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。条目由人维护，每一条都对应真实提交或 PR，
不写愿景；`fix:` 的 PR 都要在未发布页里留一行。

## 相关页面

- [变更日志索引](../CHANGELOG/index.md) —— 按版本分页的入口。
- [参与方式](index.md) —— 贡献流程与其他仓库文档的入口。
- [路线图读法](../roadmap/README.md) —— 范围与版本的权威清单。
