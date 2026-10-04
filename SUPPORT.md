# 获取支持

本文说明**去哪儿问什么**。选对渠道能让问题更快被看到，也能让后来的用户搜到同样的答案。

在提问之前，请先花两分钟：

- 读一遍 [README](README.md)（[中文版](README.zh-CN.md)）与[文档站](https://hanyang06.github.io/onconf/)；
- 在 [Issues](https://github.com/HanYang06/onconf/issues) 与
  [Discussions](https://github.com/HanYang06/onconf/discussions) 里搜一下关键词
  （报错全文、键名、文件名都值得搜）；
- 确认你用的是**最新版本**，并确认 Python 版本是 **3.14 或更高**；
- 把「最小复现」缩到不能再小 —— 大多数问题在缩小复现的过程中就自己现形了。

---

## 去哪儿问什么

| 你的问题 | 去哪儿 | 说明 |
|---|---|---|
| 「怎么用」「为什么这样设计」「这样写对不对」 | [GitHub Discussions](https://github.com/HanYang06/onconf/discussions) | 用法问答与开放式讨论的首选渠道，答案可以被别人搜到 |
| 「这是 bug」「它和文档写的不一样」 | [Bug 报告模板](https://github.com/HanYang06/onconf/issues/new?template=bug_report.yml) | 请附最小复现、完整报错、环境信息 |
| 「希望支持某个能力」「API 想这么改」 | [功能请求模板](https://github.com/HanYang06/onconf/issues/new?template=feature_request.yml) | 请写清要解决的场景，而不只是想要的写法 |
| 「文档这里看不懂 / 写错了 / 缺了」 | [文档问题模板](https://github.com/HanYang06/onconf/issues/new?template=docs.yml) | 请指出具体是哪一篇、哪一段 |
| 「我发现了一个安全漏洞」 | 见 [SECURITY.md](SECURITY.md) | **走私密渠道**，不要开公开 Issue，也不要在 Discussions 里贴细节或 PoC |
| 「有人违反了行为准则」 | 邮件 `jihanyang123@163.com` | 见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)，可附证据，会保密处理 |
| 「我想贡献代码」 | 见 [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境、检查命令、提交规范都在里面 |

> 仓库的 Issue 表单**不接受空白 Issue**（`blank_issues_enabled: false`），
> 请从上面三个模板里选一个。

---

## 提问时请附上这些

**Bug 报告**（模板里会逐项问，先准备好会更快）：

- onconf 版本（源码检出时看 `pyproject.toml` 的 `version` 字段或 `uv.lock`；
  已安装时给出 `uv pip show onconf` 的输出）；
- Python 版本（`python -V`）；
- 操作系统（Windows / macOS / Linux 及版本）；
- 安装方式（`uv sync` 源码检出 / `pip install` / `uv add`）；
- **最小复现**：能直接跑的代码片段，或一份最小的配置目录结构；
- 期望行为与实际行为；
- **完整的报错信息与相关日志**（不要只贴一行，也不要截图代替文本）；
  审计输出在当前版本还没有落地，不必附审计日志；
- 是否涉及**多进程 / 多实例并发**读写同一批配置文件 —— 这一项对本项目特别关键，
  很多问题的答案完全取决于它。

**用法问题**：

- 你想达成的目标（而不是你猜的实现方式）；
- 你已经试过的写法与结果；
- 相关配置文件的一小段（**去掉所有真实密钥与敏感值**）。

---

## 关于响应时间

这是一个**由志愿者维护的个人项目**：

- 不承诺 SLA，不承诺响应时限，也不承诺一定会实现某个功能请求；
- 维护者会在有空的时候处理，优先级通常是：安全漏洞 → 缺陷 → 文档 → 新功能；
- 提了 Issue 之后没有人回复，通常不是被忽略，而是还没轮到；
  如果过了很久仍然没有回应，可以在原 Issue 下**礼貌地补充新信息**，
  但请不要重复开 Issue 或 @ 维护者催促；
- 你能提供的最小复现越干净，问题被解决得越快。**帮助维护者复现，就是最快的支持。**

---

## 相关链接

| 内容 | 地址 |
|---|---|
| 仓库 | <https://github.com/HanYang06/onconf> |
| 文档站 | <https://hanyang06.github.io/onconf/> |
| Discussions | <https://github.com/HanYang06/onconf/discussions> |
| Issues | <https://github.com/HanYang06/onconf/issues> |
| 安全策略 | [SECURITY.md](SECURITY.md) |
| 行为准则 | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |
| 贡献指南 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 开源协议 | [LICENSE](LICENSE)（Apache-2.0） |
