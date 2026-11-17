# 模块化能力与可组合 Pipeline

HCU-TrainFlow 使用“能力模块 + Pipeline 编排”。能力定义独立功能，Pipeline 定义执行依赖；完整训练工作流通过当前阶段的 Pipeline 接入既有 Flow。模块目录、子工作流 profile 与门禁派生见[模块化拆分与子工作流](workflow-modules.md)：那里把 21 个模块、15 个功能子工作流、派生门禁和 `module-*` 入口作为能力之上的声明层。

## 职责与入口

- `kernel` 定义 CapabilityContext、Request、Result、PipelineStep 和 PipelinePlan；Runner 负责排序、数据传递及失败传播。
- `capabilities` 复用环境、适配、Profile、质量、扩容、观察、执行及交付实现。
- `services.RuntimeService` 为 CLI 与 Python 统一运行身份、持久化、恢复、证据校验和报告登记。
- `adapters` 接入既有执行机制；Flow 继续拥有任务审核和阶段转换。
- Skill 提供任务理解、资料阅读和决策方法，不替代能力实现。

旧 `core`、`flow`、`execution` 及 CLI 契约继续可用。新 CLI 仅解析参数、读取请求及展示结果：

```bash
hcu-trainflow capability-list
hcu-trainflow capability-run profiling.tracelens examples/scenario-tracelens.json
hcu-trainflow pipeline-plan pipeline.json
hcu-trainflow pipeline-run pipeline.json
hcu-trainflow pipeline-run pipeline.json --resume RUN_ID
hcu-trainflow pipeline-next TASK_ID
hcu-trainflow pipeline-default TASK_ID
hcu-trainflow module-catalog
hcu-trainflow subworkflow-list
hcu-trainflow profile-list
hcu-trainflow profile-resolve CONTEXT_JSON
hcu-trainflow module-plan MODULES_JSON
hcu-trainflow module-run MODULES_JSON --task TASK_ID
```

`module-*` 与 `profile-*` 是目录/声明层：`module-plan` 静态校验接线并给出派生门禁，`module-run` 仍走同一个 `RuntimeService`。详见[模块化拆分与子工作流](workflow-modules.md)。

`capability-list` 返回能力名称及支持的 actions。独立请求顶层包含字符串 `context`、`action`、`inputs`；绑定已有任务时指定 `task_id`，从 Store 取得真实上下文。Pipeline 文件包含 `pipeline`、对象 `context` 和 `inputs`；独立 Pipeline 的 context 例如 `{"context":"frozen-context","task_id":"caller-label"}`。

新入口始终在所选 workspace 保存 run、step 和不可变 artifact。独立运行不创建训练 Task，也不登记 Task 报告。已有合成 [quality-pipeline.json](../examples/quality-pipeline.json) 中的证据占位符必须替换为同一 Store 已保留的原件 ID；用 `artifact-add` 或 `Store.put` 导入，不把占位符视作已验证证据。

## 三个独立场景

| 能力与 action | 输入 | 动作及输出 |
| --- | --- | --- |
| `environment.check` / `check` | `contract`、`observations` | 校验条件、覆盖和实测，返回逐项结论及 observations |
| `environment.check` / `collect` | `contract`；`execution` 含 operation、card、lease | 经 Task 执行权限、Lease、Operation 运行检查，解析 stdout JSON measurements，保留原件 |
| `profiling.tracelens` / `analyze` | `project`；`trace` 或完整 rank 的 trace_pattern 与 world_size | 实际运行固定 TraceLens，保留输入、表格、日志、原报告及覆盖缺口 |
| `quality.accept` / `assess` | `contract`、`baseline`、`candidate`、`correctness`、`baseline_times`、`candidate_times` | 分别判定冻结窗口数值与至少三组无 profiler 计时，返回综合结论及 stage_eligible |
| `artifact.collect` / `retain` | `files`：名称 → 绝对 path、sha256 | 核验生产者回执，保存输出原件，返回名称 → artifact |
| `training.summarize` / `parse` | `contract`；`log_artifact` 或真实 `execution` | 解析完整 Megatron 日志，核验有效配置、从零初始化、连续 iteration、数值、验证集与计时分组 |
| `quality.accept` / `qualify` | `training`、`environment`、`analysis`；可选 `analysis_scope` | 只判定短基线与指定分析范围是否齐备，不制造 candidate、不授予优化或完整阶段通过 |

TraceLens 可选输入包括 rank、window、gpu_arch_json、timeout。`profiling.tracelens` 支持 `mode=hipprof`，输入为 `trace` 路径或 `trace_artifact`（`trace_format` 为 json、pftrace 或 pftrace.gz；后两者另需 traceconv_path）。所有模式都保留原始输入和工具输出。`profiling.analyze/analyze` 保持结构化事件分析语义；`summarize` 消费同一上下文的 hipprof 输出 `profile` 与其 `normalized_artifact`，用原始精确纳秒字段计算 kernel 摘要和设备 busy union，明确 `scope=hipprof-summary`、`model_diagnosis=incomplete`。不把 kernel 时间之和当作训练墙钟占比。质量容差、性能退化与稳定性要求由显式契约决定；缺证据为 `incomplete`，已测得不达标为 `fail`。通过局部比较不自动成为生产默认，也不替代阶段 loss 验收。

模板见 [环境请求](../examples/scenario-environment.json)、[Trace 请求](../examples/scenario-tracelens.json) 和 [质量请求](../examples/scenario-quality.json)。环境与质量模板的证据 ID 须替换。主动采集只接受真实命令 stdout 的观测，不用调用者额外提供的 observations 冒充执行。

从项目根运行完整软件示例：

```bash
python examples/run_modular_scenarios.py --project . --workspace .work/modular-demo
```

示例实际调用固定 TraceLens，使用合成 Trace、合成质量/计时与控制端环境记录，验证独立运行和组合；不证明 HCU 训练通过。实际设备链路使用 [HIP 验证脚本](../scripts/validate_hip_runtime.py) 和[冻结契约](../examples/hip-runtime/contract.json)：默认仅编译及只读发现；执行需显式占用契约、原始证据、设备 Lease 和即时检查。HIP 结果只提供局部正确性/计时，不能生成训练 loss。

## Python 公共服务

```python
from hcu_trainflow.core import Store
from hcu_trainflow.kernel import CapabilityContext, CapabilityRequest
from hcu_trainflow.services import RuntimeService

store = Store(".work/my-task")
runtime = RuntimeService(store)
context = CapabilityContext("analysis", "frozen-context", store.root)
request = CapabilityRequest("profiling.tracelens", "analyze", {
    "project": ".", "trace": "examples/tracelens-trace.json"
})
result = runtime.run_capability(request, context)
```

`run_pipeline(plan, context, inputs, resume_run_id=None)` 接受 PipelinePlan，返回各步骤结果及 `run_id`、`artifacts`、`reports`、`resumed`。`run_capability(request, context, resume_run_id=None)` 返回能力结果及相同持久化字段。绑定 Task 使用 `CapabilityContext.from_task(store.task(task_id), store.root)`，避免自行复制旧 context/revision。`Store.pipeline_state(run_id)` 查询保留状态。

## 组合与报告

步骤通过 `depends_on` 建立 DAG，原有 `inputs.dependencies` 保留依赖的完整结果。可选 `bindings` 把直接依赖的 outputs 绑定到当前输入字段：

```json
{"id":"accept","capability":"quality.accept","action":"assess",
 "depends_on":["analysis"],
 "bindings":{"analysis":{"step":"analysis","path":[]}}}
```

`path` 是输出对象键数组，空数组表示整个 outputs；绑定覆盖同名初始/步骤输入，不执行表达式，缺失路径使该步失败。大对象由 Store artifact 连接。quality.accept 的 assess 动作将 analysis/environment 作为来源记录；qualify 动作要求这些来源实际通过并匹配分析范围。

`execution.command` 设置 `config.stdout_json=true` 后，仅在命令完成时把 stdout JSON 暴露为 `outputs.document`，后续可绑定 correctness/times；解析失败记录 incomplete，不自动重跑命令。命名的 baseline/candidate/correctness 记录会附上真实执行证据，不补造 context、executed 或 profiler 状态。

带 `--task TASK_ID` 的完整任务或已有 Flow 的任务检查当前决策，只在 work/repair 时执行。没有 Flow 的独立非 full Task 可运行，仍受执行权限、Lease 和 Operation 检查。`config.report_kind` 请求任务报告；运行末尾复核输入和上下文后登记，事务检查 revision。报告须满足原始证据、实际执行和阶段契约。未绑定 Task 的运行不发布 Task 报告；缺证据结果保留为 incomplete。

`pipeline-default TASK_ID` 返回当前状态的单阶段 Pipeline；`pipeline-next` 只投影既有决策。Pipeline 不自动推进阶段，完整任务仍通过 flow-submit、独立 review 和 flow-advance。

## 从零短基线的完整串联

公共 `services.baseline_pipeline(...)` 生成以下单次运行，仍可用 capability-run 分别调用每个模块：

```text
environment.check/collect
  → execution.command（无 profiler 训练）
  → training.summarize/parse
  → execution.command（独立短 Trace 采集及传输）
  → artifact.collect/retain
  → profiling.tracelens（hipprof 转换）
  → profiling.analyze/summarize
  → quality.accept/qualify
```

现场适配器只负责启动、传输和生成文件回执；解析、分析与验收分别由公共模块完成。准备一个私有 site.json，字段如下，再用 [生成示例](../examples/build_baseline_pipeline.py) 写出可审阅的 Pipeline。生成操作不会执行训练。

| site 字段 | 内容 |
| --- | --- |
| `environment` | `contract` 与 `execution`；后者包含 operation、card、lease，stdout 为 measurements JSON |
| `training` | operation、card、lease；完成后的 stdout 必须是完整 Megatron 日志 |
| `training_contract` | 当前 context；expected_steps、steady_start、world_size、global_batch_size、seq_length、timing_groups、min_samples_per_group；可选 effective_arguments、required_evaluations、max_group_relative_spread、log_timezone |
| `profiling` | operation、card、lease；独立采集完成并传输后 stdout 输出 `{"files":{"trace":{"path":"/private/task/trace.json","sha256":"实际哈希"}}}`，可附加日志、DB 和 manifest |
| `project` | 当前绑定 TrainFlow checkout，供 TraceLens 锁定依赖定位 |

```bash
python examples/build_baseline_pipeline.py /private/task/site.json --output /private/task/pipeline.json
hcu-trainflow --workspace /private/task/store pipeline-plan /private/task/pipeline.json
hcu-trainflow --workspace /private/task/store pipeline-run /private/task/pipeline.json --task TASK_ID
hcu-trainflow --workspace /private/task/store pipeline-run /private/task/pipeline.json --task TASK_ID --resume RUN_ID
```

生成器也可直接从 Python 调用：`baseline_pipeline(environment=..., training=..., training_contract=..., profiling=..., project=...)` 返回标准 PipelinePlan，交给同一个 RuntimeService。Task、lease 和现场资源授权先按实际任务准备；完整 Flow 的阶段门禁不会被此模板绕过。

训练 summary 检查有效参数 dump 中的 load=None、load_weights=False、profile=False；从 1 开始的完整唯一迭代、finite loss、skipped/nan、预定终点验证集与测试集 loss，以及显式计时组。吞吐使用总 token 数除以所选 iteration 墙钟时间总和，启动/编译步单列。连续窗口分组不等同于多次独立启动；短基线不证明长稳或 checkpoint 恢复。缺项保留 incomplete，不能自行补造数值或从历史日志填充。

`qualify` 成功时返回 `baseline_qualified=true`，同时保持 `stage_eligible=false`、`optimization_validated=false`。默认只要求 hipprof-summary，完整模型归因仍 incomplete。Pipeline 登记 environment、profile-summary、baseline-qualification 三种报告，后两者不能冒充完整 Flow 的 analysis 或 stage-quality 报告。

生成的输出路径通过命令 stdout 与 bindings 传递，原件经生产者 SHA-256 回执封存。不要把运行后才会出现的文件路径当作初始文件输入，否则其创建会改变运行身份。初始启动脚本、配置及已有输入文件仍应显式列入命令卡/输入，以便字节变化触发指纹失效。

## 恢复和失败

运行指纹覆盖计划、输入、文件字节、实现及固定工具身份、context/revision。计划与初始输入另存为 `request_artifact`，可独立追溯。相同请求复用成功步骤；`--resume` 要求指定运行仍匹配。输入或文件变化创建新 run；旧无输入指纹记录只能查询。缓存结果、原始证据和报告的对象均重新校验，损坏或缺失不能复用为通过。

失败、阻塞与中断步骤均持久化。依赖重跑时后继缓存失效；占用、主动采集、观察及执行重新进入原准入。未知执行先 Reconcile 原 Operation。运行锁只排除并发控制器，不代替设备 Lease。

Operation 的完成/失败结果按同一 ID 与命令身份重放。Pipeline resume 重新调用执行模块时，不会因此重新派发已完成训练；需要新的现场测量或修复后重试已失败命令时，使用经过核销的新 operation。现场适配器另保留远端进程身份和退出回执，防止控制端中断后误启动第二份训练。故障演练使用独立 Task/Store，避免覆盖正式任务的当前报告。

运行中 context/revision 或文件变化记录 conflicted 并停止发布新报告；取得当前上下文后重新运行。CLI 与 Python 共享这些规则；内存 Runner 用于组合算法，不负责证明外部证据有效。
