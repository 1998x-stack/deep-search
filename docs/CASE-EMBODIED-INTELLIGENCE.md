# Case: 具身智能（人形机器人）产业链调查

This case exercises the branch end to end: **pi `iagent/standard` LLM** +
**Playwright browser search provider** + **loguru logging** + the evidence
audit gates. It is split into 分析 (analysis), 测试 (tests) and 研究 (a real,
audited research run), because each stage produced different findings — some of
which are failures of the environment, not of the code.

* Date: 2026-11-13
* Branch: `factory/cleanrl-deepseek-google-v1`
* Model: `iagent/standard` (`https://iagent.iauto.com/v1`, resolved from
  `~/.pi/agent/models.json`, key via `!cat /home/ubuntu/.config/ai-credentials/iauto_api_key`
  — never printed or persisted)
* Final artifacts: `runs/embodied-ai-chain-20261113/` (git-ignored)

---

## 1. 分析 — chain analysis and research design

### 1.1 Why this topic stresses the factory

The question is a *multi-layer industrial-chain* question, not a single fact
check. It requires:

* source types with different incentives: 券商研报/产业报告 (sell-side), 政府与
  协会公告, 公司官网 (self-reported), 媒体调查 (journalistic), 海外研究机构,
  学术论文;
* statistics with incompatible definitions: 规划产能 vs 已下线 vs 已交付 vs 已
  进入生产场景; 出货量 by 厂商 vs 机构统计;
* claims that are commercial or promotional rather than falsifiable.

### 1.2 Chain map used for scoping (evidence from the final run)

| Layer | Nodes | Evidence status in this run |
| --- | --- | --- |
| 上游 核心零部件 | 谐波/行星减速器, 行星滚柱丝杠, 无框力矩电机, 空心杯电机, 六维力/力矩传感器, 触觉传感器, 编码器, 灵巧手, 3D 视觉, 芯片/域控 | Executors dominate BOM (40–60% per McKinsey) [S017]; supplier-ecosystem maturity is uneven [S017]; domestic progress documented mostly at announcement level [S002][S006] |
| 中游 本体/量产 | 人形/四足整机厂, 具身大模型 (VLA/世界模型), 产线与质量体系 | 出货统计 conflict across institutions [S010][S011]; planned capacity ≫ delivered units [S009][S012] |
| 下游 应用 | 工业制造, 仓储物流, 商演/科研/数采, 家庭与康养 | ≈80% of shipments went to 数采/科研/文娱, ≈18% into manufacturing/logistics [S011][S016] |
| 横向 | 数据 (真机/仿真), 资本, 地方政策与国资 | Data gap (>95% claimed) and circular 数采中心 funding reported by survey journalism [S016][S014] |

### 1.3 Testable hypotheses (as executed)

* H1: 上游国产替代 progress is *announced* but documented精度/寿命/一致性 data
  is thin. → observed: mostly announcement-level evidence [S002][S006].
* H2: 量产 claims and 交付 reality diverge. → observed: capacity plans in the
  ten-thousands vs ≈1.5万台 cumulative delivery [S009][S012].
* H3: 下游 structure is dominated by demonstration, not production. → observed:
  ≈18% production-scenario share [S011].
* H4 (falsifier for the marketing narrative): evidence for "规模化盈利交付" is
  absent; the run marks such claims 未验证 rather than refuted.

### 1.4 Falsification / counterevidence strategy

The reflection lane is required to search for disconfirming material. The
discovery pool therefore deliberately contains four 泡沫/质疑 sources
([S007], [S014], [S015], [S016]) alongside promotional ones, and the planner
prompt asks for at least one query that could falsify the user's premise.

---

## 2. 测试 — what was actually tested, and what broke

All commands were executed in a `.venv` (`uv venv`, Python 3.12.3) with
`loguru 0.8.0` and `playwright 1.65.1` (+ cached Chromium 1254).

| # | Test | Command | Result |
| --- | --- | --- | --- |
| T1 | Offline unit suite | `python -m unittest discover -s tests` | **130 passed** (63 pre-existing, 67 new: logging, pi-config, iagent, replay, capabilities) |
| T2 | Real-Chromium DOM integration | `python -m unittest discover -s tests -p 'test_browser_integration.py'` | **pass** (route-fulfilled Bing HTML parsed, blocked-challenge path fails closed) |
| T3 | Offline structural benchmark | `python benchmarks/offline_eval.py --out runs/evals` | **2/2 cases** pass, `factual_accuracy_tested=false` |
| T4 | iagent connectivity smoke | `python scripts/live_smoke.py --live --llm iagent --provider playwright` | model **pass**; browser search **0 results** → reported as `search_contract: empty` |
| T5 | iagent behaviour probe | `python scripts/probe_model.py --live --max-output-tokens 1200` | **3/3 checks pass** (plain text, JSON object, JSON plan with 3 queries); key source `pi_models_json:command`; JSON corrections 0 |
| T6 | Live Playwright engine quality | `PlaywrightSearch.search("具身智能 产业链 …")` on bing + duckduckgo | **degraded**: Bing returns dictionary/ad pages for CJK *and* English queries from this datacenter IP; DuckDuckGo unreachable (`ERR_CONNECTION_REFUSED`); Bing RSS degraded too |
| T7 | Log redaction / sinks | `tests/test_logging.py` + grep of run artifacts | **pass**, no credential in `logs/*`, `run.jsonl` parses record-by-record |
| T8 | First live case run | strict lane, `max_output_tokens 4000` | **failed**: `iagent output truncated (max_output_tokens exhausted…)` at the evidence stage (24 sources) |
| T9 | Second live case run | strict lane, `max_output_tokens 8192`, 18 sources | **completed**, but the human `run.log` was empty → found `NameError` in `configure_logging` (extra fields not bound); fixed and retested with a mock run |
| T10 | Third live case run | same config, hardened-`SYNTHESIS` prompt | **incomplete**: strict gate `requires body citations for supported claims` (model under-cited) |
| T11 | Final live case run | fourth invocation, same config | **completed**, strict `audit.valid=true`, `readiness.ready=true` |

### 2.1 Engine findings (documented, not worked around)

* Bing (both the Playwright SERP and `?format=rss`) answered this host's CJK
  queries with dictionary entries (`zdic.net`, `baike.baidu.com`) and
  advertisement pages. An explicit `mkt=zh-CN&setlang=zh-hans` market parameter
  worked once, then stopped working — i.e. an IP-level degradation, not a query
  syntax problem. No stealth, CAPTCHA or proxy workaround was attempted, in line
  with the repository rules.
* `html.duckduckgo.com` is network-unreachable from this host, and the
  DuckDuckGo SERP times out.
* Google Custom Search requires credentials that are not present here.
* Consequence: the *automatic* discovery step is unusable in this environment.
  The case therefore uses the new, explicitly labelled `--provider replay`
  (operator-imported discovery list) documented below — real URLs with
  provenance, not invented ones.

### 2.2 Model findings

* `iagent/standard` (served as `DeepSeek-V4-Flash`) reasons by default;
  reasoning tokens are billed inside `max_tokens`. The adapter sends
  `chat_template_kwargs={"thinking": false}` unless `--llm-thinking` is given,
  which kept reasoning tokens at 0 and latency at ~0.2–3 s per call.
* `response_format={"type":"json_object"}` is honoured;
  `{"type":"json_schema"}` is **not** used — on this endpoint schema mode can
  return `content=null` with `finish_reason=length` after spending the whole
  budget on reasoning.
* Verified: one corrective retry on invalid JSON, balanced-brace/fenced recovery,
  explicit failure on truncation, usage tally including reasoning tokens.
* A bare `{"ok": true}` probe returns inconsistent values (e.g. `{"ok": 16}`);
  the smoke now asks for a concrete field list, which is reliable (3/3).

### 2.3 Modelling budget finding

Evidence extraction over 24 fetched pages exceeded 4000 output tokens. The final
configuration uses `max_output_tokens 8192`, `max_sources 18`,
`results_per_query 4`. Exceeding the budget fails closed with an explicit error
rather than producing a partial ledger.

---

## 3. 研究 — the audited run

```bash
python algorithms/strict_research.py \
  --config configs/cases/embodied-intelligence-chain.json \
  --question "具身智能（人形机器人）产业链调查：上游核心零部件、中游本体与量产、下游应用的真实进展与瓶颈是什么？哪些对外宣称缺乏证据支持？" \
  --out runs/embodied-ai-chain-20261113
```

Observed result (`run.json`, `audit.json`):

| Field | Value |
| --- | --- |
| `status` | `completed` |
| `stop_reason` | `critic_requested_stop` |
| sources / fetches | 18 sources, 18 fetch attempts (17 with full text) |
| claims | 35 (30 with anchored supporting evidence) |
| `audit.valid` | `true` (strict lane) |
| `audit.readiness.ready` | `true` |
| llm usage | 52 274 prompt + 9 568 completion tokens, 0 reasoning tokens |
| discovery mode | `operator_imported` (provenance in `discovery.json`) |
| logs | `logs/run.log` 8.5 KB, `logs/run.jsonl` 46 KB, `logs/errors.log` empty |

Substantive findings of the report (see `runs/embodied-ai-chain-20261113/report.md`):

1. 上游: 执行器占 BOM 40–60%; supplier-ecosystem maturity is uneven
   (executors/hands/force-tactile sensing least mature; compute and batteries
   borrowing EV/consumer-electronics capacity) [S017].
2. 中游: institution-level statistics conflict (2026H1 shipments ~2.2万台
   [S011] vs "+94% 2026 output" [S010]); planned capacity (10k-level [S009];
   75k/yr claim [S010]) is far above the ≈1.5万台 cumulative delivery [S012].
3. 下游: ~80% of shipments go to data collection/research/entertainment;
   ≈18% into manufacturing and logistics [S011][S016].
4. 未获独立证据的宣称: 数采中心 circular-funding allegations and associate-party
   claims [S016]; company-site "率先打通规模化路径" [S013]; market-size
   forecasts from supply-chain vendors [S018] — recorded as unverified, not as
   facts and not as refutations.
5. 结构性判断: the chain is transitioning from prototype to small-batch trial
   production; "量产/规模化/落地" wording should be mapped to
   prototype → trial → mass production → commercial delivery → profitable
   delivery before being accepted.

### 3.1 Discovery provenance (why `--provider replay`)

`fixtures/embodied-intelligence-chain-discovery.json` holds 28 real search
results collected with an external keyed web API (4 queries, 2026-11-13) plus a
mandatory `provenance` block. The provider:

* refuses lists marked `synthetic=true` (use `--provider mock`) and lists
  without provenance;
* ranks by deterministic query-term overlap and never serves the same URL twice;
* marks every hit `provider=operator_imported_discovery`, and the run manifest
  records `discovery_mode=operator_imported` + the provenance;
* is discovery-only: evidence still had to be anchored to full text retrieved by
  the bounded fetcher, which is what the 30 anchored claims rest on.

Two discovered URLs were excluded (unresolvable DNS; zero extractable text) and
PDF-only research notes were excluded because the fetcher accepts HTML/text —
this curation is recorded verbatim in the fixture.

### 3.2 Reproduction and limitations

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[browser]"
.venv/bin/python -m unittest discover -s tests -v
# live run (paid model calls; no Google CSE key needed for the replay lane)
.venv/bin/python algorithms/strict_research.py \
  --config configs/cases/embodied-intelligence-chain.json \
  --question "<question above>" --out runs/embodied-ai-chain-20261113
```

Limitations, stated not hidden:

* Offline tests and the corpus curated here cannot certify factual accuracy;
  `audit.json.readiness.factual_accuracy_tested` is `false`.
* The final run needed four live attempts: one truncation failure and one strict
  citation failure are preserved under `runs/*-attempt*/` precisely because they
  are real results.
* Automatic web discovery was unavailable (see 2.1). With Google CSE credentials
  or a working engine, run the same case with
  `--provider google` / `--provider playwright` and no `--search-fixture`.
* `audit.json.readiness` is a mechanical gate: it checks anchoring and citation
  presence, not semantic entailment or source independence. Several report
  numbers rest on a single 券商 or vendor source.
* Live provider integration is not exercised by CI; the iagent endpoint,
  Bing/DuckDuckGo availability and Chinese-site reachability are environmental
  facts that can change.
