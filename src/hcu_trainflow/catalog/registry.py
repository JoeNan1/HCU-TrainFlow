"""The module catalog: 20 modules, aliases, presets and declarative presets.

Every entry is data.  Aliases may only point at a catalog entry, and a preset
may only reference catalog entries, so there is a single place where behaviour
is named.  ``implementation`` names the existing capability that performs the
work; ``None`` marks a declared-but-unimplemented module (the plan reports it,
``module-run`` refuses it) instead of inventing a second engine.
"""
from __future__ import annotations

from typing import Any, Mapping

from .contracts import Module, ModuleContractError, Subworkflow

# --- 20 modules, 5 families -------------------------------------------------

MODULES: tuple[Module, ...] = (
    # 环境与资源
    Module(
        id="environment.probe", summary="契约 vs 观测逐项判定",
        actions=("check", "collect"),
        requires={"contract": "environment-contract", "observations": "observation[]"},
        provides={"status": "verdict", "observations": "observation[]", "evidence": "artifact[]"},
        report="environment", stage=("prepared", "scale_ready"), role="check",
        # ``collect`` runs a real command card; volatility is declared for the
        # stricter action so a resumed run never reuses a stale environment.
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=True, route="docs/environment-discovery.md",
        implementation=("environment.check", "check"),
    ),
    Module(
        id="resource.admission", summary="占用/空闲准入判定",
        actions=("check",),
        requires={"contract": "occupancy-contract", "observations": "occupancy-observation[]"},
        provides={"status": "verdict", "evidence": "artifact[]"},
        stage=("prepared", "scale_ready"), role="check",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ("hardware",)},
        volatile=True, route="docs/practices/capacity-and-parallel-experiments.md",
        implementation=("environment.occupancy", "check"),
    ),
    Module(
        id="resource.lease", summary="lease 申请/续期/释放",
        actions=("acquire", "renew", "release"),
        requires={"resource": "resource-id", "owner": "string", "ttl": "seconds"},
        provides={"lease": "lease-receipt"},
        stage=("prepared", "training"), role="infra",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=True, route="docs/workspace-boundaries.md",
        implementation=("resource.lease", "acquire"),
    ),
    # 执行与产物
    Module(
        id="execution.command", summary="执行命令卡并落 stdout/stderr 原件",
        actions=("plan", "run"),
        requires={"card": "command-card", "operation": "operation-id", "lease": "lease-receipt"},
        # ``*`` means "my whole result is this type": the execution result is
        # what a log summariser consumes, so it can be auto-bound with path [].
        provides={"status": "verdict", "evidence": "artifact[]", "document": "json",
                  "*": "capability-result"},
        stage=("prepared", "environment_checked", "baseline_validated", "profiling",
               "optimizing", "scale_ready", "training"),
        role="execute",
        tags={"engine": ("any",), "model_family": ("any",),
              "needs": ("hardware", "lease", "task-bound")},
        volatile=True, route="docs/contracts.md",
        implementation=("execution.command", "run"),
    ),
    Module(
        id="execution.stdout-json", summary="把保留的 stdout 解释成结构化测量记录",
        actions=("parse",),
        requires={"stdout_artifact": "artifact-id"},
        provides={"document": "json"},
        stage=("prepared", "environment_checked", "profiling"), role="collect",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ("task-bound",)},
        volatile=True, route="docs/modular-architecture.md",
        implementation=("execution.stdout-json", "parse"),
    ),
    Module(
        id="artifact.collect", summary="按生产者 SHA-256 回执封存输出",
        actions=("retain",),
        requires={"files": "file-receipts"},
        provides={"files": "artifact-map", "evidence": "artifact[]"},
        stage=("environment_checked", "baseline_validated", "profiling", "optimizing"),
        role="collect",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ("task-bound",)},
        volatile=True, route="docs/modular-architecture.md",
        implementation=("artifact.collect", "retain"),
    ),
    Module(
        id="source.transfer", summary="源码快照/物化/打包/接收",
        actions=("snapshot", "materialize", "bundle"),
        requires={"repository": "path", "paths": "path[]"},
        provides={"snapshot": "artifact-map"},
        stage=("prepared",), role="collect",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=True, route="docs/source-transfer.md",
        implementation=("source.transfer", "snapshot"),
    ),
    # 训练与质量
    Module(
        id="training.summarize", summary="Megatron 日志 → 短基线摘要",
        actions=("parse",),
        requires={"contract": "training-contract",
                  "execution": "capability-result|artifact-id"},
        provides={"training": "baseline-summary"},
        report="baseline", stage=("environment_checked", "baseline_validated"), role="judge",
        tags={"engine": ("megatron",), "model_family": ("llm",), "needs": ("task-bound",)},
        volatile=False, route="docs/training-state-validation.md",
        implementation=("training.summarize", "parse"),
    ),
    Module(
        id="adaptation.launch-parity", summary="上游启动要素 → HCU 启动要素的映射核对",
        actions=("compare",),
        requires={"upstream": "launch-record", "hcu": "launch-record", "mapping": "mapping[]"},
        provides={"parity": "parity-verdict"},
        report="adaptation-parity", stage=("prepared",), role="check",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/practices/engine-delivery-tracks.md",
        implementation=("adaptation.launch-parity", "compare"),
    ),
    Module(
        id="adaptation.config-diff", summary="适配前后的有效配置差异与依据",
        actions=("compare",),
        requires={"baseline": "config-snapshot", "adapted": "config-snapshot"},
        provides={"diff": "change-record"},
        report="adaptation-diff", stage=("prepared",), role="check",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/practices/execution-baseline.md",
        implementation=("adaptation.config-diff", "compare"),
    ),
    Module(
        id="adaptation.numeric-equivalence", summary="组件级数值对照（局部，不含阶段结论）",
        actions=("compare",),
        requires={"contract": "adaptation-contract", "baseline": "component-record",
                  "candidate": "component-record"},
        provides={"numerics": "numeric-verdict"},
        report="adaptation-numerics", stage=("prepared",), role="judge",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/practices/model-accuracy-diagnosis.md",
        implementation=("adaptation.numeric-equivalence", "compare"),
    ),
    Module(
        id="training.summarize-torch", summary="通用 torch 日志 → 短基线摘要（声明格式）",
        actions=("parse",),
        requires={"contract": "training-contract",
                  "execution": "capability-result|artifact-id"},
        provides={"training": "baseline-summary"},
        report="baseline", stage=("environment_checked", "baseline_validated"), role="judge",
        tags={"engine": ("torch",), "model_family": ("any",), "needs": ("task-bound",)},
        volatile=False, route="docs/training-state-validation.md",
        implementation=("training.summarize-torch", "parse"),
    ),
    Module(
        id="training.observe", summary="训练过程观测（成员/停滞/心跳）",
        actions=("collect",),
        requires={"manifest": "observation-manifest", "policy": "observation-policy",
                  "state_dir": "path"},
        provides={"observation": "observation-record"},
        stage=("baseline_validated", "training"), role="collect",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ("hardware", "task-bound")},
        volatile=True, route="docs/training-observation.md",
        implementation=("observation.collect", "collect"),
    ),
    Module(
        id="quality.loss", summary="数值对照",
        actions=("compare",),
        requires={"contract": "quality-contract", "baseline": "loss-record",
                  "candidate": "loss-record"},
        provides={"quality": "quality-verdict"},
        stage=("optimizing",), role="judge",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/practices/model-accuracy-diagnosis.md",
        implementation=("quality.loss", "compare"),
    ),
    Module(
        id="quality.iteration", summary="单次迭代 kept/rejected（含 MAD 稳定性）",
        actions=("assess",),
        requires={"correctness": "timing-record", "baseline_times": "seconds[]",
                  "candidate_times": "seconds[]"},
        provides={"performance": "iteration-verdict"},
        stage=("optimizing",), role="judge",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/practices/performance-methods.md",
        implementation=("quality.iteration", "assess"),
    ),
    Module(
        id="quality.proxy", summary="代理配置契约校验",
        actions=("check",),
        requires={"full": "proxy-contract", "candidate": "proxy-contract"},
        provides={"status": "verdict"},
        stage=("baseline_validated",), role="check",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/proxy-contract.md",
        implementation=("quality.proxy", "check"),
    ),
    Module(
        id="quality.qualify", summary="短基线资格（不授予阶段通过）",
        actions=("qualify",),
        requires={"training": "baseline-summary", "environment": "verdict",
                  "analysis": "analysis"},
        provides={"qualification": "qualification-verdict"},
        report="baseline-qualification", stage=("baseline_validated",), role="judge",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/quickstart.md",
        implementation=("quality.accept", "qualify"),
    ),
    # 性能分析
    Module(
        id="profiling.trace", summary="trace 采集/转换/TraceLens 运行＋表格",
        actions=("analyze", "plan"),
        requires={"project": "path", "trace": "path"},
        provides={"profile": "profile-result", "normalized_artifact": "artifact-id",
                  "evidence": "artifact[]"},
        stage=("profiling", "optimizing"), role="analyze",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ("hardware",)},
        volatile=True, route="docs/profiling.md",
        implementation=("profiling.tracelens", "analyze"),
    ),
    Module(
        id="profiling.analyze", summary="热点/上限/归因",
        actions=("analyze",),
        requires={"trace": "path", "window": "window"},
        provides={"analysis": "analysis"},
        report="analysis", stage=("profiling",), role="analyze",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/tracelens-analysis.md",
        implementation=("profiling.analyze", "analyze"),
    ),
    Module(
        id="profiling.summarize", summary="hipprof kernel 摘要＋设备 busy union",
        actions=("summarize",),
        requires={"profile": "profile-result", "normalized_artifact": "artifact-id"},
        provides={"analysis": "analysis"},
        report="profile-summary", stage=("profiling",), role="analyze",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/tracelens-analysis.md",
        implementation=("profiling.analyze", "summarize"),
    ),
    Module(
        id="profiling.communication", summary="通信/overlap 记账",
        actions=("account",),
        requires={"intervals": "interval-document"},
        provides={"communication": "communication-accounting"},
        stage=("profiling", "optimizing"), role="analyze",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/practices/communication-recipe.md",
        implementation=("profiling.communication", "account"),
    ),
    # 优化
    Module(
        id="optimization.change", summary="记录一次改动的语义（diff/hash/依据/回退）",
        actions=("record",),
        requires={"before": "config-snapshot", "after": "config-snapshot"},
        provides={"change": "change-record"},
        report="optimization-change", stage=("optimizing",), role="optimize",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/practices/engine-delivery-tracks.md",
        implementation=("optimization.change", "record"),
    ),
    Module(
        id="optimization.benchmark", summary="同 shape/dtype 隔离对照＋上限效率",
        actions=("compare",),
        requires={"baseline_times": "seconds[]", "candidate_times": "seconds[]"},
        provides={"benchmark": "benchmark-verdict"},
        stage=("optimizing",), role="optimize",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ("hardware",)},
        volatile=True, route="docs/practices/performance-methods.md",
        implementation=("optimization.benchmark", "compare"),
    ),
    Module(
        id="optimization.netgain", summary="整步净收益与噪声判定",
        actions=("assess",),
        requires={"baseline": "measurement", "candidate": "measurement"},
        provides={"performance": "performance-report"},
        report="performance", stage=("optimizing",), role="optimize",
        tags={"engine": ("any",), "model_family": ("any",), "needs": ()},
        volatile=False, route="docs/optimization-reference-map.md",
        implementation=("optimization.netgain", "assess"),
    ),
)

# --- aliases: only point inside the catalog --------------------------------
_BY_ID: dict[str, Module] = {module.id: module for module in MODULES}

ALIASES: Mapping[str, str] = {
    "optimization.iteration": "quality.iteration",
    "adaptation.proxy": "quality.proxy",
    "scale.admission": "resource.admission",
    # Compatibility names of the legacy capability surface.
    "environment.check": "environment.probe",
    "environment.occupancy": "resource.admission",
    "observation.collect": "training.observe",
}


SUBWORKFLOWS: dict[str, Subworkflow] = {}

# The functional layer started life as ``presets``; keep the old, dotted
# spellings resolvable so existing documents keep working.
SUBWORKFLOW_ALIASES: Mapping[str, str] = {
    "quality.accept/assess": "quality-accept",
    "profiling.tracelens": "profiling-tracelens",
    "environment.collect": "environment-collect",
}


def _subworkflow(name: str, summary: str, modules: tuple[str, ...], **kwargs) -> None:
    SUBWORKFLOWS[name] = Subworkflow(name, summary, modules, **kwargs)


# --- functional subworkflows: a job, not a process --------------------------
# None of these carry stages or gates; they only group modules that belong to
# one capability-level function.  A process profile composes them.

_subworkflow(
    "environment-readiness", "环境就绪：准入、租约与逐项判定",
    ("resource.admission", "resource.lease", "environment.probe"),
    notes="先占准入与租约，再按契约判定观测；观测不新鲜则整体不通过",
)

_subworkflow(
    "environment-collect", "环境主动采集：跑命令、解析 stdout、判定",
    ("execution.command", "execution.stdout-json", "environment.probe"),
    bundled=("environment.probe",),
    notes="environment.probe 的 collect 动作在单次能力调用内完成命令、解析与判定（旧 preset 名 environment.collect）",
)

_subworkflow(
    "source-handoff", "源码快照与原件封存",
    ("source.transfer", "artifact.collect"),
    notes="只保留精确字节与生产者回执，不判断源码能否运行",
)

_subworkflow(
    "baseline-megatron", "Megatron 短基线：执行、日志摘要、原件封存",
    ("execution.command", "training.summarize", "artifact.collect"),
    notes="日志按 Megatron 原生格式解析；与 baseline-torch 由引擎标签区分，不能同时使用",
)

_subworkflow(
    "baseline-torch", "纯 torch 短基线：执行、声明格式日志摘要、原件封存",
    ("execution.command", "training.summarize-torch", "artifact.collect"),
    notes="日志格式由任务契约声明；缺 meta 记录时初态与 profiler 状态记为未证明",
)

_subworkflow(
    "quality-accept", "数值与性能对照",
    ("quality.loss", "quality.iteration"),
    notes="两项分别判定，任一失败即整体不通过（旧 preset 名 quality.accept/assess）",
)

_subworkflow(
    "baseline-qualification", "短基线资格",
    ("quality.qualify",),
    notes="只判定短基线与指定分析范围是否齐备，不授予阶段通过",
)

_subworkflow(
    "adaptation-proxy", "缩层/缩维代理配置校验",
    ("quality.proxy",),
    notes="记录代理配置与未覆盖范围；不作为完整模型显存、收敛或扩 DP 的证明",
)

_subworkflow(
    "adaptation", "模型适配：启动映射、配置差异与组件级数值",
    ("adaptation.launch-parity", "adaptation.config-diff",
     "adaptation.numeric-equivalence"),
    notes="三份证据都不进阶段门禁：映射完整不代表能跑通，diff 有依据不代表改对了，局部数值不证明阶段等价",
)

_subworkflow(
    "training-observation", "训练过程观测",
    ("training.observe",),
    notes="成员、停滞与心跳；空观测不证明健康",
)

_subworkflow(
    "hipprof-summary", "trace 采集与 hipprof 摘要",
    ("profiling.trace", "profiling.summarize"),
    notes="采集与封存在 profiling.trace 内完成；摘要只给 kernel 与 busy union",
)

_subworkflow(
    "trace-attribution", "trace 采集、热点归因与通信记账",
    ("profiling.trace", "profiling.analyze", "profiling.communication"),
    notes="归因仍需 Agent 判读；通信记账只做声明区间并集",
)

_subworkflow(
    "optimization-netgain", "改动记录与整步净收益",
    ("optimization.change", "optimization.netgain"),
    notes="记录改了什么、净收益是否高于噪声；不产出该不该做的结论",
)

_subworkflow(
    "optimization-benchmark", "改动记录与隔离基准",
    ("optimization.change", "optimization.benchmark"),
    notes="同 shape/dtype 隔离对照；明确不是整步净收益",
)

_subworkflow(
    "profiling-tracelens", "TraceLens 全链（模板）",
    ("profiling.trace", "profiling.analyze", "profiling.summarize"),
    kind="template",
    notes="采集与原件封存在 profiling.trace 内部完成；分析侧按需选 analyze 或 summarize，不同时执行",
    template={"name": "tracelens-analysis", "steps": [
        {"id": "tracelens", "module": "profiling.trace", "action": "analyze",
         "inputs": "$tracelens"},
        {"id": "analysis", "module": "profiling.summarize", "action": "summarize",
         "depends_on": ["tracelens"],
         "bindings": {"profile": {"step": "tracelens", "path": []},
                      "normalized_artifact": {"step": "tracelens",
                                              "path": ["normalized_artifact"]}}},
    ]},
)

_subworkflow(
    "baseline-pipeline", "从零短基线闭环（模板）",
    ("environment.probe", "execution.command", "training.summarize", "artifact.collect",
     "execution.stdout-json", "profiling.trace", "profiling.summarize", "quality.qualify"),
    kind="template",
    notes="从零短基线的单次运行；门禁与 Flow 阶段推进不由此模板绕过",
    template={
        "name": "fresh-baseline-closed-loop",
        "steps": [
            {"id": "environment", "module": "environment.probe", "action": "collect",
             "inputs": "$environment", "config": {"report_kind": "environment"}},
            {"id": "training", "module": "execution.command", "depends_on": ["environment"],
             "inputs": "$training"},
            {"id": "training-summary", "module": "training.summarize", "depends_on": ["training"],
             "inputs": {"contract": "$training_contract"},
             "bindings": {"execution": {"step": "training", "path": []}}},
            {"id": "profile-capture", "module": "execution.command",
             "depends_on": ["training-summary"], "inputs": "$profiling",
             "config": {"stdout_json": True}},
            {"id": "profile-files", "module": "artifact.collect", "depends_on": ["profile-capture"],
             "bindings": {"files": {"step": "profile-capture", "path": ["document", "files"]}}},
            {"id": "tracelens", "module": "profiling.trace", "depends_on": ["profile-files"],
             "inputs": {"project": "$project", "mode": "hipprof", "trace_format": "json"},
             "bindings": {"trace_artifact": {"step": "profile-files",
                                            "path": ["files", "trace", "artifact"]}}},
            {"id": "analysis", "module": "profiling.summarize", "depends_on": ["tracelens"],
             "config": {"report_kind": "profile-summary"},
             "bindings": {"profile": {"step": "tracelens", "path": []},
                          "normalized_artifact": {"step": "tracelens",
                                                  "path": ["normalized_artifact"]}}},
            {"id": "qualification", "module": "quality.qualify",
             "depends_on": ["environment", "training-summary", "analysis"],
             "config": {"report_kind": "baseline-qualification"},
             "bindings": {"environment": {"step": "environment", "path": []},
                          "training": {"step": "training-summary", "path": []},
                          "analysis": {"step": "analysis", "path": []}}},
        ],
    },
)


def validate_subworkflow(entry: Subworkflow) -> None:
    """A composition may not hold two producers of the same report."""

    for module_id in entry.modules:
        if module_id not in _BY_ID:
            raise ModuleContractError(
                "Subworkflow references an unknown module: " + entry.id + " -> " + module_id)
    reports = [member.report for member in (_BY_ID[m] for m in entry.modules) if member.report]
    duplicated = sorted({kind for kind in reports if reports.count(kind) > 1})
    if duplicated:
        raise ModuleContractError("Subworkflow has conflicting report producers: "
                                  + entry.id + " -> " + ", ".join(duplicated))


def validate_catalog() -> None:
    """Reject duplicate ids, ambiguous report producers and dangling references.

    Two modules may produce the same gate report only when their engine tags are
    disjoint, i.e. no single run could ever hold both (Megatron vs torch logs).
    A profile that still lists both fails the plan-level conflict check.
    """

    if len(_BY_ID) != len(MODULES):
        raise ModuleContractError("Module ids must be unique")
    producers: dict[str, dict[str, str]] = {}
    for module in MODULES:
        if module.report not in _gate_kinds():
            continue
        seen = producers.setdefault(module.report, {})
        for engine in module.tags.get("engine", ("any",)):
            if engine in seen:
                raise ModuleContractError(
                    "Two modules produce the same gate report for engine " + engine + ": "
                    + seen[engine] + ", " + module.id)
            seen[engine] = module.id
    for alias, target in ALIASES.items():
        if alias in _BY_ID:
            raise ModuleContractError("Alias shadows a module id: " + alias)
        if target not in _BY_ID:
            raise ModuleContractError("Alias points outside the catalog: " + alias + " -> " + target)
    for entry in SUBWORKFLOWS.values():
        validate_subworkflow(entry)
        if entry.template:
            steps = entry.template.get("steps", [])
            ids = [step["id"] for step in steps]
            if len(set(ids)) != len(ids):
                raise ModuleContractError("Subworkflow template step ids must be unique: " + entry.id)


def _gate_kinds() -> frozenset[str]:
    from .contracts import GATE_REPORTS
    return GATE_REPORTS


def modules() -> tuple[Module, ...]:
    return MODULES


def module(module_id: str) -> Module:
    try:
        return _BY_ID[module_id]
    except KeyError:
        raise ModuleContractError("Unknown module: " + module_id) from None


def aliases() -> Mapping[str, str]:
    return dict(ALIASES)


def subworkflows() -> Mapping[str, Subworkflow]:
    return dict(SUBWORKFLOWS)


# Compatibility names: the functional subworkflow layer started life as
# ``presets``.  Both spellings resolve to the same entries.
presets = subworkflows


def resolve(name: str) -> Module:
    """Resolve a module id or alias to a catalog entry."""

    if name in _BY_ID:
        return _BY_ID[name]
    if name in ALIASES:
        return _BY_ID[ALIASES[name]]
    raise ModuleContractError("Unknown module or alias: " + name)


def subworkflow(name: str) -> Subworkflow:
    try:
        return SUBWORKFLOWS[name]
    except KeyError:
        if name in SUBWORKFLOW_ALIASES:
            return SUBWORKFLOWS[SUBWORKFLOW_ALIASES[name]]
        raise ModuleContractError("Unknown subworkflow: " + name) from None


preset = subworkflow


def family(module: Module) -> str:
    return module.id.split(".")[0]


validate_catalog()
