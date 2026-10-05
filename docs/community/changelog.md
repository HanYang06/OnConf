# 变更日志

本页范围：说明变更日志放在哪里、为什么本站不复制它的内容。

⏳ 正文待补：等设计定稿后补齐。若将来需要「按版本浏览」的索引页，会在这里补上；
但**条目正文永远只在仓库里**。

## 唯一事实来源

变更日志以仓库根目录的 `CHANGELOG.md` 为唯一事实来源：

- [CHANGELOG.md](https://github.com/HanYang06/OnConf/blob/main/CHANGELOG.md)

它遵循 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)，
自 v0.1.0 起人工维护，历史条目由真实 git 提交整理。

## 本站为什么不复制内容

- **避免漂移**：同一份变更说明存在两处，就必然有一处会过期，而读者无法判断哪份是准的。
- **版本与标签在仓库里**：`git log`、tag、GitHub Release 都以版本库为准，
  站点上的复制品没法跟它们对齐。
- **合并冲突更少**：`CHANGELOG.md` 在 `.gitattributes` 里标了 `merge=union`，
  这意味着它会被**多个分支同时追加**；把它复制到站点侧会让每次发版都要改两处，
  而站点侧的改动没有任何自动化保障。

## 相关页面

- [参与方式](index.md) —— 贡献流程与其他仓库文档的入口。
- [路线图](../roadmap/index.md) —— 未发布能力与进度的权威清单。
