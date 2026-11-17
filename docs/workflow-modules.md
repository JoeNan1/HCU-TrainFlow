# 模块化拆分与子工作流

**状态：B1–B6 已实现。** 目录数据在 [`catalog/`](../src/hcu_trainflow/catalog)，其中 `registry.py` 是模块、别名和子工作流的唯一来源，`gates.py` 负责门禁派生，`plan.py` 负责自动接线与静态校验。`module-*`、`profile-*` 命令已经可用；`full` 模式的阶段、报告种类和门禁判定完全未改。

结构分三层：**24 个模块 → 16 个功能子工作流 → 4 个流程 profile**。功能子工作流是几个模块组成的整体功能（如 `baseline-megatron`、`quality-accept`、`adaptation-proxy`），本身没有阶段与门禁，可单独 `module-run`。

四个流程 profile：`llm-megatron`、`torch-native-llm`、`torch-native-vision`、`analysis-only`。前三个门禁与 `flow.GATES` 完全一致（分流瘦的是模块，不是门禁），`analysis-only` 因为只做到 profiling 阶段而只有一道 `analysis` 门。

本页说明拆分判据、模块目录、门禁派生、子工作流 profile 与用法。能力/Pipeline 的运行时契约见[模块化架构](modular-architecture.md)。

## 1. 目标与不变量

把 workflow 拆成可独立调用、可声明的模块；子工作流 = 模块子集 + **派生的**门禁。这样"场景分流"是组合结果，不需要维护多套流程，也不会出现第二份门禁清单。

四条不变量由回归测试锁定：

1. 现有全量回归继续通过（本轮 1587 passed / 3 skipped）；
2. `full` 模式行为完全不变（阶段、报告种类、门禁判定一致）；
3. 现有 capability 名与 CLI 继续可用；
4. 状态机只有 `flow.py` 一套，模块不新增阶段，也不推进阶段。

## 2. 拆分判据

| 规则 | 含义 |
| --- | --- |
| R1 单一证据产物 | 一个模块至多产出一种报告；复合能力降级为功能子工作流 |
| R2 只做确定性计算 | 输入来自参数或 Store 原件，输出结构化结果 |
| R3 不写远端、不改代码 | 模块不驱动被测程序内部；发命令统一走 `execution.command` |
| R4 判据不是模块 | gate/validator 是消费者，不进入目录 |

## 3. 模块契约字段

```json
{
  "id": "environment.probe",
  "actions": ["check", "collect"],
  "requires": {"contract": "environment-contract", "observations": "observation[]"},
  "provides": {"status": "verdict", "observations": "observation[]", "evidence": "artifact[]"},
  "report": "environment",
  "stage": ["prepared", "scale_ready"],
  "role": "check",
  "tags": {"engine": ["any"], "model_family": ["any"], "needs": []},
  "volatile": true,
  "route": "docs/environment-discovery.md"
}
```

| 字段 | 作用 |
| --- | --- |
| `requires` / `provides` | bindings 自动连线；类型可用 `a\|b` 声明可替代来源（如 `capability-result\|artifact-id`） |
| `report` | 门禁派生的原子；`null` 表示不产报告 |
| `stage` | 阶段范围。**产报告的模块**：该报告被要求的源阶段（`stage` 的出边门禁）；**不产报告的模块**：它运行的阶段 |
| `role` | 闭合枚举 `check\|collect\|execute\|analyze\|optimize\|judge\|deliver\|infra` |
| `tags` | 闭合词表：`engine: any\|megatron\|torch`、`model_family: any\|llm\|vision\|video`、`needs: hardware\|lease\|task-bound` |
| `volatile` | 是否每次重跑；运行时取"模块声明 ∪ 旧白名单"，因此不存在比旧规则更宽松的复用 |
| `route` | 该模块必读文档；子工作流的阅读面 = 其模块 route 并集 |

`stage` 的两种含义是刻意的：门禁只能从"哪些阶段的出边要求这份报告"推出，而运行范围是另一件事。写反了会被 `module-plan` 的 `stage-evidence-dropped` 检查抓到。

## 4. 模块目录（24 个，全部已实现）

| # | 模块 | 职责 | report | role | volatile | 能力调用 |
| --- | --- | --- | --- | --- | --- | --- |
| **环境与资源** | | | | | | |
| 1 | `environment.probe` | 契约 vs 观测逐项判定 | `environment` | check | 是 | `environment.check` |
| 2 | `resource.admission` | 占用/空闲准入（别名 `scale.admission`） | — | check | 是 | `environment.occupancy` |
| 3 | `resource.lease` | lease 申请/续期/释放 | — | infra | 是 | `resource.lease` |
| **执行与产物** | | | | | | |
| 4 | `execution.command` | 执行命令卡，落 stdout/stderr 原件 | — | execute | 是 | `execution.command` |
| 5 | `execution.stdout-json` | 把保留的 stdout 解释成结构化测量 | — | collect | 是 | `execution.stdout-json` |
| 6 | `artifact.collect` | 按 SHA 回执封存输出 | — | collect | 是 | `artifact.collect` |
| 7 | `source.transfer` | 源码快照/物化/打包 | — | collect | 是 | `source.transfer` |
| **适配** | | | | | | |
| 22 | `adaptation.launch-parity` | 上游启动要素 → HCU 要素的映射核对 | `adaptation-parity` | check | 否 | `adaptation.launch-parity` |
| 23 | `adaptation.config-diff` | 适配前后有效配置差异与依据 | `adaptation-diff` | check | 否 | `adaptation.config-diff` |
| 24 | `adaptation.numeric-equivalence` | 组件级数值对照（局部） | `adaptation-numerics` | judge | 否 | `adaptation.numeric-equivalence` |
| **训练与质量** | | | | | | |
| 8 | `training.summarize` | Megatron 日志 → 短基线摘要 | `baseline` | judge | 否 | `training.summarize` |
| 9 | `training.summarize-torch` | 声明格式的通用 torch 日志 → 同一短基线摘要 | `baseline` | judge | 否 | `training.summarize-torch` |
| 10 | `training.observe` | 训练过程观测（成员/停滞/心跳） | — | collect | 是 | `observation.collect` |
| 11 | `quality.loss` | 数值对照 | — | judge | 否 | `quality.loss` |
| 12 | `quality.iteration` | 单次迭代 kept/rejected（含 MAD 稳定性） | — | judge | 否 | `quality.iteration` |
| 13 | `quality.proxy` | 代理配置契约校验 | — | check | 否 | `quality.proxy` |
| 14 | `quality.qualify` | 短基线资格 | `baseline-qualification` | judge | 否 | `quality.accept/qualify` |
| **性能分析** | | | | | | |
| 15 | `profiling.trace` | trace 采集/转换/TraceLens 运行＋表格 | — | analyze | 是 | `profiling.tracelens` |
| 16 | `profiling.analyze` | 热点/上限/归因 | `analysis` | analyze | 否 | `profiling.analyze/analyze` |
| 17 | `profiling.summarize` | hipprof kernel 摘要＋设备 busy union | `profile-summary` | analyze | 否 | `profiling.analyze/summarize` |
| 18 | `profiling.communication` | 声明区间的通信/overlap 记账 | — | analyze | 否 | `profiling.communication` |
| **优化** | | | | | | |
| 19 | `optimization.change` | 记录一次改动的语义（diff/hash/依据/回退） | `optimization-change` | optimize | 否 | `optimization.change` |
| 20 | `optimization.benchmark` | 同 shape/dtype 隔离对照＋上限效率 | — | optimize | 是 | `optimization.benchmark` |
| 21 | `optimization.netgain` | 整步净收益与噪声判定 | `performance` | optimize | 否 | `optimization.netgain` |

8 与 9 都产 `baseline`，但 `engine` 标签互斥（`megatron` 与 `torch`），任何一次运行都不可能同时需要两者；目录校验按引擎检查报告唯一性，profile 层的"同一集合内不得有两个同报告产出者"仍然生效。日志格式契约见[训练状态验证](training-state-validation.md#纯-torch-训练日志的声明格式)。

**排除**：gate/validator、wiki/experience/reference、team/inbox/assignment、public-export。

19–21 只产证据与结构化判定，**不产出"该不该做"的结论**；20 明确声明自己不是整步净收益，21 明确声明净收益高于噪声也不等于验收通过。22–24 同理：它们证明"改动被记录、被映射、被量化"，不证明"适配通过"。

## 5. 三层：模块 → 功能子工作流 → 流程 profile

| 层 | 是什么 | 有没有阶段与门禁 |
| --- | --- | --- |
| 模块（21） | 一个确定性动作，至多一种证据产物 | 只有 `stage` 范围 |
| **功能子工作流**（16） | 几个模块组成一个整体功能，可单独跑 | **没有**：不声明 stages、不派生门禁 |
| 流程 profile（4） | 由子工作流（或模块）组合 + 阶段范围 | 有，门禁由模块派生 |

功能子工作流不是"缩短的流程"，它就是一个可独立调用的功能单元：`module-plan`/`module-run` 拿它当来源，输入接口由成员契约自动推导（`requires` = 成员 require 减去内部能满足的部分；`provides` = 成员 provides 并集）。

| 子工作流 | 模块 | 类型 | 外部输入（自动推导） |
| --- | --- | --- | --- |
| `environment-readiness` | `resource.admission`、`resource.lease`、`environment.probe` | composition | contract、observations、resource、owner、ttl |
| `environment-collect` | `execution.command`、`execution.stdout-json`、`environment.probe` | composition（`probe` 内置） | card、operation、lease、contract |
| `source-handoff` | `source.transfer`、`artifact.collect` | composition | repository、paths、files |
| `baseline-megatron` | `execution.command`、`training.summarize`、`artifact.collect` | composition | card、operation、lease、contract、files |
| `baseline-torch` | `execution.command`、`training.summarize-torch`、`artifact.collect` | composition | 同上 |
| `quality-accept` | `quality.loss`、`quality.iteration` | composition | contract、baseline、candidate、correctness、两组 times |
| `baseline-qualification` | `quality.qualify` | composition | training、environment、analysis |
| `adaptation-proxy` | `quality.proxy` | composition | full、candidate |
| `adaptation` | `adaptation.launch-parity`、`adaptation.config-diff`、`adaptation.numeric-equivalence` | composition | upstream、hcu、mapping、baseline、adapted、candidate、contract |
| `training-observation` | `training.observe` | composition | manifest、policy、state_dir |
| `hipprof-summary` | `profiling.trace`、`profiling.summarize` | composition | project、trace |
| `trace-attribution` | `profiling.trace`、`profiling.analyze`、`profiling.communication` | composition | project、trace、window、intervals、evidence |
| `optimization-netgain` | `optimization.change`、`optimization.netgain` | composition | before、after、baseline、candidate、evidence |
| `optimization-benchmark` | `optimization.change`、`optimization.benchmark` | composition | before、after、两组 times、shape、evidence |
| `profiling-tracelens` | `profiling.trace` → `profiling.summarize` | template | tracelens |
| `baseline-pipeline` | 从零短基线 8 步 | template | environment、training、training_contract、profiling、project |

`composition` 与 `template` 的区别只有一处：**现场形状是否重要**。`baseline-pipeline` 的步骤顺序、绑定和 report_kind 是踩过坑的固定接线，写成模板；其余组合交给自动连线，接线不唯一就报错（§9）。

模块别名（只能指向目录内条目，不能是独立实现）：

| 名称 | 指向 |
| --- | --- |
| `optimization.iteration` | `quality.iteration` |
| `adaptation.proxy` | `quality.proxy` |
| `scale.admission` | `resource.admission` |
| `environment.check` / `environment.occupancy` / `observation.collect` | 旧 capability 名，同样只映射到目录内条目 |

子工作流的旧名同样保留：`quality.accept/assess` → `quality-accept`、`profiling.tracelens` → `profiling-tracelens`、`environment.collect` → `environment-collect`。

`profiling.trace` 内部已完成采集与原件封存，所以 `profiling-tracelens` 不再重复插入 `artifact.collect`——设计稿里那一步是重复计数，已修正。

## 6. 报告与门禁派生（7 条规则）

1. 阶段门禁报告仍是 7 类：`environment`、`baseline`、`analysis`、`stage-quality`、`performance`、`scale`、`completion`。
2. `baseline-qualification`、`profile-summary`、`optimization-change`、`adaptation-parity`、`adaptation-diff`、`adaptation-numerics` 是**证据类**产物，派生时一律过滤，不进入阶段门禁：适配三件套只证明改动可追溯，不构成适配通过的门禁。
3. 源阶段 `s` 的出边门禁 = 声明 `s ∈ stage` 的模块的 `report` ∪ 该阶段的 Agent 撰写报告。
4. **Agent 撰写报告**是既有事实：`stage-quality`、`scale`、`completion` 没有模块产出，由候选与复核流程提交，体现在 `catalog.contracts.AGENT_AUTHORED`，派生时必须显式并集。
5. `llm-megatron` 派生结果与现行 `flow.GATES` **逐项相等**，由 `tests/test_module_catalog.py` 锁死（按目标阶段比较集合）。
6. 任一子工作流派生结果 ⊆ 全量报告集，且 `missing_producers` 为空——被保留的阶段不得缺失证据。
7. `optimization-change` 不进 gate，但**声明了优化收益的候选必须携带其原件引用**，否则 `needs-repair`（`flow.submit` 的既有规则）。

## 7. 子工作流 profile

```json
{
  "id": "torch-native-vision",
  "applies_to": {"engine": ["torch"], "model_family": ["vision", "video"]},
  "subworkflows": ["environment-readiness", "environment-collect", "source-handoff",
                   "baseline-torch", "quality-accept", "training-observation",
                   "trace-attribution", "optimization-netgain"],
  "stages": ["prepared", "environment_checked", "baseline_validated",
             "profiling", "optimizing", "scale_ready", "training"],
  "defaults": {"budget": {"max_operations": 120, "max_seconds": 86400}},
  "notes": "为什么这么裁：单机 CNN/视频模型不装代理配置、短基线资格、隔离基准与 hipprof 摘要"
}
```

profile 用 `subworkflows`（组合）或 `modules`（直接列，二者只能选一个）。`analysis-only` 用后者，因为它没有成对的功能组合。`module_ids()` 负责把子工作流展开成模块并去重；profile 之间不会重复维护同一份模块清单。

**profile 禁止出现 `reports`、`gates`、`reading`**：报告由模块派生，阅读面由 `route` 并集派生，`Profile.from_dict` 会直接拒绝这三个字段。`stages` 是必须声明的**阶段范围**，它是门禁派生的第二个输入（第一个是模块集）。

| profile | 模块 | 派生门禁 |
| --- | --- | --- |
| `llm-megatron` | 20（无 `training.summarize-torch`） | 与现行 `flow.GATES` 完全相同 |
| `torch-native-llm` | 20（无 `training.summarize`） | **与 llm-megatron 相同**：只换日志摘要模块，门禁一项不减 |
| `torch-native-vision` | 16（无 `training.summarize`、`quality.proxy`、`quality.qualify`、`optimization.benchmark`、`profiling.summarize`） | **与 llm-megatron 相同**：只减少执行模块，门禁一项不减 |
| `analysis-only` | 7（只读，不给任何 `optimization.*` 与日志摘要） | 仅 `{"optimizing": ["analysis"]}`（`stages = ["profiling"]`） |

设计稿曾写 vision "无 `scale`"。实现时发现那等于砍掉训练准入的一份证据，违反不变量 6，因此改正为：**子工作流只减少模块，不减少门禁**；唯一门禁更窄的 profile 是 `analysis-only`，因为它明确不做训练阶段（`stages` 只到 `profiling`）。

纯 torch 大模型（torchtitan/nanotron 等）此前会因为找不到 Megatron 日志解析器而路由失败；`training.summarize-torch` 补上了这个缺口，`{"engine":"torch","model_family":"llm"}` 现在唯一命中 `torch-native-llm`。

## 8. 路由规则

```bash
hcu-trainflow --workspace /private/task/store profile-resolve /private/task/context.json
```

`context.json` 形如 `{"engine": "torch", "model_family": "vision"}`，可用 `"requested": "<profile>"` 显式指定。

| 结果 `status` | 含义 |
| --- | --- |
| `pass` + `reason: unique-match` | 唯一命中，直接采用 |
| `pass` + `reason: explicit` | 显式指定且与 context 不冲突 |
| `select` + `candidates` | 多个候选中，Agent 必须选一个并记录理由（不猜） |
| `halt` + `halt_reason: profile-unknown` | 无候选，回到人；不推进任何阶段 |

显式 profile 与 context 冲突（例如 `engine=torch` 却指定 `llm-megatron`）直接报错，不是静默改选。路由**不推进任何阶段**，只产出候选与理由。

## 9. 编排与校验

```bash
hcu-trainflow module-catalog
hcu-trainflow subworkflow-list
hcu-trainflow profile-list
hcu-trainflow module-plan /private/task/modules.json
hcu-trainflow module-plan /private/task/modules.json --stage prepared
hcu-trainflow --workspace /private/task/store module-run /private/task/modules.json --task TASK_ID
```

`--stage S` 只保留 `stage` 包含 S 的模块，输出可直接 `module-run`；越界或空集即报错。

`modules.json` 只需声明来源与输入，`profile` / `subworkflow` / `modules` 三选一（`preset` 是 `subworkflow` 的旧写法）：

```json
{
  "schema_version": 1,
  "subworkflow": "baseline-megatron",
  "inputs": {"card": {}, "operation": "op-1", "lease": {}, "contract": {"context": "..."}, "files": {}},
  "capabilities": ["hardware", "lease", "task-bound"],
  "bindings": {"quality.qualify.analysis": {"step": "profiling.summarize", "path": ["analysis"]}}
}
```

- `module-catalog`：目录（含 requires/provides/report/stage/role/tags/route/实现映射）与每个子工作流的外部接口。
- `subworkflow-list`：只看功能子工作流及其 `interface`（`requires`/`provides`/`reports`）。
- `module-plan`：静态校验并输出 `gates`、`plan`、`problems`；`status` 为 `pass` 仅当能真正跑起来。
- `module-run`：复用 `RuntimeService`（落库、恢复、报告登记不变），任务绑定时自动补 `task-bound` 能力。

子工作流作为来源时 `gates` 为 `null`：功能层不声明阶段范围，门禁只在 profile 上派生。

运行输入默认共享给所有步骤；两个模块需要**同名但不同值**的输入时（例如 `adaptation.config-diff` 与 `adaptation.numeric-equivalence` 各自的 `baseline`），用 `step_inputs` 按 `<module>.<input>` 只给其中一个模块播种：

```json
{
  "subworkflow": "adaptation",
  "inputs": {"upstream": {}, "hcu": {}, "mapping": [], "contract": {}},
  "step_inputs": {
    "adaptation.config-diff.baseline": {"tp": 8},
    "adaptation.config-diff.adapted": {"tp": 4},
    "adaptation.numeric-equivalence.baseline": {"components": {"forward": [1.0]}},
    "adaptation.numeric-equivalence.candidate": {"components": {"forward": [1.0]}}
  }
}
```

不写 `step_inputs` 时同名输入会被两个步骤共用——这不会静默出错，但会让 diff 和数值对照读到同一份基线，属于调用方必须显式表达的事。

| `problems.kind` | 含义 |
| --- | --- |
| `missing-input` | 没有提供者也不在运行输入里 |
| `ambiguous-input` | 多个模块提供同名同类型输出；必须显式绑定 |
| `binding-outside-set` | 显式绑定指向集合外的步骤 |
| `unsatisfied-need` | `needs`（hardware/lease/task-bound）未被声明 |
| `stage-evidence-dropped` | 保留的阶段缺少某份报告的产出者 |
| `module-not-implemented` | 目录里声明了但没有实现 |
| `invalid-wiring` | 接线通不过 Pipeline 计划校验（防御性） |

自动连线规则：**同名 + 类型匹配 + 唯一提供者**。多候选或缺失一律报错，不静默猜测；显式绑定的键在输入名唯一时写 `<input>`，否则写 `<module>.<input>`。报告登记由 `report` 派生到步骤 `config.report_kind`，仅在任务绑定时生效，且没有真实证据的步骤只留 incomplete（不会把摘要当成原件）。

把整个 `llm-megatron`（23 个模块）一次性 `module-plan` 会得到 `ambiguous-input` 与 `missing-input`：`analysis` 有两个产出者（`profiling.analyze` 与 `profiling.summarize`），且多数输入来自现场。这是预期结果——profile 声明的是"这个场景需要哪些模块"，实际运行总是取子集或功能子工作流；`module-plan` 的价值正是把这种不可能接线提前说清楚，而不是猜一个。

`baseline-pipeline` 子工作流是声明式的（template），`services.baseline_pipeline(...)` 就是它的调用入口——同一份接线同时服务 Python 与 `module-run`，因此不存在两份实现。

## 10. 护栏

| 风险 | 护栏 |
| --- | --- |
| 子工作流各自维护报告列表 | 只允许派生；profile 禁止 `reports`/`gates` 字段 |
| 标签词表失控 | 闭合词表 + 新增需评审（`Module` 构造即校验） |
| 别名偷偷并存 | 别名只能指向目录内条目，且不能遮蔽模块 id |
| 路由变成第二状态机 | 只返回候选与理由，不推进阶段 |
| 分流后阅读面没变薄 | `analysis-only` 阅读面 6/18 ≈ 0.33，`torch-native-vision` 16/18 ≈ 0.89 |
| 门禁被顺手放宽 | `llm-megatron` 派生 == `flow.GATES`；profile 派生 ⊆ 全量且 `missing_producers` 为空；`required_reports` 对 profile 未覆盖的阶段回落全量门禁，派生更宽直接报错 |
| 优化/适配模块把"判断"伪装成"计算" | 19–21、22–24 只产证据，`limits` 与 `stage_equivalent` 字段显式声明边界 |
| 契约与实现漂移 | 每个模块都映射到已注册 capability/action，测试逐项核对 |
| 借用别的任务的证据 | `report-add` 校验被引对象归属，只属于其他任务即拒绝（`tests/test_integrity_guardrails.py`） |
| 报告正文的数字与原件不符 | `claims` 逐条解析 `source.path` 并与 `value` 比对；profile 任务的 pass 必须带 claims |
| 上下文被压缩后约束消失 | `flow-next`/`flow-brief` 每次从存储重新下发 `invariants`；agent 的 `--notes` 不参与判定 |
| 凭记忆推进（换会话/长跑） | `--brief-hash` 绑定状态，过期即 `stale-brief`；自主任务缺哈希为 `unverified-turn` |
| 目标被悄悄改写 | `flow-align` 对照存储 plan 列出 delta，有 delta 必须 `flow-replan` 留理由 |

## 11. 批次与验收

| 批 | 内容 | 状态 | 验收判据 |
| --- | --- | --- | --- |
| B1 | 契约（含 stage/role/tags/route）+ `module-catalog` + 门禁派生 + `profile-resolve` + 基础模块 + profile | 完成 | 派生门禁 == 现状；全量回归 1548 passed |
| B2 | 补 2、3、7、10、11、12、13 + `baseline-pipeline` 声明式 | 完成 | 接线与历史 8 步逐项一致（`tests/test_module_plan.py`） |
| B3 | 性能族 15–18 | 完成 | 既有 TraceLens/hipprof 能力等价；通信记账新增回归 |
| B4 | 优化族 19–21 + 三个 profile | 完成 | 三个 profile 各跑一个合成任务（`module-plan`/`module-run` 回归） |
| B5 | 通用 torch 日志模块 9 + `torch-native-llm` profile | 完成 | `{"engine":"torch","model_family":"llm"}` 唯一命中；四个 profile 派生门禁 ⊆ 现状 |
| B5.5 | 功能子工作流层（15 个）+ profile 改为组合 + `subworkflow-list` | 完成 | 接口自动推导；`module-run` 能直接跑 `quality-accept`；旧 preset 名仍可用 |
| B6 | 适配模块 22–24 + `adaptation` 子工作流 + `step_inputs` | 完成 | 三个 profile 都含适配模块；三份证据均不进阶段门禁；`module-run` 能登记 `adaptation-diff` |
| B6 | `spec.profile` + `flow.required_reports` 按派生门禁 + `module-plan --stage` + `expected_evidence` | 完成 | 见 §14；`llm-megatron` 派生 == 现状，profile 未覆盖阶段回落全量 |

每批结束执行：全量回归、`python scripts/check_documentation.py`、`python scripts/check_skill_resources.py`、本机同步 `--check`。

## 12. 兼容与回退

- 旧 capability 名、CLI 与旧 preset 名不退场，全部映射到目录内条目或子工作流。
- 模块层与门禁派生是新增代码，删除 `catalog/` 与 6 个新 capability 即回到原状；`services.baseline_pipeline` 的签名与输出未变。
- `RuntimeService` 只多了可选参数 `volatile_steps`；不传时行为与之前完全相同。

## 13. 已知缺口

- **真实硬件未验证**：全部证据是合成/CPU 回归，"目录与门禁一致"不等于真机无人验收。
- `torch-native` 场景仍缺这些专属模块（按同一契约新增，不要混进重构批次）：数据加载/输入流水检查、AMP 与数值模式、`compile` 断图与重编译、DDP/FSDP 扩展性检查、视频模型的序列/解码显存。
- `profiling.communication`、`optimization.benchmark`、`optimization.netgain` 目前只做声明区间/计时的确定性记账；从真实 profiler 输出到这三份输入的适配器仍需按站点补齐。
- `module-run` 只为任务绑定运行登记报告；独立运行（无 `--task`）不发布任何任务报告，沿用既有边界。
- 适配三件套目前只吃**声明好的**记录（启动要素、配置快照、组件张量样本）；从真实工程里抽取这些输入的适配器（例如从 effective-args dump 生成配置快照、从 HCU/上游对照脚本导出组件数值）仍需按站点补齐。
- 适配模块不判断"这个改动是否正确"——那是 Agent 与独立复核的职责，模块只保证改动被记录、被映射、被量化。

## 14. B6：把门禁接进任务（已完成）

之前 profile 只活在 `profile-resolve` 的输出里，`flow.required_reports` 仍然只看 `flow.GATES`——分流是计划层建议。现在三处都接上了：

1. **`spec.profile`**：任务声明 `{"id": "<profile>", "reason": "<为什么选它>"}`，两个字段都必填、字段封闭。`flow-start`（含 replan）校验 profile 存在且与任务 context 的 engine/model_family/mode 不冲突，否则拒绝启动。选择 profile 不推进任何阶段。
2. **门禁按 profile 派生**：`flow.required_reports` 取 `catalog.derived_gates(profile)`；**profile 未覆盖的目标阶段回落到全量 `flow.GATES`**（fail-closed），派生结果若比全量门禁更宽直接报错。因此"分流"只能减模块，不会减掉任何仍被保留阶段的证据；`llm-megatron` 的派生结果与 `flow.GATES` 逐项相等，行为零变化。
3. **`module-plan --stage <stage>`**：只保留服务于该阶段的模块，输出可直接交给 `module-run`。`--stage prepared` 就是 adapt 阶段的模块集（环境就绪 + 执行 + 适配三件套），它的门禁只有 `environment`。

非门禁证据（`baseline-qualification`、`profile-summary`、`optimization-change`、`adaptation-*`）由 `flow.next_step` 以 `expected_evidence` 形式给出：**只是提示**，不进 `required_reports`，不会阻挡推进。这样适配证据能挂进 adapt 阶段，又不至于把一份证据型记录变成新门禁。

```bash
hcu-trainflow module-plan /private/task/plan.json --stage prepared
hcu-trainflow --workspace /private/task/store flow-next TASK_ID     # 带 profile 与 expected_evidence
```

护栏：`tests/test_profile_wiring.py` 锁死四件事——profile 未覆盖的阶段回落到全量门禁、派生不能放宽门禁、adapt 阶段的证据不进 `required_reports`、`--stage` 越界即报错。
