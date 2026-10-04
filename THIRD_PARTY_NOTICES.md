# 第三方软件声明

> 本文件由 `scripts/gen_third_party_notices.py` **自动生成，请勿手工编辑**。
> 任何手工改动都会在下一次生成时被覆盖，并使 CI 的 `--check` 失败。

## 生成方式

```bash
# 重新生成
uv run python scripts/gen_third_party_notices.py

# 校验（与当前文件不一致则退出码 1）
uv run python scripts/gen_third_party_notices.py --check
```

依赖清单由 `uv export --no-dev --no-emit-project --format requirements-txt --no-hashes` 得出，许可证信息由 `importlib.metadata` 从**已安装分发**的元数据读出。

本文件覆盖 onconf 的**运行时依赖闭包**（含传递依赖），不含 dev / docs 依赖组；
后两组只在开发期使用，不进入发行物。onconf 自身的许可证见仓库根目录的 `LICENSE`
与 `NOTICE`（Apache-2.0）。

许可证列优先取 PEP 639 的 `License-Expression`（SPDX 表达式），其次为 `Classifier: License ::` 分类器，再次为旧式 `License` 字段；都没有时记为 `UNKNOWN`。许可证全文随各分发一并提供，路径见下方逐包明细（相对 `site-packages`），也可在对应的上游页面获取。

当前运行时依赖数量：**5**。

## 汇总

| 包 | 版本 | 许可证 | 许可证来源 | 环境标记 |
|---|---|---|---|---|
| markdown-it-py | 4.2.0 | OSI Approved :: MIT License | Classifier: License :: | — |
| mdurl | 0.1.2 | OSI Approved :: MIT License | Classifier: License :: | — |
| Pygments | 2.21.0 | BSD-2-Clause | License-Expression | — |
| PyYAML | 6.0.3 | OSI Approved :: MIT License | Classifier: License :: | — |
| rich | 15.0.0 | OSI Approved :: MIT License | Classifier: License :: | — |

## 逐包明细

### markdown-it-py 4.2.0

- 元数据名称：`markdown-it-py`
- Metadata-Version：`2.4`
- 许可证：OSI Approved :: MIT License（来源：Classifier: License ::）
- 环境标记：无（所有平台都装）
- Home-page：元数据未声明
- Project-URL：Documentation <https://markdown-it-py.readthedocs.io>；Homepage <https://github.com/executablebooks/markdown-it-py>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`markdown_it_py-4.2.0.dist-info/licenses/LICENSE`、`markdown_it_py-4.2.0.dist-info/licenses/LICENSE.markdown-it`
- 上游页面：<https://pypi.org/project/markdown-it-py/4.2.0/>

### mdurl 0.1.2

- 元数据名称：`mdurl`
- Metadata-Version：`2.1`
- 许可证：OSI Approved :: MIT License（来源：Classifier: License ::）
- 环境标记：无（所有平台都装）
- Home-page：元数据未声明
- Project-URL：Homepage <https://github.com/executablebooks/mdurl>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`mdurl-0.1.2.dist-info/LICENSE`
- 上游页面：<https://pypi.org/project/mdurl/0.1.2/>

### Pygments 2.21.0

- 元数据名称：`Pygments`
- Metadata-Version：`2.5`
- 许可证：BSD-2-Clause（来源：License-Expression）
- 环境标记：无（所有平台都装）
- Home-page：元数据未声明
- Project-URL：Homepage <https://pygments.org>；Documentation <https://pygments.org/docs>；Source <https://github.com/pygments/pygments>；Bug Tracker <https://github.com/pygments/pygments/issues>；Changelog <https://github.com/pygments/pygments/blob/master/CHANGES>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`pygments-2.21.0.dist-info/licenses/AUTHORS`、`pygments-2.21.0.dist-info/licenses/LICENSE`
- 上游页面：<https://pypi.org/project/pygments/2.21.0/>

### PyYAML 6.0.3

- 元数据名称：`PyYAML`
- Metadata-Version：`2.4`
- 许可证：OSI Approved :: MIT License（来源：Classifier: License ::）
- 环境标记：无（所有平台都装）
- Home-page：<https://pyyaml.org/>
- Project-URL：Bug Tracker <https://github.com/yaml/pyyaml/issues>；CI <https://github.com/yaml/pyyaml/actions>；Documentation <https://pyyaml.org/wiki/PyYAMLDocumentation>；Mailing lists <http://lists.sourceforge.net/lists/listinfo/yaml-core>；Source Code <https://github.com/yaml/pyyaml>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`pyyaml-6.0.3.dist-info/licenses/LICENSE`
- 上游页面：<https://pypi.org/project/pyyaml/6.0.3/>

### rich 15.0.0

- 元数据名称：`rich`
- Metadata-Version：`2.4`
- 许可证：OSI Approved :: MIT License（来源：Classifier: License ::）
- 环境标记：无（所有平台都装）
- Home-page：元数据未声明
- Project-URL：Documentation <https://rich.readthedocs.io/en/latest/>；Homepage <https://github.com/Textualize/rich>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`rich-15.0.0.dist-info/licenses/LICENSE`
- 上游页面：<https://pypi.org/project/rich/15.0.0/>
