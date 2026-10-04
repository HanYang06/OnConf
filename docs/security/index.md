# 安全总览

本页范围：安全相关文档的**索引**与阅读顺序；威胁建模细节与漏洞报告流程不在本页。

⏳ 正文待补：等设计定稿后补齐。当前已有的安全材料以下面的链接为准，
本页不复制它们的内容。

## 本站页面

- [运行时威胁模型](threat-model.md) —— 当前实现的信任边界、资产与已知缺口，
  每条判断都给出代码依据。这是站点上唯一一份**已撰写**的安全文档。

## 仓库根目录

- [SECURITY.md](https://github.com/HanYang06/auto-conf/blob/main/SECURITY.md)
  —— 漏洞报告渠道与支持范围。安全问题请走私密渠道，不要开公开 issue。
- [CODE_OF_CONDUCT.md](https://github.com/HanYang06/auto-conf/blob/main/CODE_OF_CONDUCT.md)
  —— 社区行为准则（Contributor Covenant 2.1 简体中文译本）。

## 待补内容

⏳ 正文待补：等设计定稿后补齐。计划覆盖：

- 配置文件的权限模型（新建文件在 POSIX 上是 `0600`，已有文件的权限位原样保留；Windows 上
  依赖目录 ACL —— 见威胁模型 T6）。
- 密钥类配置的处理建议（当前实现仍不适合存放需要严格保密的凭据）。
- 依赖供应链（第三方许可证清单见仓库根目录的
  [THIRD_PARTY_NOTICES.md](https://github.com/HanYang06/auto-conf/blob/main/THIRD_PARTY_NOTICES.md)）。
