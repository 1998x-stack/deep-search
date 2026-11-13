# Deep Search Factory Mode

在空白文件树上重新设计的研究系统：保留主分支的证据台账、反证和审计理念，结合 AdamFangKK 的配置驱动与严格执行，使用 CleanRL 风格的显式入口和简单 Factory Pattern。**主分支不变**；但新分支的 Git 初始提交仍有 main 父提交，并不是 orphan 历史。

## 代码分类

- `factory/`：配置、DeepSeek/OpenAI/**pi-agent `iagent`** 模型、Google/Playwright/**replay（操作者导入的真实检索清单）** 搜索、抓取、证据、独立 Reflection Policy、**loguru 运行日志** 和编排。
- `algorithms/`：单文件可读的研究执行入口；Strict Mode。
- `configs/`：默认预算与领域路由；`configs/cases/` 存放具体案例配置。
- `fixtures/`：带 provenance 的真实检索清单（案例用）。
- `examples/`：可重复运行的虚构离线用例。
- `tests/`：不消耗 API 的回归测试。
- `runs/`：研究产物（含 `logs/`），默认忽略，不提交。

## 运行

~~~bash
python -m pip install -e .
python algorithms/deep_research.py --question "虚构图书馆何时建成" \
  --provider mock --llm mock --fixture examples/offline_fixture.json --out runs/demo
python -m unittest discover -s tests -v
python benchmarks/offline_eval.py --out runs/evals
~~~

DeepSeek + Google 需要 `DEEPSEEK_API_KEY`、`GOOGLE_API_KEY`、`GOOGLE_CSE_ID`；OpenAI 则需 `OPENAI_API_KEY`，默认通过 Responses API 调用可配置的 `gpt-6`（是否有 API 权限需实际验证）。Playwright 搜索需另行安装浏览器，但不需要 Google CSE Key。密钥不得提交至仓库。

`--llm iagent` 不硬编码任何密钥：provider、模型 ID、Base URL 与 Key 均在运行时从本地 Pi agent 配置 `~/.pi/agent/models.json` 解析（支持 `!cat <密钥文件>` 形式），也可用 `IAGENT_API_KEY` / `IAGENT_BASE_URL` / `IAGENT_MODEL` / `PI_MODELS_JSON` 覆盖。解析结果中的密钥绝不写入日志、产物或报告。

每次运行都会在输出目录下写入 `logs/run.log`（人读）、`logs/run.jsonl`（机器读）与 `logs/errors.log`（仅错误），并对已注册密钥与常见凭据形态做脱敏；详见 [日志说明](docs/LOGGING.md)。

~~~bash
python algorithms/deep_research.py --question "研究主题" \
  --provider google --llm deepseek --fetch-pages --out runs/live
~~~

# OpenAI + Playwright 搜索
pip install -e '.[browser]'
python -m playwright install chromium
python algorithms/deep_research.py --question "研究主题" \
  --llm openai --provider playwright --browser-engine bing \
  --fetch-pages --reflection-patience 2 --out runs/browser

Google Custom Search JSON API 面临 2027-01-01 迁移截止，因此搜索接口单独封装。引用匹配、来源数、LLM 输出均不自动证明事实真实；未获取原文的搜索摘要也不能冒充原始证据。

联网连接测试：设置好环境变量后显式运行 `python scripts/live_smoke.py --live`（仅检查接口形态，不检验事实准确性）。运行时能力清单写入 `capabilities.json`，自主反思逐轮轨迹写入 `reflection.json`。代码根据新增证据、查询新颖性、连续停滞与预算决定是否批准 Critic 提议。

阅读 [Reflection 设计](docs/REFLECTION.md)、[设计文档](docs/ARCHITECTURE.md)、[API 契约](docs/API.md)、[总控 Prompt](prompts/master.md)、[离线评测](evals/README.md)、[日志说明](docs/LOGGING.md)、[踩坑记录](docs/gotchas.md)、[案例：具身智能产业链](docs/CASE-EMBODIED-INTELLIGENCE.md) 与 [运行手册](docs/OPERATIONS.md)。

## 检索不可用时的 replay 通道（2026-11-13）

当宿主机无法使用自动化搜索时（无 Google CSE 凭据；浏览器或 RSS 引擎对本机 IP 返回词典/广告页或 0 条可解析结果；DuckDuckGo 网络不可达），**不得编造来源**。做法是：用可用工具采集真实结果，连同 provenance 写入清单文件，然后：

~~~bash
python algorithms/strict_research.py --config configs/cases/embodied-intelligence-chain.json \
  --question "具身智能（人形机器人）产业链调查：…" --out runs/embodied-ai-chain-20261113
~~~

`--provider replay` 会拒绝 `synthetic=true` 的清单，要求 `provenance.collected_by/collected_at/collection_tool`，并在 `run.json` 标记 `discovery_mode=operator_imported`、把 provenance 写入 `discovery.json`。清单只是检索线索，证据仍必须锚定到受限抓取器取回的全文。



## 2026-11-13 复核加固

本次修复了三类问题：

- 非 Strict 模式不能再把“只有搜索摘要、没有可核验原文”或“空论断台账”误标为研究完成。必须有与论断状态匹配的正文锚定证据，且报告正文实际引用对应来源，否则返回 `incomplete`，并在 `audit.json.readiness` 记录原因。
- 直接调用 `ResearchConfig(question="...", llm="openai")` 时使用 OpenAI 默认模型和 API 地址，不再误继承 DeepSeek 默认值。
- 通过 `--max-context-chars 48000` 限制每次传给模型的总序列化输入。过长则清楚失败并保留产物，而不是无上限消耗 Token；来源只发送标明截断的摘录。

这些只是**工程完整性与引用结构检查**，不是自动事实认证。见 [完整审计记录](docs/REVIEW-2026-11-13.md)。
