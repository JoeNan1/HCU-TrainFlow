# 调用方式：模块、子工作流与流程 profile

> 一页说清三层怎么调用：入参是一份 JSON 文档，命令只当动词，判定看返回的 `status`。命令之外的 Python 入口（`catalog.build_plan`、`RuntimeService`、`flow.*`）与 CLI 是同一份实现，没有第二套逻辑。契约细节见[JSON 契约](contracts.md)与[模块化拆分与子工作流](workflow-modules.md)。

## 1. 三层与四种调用形态

| 层 | 形态 | 命令 | 改任务状态 | 产物 |
| --- | --- | --- | --- | --- |
| 模块（24 个） | 单能力 | `capability-run <capability> FILE` | 否 | 结果 + 证据 artifact |
| 模块 | 单模块/多模块计划 | `module-plan FILE` → `module-run FILE` | 否（带 `--task` 只做登记） | 可执行步骤 + 报告 |
| 子工作流（16 个） | 功能组合 | `module-plan FILE`（`{"subworkflow": ...}`）→ `module-run` | 否 | 证据报告 |
| 流程 profile（4 个） | 一次性计划 | `module-plan FILE`（`{"profile": ..., "stage": ...}`）→ `module-run` | 否 | 某阶段的模块子集与证据 |
| 流程 profile | **正式任务** | `task-create` → `flow-start` → `flow-next` 循环 | **是** | 阶段、门禁、复核、证据绑定 |

判断句：**要阶段、要门禁、要独立复核 → 正式任务；只要一组证据 → 子工作流；只要一份结果 → 单能力。**

## 2. 模块调用

### 2.1 单能力：`capability-run`

```bash
hcu-trainflow --workspace .work/T capability-run environment.check .work/T/req.json
```

```json
{
  "action": "check",
  "inputs": {"contract": {"context": "ctx-1", "required": []}, "observations": []},
  "config": {}
}
```

请求字段是封闭集：`action`、`inputs`、`config`、`request_id`，以及可选的 `task_id`（绑定任务）与 `context`（独立运行时必须是字符串）。能力名从 `capability-list` 取，模块的 `implementation` 就是 `(capability, action)`。

### 2.2 按模块 id：`module-plan` + `module-run`

```json
{
  "schema_version": 1,
  "modules": ["training.summarize"],
  "capabilities": ["task-bound"],
  "inputs": {"contract": {"context": "ctx-1"}},
  "context": {"context": "ctx-1"}
}
```

```bash
hcu-trainflow --workspace .work/T module-plan .work/T/module.json
hcu-trainflow --workspace .work/T module-run  .work/T/module.json --task T
```

`module-run` 要求计划 `status=pass`；`--task` 会补上 `task-bound` 能力，未绑任务时必须给 `context.context`。

### 2.3 模块计划文档的字段

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 只能是 `1` |
| `profile` / `subworkflow`（旧名 `preset`）/ `modules` | 三选一，不能同时出现 |
| `stages` | 覆盖范围，用于"保留阶段缺产出者"的检查 |
| `stage` | 只保留服务该阶段的模块（等价 CLI `--stage`） |
| `inputs` | 所有步骤共享的运行输入 |
| `step_inputs` | 同名输入分别播种，键必须是 `<module>.<input>` |
| `bindings` | 显式接线：`"<module>.<input>": {"step": "<id>", "path": ["key"]}` |
| `capabilities` | `hardware` / `lease` / `task-bound`；未声明即 `unsatisfied-need` |
| `name` | 可选计划名 |

自动接线规则：**同名 + 类型匹配 + 唯一提供者**；多候选或缺失都报错，不猜。报告由模块 `report` 派生到步骤 `config.report_kind`，未绑任务的步骤只留 incomplete。

## 3. 子工作流调用

```json
{
  "schema_version": 1,
  "subworkflow": "trace-attribution",
  "capabilities": ["hardware", "task-bound"],
  "inputs": {"project": "/repo", "trace": "/repo/trace.json",
             "window": {"start": 0}, "intervals": {}}
}
```

```bash
hcu-trainflow --workspace .work/T subworkflow-list
hcu-trainflow --workspace .work/T module-plan .work/T/sub.json
hcu-trainflow --workspace .work/T module-run  .work/T/sub.json --task T
```

| 要点 | 说明 |
| --- | --- |
| 名字 | 只能用 `subworkflow-list` 里的名字；旧名 `quality.accept`、`quality.assess`、`profiling.tracelens`、`environment.collect` 仍可解析 |
| 接线 | `composition` 自动连线；`template`（`baseline-pipeline`、`profiling-tracelens`）用固定步骤加 `$input` 替换 |
| 输入 | 成员 `requires` 里内部无人提供的那部分，可用 `interface()` 查看 |
| 门禁 | 子工作流**不声明阶段、不派生门禁**，返回的 `gates` 为 `null` |

## 4. 流程 profile 调用

### 4.1 一次性计划：按阶段切片

```json
{
  "schema_version": 1,
  "profile": "llm-megatron",
  "stage": "environment_checked",
  "capabilities": ["hardware", "lease", "task-bound"],
  "inputs": {"card": {"cmd": "train.sh"}, "operation": "op-1", "lease": {"id": "l1"},
             "stdout_artifact": "sha", "contract": {"context": "ctx-1"}, "files": []}
}
```

```bash
hcu-trainflow --workspace .work/T profile-resolve .work/T/context.json
hcu-trainflow --workspace .work/T module-plan .work/T/slice.json
hcu-trainflow --workspace .work/T module-run  .work/T/slice.json --task T
```

按阶段切片后只保留服务该阶段的模块，`gates` 是该切片能支持的阶段门禁。直接对整个 profile 出计划只会得到接线检查结果：现场输入必然 `missing-input`，这正是它的用途——把不可能接线提前说清，而不是替调用方猜。

### 4.2 正式任务：唯一带阶段与复核的形态

```json
{
  "schema_version": 1,
  "task_id": "qwen3-8b-meg",
  "mode": "full",
  "objective": "在 8 卡 HCU 上跑通并优化 Qwen3-8B 预训练，最终扩到 64 卡",
  "context": {"source": "site-a", "engine": "megatron", "model_family": "llm",
              "model": "Qwen3-8B", "data": "pile-1T", "baseline": "frozen-v1"},
  "permissions": ["execute"],
  "budget": {"max_operations": 240, "max_seconds": 259200},
  "profile": {"id": "llm-megatron", "reason": "Megatron 大模型完整流程"}
}
```

```json
{
  "acceptance": {
    "environment": "所有分配设备和相关互联有可比预期与验收证据",
    "quality": "阶段候选相对初始冻结基线通过约定的 loss 与梯度验证",
    "performance": "给出热点覆盖、非通信上限模型及 profiler-off 性能",
    "scale": "恢复完整模型、逐级扩 DP 域验证及约定时长稳定运行"
  },
  "max_rounds": 20,
  "max_stalled_rounds": 3,
  "full_review_every": 4,
  "max_review_failures": 3,
  "poll_seconds": 300
}
```

```bash
hcu-trainflow --workspace .work/T task-create .work/T/spec.json
hcu-trainflow --workspace .work/T flow-start  qwen3-8b-meg .work/T/plan.json
hcu-trainflow --workspace .work/T flow-next   qwen3-8b-meg
hcu-trainflow --workspace .work/T flow-brief  qwen3-8b-meg
```

之后按 `action` 走：`work` 后形成候选并 `flow-submit ... --brief-hash H`，`review` 交给独立 reviewer 再 `flow-review`，`advance` 时 `flow-advance`。阶段边界跑 `flow-align` 对账。只有这一层会派生 `required_reports`、跑门禁、要求独立复核、校验 `claims` 与 `brief_hash`。

`mode` 决定终点与要交的报告：`full` 交全部阶段门禁；`environment`/`analyze`/`optimize`/`diagnose`/`operate` 只交各自交付报告，`optimize` 另加 `performance`。

## 5. 返回、判定与退出码

| 项 | 规则 |
| --- | --- |
| 输出 | 每个命令一个 JSON；判定看 `status`（`pass`/`incomplete`/`blocked`/`halt`/`attention` 等） |
| 退出码 | `0` 正常；`2` 需处理（`incomplete`/`blocked`/`halt`/`attention`/`failed`）；`1` 调用本身出错 |
| 计划问题 | `problems[].kind` 取 `missing-input`、`ambiguous-input`、`unsatisfied-need`、`stage-evidence-dropped`、`module-not-implemented`、`binding-outside-set`、`invalid-wiring` |
| 证据 | `module-run` 只登记证据与报告；推进判定在 `flow-advance` |
| 护栏位置 | `claims`、`brief_hash`、`invariants`、证据归属只在正式任务的写入边界生效 |

## 6. 常见入口措辞对应的调用

入口措辞可以不写 JSON；下表是主控把一句话落到具体调用时的规范路径。`context` 里写清 `engine`/`model_family` 才能唯一命中 profile。

| 入口 | mode | profile | 第一组调用 |
| --- | --- | --- | --- |
| 从新模型开始，跑通并优化，最后扩到目标卡数 | `full` | `llm-megatron` 或 `torch-native-llm` | `task-create` → `flow-start` → `flow-next` 循环 |
| 只检查环境 | `environment` | 目前无专属 profile：不声明 profile，按全量门禁运行，交付 `environment` 报告 | 同上 |
| 只分析性能 | `analyze` | `analysis-only`（带 engine 时路由会给出候选，需显式选择） | 同上，交付 `analysis` 报告 |
| 适配完成，继续优化 | `optimize` | 引擎对应训练 profile | 同上，交付 `stage-quality` 与 `performance` |
| 扩规模并持续观察训练 | `full`（扩容验收），观测另起 `operate` | 训练 profile | `full` 完成后按需 `module-plan` 跑 `training-observation` |
| 只诊断故障 | `diagnose` | `analysis-only` 或训练 profile | 交付 `diagnosis` 报告；单点取证用子工作流 |
| 审查改动并提 PR | 不建任务 | — | 直接按[代码交付](change-delivery.md)执行 |
| 查询或更新 Wiki | 不建任务 | — | 直接用 `$hcu-trainflow-wiki-search` / `$hcu-trainflow-wiki-skill-update` |

在这张表之外，单次补测（一次 environment-check、一次 iteration-check）用 `capability-run`；一组功能（trace 归因、质量对照、适配三件套）用子工作流。

## 7. 谁写 JSON

每份文档都有作者，区别在于**谁必须读懂它**。格式和现场输入由主控生成；**内容是人的意图和授权，人必须确认**。

| 文档 | 谁写 | 人是否必须看 | 在哪看 |
| --- | --- | --- | --- |
| capability 请求、模块计划、子工作流计划 | 主控 | 否，排障时才看 | `module-plan` 的返回 |
| profile 一次性计划（`{"profile":…}`） | 主控 | 否；站点接线有特殊形状时才手改 `bindings`/`step_inputs` | 同上 |
| TaskSpec 的 `objective` | 主控起草 | **是**：这是用户目标的原文 | `task-show`、BOARD |
| TaskSpec 的 `context` | 主控 | 是：比较范围（引擎、模型、数据、基线）不能由主控自行改写 | `task-show` |
| PLAN.json 的 `acceptance` | 主控起草 | **是**：验收条款就是"什么算做完" | `flow-brief` 的 `acceptance.clauses` |
| `permissions`、`budget` | 主控起草 | **是**：授权与硬顶属于人 | TaskSpec、`flow-brief` 的 `invariants` |
| `autonomy.escalation`（降级下限、追加上限、验收策略） | 主控起草 | **是**：这是预授权信封 | `flow-brief` 的 `invariants`、`flow-degradation` |
| 候选、报告、复核 | 执行者/复核者 | 按契约抽样 | 任务 workspace |

三条理由说明"格式"不该由人写：

1. 现场输入只有执行时才确定（路径、租约、命令卡），提前写只能写成猜的值；
2. 计划是可校验对象，写错会被 `problems` 拒绝，而不是跑出错误结果；
3. 同一份文档可重放、可交给 reviewer 核对，比会话里的一段话更可追溯。

但"内容"有一条真实风险：`acceptance` 由主控起草，就可能写得比用户本意更松，而主控又恰好是被考核的一方。现有防线是：`acceptance_edit` 默认 `forbid`（运行中改不了）、`flow-align` 会把"验收自起始改变"列成 drift、`flow-brief` 原样列出条款供人核对；**开工前读一次 `flow-brief` 的 `acceptance.clauses`** 是这轮唯一不能省的人工动作。目前 `flow-start` 不强制"人已确认"，这是可以再收紧的地方。

入口措辞仍是人和主控之间的接口，JSON 是主控与执行层之间的接口；两者的分界不在"谁敲键盘"，而在"谁对内容负责"。具体到每个模块、每个子工作流、每个阶段要人给哪些输入，见第 8 节。

## 8. 人必须提供什么：按模块、按子工作流

人提供的是**值**，主控把它写成文档。三类输入：

| 标记 | 含义 | 例子 |
| --- | --- | --- |
| **H** | 只有人能定：授权、验收阈值、口径、现场启动方式与路径 | `contract`、`card`、`repository`、`resource`、`ttl` |
| **S** | 现场事实，人可以给文件或给路径由主控读 | `project`、`trace`、`state_dir` |
| **A** | 主控产出或实测：上游结果、实测值、从仓库抽取的快照 | `stdout_artifact`、`observations`、`*_times`、`config-snapshot` |

### 8.1 输入类型总表

| 输入 | 类型与归属 | 说明 |
| --- | --- | --- |
| `contract`（environment / occupancy / quality / training / adaptation） | **H** | 验收条件、阈值、容差、训练配方；主控只能照人的约定填 |
| `full` / `candidate`（proxy-contract） | **H** | 缩模授权边界：允许缩到哪、缺口如何说明 |
| `card`（command-card） | **H** | 实际启动命令、环境变量、工作目录；不得臆造 |
| `resource` / `ttl` | **H** | 预约哪台设备、多久 |
| `repository` / `paths` | **H/S** | 源码位置与纳入快照的路径 |
| `project` / `trace` / `state_dir` | **S** | 现场路径 |
| `manifest` / `policy`（observation-*） | **H** | 观测什么、多久一次、什么算异常 |
| `upstream` / `hcu` / `mapping` | **H** | 适配对照的原始启动记录与映射依据（主控起草、人确认） |
| `owner` | A | 会话/负责人标识，主控填 |
| `operation` | A | 操作 ID，主控生成 |
| `lease` | A | 由 `resource.lease` 产出，内部接线 |
| `observations`（environment / occupancy） | A | 实测值；阈值仍来自 `contract` |
| `stdout_artifact` / `files` | A | 上游执行产物与待封存文件清单 |
| `baseline` / `candidate` / `correctness` / `*_times` / `before` / `after` | A | 实测记录、成对计时、配置快照 |
| `window` / `intervals` | A | 从 trace 判读的窗口与通信区间 |
| `verdict` / `analysis` / `baseline-summary` / `profile-result` | A | 上游模块产物，自动接线 |

### 8.2 24 个模块：人必须给哪些输入

| 模块 | 人必须提供 |
| --- | --- |
| `environment.probe` | `contract`（environment-contract） |
| `resource.admission` | `contract`（occupancy-contract） |
| `resource.lease` | `resource`、`ttl` |
| `execution.command` | `card`（command-card） |
| `execution.stdout-json` | — （`stdout_artifact` 由上游执行产出） |
| `artifact.collect` | — （`files` 由执行目录/命令卡得出） |
| `source.transfer` | `repository`、`paths` |
| `training.summarize` | `contract`（training-contract） |
| `training.summarize-torch` | `contract`（training-contract） |
| `training.observe` | `manifest`、`policy`、`state_dir` |
| `adaptation.launch-parity` | `upstream`、`hcu`（`mapping` 主控起草，人确认） |
| `adaptation.config-diff` | — |
| `adaptation.numeric-equivalence` | `contract`（adaptation-contract） |
| `quality.loss` | `contract`（quality-contract） |
| `quality.iteration` | — |
| `quality.proxy` | `full`、`candidate`（proxy-contract） |
| `quality.qualify` | — （三份输入全部可由上游模块提供） |
| `profiling.trace` | `project`、`trace` |
| `profiling.analyze` | `trace` |
| `profiling.summarize` | — （内部接线） |
| `profiling.communication` | — （`intervals` 从 trace 提取） |
| `optimization.change` | — （`before`/`after` 从仓库与运行配置抽取） |
| `optimization.benchmark` | — （成对计时由实测得到） |
| `optimization.netgain` | — （两次测量由实测得到） |

### 8.3 16 个子工作流：人必须给哪些输入

| 子工作流 | 人必须提供 | 其余输入 |
| --- | --- | --- |
| `environment-readiness` | `contract`、`resource`、`ttl` | `observations` 实测 |
| `environment-collect` | `card`、`contract` | `operation`、`lease`、`stdout_artifact` 内部或主控 |
| `source-handoff` | `repository`、`paths` | `files` 主控 |
| `baseline-megatron` | `card`、`contract`（training） | `operation`、`lease`、`files` |
| `baseline-torch` | 同上 | 同上 |
| `quality-accept` | `contract`（quality） | 两组 loss、成对计时由实测得到 |
| `baseline-qualification` | — | 三份上游结果 |
| `adaptation-proxy` | `full`、`candidate` | — |
| `adaptation` | `upstream`、`hcu`、`contract`（adaptation） | `mapping` 主控起草；两组快照从仓库抽取 |
| `training-observation` | `manifest`、`policy`、`state_dir` | — |
| `hipprof-summary` | `project`、`trace` | — |
| `trace-attribution` | `project`、`trace` | `window`、`intervals` 从 trace 判读 |
| `optimization-netgain` | — | 快照与两次测量均由主控产出 |
| `optimization-benchmark` | — | 同上 |
| `profiling-tracelens` | `project`、`trace` | `window` 由主控 |
| `baseline-pipeline` | `contract`、`card`、`project`、`trace` | 其余现场事实与实测 |

### 8.4 4 个 profile：分阶段的人输入

profile 的静态接口很大（`llm-megatron` 有 31 项），但**按阶段切片后每阶段只有 2–5 项要人给**：

| 阶段 | 人必须提供（llm / torch-llm / vision 相同） | analysis-only |
| --- | --- | --- |
| `prepared` | 设备占用与环境契约、适配契约；`card`；`resource`、`ttl`；`repository`、`paths`；`upstream`、`hcu` | — |
| `environment_checked` | training 契约；`card` | — |
| `baseline_validated` | training 契约；`card`；`manifest`、`policy`、`state_dir`；两档 profile 另有 proxy 契约 | — |
| `profiling` | `project`、`trace`；`card` | `project`、`trace`；`card` |
| `optimizing` | quality 契约（容差与口径）；`project`、`trace` | — |
| `scale_ready` | 设备占用与环境契约；`card` | — |
| `training` | `resource`、`ttl`；`card`；`manifest`、`policy`、`state_dir` | — |

`vision` 在 `baseline_validated` 少 proxy 契约（该 profile 不做代理校验）；其余同表。

### 8.5 结论：人实际给的只有六件事

1. **目标与验收条款**（`objective`、`acceptance`）——主控起草，人确认；
2. **五类 `contract`**（环境/占用/质量/训练/适配）——阈值、容差、配方；
3. **启动方式**（`card`）与**源码位置**（`repository`、`paths`）；
4. **资源预约**（`resource`、`ttl`）与设备占用契约；
5. **现场路径**（`project`、`trace`、`state_dir`）；
6. **观测策略**（`manifest`、`policy`）与**缩模授权**（`full`/`candidate`）。

其余输入由主控实测、抽取或由上游模块接线；人不需要写整份 JSON，只需要给这些值和一句确认。

## 9. 可复用 intake

一个站点/模型要跑多个任务时，把"不变的事实"和"每次变的目标"分开写进一份文档（模板见 [examples/intake.json](../examples/intake.json)）：

```json
{"schema_version": 1, "revision": "2026-11-19",
 "scope": {"site": "site-a", "engine": "megatron", "model_family": "llm", "model": "model-8b"},
 "site": {"ssh_target": "…", "container": "…", "cwd": "…",
          "commands": {"train": {"argv": ["bash", "train.sh"], "timeout_seconds": 3600, "basis": "…"}},
          "devices": [], "occupancy": {}, "leases": []},
 "source": {}, "paths": {}, "contracts": {}, "observation": {},
 "authority": {"permissions": [], "budget": {}, "autonomy": {}},
 "tasks": [{"task_id": "full-run", "mode": "full", "objective": "…", "acceptance": {},
            "profile": {"id": "llm-megatron", "reason": "…"},
            "use": {"contracts": ["environment", "quality"], "commands": ["train"]}}]}
```

| 块 | 复用粒度 | 谁维护 |
| --- | --- | --- |
| `site`（ssh/容器/命令卡/设备/占用/租约模板） | 站点级 | 站点负责人 |
| `contracts`（environment/quality/training/adaptation/proxy）、`observation` | 模型级 | 阶段负责人 |
| `source`、`paths` | 任务级（跟快照走） | 主控 |
| `authority`（`permissions`、`budget` 信封、`autonomy`） | 授权信封，**任务只能收窄** | 人 |
| `tasks[]` | 每个任务一条 | 主控起草、人确认 |

两个命令：

```bash
python scripts/check_intake.py /private/task-a/intake.json
python scripts/build_autonomous_task.py --intake /private/task-a/intake.json --output /private/task-a/bundles
```

- `check_intake` 只读检查：结构、`revision` 格式、每个任务是否被真实运行时接受（`validate_spec` + `validate_plan`）、**任务预算是否超过授权信封**、`use.contracts`/`use.commands` 是否存在、租约是否落在已准入设备上、声明的 profile 是否与 `scope` 一致。退出码 `0` 通过、`2` 需处理、`1` 文档本身畸形。
- 生成器按任务展开到 `bundles/<task_id>/`（单个任务或 `--task <id>` 时直接写进 `--output`）：`task.json`、`plan.json`、`admission.json`、`cards/*.json`，另加 `contracts/*.json`、`leases.json`（含 owner/ttl，用于 `lease-acquire`）与 `inputs.json`（`observation`/`paths`/`source`）。

边界要讲清楚：

1. **复用不等于长期授权**：`authority.budget` 是信封，`tasks[].budget` 只能更小；租约是预约，每次运行前用 `lease-acquire` 重新取得。
2. **`revision` 目前只是标记**：改了站点或契约不会让已建任务失效，需要按 `task-context` + `flow-replan` 显式重置。
3. **生成的 bundle 仍需人确认**：`task.json` 的 `objective`/`context`/`profile` 与 `plan.json` 的 `acceptance` 就是第 7 节说的"人必须确认的那几项"，生成成功不代表验收成立。
4. **人只需要给值**：每个 `tasks[]` 只写目标、验收、预算与所用契约/命令，其余输入的主控/站点归属见第 8 节。

## 10. 已知缺口

- 非 `full` 模式下 `flow-next` 的 `invariants.gates` 仍按全量门禁输出，而 `required_reports` 只要求该模式的交付报告：读 `invariants` 时以 `required_reports` 为准。
- `analyze`/`diagnose` 且声明了 engine 时，路由会同时命中训练 profile 与 `analysis-only`，需要显式选择并记录理由。
- `environment` 与 `operate` 目前没有专属 profile：前者在不声明 profile 时按全量门禁运行，后者落到引擎对应训练 profile。
