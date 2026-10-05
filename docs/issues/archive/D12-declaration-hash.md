# D12 声明哈希的处置

| 项 | 值 |
|---|---|
| 类型 | 缺陷 |
| 优先级 | P2 |
| 状态 | 待决策（取最不确定成员） |
| 成员状态 | 待决策 1 —— 未定稿：ISSUE-014（待决策） |
| 前置 | 无 |
| 联动 | 无 |
| 覆盖原编号 | ISSUE-014 |
| 影响面 | `src/onconf/_core.py`、`src/onconf/_vocab.py`、`src/onconf/_engine.py`、`tests/test_vocab.py`、`docs/design/DESIGN.md` §18.7 / §23.3 / §29.3、`docs/roadmap.md` |
| 标签 | `area:core` |

## 0. 本决策的整体口径

`declaration_hash` 已计算、已持久化进词表产物（`x-onconf-hash`），但在生产代码里没有任何消费者 —— 唯一的 `Vocabulary.matches` 全仓没有调用点。

三条候选路径未选定：**删除字段**、**接线为写入阶段的整体短路**、**保留字段改用于变更检测**。
本项在选定之前不改行为；三条边界是硬的：指纹是脏检查不是锁、三态编码不可回退、`x-onconf-hash` 是对外可见的产物。

本单元不依赖任何单元，也不被任何单元依赖，可独立推进。

### 0.1 成员索引

| 原编号 | 本文件 | 一句话 |
|---|---|---|
| ISSUE-014 | §1 | `declaration_hash` 的三条候选路径与各自代价（未定） |

> 本文档内的 `ISSUE-NNN` 是**原始编号**。同一 `D` 单元内的编号都在本文件里，完整编号映射见 `README.md`。

---

## 1. `declaration_hash` 计算了但从不用于短路（原 ISSUE-014）

| 原项 | 值 |
|---|---|
| 原类型 / 优先级 / 状态 | 缺陷 / P2 / 待决策 |
| 原依赖 | 无 |
| 原影响面 | `src/onconf/_core.py`、`src/onconf/_vocab.py`、`src/onconf/_engine.py`、`tests/test_vocab.py`、`docs/design/DESIGN.md` §18.7 / §23.3 / §29.3、`docs/roadmap.md` |
| 原标签 | `area:core` |

### 背景

- `declaration_hash`（`src/onconf/_core.py:280-300`）把每个声明的 `key` / `type` / `doc` 与值三态一起编码后取 `sha256[:16]`，`type` 被编码进 payload（`src/onconf/_core.py:290-298`）。
- 它在提交点被计算（`src/onconf/_vocab.py:141`），写进词表产物 `x-onconf-hash`（`_vocab.py:172-173`、常量 `:35`），并在读回词表时还原（`_vocab.py:188`）。
- 唯一的消费者是 `Vocabulary.matches`（`_vocab.py:145-147`），而它在生产代码里没有任何调用点：全仓检索只命中定义与 `tests/test_vocab.py:125,131,136,143`。
- 设计文档自己写着它没有接线：`docs/design/DESIGN.md:1877`（§29.3）「声明集哈希（§18.7）是更进一步的整体短路，尚未接线」；`docs/roadmap.md:38` 也把它列在「进行中」。
- 为什么不可接受：一个被持久化进公开产物的指纹没有任何行为后果，词表消费者无法判断它是判据还是噪音。

### 结论

#### 1. 现状定性

`declaration_hash` 属于「已计算、已持久化、无消费者」：写入阶段不因指纹相同而跳过，`src/onconf/_engine.py` 中没有 `Vocabulary.matches` 的调用点。

#### 2. 任何处置都必须满足的三条边界

| # | 边界 | 依据 |
|---|---|---|
| 1 | 指纹是**脏检查，不是锁**：相同才允许跳过；不同只表示「这次短路不成立」，不得据此报错或拒绝写入 | `src/onconf/_core.py:283-284` |
| 2 | 三态编码不可回退：`["missing"]` / `["value", v]` 两段式必须保留，不得让「只登记」与「值为 `None`」塌陷成同一指纹 | `src/onconf/_core.py:286-288` |
| 3 | `x-onconf-hash` 是对外可见的产物：保留它就必须兑现语义，否则连写入一起移除 | `src/onconf/_vocab.py:172-173` |

#### 3. 处置未选定

三条候选路径与各自代价见未决事项。本项在选定之前不改行为。

### 变更项

| 位置 | 改动 |
|---|---|
| `src/onconf/_core.py:280-300` | `declaration_hash` 与其 docstring：随选定方案保留、改写或删除 |
| `src/onconf/_vocab.py:35,141,145-147,172-173,188` | `HASH_KEY`、`hash` 字段、`matches`、`to_schema` / `from_schema` 的读写 |
| `src/onconf/_engine.py` | 若选短路：在提交路径接入判定；若选删除或改用途：不动 |
| `tests/test_vocab.py:118-153` | 哈希往返与 `matches` 用例按选定方案改写 |
| `docs/design/DESIGN.md:1877`（§29.3）、`:1180`（M2 行） | 「尚未接线」的表述按选定方案收口 |
| `docs/design/DESIGN.md:1403,1434-1450`（§23） | 若删除字段，跨机哈希方案缺少现成指纹，需另给方案 |
| `docs/roadmap.md:38` | 「声明集哈希的整体短路」一行按选定方案收口 |

### 验收标准

- [ ] 选定方案后，`x-onconf-hash` 只有一种解释：要么是短路判据，要么不存在，要么明确改名成版本标识
- [ ] 若选短路：新增用例证明「声明集未变 ⇒ 一个字节都不写」，并断言未触及字节逐字不变
- [ ] 若选删除：`x-onconf-hash` 从词表产物中消失，旧词表的读回行为有测试
- [ ] 指纹的三态区分有测试：只登记 / 值为 `None` / 值为其它，三者两两不同
- [ ] `docs/design/DESIGN.md` §18.7 / §23.3 / §29.3 与 `docs/roadmap.md:38` 与本项结论一致

### 未决事项

1. **删除字段**：移除 `declaration_hash` 与 `x-onconf-hash`（`src/onconf/_core.py:280-300`、`_vocab.py:35,141,145-147,172-173,188`）。代价：`DESIGN.md:1434-1450`（§23.3）的跨机哈希方案失去现成指纹，要另设计；旧词表里已有的 `x-onconf-hash` 需要向下兼容规则。
2. **接线为写入阶段整体短路**：在 `Engine` 的提交路径调用 `Vocabulary.matches`。代价：短路跳过的是整个写入阶段，必须先证明它在规则 1（清理未知键）与 `flush_window > 0` 的攒批路径下都不会漏掉应有的清理；`DESIGN.md:1877` 与 `docs/roadmap.md:38` 随之收口。
3. **保留字段，改用于变更检测**：例如日志里打一行指纹，或供 CLI 的 `diff` 判定「代码是否改过声明」。代价：语义从「写入脏检查」变成「版本标识」，而 `DESIGN.md:1403` 已把同族用途定性为「版本不一致」，两者若共用一个字段名会产生两种解释。

