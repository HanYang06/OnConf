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

当前运行时依赖数量：**12**。

## 汇总

| 包 | 版本 | 许可证 | 许可证来源 | 环境标记 |
|---|---|---|---|---|
| anyio | 4.15.1 | MIT | License-Expression | — |
| certifi | 2026.7.22 | OSI Approved :: Mozilla Public License 2.0 (MPL 2.0) | Classifier: License :: | — |
| h11 | 0.16.0 | OSI Approved :: MIT License | Classifier: License :: | — |
| httpcore | 1.0.9 | BSD-3-Clause | License-Expression | — |
| httpx | 0.28.1 | OSI Approved :: BSD License | Classifier: License :: | — |
| idna | 3.20 | BSD-3-Clause | License-Expression | — |
| markdown-it-py | 4.2.0 | OSI Approved :: MIT License | Classifier: License :: | — |
| mdurl | 0.1.2 | OSI Approved :: MIT License | Classifier: License :: | — |
| Pygments | 2.21.0 | BSD-2-Clause | License-Expression | — |
| PyYAML | 6.0.3 | OSI Approved :: MIT License | Classifier: License :: | — |
| rich | 15.0.0 | OSI Approved :: MIT License | Classifier: License :: | — |
| typing_extensions | 4.16.0 | PSF-2.0 | License-Expression | `python_full_version < '3.15'` |

## 逐包明细

### anyio 4.15.1

- 元数据名称：`anyio`
- Metadata-Version：`2.4`
- 许可证：MIT（来源：License-Expression）
- 环境标记：无（所有平台都装）
- Home-page：元数据未声明
- Project-URL：Documentation <https://anyio.readthedocs.io/en/latest/>；Changelog <https://anyio.readthedocs.io/en/stable/versionhistory.html>；Source code <https://github.com/agronholm/anyio>；Issue tracker <https://github.com/agronholm/anyio/issues>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`anyio-4.15.1.dist-info/licenses/LICENSE`
- 上游页面：<https://pypi.org/project/anyio/4.15.1/>

### certifi 2026.7.22

- 元数据名称：`certifi`
- Metadata-Version：`2.4`
- 许可证：OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)（来源：Classifier: License ::）
- 环境标记：无（所有平台都装）
- Home-page：<https://github.com/certifi/python-certifi>
- Project-URL：Source <https://github.com/certifi/python-certifi>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`certifi-2026.7.22.dist-info/licenses/LICENSE`
- 上游页面：<https://pypi.org/project/certifi/2026.7.22/>

### h11 0.16.0

- 元数据名称：`h11`
- Metadata-Version：`2.4`
- 许可证：OSI Approved :: MIT License（来源：Classifier: License ::）
- 环境标记：无（所有平台都装）
- Home-page：<https://github.com/python-hyper/h11>
- Project-URL：元数据未声明
- 许可证全文（随分发提供，路径相对 `site-packages`）：`h11-0.16.0.dist-info/licenses/LICENSE.txt`
- 上游页面：<https://pypi.org/project/h11/0.16.0/>

### httpcore 1.0.9

- 元数据名称：`httpcore`
- Metadata-Version：`2.4`
- 许可证：BSD-3-Clause（来源：License-Expression）
- 环境标记：无（所有平台都装）
- Home-page：元数据未声明
- Project-URL：Documentation <https://www.encode.io/httpcore>；Homepage <https://www.encode.io/httpcore/>；Source <https://github.com/encode/httpcore>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`httpcore-1.0.9.dist-info/licenses/LICENSE.md`
- 上游页面：<https://pypi.org/project/httpcore/1.0.9/>

### httpx 0.28.1

- 元数据名称：`httpx`
- Metadata-Version：`2.3`
- 许可证：OSI Approved :: BSD License（来源：Classifier: License ::）
- 环境标记：无（所有平台都装）
- Home-page：元数据未声明
- Project-URL：Changelog <https://github.com/encode/httpx/blob/master/CHANGELOG.md>；Documentation <https://www.python-httpx.org>；Homepage <https://github.com/encode/httpx>；Source <https://github.com/encode/httpx>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`httpx-0.28.1.dist-info/licenses/LICENSE.md`
- 上游页面：<https://pypi.org/project/httpx/0.28.1/>

### idna 3.20

- 元数据名称：`idna`
- Metadata-Version：`2.5`
- 许可证：BSD-3-Clause（来源：License-Expression）
- 环境标记：无（所有平台都装）
- Home-page：元数据未声明
- Project-URL：Changelog <https://github.com/kjd/idna/blob/master/HISTORY.md>；Issue tracker <https://github.com/kjd/idna/issues>；Source <https://github.com/kjd/idna>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`idna-3.20.dist-info/licenses/LICENSE.md`
- 上游页面：<https://pypi.org/project/idna/3.20/>

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

### typing_extensions 4.16.0

- 元数据名称：`typing_extensions`
- Metadata-Version：`2.4`
- 许可证：PSF-2.0（来源：License-Expression）
- 环境标记：`python_full_version < '3.15'`
- Home-page：元数据未声明
- Project-URL：Bug Tracker <https://github.com/python/typing_extensions/issues>；Changes <https://github.com/python/typing_extensions/blob/main/CHANGELOG.md>；Documentation <https://typing-extensions.readthedocs.io/>；Home <https://github.com/python/typing_extensions>；Q & A <https://github.com/python/typing/discussions>；Repository <https://github.com/python/typing_extensions>
- 许可证全文（随分发提供，路径相对 `site-packages`）：`typing_extensions-4.16.0.dist-info/licenses/LICENSE`
- 上游页面：<https://pypi.org/project/typing-extensions/4.16.0/>
