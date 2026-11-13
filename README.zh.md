# Deep Search · 深度研究与证据审计 Skill

这是一个面向 **Codex / Claude Code / OpenCode** 的可复用研究能力包，同时包含 Python 3.10+ 工具链。它的原则是 **先追溯证据，再形成结论**：检索结果、引用存在、事实真实是三个不同的问题。

## 工作流

**明确问题 → 初步规划 → 多轮检索 → 阅读原文 → 去重与溯源 → Claim–Evidence 台账 → 反例搜索 → 综合分析 → 报告审计。**

研究质量门槛不是“至少引用 N 个链接”；相同通讯社文章被转载十次，不能算十条独立证据。真正的判断需要检查来源原始性、发布时间、适用范围、利益关系、反证和证据与结论之间的关系。

## 安装

```bash
git clone https://github.com/1998x-stack/deep-search.git
cd deep-search
python -m pip install -e .
python -m unittest discover -s tests -v
```

三种 Agent 的入口分别是 `.agents/skills/deep-search/SKILL.md`、`.claude/skills/deep-search/SKILL.md`、`.opencode/skills/deep-search/SKILL.md`。

## 无网络环境测试

```bash
deep-search plan --question "某政策的历史依据与实施效果是什么？" --output runs/plan.json
deep-search validate --input examples/demo-ledger.json
deep-search report --plan examples/demo-plan.json --ledger examples/demo-ledger.json --output runs/report.md
deep-search audit --report runs/report.md --ledger examples/demo-ledger.json
```

注意：`examples/` 的示例完全是虚构数据，用于测试格式与程序行为，不是现实世界的事实来源。

## 联网检索（可选）

```bash
export TAVILY_API_KEY="your-key"
deep-search search --input runs/plan.json --output runs/search.json
deep-search fetch --input runs/search.json --output runs/fetched.json --allow-network
deep-search dedup --input runs/fetched.json --output runs/unique.json
```

`fetch` 只适用于受信环境；它检查非公网地址、重定向和响应大小，但没有 DNS IP 固定机制，不适合暴露给陌生用户直接请求任意 URL。没有密钥时 CLI 不会假装检索成功。

## 模块分工

| 模块 | 功能 | 不提供的保证 |
| --- | --- | --- |
| Planner | 模板式初始计划，支持修改 | 不是自主完备的研究策略 |
| Search / Fetch | 搜索接口与网页正文获取 | 不保证覆盖整个互联网 |
| Dedup | 相同 URL / 内容去重 | 不等于来源独立性检验 |
| Evidence | 断言、证据、反证结构化 | 不自动判断语义蕴含 |
| Validator | 检查证据 ID、原文引句 | 引句存在不代表结论为真 |
| Synthesizer | 为研究 Agent 提供写作 Prompt | CLI 仅生成证据清单 |
| Audit | 报告引文与台账关联校验 | 不是权威事实核验认证 |

详细使用请参阅 [英文 README](README.md)、[Skill](SKILL.md)、[设计架构](docs/ARCHITECTURE.md)、[研究方法论](references/research-methodology.md) 和 [质量评估](evals/README.md)。

**下一阶段建议：** 引入可配置的多搜索提供方、受控抓取执行环境、基于语义的断言-证据判定和有人工标注的数据集，在此基础上开展回归评测。

