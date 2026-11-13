# Deep Search Factory Mode

在空白文件树上重新设计的研究系统：保留主分支的证据台账、反证和审计理念，结合 AdamFangKK 的配置驱动与严格执行，使用 CleanRL 风格的显式入口和简单 Factory Pattern。**主分支不变**；但新分支的 Git 初始提交仍有 main 父提交，并不是 orphan 历史。

## 代码分类

- `factory/`：配置、DeepSeek 模型、Google 搜索、抓取、证据、Prompt 和编排。
- `algorithms/`：单文件可读的研究执行入口；Strict Mode。
- `configs/`：默认预算与领域路由。
- `examples/`：可重复运行的虚构离线用例。
- `tests/`：不消耗 API 的回归测试。
- `runs/`：研究产物，默认忽略，不提交。

## 运行

~~~bash
python -m pip install -e .
python algorithms/deep_research.py --question "虚构图书馆何时建成" \
  --provider mock --llm mock --fixture examples/offline_fixture.json --out runs/demo
python -m unittest discover -s tests -v
python benchmarks/offline_eval.py --out runs/evals
~~~

联网需配置 `DEEPSEEK_API_KEY`、`GOOGLE_API_KEY`、`GOOGLE_CSE_ID`。无需写入任何实际密钥到仓库。DeepSeek 模型默认 `deepseek-flash`，对应 V4.1-Flash-1017。

~~~bash
python algorithms/deep_research.py --question "研究主题" \
  --provider google --llm deepseek --fetch-pages --out runs/live
~~~

Google Custom Search JSON API 面临 2027-01-01 迁移截止，因此搜索接口单独封装。引用匹配、来源数、LLM 输出均不自动证明事实真实；未获取原文的搜索摘要也不能冒充原始证据。

联网连接测试：设置好环境变量后显式运行 `python scripts/live_smoke.py --live`（仅检查接口形态，不检验事实准确性）。运行时能力清单写入 `capabilities.json`。

阅读 [设计文档](docs/ARCHITECTURE.md)、[API 契约](docs/API.md)、[总控 Prompt](prompts/master.md)、[离线评测](evals/README.md) 与 [运行手册](docs/OPERATIONS.md)。

