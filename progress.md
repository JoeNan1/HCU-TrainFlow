# Implementation progress

> 本文件是按任务保留的历史记录；每段计数、版本、完成状态和限制仅对应当时的检查。现行用法见 README、AGENTS.md 与对应 Skill/docs，当前任务见 task_plan.md；不将旧安装或发布计划当作当前要求。

## 2026-11-05：模块化能力与 Pipeline 重构首轮

- 新增 `src/hcu_trainflow/kernel`，定义独立 capability 与 Pipeline 契约；旧 `core.py`/`flow.py` 仍作为兼容控制面。
- 新增 `capabilities` registry 和 environment/adaptation/profiling/optimization/quality/scale/observation/delivery facade；新增 execution adapter facade。
- CLI 新增 `capability-list`、`capability-run`、`pipeline-plan`、`pipeline-run`、`pipeline-next`、`pipeline-default`；基础 task/flow 命令改为延迟导入，缺少 Wiki 可选依赖时仍可初始化和接手 flow。
- 任务态 Pipeline 通过现有 Flow gate 执行，步骤结果登记为 artifact，可按配置登记 report，并以 context/revision 绑定 run/step，重复调用可恢复已完成步骤。
- 模块化 CLI 的注册与分发已移入 `command_registry.py`，旧 CLI 入口保持兼容，模块化入口继续隔离可选 Wiki/TraceLens 依赖。
- 新增 `docs/modular-architecture.md` 与 `examples/quality-pipeline.json`，文档检查和 Skill 资源检查通过。
- `py_compile`、13 项模块化/桥接/CLI registry 测试、CLI init/flow/pipeline smoke 通过；完整 CPU 回归为 1353 passed / 8 skipped，知识校验为 22185 pages / 24 sources / 0 errors，文档和 Skill 资源检查均为 current。按安装协议执行 `sync_local_install.py --check` 时发现当前 `/root/.codex/skills` 没有已绑定的 TrainFlow Skill 安装；没有另行进行首次安装或写入系统 Skill 目录。

## 2026-11-05：两阶段维护的 TrainFlow 集成检查点

前置HCU-Knowledge v0.5.7 / c08470f7已独立交付，当前阶段没有再次更新大库。98篇作者页、54份工作流关联目标、三个阶段HCU方法、官方来源及许可已集成；24份当前正文/工作流回执通过原生review/apply，旧未决目录项完整继承，未深读17,003项仍保留。直接引用46项PR完成语义复核和当前公共原件的原生绑定。

新增TraceLens高级告警传播、受管依赖防回退保护及文档symlink跨固定commit重读target修复，均有独立review和真实回归。当前全仓1,343通过/4平台跳过；受影响工作流回执与选定本机安装已原生更新，11项必需Skill验证和同步/check为current，可选KernelWiki定制与独立知识库绑定保留。版本元数据准备为0.7.4，最终独立发布审阅、提交/main CI/tag/push及远端核验继续收尾。未新增训练或硬件验证。

最终无截断全24来源审计已实际结束：22Git/2web、870份登记Git源码、1,251份文档、20,780条PR，未知错误和输入漂移均0。可访问范围完成，精确19条SG/vLLM真实原生404仍保留快照及pending；原10,493项队列减少唯一10,474项，不改窗口或强造零缺口。四份完整固定Git路径补证已发布，原3000条API上限、null SHA、缺patch与diff_complete=false事实保留。所有历史失败/恢复及采集后的doc-only源码修复分别留证，不回填历史runtime指纹。

最终目录已原生生成。终检发现PR标题中的链接语法会形成嵌套链接，已仅修复catalog标签的方括号转义并保留原标题；旧实现精确回放失败，72项相关回归通过，维护回执与本机安装已原生更新。修复前f65索引/20次成功查询保留原件，修复后最终索引efa92f2b67444fbddb688b5256885d2fec8bcfda85229685e06878784d19b475共22,185页。20组真实问题默认混合检索全部命中并读取同generation完整当前正文，目标正文SHA与当前文件逐一相符；最终完整提交由GitHub Actions矩阵验证。

发布前最终独立review已完成，零阻断发现；后续仅提交、提交后安装检查、main实际CI与tag/远端验收。附带下载任务已取消，不执行桌面或下载操作。

## 2026-10-20：两阶段维护的 TrainFlow 阶段

前置 HCU-Knowledge v0.5.6 已提交推送并核验两远端；本阶段不再更新大库。24项官方来源的固定树、登记源码/官网正文、98页作者内容和受影响工作流已集成并独立复核。全树路径分类、46项直接引用PR内容回执及现存上游缺口均已保留，未读机制继续待审。

本阶段已通过1,312项CPU测试（4项平台跳过）和知识/文档/阅读路线/覆盖检查；完整安装、本机六项同步及11个必需Skill/绑定核对成功。最终10,736页、24来源知识校验无错误；新索引 f07ae184a6c1 的12组真实问题均读取完整当前正文，其中11组默认检索直达，1组按已文档化的作者页kind细化后直达。未执行训练或硬件实验，可选KernelWiki原有定制验证脚本保留。

PR原窗口发现及全部可访问条目/周期讨论采集已完成。达到GitHub REST配额时保存队列，按服务重置时间续接；已用当前状态样本比较GraphQL完整讨论/REST文件路线，分页不完整回到原采集器。配额等待期间的严格零REST首轮留存340条，原窗口和公共游标不变。最终22项Git来源的798份登记源码、1,218份选定文档与9,359条PR记录通过来源验收，46项已引用PR的当前原件/作者页哈希绑定通过；其他原件仍为source-reported，未读机制继续待审。

Swift历史PR #10260与vLLM历史PR #48358的认证PR/Issue两入口均返回404，最终又由原生采集器各实际重试一次。仅增加availability注释，保留原来源日期、正文、JSON与失败pending，未推进这两个来源的公共游标，不推断删除或制造新鲜内容。20项其余Git队列为空；所有来源的原发现分页均已结束。目录、新索引及最终证据检查已完成，交付版本为0.6.10；提交main与annotated v0.6.10的发布结果以远端refs核验为准。

## 2026-10-12: Check/adapt rename and optional KernelWiki verification

- Renamed stage Skill and updated runtime/UI/docs/maintenance routes; exercised migration from the previous entry, verified old installation removal only after replacement succeeded.
- Focused installation/routing regressions: 100 passed. Full CPU suite: 1234 passed, 4 platform skips. Wiki validator: 489 pages/25 sources, zero errors. Reading resources: 59 pages/78 reachable, zero issues. New Skill metadata validation passed.
- Actual pinned KernelWiki checkout, isolated installation, read-only installation check and warp-specialization query passed. Existing customized system KernelWiki was not overwritten. Built source distribution contains the renamed Skill and excludes the optional checkout.
- Full local setup succeeded with the existing HCU-Knowledge binding/current index reused: 11 required Skills verified, renamed entry installed and old name removed. No online knowledge update or live HCU training performed. Final local sync/check passed for the package, six workflow Skills and all 11 required Skills; reviewed tree is ready for Git publication.


- Preserved original approved planning privately before preparing public documentation.
- Resolved 10 public upstreams to immutable commits and acquired 145 selected files; acquisition is distinct from content review.
- Implemented transactional tasks/evidence/fencing, explicit command plans, immutable selected-source snapshots, health coverage, overlap-aware operator assessment, stage loss gates, durable watcher and replayable inbox, staged Wiki refresh/PR reviews and workflow impact checks.
- First local regression run: 39 passed, one Windows SQLite rename failure. Fixed by explicitly closing connections before immutable-index publication.
- Corrected crash boundary: watcher cursor, observations and incidents commit in one transaction; heartbeat is derived.
- Public Wiki, five Skills, packaging/docs and end-to-end publication review remain in progress.

- Public Wiki now contains 31 topical pages plus index, with 20 upstream repositories and 178 acquired fixed-source files. Deepest coverage is Megatron plus representative ecosystem mechanisms; other engines explicitly retain entry-guide scope.
- Five Skills validated with the Skill creator validator.
- 51 local regression tests passed; installed CLI demo and separate wheel-import demo passed.
- Live GitHub refresh verified TraceLens registered paths. Live PR collector retrieved Megatron-LM #7942 including five independent reviews and both changed files; its fusion/precision lesson is now an authored case.
- Public file and local Markdown link scan found no internal address, credential pattern or broken local link.

- Final pre-publication local validation: 52 tests passed; 32 Wiki pages (31 topics + index), source/maintenance integrity passed, five Skill validations passed. Source bundle integrity and resource ownership under unresolved execution are covered.
- Repository relocation now creates a new Wiki index generation so search results cannot retain obsolete absolute paths.

## v0.1.0 release verification

- Final local suite: 55 tests passed. Added stale-event dispatch rejection and cross-task resource serialization checks during release review.
- Public GitHub repository created under yuguo-Jack; initial Windows/Linux × Python 3.10/3.12 matrix completed successfully. Final release commit is validated by the same workflow.
- CLI editable install, wheel build/import demo, source locks, five Skills, local Markdown links and public file boundary reviewed.
- Source/field limitations and the next real HCU pilot are documented in docs/capabilities.md. No real HCU benchmark, training deployment or notification service was claimed or performed.

## HCU launch recipe guidance correction

- Updated prepare to prefer applicable HCU model scripts and the actual deployment, preserve user patches, trace sourced configuration and launch wrappers, and compare official model/training semantics.
- Aligned project instructions, general workflow, three Megatron pages, profiling guidance and workflow maintenance; recorded launch source/version, effective configuration and adjustment rationale as adaptation evidence.
- Validation passed: 32 Wiki pages / 20 sources with no integrity errors; all three changed Skills passed the Skill validator; Git whitespace review passed. This is a guidance change, without new runtime behavior or HCU execution claims.

## v0.2.0 training libraries and integrations

- Authored 14 independent TE/cuDNN Frontend pages with source maps, build/run/test guidance, numerical and storage contracts, attention, fusion cases, tutorials and update routes. Wiki totals: 46 pages, 21 Git sources and 2 website groups.
- Read selected pinned source and repository tutorials; acquired all 16 registered official HTML pages. Code and website fingerprints remain distinct; no NVIDIA tutorial or model loss was executed on HCU.
- Integrated TraceLens report APIs with private tables/logs and pinned provenance. Real local tool invocation produced 10 tables from the compressed single-rank synthetic fixture and 5 tables from synthetic two-rank collectives. No hardware/throughput claim follows from these fixtures.
- Verified a fresh checkout of both public dependencies using the bootstrap implementation; TraceLens uses sparse acquisition. Verified optional private repository Git access without copying its materials into this project.
- Verified full eight-Skill installation into a temporary directory and protection of modified existing Skills. Five workflow Skills pass schema validation; real questions find the intended new Wiki pages and all local Markdown links resolve.
- Built wheel and source distribution with system Python; archive inspection confirms private workspaces and thirdparty checkout contents are absent. Public manifest and installation scripts are included in the source distribution.
- Final local validation: 72 tests passed, 46 Wiki pages / 23 sources have no integrity errors, public file scan and Git whitespace review passed. Package metadata and documentation now declare 0.2.0.

## v0.2.1 TraceLens fork integration

- Published public fork commit e4e891de60d3ac3cff3046a58e5852d0814b3dc6 on `hcu`, based on AMD upstream c5da90ee7d59e49bf75e8602f0211da1f6dcd8b3. All upstream analysis modules and native entrypoints remain available.
- Locally passed 15 portability tests covering all 13 native CLI help entrypoints and two CSV integer-bound cases, 41 existing deterministic report tests, and 7 existing architecture-resolution tests. The same selected tests pass on Windows/Linux with Python 3.10/3.12 in fork CI.
- Migrated this machine's clean upstream dependency checkout using the explicit migration command, preserved the upstream remote, reinstalled the pinned fork and generated 10 single-rank tables plus 5 two-rank collective tables from synthetic fixtures.
- TrainFlow validation: 77 tests passed, including preservation of dirty/unknown/conflicting migration states; 46 Wiki pages and 24 registered sources have no integrity errors. Both upstream and fork now participate in workflow maintenance.
- Real HCU graph attribution, custom collective classification, hardware performance models and replay remain deployment-validation work; no full upstream GPU/JAX/Origami suite or real training result is claimed.

## 2026-10-09 collaborative workflow follow-up

Inspected clean local checkout, project rules and current interfaces; read planning-with-files and skill-creator. Work is development-only: no release/tag. Planned names: hcu-trainflow entry, hcu-train-adapt, hcu-train-optimize, hcu-train-fault-tolerance, plus existing Wiki search/update. Reference-only source checkouts stay under ignored .private.

Reference retrieval note: older .private/sources directories are source snapshots, not independent Git checkouts; attempted git -C fetch resolved the TrainFlow root (read-only fetch only). Created explicit ignored .private/reference Git checkouts for current comparison instead. A referenced rlar.py path was a package; corrected inspection to rlar/__init__.py.


- Implemented durable goal/candidate/reviewer rounds, explicit correction/blocked decisions, current evidence checks, stage and iteration gates, bounded failures/plateaus, and manual-transition protection. Independent reviewer identity remains a runtime responsibility; no actual second model or GPU result is claimed by the synthetic fixture.
- Added generated BOARD.md, preserved GUIDANCE.md, revision events and responses, blocking/advisory questions, polling and existing inbox integration. No persistent monitor service was deployed by this task.
- Added hcu-trainflow and renamed stage Skills to adapt/optimize/fault-tolerance. Installer migrates old names with preserved backups outside Skill discovery; six workflow Skills are installed locally, matching checkout bytes. Existing Hygon kernel Skill installations were not replaced.
- Updated workflow-first README, architecture/contracts/operations, source-maintenance links, CLI, unreleased changelog and package metadata to 0.3.0.dev0. Local editable installation reports the same version.
- Validation: 100 full-suite tests passed; 22 focused flow tests passed again after final contract/error-handling review. All six Skills validate; all 46 Wiki pages and 24 source registrations validate; authored local Markdown links resolve. CLI collaboration demonstration completed with explicitly scripted CPU-only evidence and a retained board. Existing real-site/multi-Agent/notification validation gaps remain explicit. No release or new tag was created.


Started the approved project-description/five-minute guidance/multi-Agent coordination follow-up. No real training environment or background service is being deployed. Using the existing planning-with-files and skill-creator workflow; prior checkout is clean.

## Agent coordination and five-minute guidance follow-up

- Applied the agreed agentic workflow description to README, package metadata and GitHub About (authenticated account verified as yuguo-Jack). Version remains 0.3.0.dev0; no release/tag requested or created.
- Implemented DAG work plans, atomic bounded claims, actual session mapping, immutable accepted-input hashes, result review, quiescent yield/cancel and durable peer messages with explicit receipts. Integrated incomplete-team gates and stale-candidate invalidation with the existing flow loop.
- Enabled independent assignment command execution while preserving task/assignment budgets and uncertainty checks. Shared GPU measurement remains fenced; operation-scoped resources let different operator Agents continue development concurrently without reserving GPU for their whole task.
- Guidance collection defaults to 300 seconds; normal flow operations share the collection timestamp, and explicit refresh remains immediate. Task board includes assignments, dependencies, sessions, results and peer exchanges.
- Updated coordinator/three stage Skills with concrete parallelization, direct peer interaction and operator optimization guidance. Reviewed Multica alongside the prior Hyperloom/Humanize/BBuf evidence. The local protocol demo now includes two scripted lanes, question/answer/acknowledgement and result acceptance before the full review loop.
- Validation: 127 tests passed, including 26 team/parallel/message/resource tests; 46 Wiki pages and 24 sources validate; six Skills validate and installed copies match repository bytes; local Markdown links and Git whitespace pass. Private/cache paths remain excluded from candidate tracked files. System Python editable metadata remains 0.3.0.dev0.
- Real model-provider launch, native runtime message delivery and HCU hardware behavior remain deployment validation work. Only the synthetic protocol was executed; no background watcher, production training, release or tag was started.

- Follow-up clarification: operator Agent names/counts are generated from actual model/profile evidence, with no fixed roster. Updated coordinator/optimization Skills, README, project rules and the diagram to permit independent per-operator analysis-to-optimization progress while other operators are still being analyzed. The generic scheduler already supports arbitrary assignment identities and per-task dependencies; no operator enumeration or new runtime restriction was introduced.

## 2026-10-09 Wiki completion

Implemented scoped PR search, pinned code reading, public PR source pages, complete tree inventory, bounded resumable PR refresh and content/workflow review separation. Added private experience storage/search/replay, metric/loss and cookbook provenance contracts and automatic report/flow milestones. Existing 127 tests and 9 new focused tests pass so far; broader review pending. Official source inventory acquisition in progress.

- Completed public upstream acquisition: 22 full inventories, 388 repository documents and 24 selected PR source pages with all discussion types. Expanded eight engine guides plus Bridge/Energon and Megatron engineering map; added paged-stash launch and DeepSpeed offload lifecycle cases. These are selected-source readings, not hardware validation. Canonical names and license notices retained.
- Functional review fixed mixed upstream newline hashes, persistent untriaged tree changes, same-repository page review, changed PR discussion review, missing document regeneration, source-type ranking and private milestone idempotency. Real PR search reached unretained PRs and fork-head source; an Energon raw-host failure was exposed and recovered through the fixed-SHA content API. Local tests currently 142 passed; final regression includes additional PR-impact tests.

- Final pre-publication checks: 144 tests passed; 484 Wiki pages / 24 registered sources validated with no errors; authored relative links and changed-file secret patterns passed. Live query returned unretained Megatron PR #7992 with correct open state and pagination; #7897 discussions and exact fork-head source read successfully. Source partial failures remain visible and pinned API fallback recovers raw-host failures. Six local Skills and development package metadata are being synchronized before push; no release or tag for TrainFlow.

- Final extensions: automatic source catalog, explicit historical/pending document state, PR discussion-to-author-page review receipts, and inventory failure dependency handling. Full regression 145 tests passed; 485 pages / 24 sources validate. Installed all six Skills, confirmed source and installed package version 0.4.0.dev0. Public-source corpus ~30 MiB; no task data, private workspace or credentials staged.

- Commit 844f791 contains the reviewed Wiki/experience work. A final whitespace pass normalized generated directory-page endings without changing content hashes. Authenticated GitHub account verified as yuguo-Jack; origin was up to date before commit. Publication uses main only, with no TrainFlow tag/release.


## 2026-10-09: overall review before real HCU integration

- Reproduced and fixed monitoring retention/rotation, execution reconciliation budgets, global assignment reservations, context reset/late dependency evidence, false PASS coverage, stale Wiki review/index scope and concurrent experience persistence. Cross-review additionally caught source-citation removal and full-page read generation binding.
- Final system Python regression: **206 passed in 22.49 s**; validator **485 pages / 24 sources / no errors**. Both synthetic workflow demos run through regression tests.
- Authored documentation/Skill relative links and Python syntax checks passed; tracked private/cache paths absent; git diff whitespace check passed.
- Fixed TraceLens and kernel-Skill checkouts are clean and ready. System installed version remains **0.4.0.dev0**; all six installed workflow/Wiki Skills byte-match their repository copies.
- No live training, remote recovery, external notification or HCU-Knowledge update performed. Public repository has no site data. Real environment onboarding can now validate command adapters, HCU traces/numerics, distributed recovery and Agent wake-up.
- Commit/push development fixes using yuguo-Jack; retain no new tag/release. Remote publication/CI status is checked after committing.


## 2026-10-09: parallel mapping before kernel optimization

- Added an early parallel-layout/memory-budget assessment to optimize and coordinator Skills; linked the workflow to the Megatron parallelism topic and retained official parallelism, Bridge performance and memory-estimator tutorials.
- Compare actual HCU topology, TP/PP/DP/CP/EP/SP, microbatch/accumulation, recomputation and state sharding against worst-rank peak/headroom and measured throughput. Preserve model/global-batch/token/precision/optimizer semantics; refresh process groups and shapes after layout changes; stage loss cadence is unchanged.
- Documentation-only change: knowledge validator passed 485 pages/24 sources; changed links, Skill metadata, numbered flow and whitespace checked. Changed Skills installed with backups. No training or HCU-Knowledge update.

## 2026-10-09: detailed workflow diagrams

- Added docs/workflow-map.md: ten editable Mermaid diagrams covering the overall task, adaptation, parallel-layout/memory tuning, fusion and hotspot bounds, local/stage validation, review, dynamic Agent collaboration, remote execution, long-training recovery and the knowledge lifecycle. Added exact full-mode gate/source mapping and linked from README/architecture.
- Rendered all ten diagrams with Mermaid 11.12.0 and inspected overview/optimization/monitoring views using Playwright. A local offline HTML preview with embedded SVGs and original-size controls is retained under ignored .work/workflow-map; diagrams remain editable in the tracked Markdown.
- Verified local links and all seven core.GATES report sets; knowledge validation passed 485 pages/24 sources. No runtime logic or Skill changes, so no additional training/runtime tests. Version remains 0.4.0.dev0; no HCU-Knowledge update, tag or release.

## 2026-10-09: homepage alignment

- Gave the README overview its own section; made the failed stage-validation loop, full-model minimum-DP validation and completion/handoff condition explicit. Summarized parallel-layout/memory tradeoffs and linked the ten detailed diagrams.
- Added concise official/private/HCU knowledge roles, online PR-to-source fallback, local Wiki maintenance and private experience boundaries. Kept the development version and site-validation status unchanged; no runtime or Skill changes.

## 2026-10-09: illustrated README overview

- Used built-in imagegen to create a navy/cyan technical workflow illustration. Refined parallel-task presentation, the separate pass/retry branches and text readability; selected the final shorter-copy image after visual inspection.
- Stored the PNG and final generation prompt under docs/assets; README links to the full-size image. The editable ten-diagram workflow map remains the detailed technical source. No runtime, Skill, version, release or HCU-Knowledge changes.
- Verified the 1536×1024 PNG, README/prompt links and Git whitespace; knowledge validation passed 485 pages/24 sources with no errors. Only the selected final image is included in Git.

## 2026-10-09: white overview and workflow comparison

- Restyled the README overview with built-in imagegen using the supplied picture only for white/pastel/line-art appearance. Preserved TrainFlow's own stages and wording; refined the continuous quality-pass connector into scaling. Replaced the asset and updated its prompt and README reading links; the dark version remains in Git history.
- Compared visible reference-flow capabilities with current TrainFlow Skills/source and recorded the evidence limits and concrete gaps in findings.md. No capabilities from the reference diagram were silently added or claimed implemented; no private reference image was added to the repository.
- Validation: final PNG decoded successfully, README/prompt links and whitespace passed, knowledge validator passed 485 pages/24 sources. Version remains 0.4.0.dev0; no runtime/Skill changes or release/tag.

## Torch training / communication / installation follow-up

Confirmed access to the supplied reference repository; read framework and communication workflows. Added training-specific conditional references and started full installation changes. Full HCU-Knowledge setup must include local index readiness and workspace-bound search/update Skills. No source refresh of the domain KB is authorized as a side effect.

Validation: full dependency/Python/index/11-Skill setup succeeded against the existing independent HCU-Knowledge checkout, with all 77,358 evidence objects and 32,269 derivatives checked. A second run exercised the current-index reuse path and synchronized the system Skills without rehashing historical data. Knowledge repository tracked files remain clean; no source update or extra clone. Six TrainFlow Skills validated; relative links resolve; all 12 Mermaid diagrams render without parser errors. README image regenerated and visually checked. Public/private files and Git diff reviewed; no release/tag.

Final regression: 218 tests passed; knowledge validator checked 485 pages / 24 sources with no errors. Current-index reuse and installed Skill bindings verified; generated browser artifacts are ignored.

## Real environment integration in progress

Implemented and locally tested occupancy admission, SSH hop contracts, dimensional-proxy authorization, HIP trace attribution, batching/source-link integrity and training log/lifecycle observation. Actual fixed source transfer and bounded device/component diagnostics have run; full environment, model baseline, multi-rank optimization and long-run recovery remain open. Parser/tool issues and model initialization defects are retained with private evidence. No public site data, domain-knowledge update, release or completed-training claim.

## Real-environment workflow qualification checkpoint

- Generalized fresh device/process admission, nested SSH execution, immutable source transfer including nested Git modes, multi-node command receipts and uncertain-execution reconciliation. A dangling child Git marker and Windows path-case ambiguity are rejected before incorrect source metadata can propagate.
- Added real training-log adapters, scoped observer lifecycles, all-member health aggregation, context handoff, versioned file Q&A, reusable private reference data, conservative cache maintenance and offline training curves with original-byte provenance.
- TraceLens fork changes were independently reviewed and pinned after processing actual compressed, multi-rank HCU traces. Shape attribution, denominator coverage, missing groups and conditional operator bounds remain explicit.
- Actual bounded training, optimization and stage-loss records are retained privately; collector pause/recovery demonstrates monitoring behavior, not recovery of a failed training job. Main-branch model integration has separate qualification and a retained checkpoint failure; full numerical/production gates are not marked passed.
- Final local regression: **844 passed in 85.74 s** using system Python; knowledge validation: **485 pages / 24 sources / no errors**. Independent source-transfer checks passed; new chart tests include extreme finite numbers, missing values and raw-log byte verification. Public changed/new files were checked for private site identifiers and credentials; no matches. Final independent review and publication verification follow.

- Clean GitHub CI exposed fixture assumptions hidden by the development machine: workflow-only replacement tests were invoking full installation with local thirdparty dependencies, and Linux observer mocks omitted the unlock constant. Scoped the lifecycle tests to explicit workflow refresh and completed the lock mock; full required-dependency setup remains covered separately and unchanged. Local success and CI success are recorded separately.

## Checkpoint IPC and concurrent evidence follow-up

- Replaced CAS overwrite publication with atomic no-clobber publication and verified-content reuse; bounded only Windows sharing conflicts. Added deterministic racing writers/readers, corrupt object, fsync/I/O and unsupported-filesystem regression cases. Mutable file publication remains separate.
- Added explicit Linux checkpoint TMPDIR preflight with actual AF_UNIX and spawn Manager queue roundtrips, exact-path evidence and bounded own-process cleanup. Actual target-container short/oversized path tests succeeded/failed as expected without fallback; platform limitations remain explicit.
- Local full regression: **875 passed, 4 Linux-specific tests skipped on Windows**, 58.74 seconds. Knowledge validator: **485 pages / 24 sources / no errors**. Cross-platform CI remains a separate result; matrix now completes all combinations even if one fails.

## Performance discrepancy workflow review

- Added explicit unresolved performance discrepancies, typed/evidence-linked validation, follow-up classification and a common reference-to-controlled-trial procedure. Synchronized the coordinator and all three phase Skills with that procedure; analysis-only and occupied-resource boundaries remain explicit.
- Independent root review and full local regression: **905 passed, 4 platform-specific skips**, 59.03 seconds. Knowledge validator: **485 pages / 24 sources / no errors**. Private hardware experiments and publication are recorded separately; no site measurements or identifiers are included here.

- Root reviewed the complete public diff and synced the four changed managed Skills (the two Wiki Skills were already current). The private A/B/A executed with native correctness and per-rank shutdown evidence; reference comparability and shared-network uncertainty remain explicit. Further site analysis stays in the private workspace.


## 2026-10-10：跨任务站点知识归属修正

- 按用户明确要求将真实站点配置、通信配方、三轮测量和关键证据放入 knowledge/sites，随本仓提交；不建独立共享私有 Store，不沿用外部 Cookbook 的无数据限制。
- 新增通用 practices、知识归属说明；六个 Skill、README、贡献/安装文档同步，已安装到本机 Skill 目录。
- 新任务 Store 实测4条跨引擎查询均能找到站点，读取正文无需原任务。62份声明证据、491页/24来源校验通过。
- 独立 reviewer 找到并已复核关闭旧发布规则、站点目录/相对路径符号链接漏检、源码机制依据仅在旧workspace三项问题。
- 全套本地961通过/4平台跳过；之后新增符号链接回归并单独9通过。硬件实测与本地协议测试范围分别保留，整体训练与真实自动恢复仍未完成，不发布release。


## 2026-10-10：全参容量预估与多实例优化

用户补充：先用 HCU Train Sim 等判断完整模型可行性，卡足优先全参，卡不足才缩 layer；资源富余时独立完整模型实例并行优化，明确分工和及时交流。已核对公开模拟器 b7d8e6f3（CLI/adapter/模板），并修正 proxy/adapt 的旧“优先缩层”措辞；协同协议沿用现有 team/lease/inbox，新增实践、更新阶段 Skill 和可编辑流程图。预测不作为硬件或全模型验证，当前 Kimi K3 模拟覆盖仍需核实，实际实验继续。


## 2026-10-10：HCU底层工程联动

按用户要求将HCU Primus Turbo、UCCL、UltraEP、MoonEP纳入按瓶颈选择/复用/修改重编/分层验证/目标PR的链路。已检索HCU-Knowledge保留报告，明确通用与专项分支和接口边界；HCU问题先查询大知识库，同问题已取回证据可复用，不触发大库更新。训练引擎与容错项目不扩名单。

- 本轮容量/联动/模型案例独立只读复核完成：源锁10文件与24份案例原件及解压哈希吻合；修正一处启动审计字段的原件指针。495页/25来源校验零错误；9项证据校验测试通过；12张Mermaid图实际渲染零错误。新Store三类查询均找到正确实践/模型入口。Skills已同步本机，实际训练与恢复资格另行验收。


## 2026-10-10：知识筛选、通用方法与 Skill 改名

按最新要求移出未定模型试验与中间报告，72份材料逐字节校验后保留任务档案；共享站点配方及原件保留。方法文档移 docs/practices，修复关联路径和维护表。六个 Skill 的入库边界统一，更新入口改 hcu-engine-wiki-skill-update，本机同步并备份旧入口。独立复核发现并修正两组旧入库/搜索指引；实际新旧 Store 检索均保留站点命中、移出模型中间页。完整本地套件963通过/4跳过；改名后针对安装/迁移/集成/知识检查46通过，489页/25来源校验零错误。真实模型算子验证及后续阶段质量保留任务状态，不宣称全部工作流已验收。


## 2026-10-10 硬件建模交接与算子阶段复核

- 两节点16卡只读属性与管理工具复核，统一硬件基线；产品标签冲突、旧测量执行映射缺口明确保留。
- 非Adam高贡献模型8项CPU检查通过，主控接受分析阶段；每项工作量、条件效率、余量与下一动作已更新看板。完整优化没有据此关闭。
- baseline初版→HIP优化、现有Triton→Triton优化的交接与负责人验收已写通用Skill；本机三项变更Skill已同步。
- 真实CM恢复密封日志经现有解析/绘图得到3张图、9步记录，历史离线视图不进入实时监控。
- 站点硬件知识及精选6原件随公共工程；全新Store可搜读；独立review唯一来源过度断言已修正。72项相关测试和490页/25来源校验通过，无release。
# Integrated review, 2026-10-10

- Final integrated acceptance: **1054 passed, 4 platform-specific skips**, 68.69 seconds with system Python. Wiki: **490 pages / 25 sources / zero errors**; 50 README/docs/Skill Markdown files have no missing local file links. Both synthetic demos complete within their stated CPU-only scope. Actual 0.4.0.dev1 sdist retains **68/68** declared originals, workflow image, knowledge notices and source licenses; extracted knowledge validation passes.
- Independent integrated reviewer reproduced then verified fixes for legacy quality advancement and dispatch context/epoch races; no remaining reproduced blockers. Retained-input numerical gate has direct Store and full flow-review/advance regression coverage, including historical evidence compatibility. No further real-environment tuning was performed.
- Refreshed system editable metadata to **0.4.0.dev1**, synchronized all six workflow/Wiki Skills with backups and project bindings, and verified a second installation is unchanged. All six Skills pass validation. Existing kernel/knowledge Skills and the large knowledge repository were preserved; their dependency readiness was checked earlier.
- Publication target: main plus annotated **v0.4.0-dev.1**, explicitly requested by the user; no GitHub Release. Commit/tag refs provide the final publication receipt after local verification.

- All six revised Skills pass skill-creator validation with system Python UTF-8 mode (the external validator's default Windows GBK decoding failed; no skill content was changed to work around it). Fresh temporary Skill install carries project bindings. Fresh Store Wiki search resolves GPU_MAX_HW_QUEUES with official and site context; dependency status confirms all three pinned/external checkouts are ready and clean. No HCU-Knowledge update, live training or remote mutations were performed.
- Origin fetch succeeded; no upstream commits beyond the starting HEAD. Selected 0.4.0.dev1 / v0.4.0-dev.1 as an explicitly requested development milestone, without a GitHub Release. Installed editable-package metadata will be refreshed together with managed Skills after final validation.

- Added the common takeover/phase/evidence-reuse playbook and connected it to coordinator and docs. Clarified standalone environment/diagnose/optimize scope, stage A/B initial-state and recipe contracts, installation binding discovery, and existing physical qualification limits. Focused numerical/flow/proxy regressions: 90 passed before the additional identity checks; full validation follows integration.

- Read current project instructions, coordinator Skill, skill-creator and file-planning instructions; session catchup reported no additional context. Inventoried source, docs, tests and six Skills. Started independent workflow and runtime audits without remote execution.

## 2026-10-10：0.5.0 文档与版本发布准备

- 完成工程介绍、README 入口、白底科技风主页图以及 12 张 Mermaid 的衔接更新；独立复核发现的范围和部署表述已修正。
- 系统 Python 全量回归：1054 passed、4 platform-specific skips（71.54s）。Wiki：490 pages / 25 sources / zero errors。
- Playwright + Mermaid 11.12.0 实际渲染 12 图，零解析错误，并检查优化及验收图截图；文档检查覆盖 33 份 Markdown、199 个本地链接，零失效文件链接。
- 实际构建 0.5.0 sdist，确认新增介绍、流程图、PNG、提示文件逐字节保留；68/68 声明原件哈希一致，私有 workspace 和第三方 checkout 未入包。检查脚本兼容 Windows PKG-INFO 的 CRLF。
- 源码版本、CLI 与本机 editable-package metadata 均为 0.5.0。远端 origin/main 没有新增提交，v0.5.0 tag 尚不存在；待本轮提交后推送并核对 main/tag refs。不创建 GitHub Release。
- 没有运行新的硬件实验、更新 HCU-Knowledge 或修改其他任务的运行现场。

## 2026-10-10：README 与升级同步验收

完成 README、集成说明、安装器和更新 Skill 的对应修订。安装/重命名/绑定/依赖相关 60 项测试通过；新增覆盖复制失败、校验失败保留原件、成功仅清理本次备份、拒绝目录外清理。Wiki 校验 490 页/25 来源/0错误。更新 Skill 源文件及已安装副本通过 quick_validate；实际同步六个工作流入口后，本次临时备份已清理，再次安装全部 already current，历史备份文件数仍为87，本机无旧名称入口。没有执行知识刷新、远端任务或其他依赖升级。

## 2026-10-10：阶段命名与故障诊断补强

- 两个阶段入口改为 hcu-train-check-and-adapt、hcu-train-scale-and-stability；六 Skill 总体分工、CLI mode/state 和历史任务格式不变。
- 新增按症状诊断、知识/源码查证、适配失败分流和优化异常交接四份引用指南；主控、更新 Skill、README、介绍/流程图和 maintenance targets 同步。
- 62 项安装/完整配置/集成相关测试通过；6 个 Skill quick_validate 通过；490 页/25 来源 Wiki 校验无错误；228 个本地 Markdown 引用无断链。
- 独立前向复核完成：通信超时/主机OOM/旧观察身份、显存增长/动态输入/空报告两组模拟场景均能形成正确的有界下一行动，没有发现误导或断链；不构成真实故障验证。
- 本机六个 Skill 同步完成，目录绑定与逐文件哈希核对一致；旧 adapt/fault-tolerance 入口已清理，本次临时备份验证后清理，历史备份未动。
- 提交目标 main，沿用 0.5.0 版本和既有 tag；推送回执在会话中核对，不发布新 tag。


## 2026-10-10 — 0.5.1 方法复核与验证

- 完成参考工程源码、HCU知识及现有三个阶段对照，已落地通用决策方法、诊断与维护入口；无实际训练、GPU采集、故障注入和HCU大库更新。
- Python全套测试：1081 passed, 4 skipped（70.07s）；本地平台受限用例继续保留skip。上限/归因定向回归80 passed。
- Wiki校验490页/25来源/0错误；六项Skill UTF-8 quick_validate通过；本地Markdown链接检查357条无失效（新增最终导航在发布前再检查）；新方法Mermaid语法通过。
- 初次Skill验证受Windows默认GBK影响失败，显式python -X utf8重验通过；没有修改系统验证器。
- 独立场景检验完成，无新增可行动问题；旧安装Skill与HEAD归一换行比对无独立修改，已通过仓内安装器更新六项工作流Skill，三个算子和两个大库Skill保留原绑定。
- 版本统一0.5.1；准备提交main及annotated v0.5.1，不创建GitHub Release。现场能力声明保持原验证范围。

- 发布前最终核对：359条本地链接无失效；六项已安装Skill内容/绑定一致；系统Python包与源码均0.5.1；HCU-Knowledge工作树干净；origin/main无外部新增提交，v0.5.1尚不存在。四项skip为Linux专用AF_UNIX/spawn现场测试。本轮发布目标为main与annotated v0.5.1，实际远端以Git回执为准。


## 2026-10-11：阅读导航与本机维护同步

- 完成分析与优化 Skill 更名、各文档/维护关联/元数据引用和安装迁移。
- 新增分层与模式阅读导航、资源可达性检查；更新主控和五个独立入口及其工作区说明。
- 新增本机包/六 Skill 同步及只读校验，安装失败保留明确阶段；完整安装/CI 检查本地阅读资源。
- 全量回归 1094 passed / 4 skipped（Windows 不支持的 Linux 路径）；之后新增完整安装资源阻断用例，定向 39 passed。490 页/25 来源 Wiki 与六 Skill 结构校验通过。
- 本机已实际同步包和六 Skill，旧优化目录清理；同步后只读校验通过。最后文档细化后再次同步并提交推送。

## 2026-10-11：入口、独立交付与整体契约复核

- 复现旧 Skill 动态路由，添加真实 CLI/临时安装场景后修复；交付-only 复用三阶段交付职责和共用文档，独立只读走查通过。
- 1 个独立审查任务复现监控时钟与完整安装相对路径两处边界，主控修复并加回归；旧监控状态迁移纳入检查。
- 定向回归 155 passed；知识校验 490 页/25 源无错误；阅读资源 58 个检查页/75 个可达页无问题。
- PowerShell 下 rg 不展开传入的路径通配符，个别初查命令失败；改用目录与 --glob/明确文件继续，未改数据。
- 全量回归 1109 passed / 4 skipped（Windows 不支持的 Linux 专用场景）；两套 CLI 合成演示完成；六 Skill 格式和阅读资源校验通过。
- 系统 Python 可编辑包及六个本机 Skill 已同步到当前工程，再以独立 --check 核验版本、内容和绑定，全部 current；独立监控复现重跑已转为 completion-unverified，不再派生 slowdown。
- 最终差异审查完成，提交推送为最后操作，实际结果以 Git 回执为准。本轮不打新 tag；未执行远端训练或更新 HCU 大知识库，知识库工作树仍干净。


## 2026-10-11 TraceLens 全能力维护

已完成独立fork开发、实际HCU采集及有界回放、XProf/XCompute实采、原生Agent推理复核和通用入口实现。复核修复跨shape模型复用、缺失数据当0、PF源文件覆盖、转换子进程超时残留及XCompute状态接口。正在收尾来源升级、全量回归与本机安装，再发布fork和TrainFlow。未更新HCU大库、未启动新的长训或发布tag。

### 收尾验收

- TraceLens HCU fork 已发布 `30f5dcd539dd4e588678e34168c7fcf726dd987e`；GitHub HCU portability 五个作业（Linux/Windows、Python3.10/3.12 与 CPU replay）全部 success。215 项定向通过；最后 Agent/Roofline 60 项通过，兼容组585项通过/3跳过/1缺大trace fixture排除，组间有重叠不相加。
- TrainFlow 全量1146通过/4个Linux专用场景在Windows跳过；Wiki刷新后的定向68项通过。真实原件在干净锁定依赖上重跑六个请求：JSON/PF/Graph/counters生成，Roofline保留7个unknown，Agent准备返回needs-agent-review及退出码2；同源JSON/PF六张表一致。
- 当前活跃 Agent 已完成真实六类别推理、显式review及聚合：metrics_complete/findings complete/report complete，failures为空；旧输入和旧推理不能自动沿用。
- 来源目录67项变化（含目录），保留5份HCU原始指南、37个固定源码文件证据；工具总览与Megatron profiling共同更新，22个维护目标逐项留回执，无待办。495页/25来源校验通过，代表性检索命中当前工具/专题/原文。
- 本机TraceLens包已安装到新固定提交，TrainFlow 0.5.1 editable及六个Skill同步并核验。59个阅读页/76个可达资源无缺失。原始trace/张量/站点采集日志及中间结果留忽略目录或私有workspace；未改HCU-Knowledge。
- 实测覆盖为gfx936/DTK26.10有界工具资格；其他硬件/版本、并发Graph、复杂有状态回放、GUI和完整训练loss仍按各自实际任务验证。TrainFlow本次提交后推送main；不新增tag/release。
- 首次推送的Linux CI发现既有DeepSpeed案例PR目录链接大小写错误，Windows存在性检查未发现。已修正真实Git路径，并在Windows也逐层校验链接大小写；增加跨平台回归，定向33项及495页校验通过。此为新增检查暴露的文档可移植性问题，源码内容结论未改变；修复后再次同步并推送，远端最终检查以最新提交为准。

## 2026-10-11：局部 Wiki 内容筛选

- 清理站点总览/通信正文中的会话决定、临时设施过程及无实际调度的复核排期；保留现场条件、指标、版本、限制和全部已登记原件。
- 审查并移出六份低相关官方入门/前端文档，登记 document_exclusions 理由；文档 ledger、来源导航与索引同步。完整源码树与线上按问题查 PR/代码保留。
- 同步实现排除优先于目录匹配，避免下次恢复已删页；既有页冲突显式要求整理，不自动删历史。离线校验同时拒绝仍保留的排除页（包括无 ledger 的孤立页）。
- 更新 Skill 和知识归属文档要求每次新增/修订检查复用价值，正文与过程记录分开；程序不冒充内容价值判断。
- 定向90项通过，489页/25来源知识校验无错误，59个阅读页/76个可达资源无缺失。新索引验证六页已移出，RCCL、ZeRO offload、Paged Stash 仍正常命中；回归覆盖旧索引切换、新上游排除文件与同步冲突。
- 系统Python包及六个已安装Skill同步并独立--check通过，更新Skill格式验证通过。本轮未刷新上游/大知识库，未变更运行依赖或执行远端任务，不新增tag。

## 2026-10-11：README、介绍与流程图更新

- 内置 imagegen 生成新版白底总览，保留准确阶段名、动态 Agent、热点优先级、并行单测/建模、阶段 A/B、扩 DP/长稳、精选 Wiki 与独立模式；提示词随图提交。
- 同步首页、工程介绍、架构/细图、快速开始、阶段说明、能力边界，以及 knowledge/thirdparty/practices README。
- 14 个 Mermaid 全部解析和渲染成功，人工检查总览图、新增 TraceLens 图与架构图；最终 237 个本地链接/章节检查无错误。489 页/25 来源知识校验无错误，59 个阅读页/77 个可达页无缺失。
- 更新本机 Wiki 索引；系统 Python 0.5.1 editable 与六个 Skill 同步成功，独立 --check 确认 current。六个 Skill 内容本身未变，继续通过绑定读取新 docs。差异与空白校验通过，推送结果以 Git 回执为准。
- 本轮为文档/图片变更，未重跑无关 GPU 实验或全量程序测试；没有新增实测资格、版本 tag 或上游依赖更新。

## 2026-10-11：全工程衔接审查与 0.6.0

- 主控检查执行/监测、热点与 TraceLens 证据、安装及知识维护入口；一名独立成员检查阶段协议、多 Agent 消息和结果依赖，修复后再次只读复核。
- 修复截断通信完整性、晚到阻塞返工、首次启动中断重入、上下文往返旧消息四项问题；新增13个参数化后的回归用例，相关132项通过，全量1167通过、4项Linux专用测试在Windows跳过。
- 流程图不标工程版本，修订分析/独立优化/全流程质量分流、TraceLens入口、监测时钟、状态交接与恢复资格。README、包元数据和changelog统一0.6.0；历史版本记录保留。
- 两套全新目录的合成演示完成；16张工程Mermaid成功渲染，PNG无版本，390个链接/锚点、489页/25来源Wiki及59阅读页/78可达页均通过。
- 系统Python editable升级0.6.0，六个系统Skill及绑定校验current；优化Skill已替换，其余保持当前。独立 --check 及 hcu-trainflow --version 确认一致。临时备份自动清理，新会话载入新版。
- sdist隔离与资产覆盖已包含在全量测试中。发布前origin/main为e8d7a43，v0.6.0不存在；提交、main推送与annotated tag的结果以Git远端回执为准。本轮未刷新外部来源或HCU大知识库、未运行远端训练、不新增硬件资格声明。


## 2026-10-11：减少重复审核与低效实验

- 完成两项程序修复与三个阶段/两个 Wiki Skill/主控的执行粒度修订；共享规则在 docs/collaboration.md，其余入口按职责引用。README、介绍与可编辑流程图同步，不新增阶段/状态机/依赖。
- 全量 CPU/本地协议回归 1175 passed、4 skipped（Windows 不具备的 Linux AF_UNIX/spawn）；之后新增团队范围变化的复用失效场景，最新定向 flow/Skill路由/团队审核61项全部通过，包含该新增用例。没有重跑无关硬件实验，也不新增 HCU 资格声明。
- 489页/25来源知识校验、59阅读页/78可达页检查通过；63份Markdown的394个链接/锚点和16张Mermaid解析/渲染通过。
- 系统Python editable 0.6.0与六个Codex Skill均完成替换，临时备份由安装器验证后清理；只读同步复核另行执行。无大知识库/上游来源更新，不改既有v0.6.0 tag；本轮改动记Unreleased。最终提交/推送以Git回执为准。

- 收尾统一文本换行后，安装哈希检查发现四个Skill副本需刷新；仅重装变化的Skill，独立sync --check确认包、六个Skill和资源绑定全部current。提交前差异无空白错误，既有v0.6.0保持不动。

## 2026-10-11：临时大文件维护与 0.6.1

- 已核对维护模块、CLI、测试和阶段引用；开始扩展临时产物生命周期与容量检查。没有操作真实训练数据。

- 扩展 register-temporary/retire/capacity 与阶段/低频 tick，复用 pin、活动保护、计划、隔离及部分失败回执。metadata-only 只用于关闭且退役的临时大文件，不宣称内容完整性。
- 根据用户补充将清理与五分钟交互彻底分开，持久6小时周期/1小时节点冷却；接回主控和三个阶段，明确本地/远端/CFS唯一责任人与无自动后台调度的边界。
- 全量回归最新一次1217 passed、4 skipped（Windows不具备的Linux专用测试）；随后补充原owner重新退役和明确零宽限收尾两项场景，最终定向结果另记。Wiki489页/25来源、阅读资源59页/78可达、395个Markdown链接/章节检查通过。没有改动模型执行/性能分析算法、没有删除真实任务数据或运行远端试验。

- 最终清理/生命周期/调度回归86项通过，涵盖复核后重新退役、零宽限收尾、不重读大文件、低空间与六小时去重；旧缓存兼容测试全部保留。README、包元数据、__version__和CHANGELOG统一0.6.1，包含此前未打tag的工作流效率改进。
- 系统Python editable升级0.6.1；主控和三个阶段Skill已替换，两个Wiki Skill仍current。六个绑定校验通过，临时备份由安装器验证后清理；独立--check和CLI版本检查通过。未升级外部依赖、未刷新大知识库，未添加新的常驻调度服务。
- 本地检查和远端main基线核对完成，准备推送main并在GitHub检查后发布annotated v0.6.1；远端回执由最终交付确认。

## 2026-10-11：Skill 名称、Wiki 生命周期与 0.6.2

- 已读现有元数据、两个 Wiki Skill、安装迁移/绑定校验和知识归属；准备保持六个工作流入口数量不变进行改名及衔接。

- 0.6.2：六个菜单名称与英文 ID 对齐，两个 Wiki 目录/引用/维护关联与旧名迁移完成。范围明确包含官方资料、通用站点经验、最终模型总结与受影响用法。新增非阻塞 knowledge_followup 提示及恢复去重记录规范，不改变训练 gates 或自动采集。
- README 增加九个详细任务/知识入口示例；知识验证 489 页/25 来源无错误，63 份文档的 403 个链接/锚点有效，16 张 Mermaid 渲染通过。正在执行全量回归和安装同步。

- 0.6.2 本地验收：1225 passed / 4 平台跳过；本机 editable 包 0.6.2 与六个 Skill 同步并 --check 为 current，旧 Wiki 名称迁移后无残留，临时备份按安装器验证规则清理。计划按 main 提交推送、远端 CI、annotated tag 顺序发布。未刷新官方上游/大知识库，未进行远端训练实验。

## 2026-10-12：能力说明补充

补齐 capabilities、Wiki 查询指南、两个 Wiki Skill：官方发布/规划和 SFT/RL 模型资料本地不足时按需查询官网/仓库页面，再追特性 PR、实际模型配置和底层源码。只完善查询与维护规则，未扩充知识正文或刷新大知识库。59 个资源页、489 份知识/25 个来源及 405 个文档链接检查通过。按现有安装同步协议提交 main，原版本标签不变。

## 2026-10-12：HCU-Knowledge 内部镜像安装入口

- thirdparty 清单与说明登记内部 GitLab 同步仓，GitHub 保持默认主来源；完整安装和定向 bootstrap 新增 `--knowledge-source gitlab`，仅影响新建 checkout。
- 修复来源校验只接受 GitHub 的限制：受管 checkout 和独立知识库绑定均接受两处登记来源，保留已有 origin、固定提交与本地修改，不自动降级或切换。
- 两边远端 main 均为 `bd33cae44563b80c75615f6f6de7f047c0298d83`，锁定提交 `80da7cef` 为其祖先。72 项依赖/安装回归通过，含本地 Git 实际检出、镜像绑定与来源保护；知识验证 489 页/25 来源、阅读资源 59 页/78 可达均无错误。
- 本机包与六个 TrainFlow Skill 同步并独立 `--check` 通过；未刷新知识库、未重下载 LFS、未重跑完整新机安装。版本保持 0.6.2，本轮不新增 tag。

## 2026-10-12：精度诊断补强

开始复核三阶段精度分支、质量契约、图表与安装路线；已读 HCU Probe 工程报告和 hook/首差专题。当前没有新现场精度实验，后续报告区分源码/方法/离线回归和硬件验证。

- 完成共用精度方法：实际初态/输入/并行语义、有 NV 分层对照、无 NV 独立参考、Probe 采集与首差判读、输出/梯度/更新、SFT/RL/视频及扩并行/保存恢复。主控、三阶段、更新 Skill、阅读图与维护关系均已衔接。
- 自查质量/阶段报告、训练日志、监控、资源与安装边界；沿用原运行门槛。新增方法不意味着 Probe 自动安装执行或全模型/后端实测通过，保留局部回归和阶段 loss 的节奏。
- 本地全量回归：1243 passed / 4 skipped；489 页知识与 25 来源、60 资源页/79 可达页均无错误；64 份文档的 421 处本地链接/锚点有效；17 张 Mermaid 渲染通过。demo 与 collaboration-demo 合成场景完成，不冒充 HCU 实验。
- 本机 editable 包 0.6.3 与六个 Skill 已同步；替换备份经安装器验证后清理。准备提交 main、核对远端 CI 后发布 annotated v0.6.3，结果以 Git 远端回执确认。不刷新大知识库、不启动现场训练。

## 2026-10-12：总览图轻量化与说明同步

- 更新首页位图及完整生成提示词，简化库列表，明确规模/长稳精度检查与训练引擎等改动的 PR 交付；README、介绍、工作流和详细图同步。
- 知识验证 489 页/25 来源无错误；阅读资源 60 页/79 可达页通过；64 份 Markdown 的 423 处本地链接/锚点有效；17 张 Mermaid 渲染成功。人工核对新图文字与阶段箭头。
- 本轮为图文调整，不改执行代码、不启动训练、不刷新知识库，不新增 tag；同步本机安装后提交推送 main。

- 本机 editable 包 0.6.3、六个 Skill 和资源绑定同步完成，独立 `--check` 返回 current；本地差异检查通过，远端 main 基线未变化。

- 文档范围检查发现递归 glob 会纳入上游 .claude 提示词，已逐文件移除本轮生成副本并登记永久排除，保留源码路径导航。首次 PowerShell 批量清理被自动策略阻止，改用明确文件路径的补丁删除成功，未修改上游参考 checkout。最终保留 64 份官方文档。

### TorchTitan 补充与发布检查

- 新增 15 页作者专题（含 WGRAD 累积、Attention Residual 融合、RL 权重同步三个案例）；保留 64 份官方教程、59 份 PR 原文/review/评论/diff、完整 1187 路径清单及官方 release 快照，登记 76 个监测文件。精读 PR 回执覆盖 12 项相关变更；其他 PR 保持 source-reported，未读源码路径没有标成全面复核。
- 核对了当前 recipe 目录、CLI、EP mesh、token 归一化、DistMuon、重算/graph 与 RL 状态；补充实际测试路径，并修正初稿中 RL wrapper 路径及两个暂存 helper 的旧名称。案例保留上游报告的退化、数值与未验证范围，不只摘取提速。
- 增量文档重跑：64 份发现/保留，0 新处理、0 pending、0 errors；同来源总览/专题/案例与五个维护入口完成联动复核。删除本轮重复采集且未被引用的 7 份公共 PR 中间副本，当前原件及私有采集证据保留。
- 102 项相关回归通过；628 页知识/26 来源、60 阅读资源页/81 可达页无错误，64 份描述/Skill Markdown 的 442 处链接/锚点有效。新 Wiki 作者页本地链接另由知识校验覆盖。
- 六类检索问题的预期页排在前两位；线上查到未收录 DistributedMuon PR #4105，读取完整 PR 到私有缓存并验证固定源码读取。首次搜索限定五项产生真实分页 partial，扩大到十项覆盖七个结果后完成，不将 partial 当作失败或全量结果。
- 系统 Python editable 包升级至 0.6.4，六个 Skill/引用绑定同步，独立 --check 为 current。未安装 TorchTitan、未执行其 CPU/GPU 测试或训练、未更新 HCU-Knowledge；本轮上游测试内容核对和 TrainFlow 工具回归分别记录。远端 main 基线为 2967a9a，准备提交推送并打 v0.6.4。
- Git 暂存检查发现上游 PR 评论自带行尾空格；保留原文和正文 hash，在 `.gitattributes` 仅对生成的 PR/官方文档页沿用原始证据的 whitespace 例外，作者文档仍照常检查。


## 2026-10-12：工作空间范围与 0.6.5

- 新增共用 workspace-boundaries 指南并贯穿六个入口、独立模式、成员交接、同步/输出、维护和交付；记录已有授权，不重复询问。版本准备升至 0.6.5。
- 源码传输增加真实路径预检；145 项传输/执行/清理回归通过，含 Windows 真 junction、悬空目标、暂存链接、父路径和普通嵌套目标。
- TraceLens 受管 worker 统一临时/绘图/转换缓存；46 项相关回归通过，真实 Python 子进程验证 tempfile 落点与 HOME/父环境保持不变。没有执行 GPU/远端训练。
- 阅读资源 61 页/82 可达、知识 628 页/26 来源验证通过；65 份文档/Skill 的 460 个本地链接/锚点有效。
- 初次追加计划补丁锚点未匹配，改用文件尾确切内容后成功；PowerShell 下 rg 路径通配不展开，后续使用目录与 -g 过滤。均未导致文件变更或证据丢失。

- 全量回归：1255 passed、4 skipped（保留平台限制，不冒充远端硬件验证）；文档增加契约边界说明后 65 页/461 处链接校验通过。此前 v0.6.4 的 Linux/Windows 3.10/3.12 CI 也已全部成功。
- 本机系统 Python editable 包已升级 0.6.5；六个工作流/Wiki Skill、引用与工程绑定同步完成，独立 --check 为 current。安装器只清理本次校验完成的临时备份，第三方依赖和 HCU 大知识库没有更新。
- 发布审查覆盖六入口、阶段/独立模式、协作交接、命令和源码传输、数值/性能判定的既有回归、长训观察及清理、Wiki 与安装同步；未新增状态门槛、不要求重验已匹配实验。本轮最终 Git 推送/tag 以远端回执确认。

2026-10-12：已建立均衡内容标准与检查器、跨引擎参考路由和最新 HCU 库归属。采集进程在新输入切换后退出，已确认无原进程，沿落盘的文档/PR游标续接；不将中断批次记为完成。

### 本轮进行中：统一内容粒度与来源刷新

- 新增九维作者内容规范、跨引擎参考/修改归属表、覆盖检查器及3项回归；README和搜索/更新Skill已接入。
- TE补RMSNorm→MXFP8和grouped低精度MLP案例；cuDNN补FlexAttention计划、Graph/NORM与稀疏API生命周期；TorchTitan复核EMA、MoE aux loss与RL请求故障。
- Cluster Manager实读当前hcu-cluster-run入口；补Train Simulator、Hyperloom和BBuf方法页。
- cuDNN main停在1.31.0 RC，develop为1.32.0开发且包含既有专题机制；已记录选线依据，改跟踪develop，部署版本仍需单独确认。
- 26个登记来源正进行全范围增量采集，未完成前不声明已全量刷新；采集原文不等于内容精读或硬件验证。
# 2026-10-12 前置影响检查补齐

按用户澄清先完成 HCU 大库更新影响检查：本机 11 个 Skill 的原安装无漂移，两个知识 Skill 与大库新版本一致；TrainFlow 大库锁滞后已修正。三个阶段的工具、依赖和能力变化已落实到环境、适配、通信/库调优、精度及恢复指南。后续继续合并作者 Wiki 深化和全源采集，最后统一验证、安装、提交及 tag；本轮没有硬件实测或大库写入。

## HCU alignment and balanced Wiki completion (2026-10-12)

- Completed read-only comparison with HCU-Knowledge 4596fd4 and installed Skill/dependency bindings. Updated only affected environment checks, adaptation, numerical contracts, math-library/communication integration and recovery guidance.
- Expanded every registered engine/library/ecosystem to the shared authoring dimensions and concrete mechanisms; 22 coverage groups / 27 sources. Added 37 authored/navigation pages and jointly reviewed 99 authored pages with 27 workflow targets. Fixed parent/child gitlink coverage, current branch labels, reference navigation and exact HCU RCCL ownership.
- Updated all registered source/document stages and completed all 25 PR queues after rate-limit recovery. Final public navigation has 3835 PR pages, 1211 document pages and 5179 total Markdown pages. These are retained sources, not counts of independently reviewed cases. Twenty-one directly cited PR conclusions were reviewed with 244 related-page bindings; uncurated files and discussions remain explicitly unreviewed.
- Full suite: 1262 passed / 4 platform skips; final data/integrity subset: 22 passed. Knowledge validation reports zero errors. Twenty-two representative engine/tool searches, cross-engine queries and six default-ranking checks find the intended explanations and source evidence. No new GPU/site qualification.
- Full setup preserved the external HCU-Knowledge checkout and current index, installed TrainFlow 0.6.6 and verified 11 required Skills. Local synchronization/check passed for the six TrainFlow Skills and package. Raw download caches, interim scripts and maintenance receipts remain ignored. Source/license notices accompany retained public documents.
- Ready to publish reviewed main and annotated v0.6.6; verify remote refs after push.
# Wiki layout migration (2026-10-12)

- Started ownership/path audit and persistent migration plan. No knowledge/source files moved yet; no HCU-Knowledge update or runtime dependency change requested.
- Completed project-first migration, consistent project navigation, ownership delegation, source/PR/doc path generators and persisted-path compatibility. Updated authored links, coverage, ledgers, source locks, README/docs and Skills. Removed only empty legacy directories after content migration; original official documents and PR JSON pass byte-level audit.
- Offline knowledge validation: 5,185 pages / 24 sources, zero errors. Coverage and Skill reading-route checks pass. Full initial suite: 1,268 passed, 4 platform skips; added review checks then passed 69 focused tests, with final whole-suite rerun underway. No new hardware qualification or broad online source acquisition.
- System Python package and six installed TrainFlow Skills synchronized to 0.6.7; bindings/resource checks pass. Official source ownership and external use contracts are separate; HCU-Knowledge checkout and source data are unchanged by this task. Publication of main and annotated v0.6.7 remains the final operation.
- Final review repaired relative `.` project handling in PR/document/catalog operations; real `wiki-catalog .` succeeds and remains idempotent. Final full suite after all fixes: 1,272 passed, 4 platform skips; knowledge validation 5,185 pages / 24 sources, coverage and Skill resource checks clear. System package/six Skills synchronized and checked again. Ready to push the reviewed commit and annotated v0.6.7, then verify remote refs.

## 2026-10-13: TraceLens parity task started
Read remote workflow, Wiki/Skill maintenance, repository instructions and existing qualification records. No active training dependency has been changed. Remote identity, occupancy and mounts will be rechecked before experiments.

Merged published HCU 30f5dcd then upstream 493f750 in development checkout, merge fda36c8 authored yuguo-Jack. Initial local collection failed because sparse checkout omitted scripts/examples; expanded required paths. SSH through jump-host nested SSH reuses existing internal host trust. HCU-Knowledge queried read-only; command entry is kb.py, not hcu-knowledge.

- TraceLens upstream merge and HCU fixes published as 22786b16d429783927981bd592a47ad0f79db3ba on the hcu branch with yuguo-Jack identity. Added standalone HCU README and reproducible qualification probes; native commands preserved.
- TrainFlow adds three managed native modes, source/shape/refresh handoffs, verified Hyperloom/GEAK references and expanded dependency maintenance paths. Pinned checkout and actual Python import now point to the published fork; six installed Skills/bindings verified at 0.6.8. No HCU-Knowledge source update occurred.
- Initial full TrainFlow run: 1,284 passed/4 skips with one packaging failure; corrected setuptools/metadata compatibility. Final rerun and publication checks follow.

- Final TrainFlow regression: 1,287 passed, 4 platform skips. All three new managed modes ran with real HCU traces against the published pin. Skill reading resources, six installed bindings and actual editable imports are current at 0.6.8. Dedicated remote validation containers stopped with no experiment processes remaining. Ready for main/v0.6.8 publication.

## 2026-10-13: Current Markdown consistency review

- Reviewed current root/docs/Skills/navigation against local code, installation and dependency contracts; repaired installation guidance, checker discovery, board interaction, navigation and ambiguous historical wording. Historical plans are explicitly separated from current instructions. No obsolete standalone page needed deletion after checking its purpose and incoming routes; retained upstream evidence and stable Wiki IDs keep their original identity.
- Added offline documentation checks to CI, full setup and local synchronization, with regressions for stale paths/anchors, examples, versions/names, attribution and stopping installation before package/Skill replacement. The checker also runs with `python -S`, confirming it needs no installed third-party Python package for first setup.
- Validation: 200 current authored Markdown pages, 68 CLI examples and 38 JSON examples pass; 5,185 knowledge pages / 24 sources pass validation; Wiki coverage and Skill reading routes pass. Full CPU suite: 1,298 passed, 4 platform skips. No new hardware or upstream-source qualification is implied.
- System Python package and six TrainFlow Skills synchronized and checked at 0.6.8; the Wiki/Skill update Skill now includes the documentation maintenance rules. Source docs are read from the bound checkout. The reviewed changes are ready for main publication under yuguo-Jack; this maintenance does not create another release tag.


## 2026-10-20 独立阶段二开始

HCU-Knowledge阶段已提交3829ef06、tag v0.5.6，两远端核对current且工作区干净；本阶段仅维护TrainFlow/Wiki及其选定安装。按AGENTS约定拆分适配/容量/精度和优化/通信/诊断两个互斥审查范围，主控负责官方来源与最终集成。写入映射和允许路径见task_plan，KB只读。

## 2026-11-05：模块化入口与本机依赖安装

- 用户已明确授权获取锁定 TraceLens、复用 `/home/cuda-optimized-skill`、安装 HCU-Knowledge 运行依赖，以及同步 `/root/.codex/skills`。本轮继续已有模块化工作，不覆盖未提交改动。
- 写入范围：本项目 `/home/HCU-TrainFlow`（含 `.work/setup`、下载缓存和受管 `thirdparty/TraceLens`）；当前 Python `/usr/local/bin/python` 的安装位置 `/usr/local/lib/python3.10/site-packages` 及 `/usr/local/bin` 中相应包入口；`/home/hcu-knowledge` 仅允许安装元数据和必要的本机派生索引；`/root/.codex/skills` 仅安装工具管理的 11 个 Skill 及绑定。安装器需要时保留 `/root/.codex/trainflow-skill-backups` 下本次替换备份，通过验收后仅清理本次备份。
- `/home/cuda-optimized-skill` 作为只读外部输入；不更新两个外部仓的 Git 提交或知识正文。Python 包可卸载/重新绑定；Skill 替换失败保留备份。既有 checkout 和历史备份均保留。
- TraceLens checkout 已完成，锁定提交 `22786b16d429783927981bd592a47ad0f79db3ba`，工作树干净，无运行中的 checkout 或 Git 锁。下方记录实际安装与验收结果。
- Python 包安装完成，`pip check` 通过，96 项依赖/安装回归通过。知识库首次 bootstrap 发现 LFS 指针尚未恢复且本机缺 Git LFS；安装所需 Git LFS 官方独立二进制到 `/usr/local/bin/git-lfs`（该路径原先不存在），下载与校验记录留在本项目 `.work/setup`。知识库额外安装写入包括其 `.git/config`、标准 LFS hooks、`.git/lfs` 和当前提交指针对应的 `materials/`、`evidence/` 原始字节，仅恢复固定对象，不更改知识内容或提交。此项是用户已授权完整本机安装的必要前置；不更新远端知识或切换版本。
- Git LFS v3.8.1 二进制已按官方发布的 SHA-256 校验，知识库局部 LFS 初始化完成。原件恢复失败：当前 origin 的 LFS 端点没有可用 Git 凭据；1,255 个文件仍为指针（1,209 个唯一对象，约 6.35 GB）。完整 setup 回执保持 incomplete，已请求用户配置凭据或提供已有完整副本，不复制任何未验证的知识数据。
- 独立安装六个 TrainFlow Skill 和三个 Hygon Skill，后者由只读源仓的官方安装器执行，备份/哈希清单保存在本项目 `.work/setup/kernel-skill-backups`；两项 HCU-Knowledge Skill 仍等待 doctor 就绪。六个 TrainFlow Skill 的本机同步完成，包、文件和绑定验收通过；TraceLens 报告 CLI 帮助可运行。
- 最终 CPU 回归 1368 passed / 3 skipped（513.66 秒）；知识校验 22185 页 / 24 来源 / 零错误，206 页文档和阅读资源检查通过；编译与差异空白检查通过。同步及独立 `--check` 均返回 current，三个 Hygon Skill 文件树与所绑定源仓哈希完全相同。完整安装与九个独立入口的状态分别记录在 `.work/setup/status.json`、`.work/setup/installation-review.json`，没有将 checkout ready 或 CPU 回归当成完整知识检索/硬件验收。pytest 自动分配的 `/tmp/pytest-of-root/pytest-13` 仅作本轮测试临时产物，未清理其他测试目录。
- 真实 doctor：missing_packages 为空，index_ready/index_current/local_ready 均为 false，仅报告 LFS 原件未恢复。无仍在运行的安装、LFS 下载或测试进程；等待用户提供现有凭据配置或完整副本路径后，可重跑原完整安装命令并验收全部 11 个 Skill。
- 用户随后明确选择自己的 GitLab fork，重新克隆到同一路径 `/home/hcu-knowledge`。已核对新 origin 为 `http://42.228.13.241:10068/xuxc/hcu-knowledge.git`，HEAD 仍为锁定的 `c08470f7c1032f8ad9f072a161c687d2a6b50a3b`、工作树干净。沿用安装写入范围，按用户选择记录本机 fork 来源；不修改公共来源清单，不切换或更新知识提交。下载认证仅通过进程内存及任务私有凭据缓存 socket 传递，缓存结束后清除，日志/源码/配置均不保存令牌。
- fork LFS 实测认证通过，1209 个唯一对象（6353879284 字节）全部下载完成，1255 个工作树文件均已恢复；缺失/指针计数均为零，临时凭据 socket 已关闭。新增 `--bind-origin` 及本机 `external_sources` 记录，批准仅适用选定路径，拒绝凭据 URL、未知来源变更和无法证明包含锁定提交的 fork；106 项相关回归通过，206 页文档与 Skill 阅读资源检查通过。
- fork 知识库本机 bootstrap 的解析快照恢复和全量原件/证据校验已通过，正在构建本地索引。项目完整回归与 Wiki 校验同时执行；原先缺凭据的阻塞已解除，最终 11 个 Skill 安装等待索引构建成功。
- 本机索引构建及完整性检查成功，29497 条资料 / 932404 个分块；doctor 的 local_ready/index_ready/index_current 均为 true，snapshot_mode=current，errors 为空。真实 `RCCL topology` 本地查询返回 3 条相关结果。完整 setup 复用当前索引、安装所选三个 Python 包并补齐两个知识库 Skill，11 个 Skill 和绑定全部验证通过，完整 setup 状态为 ready。
- fork 来源机制最终全量回归 1378 passed / 3 skipped（537.99 秒）；Wiki 校验 22185 页 / 24 来源 / 零错误，206 页文档与 Skill 阅读资源检查通过。准备执行最后本机同步、独立检查和安装回执更新。
- 最终安装验收完成：全部 11 个 Skill 独立 `--check` 为 current，六个 TrainFlow Skill 与 editable 包同步及独立 `--check` 为 current。`pip check` 通过，三个包均从预期 checkout 导入；知识 fork、cuda-optimized-skill 和 TraceLens 的 HEAD 保持原锁定值且工作树干净。本轮生成的 28 个安装文件/日志及本机绑定、知识仓 Git 配置检查未发现令牌内容，临时凭据 socket 已关闭。安装回执 `.work/setup/installation-review.json` 更新为 ready，无待装 Skill 或未解决阻塞。

## 2026-11-05：第二阶段实施中

已开始提取公共 RuntimeService 与独立 Store run，增加输入/文件指纹、缓存证据检查、阻塞/中断记录和显式输出 bindings；场景能力及硬件资格准备在独立编辑范围并行。当前硬件准入被现场占用及进程覆盖缺口阻塞。

第二阶段实现及软件演示完成。相关领域回归255项通过，最终模块回归63项通过（含后续补充的真实CPU命令JSON到质量验收绑定、并发运行锁、CLI非零blocked状态和请求原件追溯）。固定TraceLens实际生成10张报表；三场景独立调用与组合、CLI/Python观察一致、显式resume的artifact一致均通过。合成loss/timing/Trace不代表硬件。Wiki校验22185页/24来源零错误，文档206页无问题，阅读资源通过。所选包和六个Skill同步及独立check均current；外部三个checkout保持干净。全量测试正在执行，最终结果另记。HIP gfx936编译通过，设备负载因资源/进程证据不足保持blocked。

第二阶段最终验收：全量1428 passed / 3 skipped（512.51秒）；全量收集后补充的最终模块回归63 passed（2.01秒），覆盖最终请求artifact、blocked退出码、CPU命令到质量验收绑定与并发排斥。pip check与git diff --check通过。软件总体pass；HIP主动执行blocked，真实训练not-validated。汇总回执`.work/modular-phase2/verification.json`；本机包与六个Skill同步及独立验收current，三个外部checkout均保持干净。未提交或推送本轮及之前未提交改动。

## 2026-11-06：真实基线 Pipeline 闭环

- 用户要求先完成工作流闭环；本轮单主控，未启动成员或模型优化。新增输出封存、Megatron 日志摘要、hipprof capability 接入、显式 baseline qualification 和通用八步 Pipeline 生成器；公共 RuntimeService 继续负责运行身份、持久化、恢复和报告。
- 新 Lane C 独立目录/Store/输出/缓存使用冻结源码与重新核验的输入，实际完成完整 Qwen3-8B 8 卡 100 iteration 和独立 6-step Trace。训练与 Trace 各仅启动一次；A/B 日志、Trace、缓存和 Store 不作为新结果输入，也未被修改。
- 稳态 iteration 3–100：8.614043 秒/步，3804.021 token/s/GPU；三段连续窗口均值相对差异 0.1507%，skipped/NaN 为 0，末尾验证/测试完成。只授予短基线资格，optimization_validated=false、stage_eligible=false、model_diagnosis=incomplete。
- 现场依次暴露 ip 命令缺失、MPI 退出早于显存释放、hipprof DB 父进程 PID 不等于实际 rank PID，均保留失败 run 后修复。更改 operation/输入生成新 run，成功训练由原 immutable operation 重放，已完成 Trace 由远端退出回执重放，没有重新占卡。最终同 run 显式 resume 通过，原始证据与当前三种报告一致，Flow 未自动推进。
- 新训练摘要、分析摘要与 qualification 独立调用和串联输出完全一致，独立调用不发布任务报告。16 项真实运行审计全部通过；交接等待的 3 项任务内 CPU 回归通过。8 卡已释放至空闲显存基线。
- 全量软件回归 1443 passed / 3 skipped（502.05秒）；知识校验 22185 页 / 24 来源零错误，206 页文档及 66 页 Skill 阅读资源检查通过。性能训练与 Trace 期间暂停重型 CPU 回归，避免同宿主机干扰；安装同步进行中。
- 未完成项保留：完整模型窗口/shape/phase/source/跨 rank 归因、固定 TraceLens 原生 CSV 单位问题、resume 对纯离线分析的过度失效，以及训练 checkpoint 恢复/扩容/长稳。任务总览为 `.work/qwen3-8b-workflow/lane-c-pipeline-closed-loop/CLOSED_LOOP.md`，审计与 gap 矩阵均留任务 workspace，不发布公共知识库。
- 最终安装同步及独立 --check 均 current（选定 editable 包及六个 TrainFlow Skill/绑定）；pip check、差异空白检查及安装后新增能力导入通过。通用生成器与安装后的 pipeline-plan 实际验证通过，没有额外 GPU 执行。完整回执 `software-verification.json` 为 pass；本轮基线 Pipeline 闭环完成，原工作树改动保留，未提交或推送。

## 2026-11-16：自主模式（无人工通道）

- 用户要求整个流程无人接入。实现方式是替换"决策来源"而不是放宽门禁：TaskSpec 新增封闭 `autonomy` 策略；自主任务里原本返回 `human` 的等待点改为 `halt`，采集到的指导以 `autonomy-policy` 身份记为 advisory，不冒充人的决定。
- 新增 `flow.resolve_question` / `flow-question-resolve`：自主任务用自己的决议（answer/source/note）关闭问题，留存策略指纹与事件；只解除问题，不触碰报告、复核、证据与预算。
- 新增 `autopilot.drive` / `flow-drive`：有界循环自动执行 `advance`，把 work/repair/review 交回主控；`halt` 去重记录 `flow-halted` 并以退出码 2 收口；`stop_report` 留存停机回执；`guard_execution` 在 halt 下拒绝继续派发命令。
- 门禁未放宽：复核身份必须来自声明的 reviewer 池；缺报告仍为 needs-repair/repair；自主策略不能把缺失或 incomplete 证据变成 pass（均有回归覆盖）。
- 验证：新增 26 项自主模式回归（spec 校验、指导 advisory、声明答案与 Agent 决议、review 池、复核失败/轮次预算 halt、drive 自动推进、halt 退出码、stop_report）；全量回归 1469 passed / 3 skipped（513.00 秒）；206 页文档与 66 页 Skill 阅读资源检查 current；CLI 端到端冒烟确认 work 退出 0、halt 退出 2。
- 未完成项：真实硬件上的无人值守整链验收（需真实训练/Trace 证据与站点授权）；候选生产与 review 委派仍由主控 Agent 承担，未脚本化为仓库内 worker。原工作树改动保留，未提交或推送。

## 2026-11-16：自主自救（降级、预算、验收）

- 目标：用户只在创建任务时给一次输入，技术性失败由 Agent 自己闭环。
- `spec.autonomy.escalation.degrade_ladder`：预先声明允许的降级动作与下限（微批下限、重算模式、可调并行维度、层数下限与代理缺口、checkpoint 恢复次数）；`flow-degrade` 按边界执行并留存 `autonomy-degradation` 原件与 `flow-degraded` 事件，阶梯用尽才 halt。
- `spec.autonomy.escalation.budget_extension`：每次追加上限 + 追加次数 + 硬总上限；新增 `budget_extensions` 账本表，执行层与命令组改按 `Store.effective_budget` 判定，`budget-extend` 只能支取已授权 headroom，超硬顶/超次数即拒。
- `spec.autonomy.escalation.acceptance_edit`（默认 forbid，可 add-only）：自主任务重规划不得修改或删除既有验收条款，放宽目标必须新建任务。
- 修复上轮遗留缺陷：带 `report_kind` 的步骤没有证据时不再抛异常中断整次运行，改为跳过并记录 `pipeline-report-skipped`。
- 验证：新增 18 项策略/降级/预算/验收回归 + 1 项 report_kind 回归；全量 1488 passed / 3 skipped（500.39 秒）；文档 206 页与 Skill 资源 current；CLI 冒烟确认降级计数、预算追加生效、放宽验收被拒。
- 仍不自动化：场地/设备授权、新增权限、真实硬件整链验收，以及"目标本身达不到"的负结果判定。

## 2026-11-16：无人值守工程补齐（worker、生成器、告警）

- ① worker 契约：`autopilot.drive(worker=...)` 接受 `work(store,tid,decision)`/`review(store,tid,decision)`；CLI `flow-drive --worker module:factory`。返回 `None`→`worker-declined`；抛 `autopilot.Handoff`→停机并保留原因；其他异常记 `worker-error` 并在 `--max-worker-errors` 次后停机；候选反复被 gate 拒记 `repair-not-converging`。worker 只准备文档，校验仍由 `flow.submit`/`flow.review` 完成。
- ② 站点契约生成器：`scripts/build_autonomous_task.py` + `examples/autonomous-site.json`。一次输入（task/autonomy/plan/site）写出 task.json、plan.json、admission.json、cards/*.json；`admission.context` 由任务 context 派生，命令卡用真实执行契约校验，lease 必须匹配准入设备，输出目录非空即拒绝覆盖；`flow.validate_plan` 抽为共用校验供生成器与 flow-start 使用。
- ③ 停机告警接线：`flow-halted` 以 `channel=agent` 进入既有 outbox，新增 `autopilot.halts()` 与 CLI `halt-list`（有待处理项退出码 2），可用既有 `inbox claim/complete` 销账；重复同一停机原因不重复刷事件。
- 文档：新增 `docs/autonomous-task.md`（一次性输入、生成器、worker 契约、halt 处置矩阵、告警、验证边界），并在 quickstart、collaboration、examples/README 建立入口。
- 验证：新增 20 项回归（6 worker + 14 生成器），全量 1508 passed / 3 skipped（501.24 秒）；文档 207 页 / 92 CLI 示例与 Skill 资源 current；CLI 冒烟跑通"模板→bundle→task-create→flow-start→flow-drive(work)→halt-list(pass)"。
- 仍未验证：真实硬件整链无人值守（需现场授权与真实训练/Trace 证据）。
- ④ halt 选项菜单：`flow.halt_options` 让 halt 判定直接携带 `options`——可用降级动作（含 `used` 次数）、`budget_extension`（剩余次数/每次上限/距硬顶额度，用尽为 null）、可自决的阻塞问题、必须升级的四类（授权/验收放宽/负结果/取消）。`flow-drive` 结果同样携带；Agent 据此自决，不再需要人工维护"预期 halt 清单"文档。新增 4 项回归，全量 1512 passed / 3 skipped（514.63 秒）；文档 207 页 / 40 JSON 示例 current；本机安装同步并独立 --check current。

## 2026-11-16：模块化与子工作流设计定稿

- 评审通过并落稿 `docs/workflow-modules.md`：20 个模块（环境资源 3／执行产物 4／训练质量 6／性能分析 4／优化 3）、契约字段（requires/provides/report/stage/role/tags/volatile/route）、别名与 preset、7 条门禁派生规则、3 个首批 profile 与路由规则、6 条护栏、B1–B4 批次与验收判据。
- 关键决定：报告种类维持 7 类不变；`optimization-change`/`baseline-qualification`/`profile-summary` 为证据而非门禁；`stage-quality`/`scale`/`completion` 属 Agent 撰写报告，派生必须显式并集；profile 文档禁止 `reports`/`gates`/`reading`；`profiling.plan` 并入 `profiling.trace`；`execution.stdout-json` 与 `resource.lease` 独立成册；优化族三项只产证据、不产结论。
- B1 范围同时包含门禁派生与 `profile-resolve` 骨架，确保第二步"分流 + 串起来"不需重摸契约。
- 校验：`check_documentation` 208 页 / 42 JSON 示例 0 issues；`check_skill_resources` current；本机安装同步及独立 `--check` current。本轮仅文档改动，未改代码。

## 2026-11-16：模块化落地（B1–B4）

- `catalog/` 成为目录唯一来源：`contracts.py`（闭合词表 + `Module`/`Profile` 构造即校验 + profile 拒绝 `reports`/`gates`/`reading`）、`registry.py`（20 模块、6 个别名、4 个 preset、实现映射）、`gates.py`（7 条派生规则 + `missing_producers`）、`profiles.py`（3 profile + 确定性路由 + 阅读面统计）、`plan.py`（自动接线、静态校验、preset 模板展开）。
- 门禁派生与现状对齐：`llm-megatron` 派生结果按目标阶段与 `flow.GATES` 逐项相等，由回归锁死；`stage-quality`/`scale`/`completion` 作为 Agent 撰写报告显式并集；`baseline-qualification`/`profile-summary`/`optimization-change` 派生时一律过滤。
- 修正设计稿两处事实错误：①"vision profile 无 scale"会砍掉训练准入证据，改为"分流只瘦模块、不瘦门禁"；②`profiling.tracelens` preset 原方案重复插入 `artifact.collect`，实际采集与封存已在 `profiling.trace` 内完成。
- 接线规则可验证：同名 + 类型匹配 + 唯一提供者才自动绑定；多候选/缺失/越界/`needs` 未满足/阶段证据被裁/未实现全部落到 `problems.kind`，`module-run` 在 `status!=pass` 时拒绝执行。
- 新增 capability 均为确定性记账并声明边界：`execution.stdout-json`（非 JSON → incomplete）、`resource.lease`、`source.transfer`、`profiling.communication`（只做声明区间并集/重叠）、`optimization.change`（记录 diff 与回退，不判断该不该做）、`optimization.benchmark`（同 shape 隔离对照，明说不是净收益）、`optimization.netgain`（含启动步的净收益 + 噪声门槛，且要求真实证据 ID 否则 incomplete）。
- `baseline-pipeline` 转为声明式 preset，`services.baseline_pipeline` 委托同一份接线；历史 8 步由 `tests/test_module_plan.py` 逐项锁定，避免二次实现漂移。
- `RuntimeService.run_pipeline` 新增可选 `volatile_steps`：模块声明的 volatile 覆盖旧白名单；不传时行为不变，并有测试证明"未声明可复用、已声明必重跑"。
- 文档与示例：`docs/workflow-modules.md` 改为实现态并补命令用法；modular-architecture/architecture 更新入口；新增 `examples/module-plan.json` 并在 examples/README 建立入口。
- 验证：新增 36 项回归（目录 19、计划 11、运行 6）；全量 1548 passed / 3 skipped（507.57 秒）；`check_documentation` 208 页 / 102 CLI 示例 / 43 JSON 示例 0 issues；`check_skill_resources` current；本机安装同步并独立 `--check` current。
- 仍未验证：真实硬件上的子工作流整链（缺现场授权与真实训练/Trace 证据）；`profiling.communication`/`optimization.*` 从真实 profiler 输出到契约输入的适配器仍需按站点补齐。

## 2026-11-17：第三个子工作流 `torch-native-llm`（B5）

- 新增能力 `training.summarize-torch`（模块 9）：纯 torch 训练没有通用日志格式，因此由任务契约显式声明 `log_format`——`jsonl`（每行一个对象，可选 `meta`/`evaluation` 记录，字段名可配）或 `pattern`（单条正则，必须含 `step`/`loss` 命名组）。输出与 Megatron 摘要同一 schema（`scope=fresh-short-baseline`、`executed`、`failures`、`required_missing`、`steady`、`evidence`），所以 `quality.qualify` 与 `baseline` 门禁无需改动。
- 诚实边界：不匹配/非 JSON 行计入 `unparsable-log-lines`，不静默丢弃；`pattern` 模式没有 meta 记录，无法证明从零初始化与 profiler 关闭，摘要保留 `false` 并记入 `required_missing`——这类摘要能看 step 与耗时，但不能当成 `baseline` 通过证据。
- 目录规则修正：报告唯一性从"全局唯一"细化为"同一引擎唯一"。`baseline` 现有两个产出者（`training.summarize` engine=megatron、`training.summarize-torch` engine=torch），标签互斥保证任何一次运行都不会同时需要两者；profile 内仍禁止两个同报告产出者（`_module_list` 报 `conflicting report producers`）。
- profile 调整：新增 `torch-native-llm`（20 模块，全阶段，门禁与 `llm-megatron` 相同）；`torch-native-vision` 改用 torch 摘要（ResNet 日志不是 Megatron 格式）；`analysis-only` 去掉日志摘要，变为 7 个与引擎无关的只读模块，阅读面 6/17 ≈ 0.353。
- 路由闭环：`{"engine":"torch","model_family":"llm"}` 此前是 `halt: profile-unknown`，现在唯一命中 `torch-native-llm`。
- 文档：`docs/workflow-modules.md` 更新为 21 模块 / 4 profile / B1–B5 完成，并新增 §14 说明 B6（把 profile 真正接进任务的 `required_reports` 与按阶段模块子集）；`docs/training-state-validation.md` 补"纯 torch 训练日志的声明格式"。
- 验证：新增 9 项回归（torch 摘要 6、profile/路由 2、module-run 1）；全量 1557 passed / 3 skipped（505.06 秒）；文档 208 页 / 102 CLI 示例 / 43 JSON 示例 0 issues；CLI 冒烟确认四个 profile 的模块数/阅读面/派生门禁与 torch-llm 路由结果。
- 仍未验证：真实 torch 模型日志现场适配（当前只用合成日志证明解析契约）；B6 的门禁接线未做，分流目前仍是计划层建议。

## 2026-11-17：功能子工作流层（模块 → 子工作流 → profile）

- 用户指出"子工作流不一定是完整流程，可以是几个模块集成的整体功能（适配、分析等）"。据此把原来的 `preset` 提升为独立的**功能子工作流**层，结构变为三层：21 模块 → 15 子工作流 → 4 流程 profile。
- `catalog/contracts.py` 新增 `Subworkflow`（id/summary/modules/kind/template/bundled/notes），**不声明 stages、不派生门禁**；`kind=composition` 自动连线，`kind=template` 保留固定接线（`baseline-pipeline`、`profiling-tracelens`）。
- `catalog/plan.py` 新增 `interface(modules)`：`requires` = 成员 require 里没有内部提供者的部分（同名同类型，含 `a|b` 可替代类型），`provides` = 成员 provides 并集，外加 `reports`。CLI `subworkflow-list` 直接输出这份接口。
- 自动连线补 `"*": "<type>"` 约定：模块声明整体结果类型（`execution.command` → `capability-result`），消费方以路径 `[]` 绑定。于是 `baseline-megatron` 这类组合能自动接成 `execution.command → training.summarize`，不用手写绑定。
- `Profile` 支持 `subworkflows`（组合）或 `modules`（直接列，二者互斥）。四个 profile 改为引用子工作流，`module_ids()` 展开去重；`analysis-only` 仍用显式模块列表（没有成对功能组合）。
- 兼容：旧 preset 名 `quality.accept/assess`、`profiling.tracelens`、`environment.collect` 通过 `SUBWORKFLOW_ALIASES` 继续可用；`presets()`/`preset_plan()`/`preset()` 保留为别名，文档里的 `"preset"` 键仍解析。
- 校验：子工作流内不得有两个同报告产出者（`validate_subworkflow`），未注册模块、越界模板步骤、`kind=composition` 却带模板都会被拒。
- 验证：新增 12 项回归（接口推导、自动连线、模板接线、报告冲突、profile 组合、`module-run` 跑通 `quality-accept`）；全量回归见下条；`check_documentation` 208 页 / 104 CLI 示例 0 issues。
- 文档：`workflow-modules.md` §5 重写为三层模型与 15 个子工作流接口表，§7/§9 更新为 `subworkflows` 与 `subworkflow-list`；modular-architecture 与 examples/README 补入口。

## 2026-11-17：第 2 步——适配模块与 `adaptation` 子工作流

- 新增 3 个适配模块（22–24），全部只做确定性核对、只产证据型报告，**不进任何阶段门禁**：
  - `adaptation.launch-parity`（`adaptation-parity`）：上游 `argv`/`env`/`config` 每个元素都要有带 `basis` 的映射；未映射、空依据、重复目标、映射源/目标不在对应记录里都进 `required_missing`。HCU 独有要素作为 `unmapped_hcu` 列出。
  - `adaptation.config-diff`（`adaptation-diff`）：记录增/删/改并保留自身原件；`basis` 里出现未改动的 key 直接报错；无依据的改动进 `unexplained` → `incomplete`。
  - `adaptation.numeric-equivalence`（`adaptation-numerics`）：按契约逐组件比较，输出 `max_abs_diff`/`max_rel_diff`/容差判定，显式 `stage_equivalent=false`；缺组件、长度不一致、非法数值进 `required_missing`。
- 证据类型从 3 个扩到 6 个（新增三种 `adaptation-*`），仍在 `EVIDENCE_REPORTS`（门禁派生时过滤），目录校验不受影响。
- 新子工作流 `adaptation` = 启动映射 + 配置差异 + 组件数值；`adaptation-proxy`（缩层代理）保持独立，两处按需组合。三个 profile 都挂上 `adaptation`（llm 23 / torch-llm 23 / vision 19 个模块）。
- `module-plan`/`module-run` 新增 `step_inputs`：运行输入默认共享给所有步骤，两个模块要同名不同值时用 `<module>.<input>` 单独播种（例如 diff 的 `baseline` 与数值对照的 `baseline`）。键格式非法即报错。
- 文档：模块表 +3、子工作流表 +1、证据类型说明、`step_inputs` 用法与共享输入注意事项、阅读面数字（analysis-only 6/18 ≈ 0.33）；三个模块各自的 route 页各补一节说明模块边界。
- 验证：新增 9 项回归；全量 **1578 passed / 3 skipped**（520.57 秒）；文档 208 页 / 104 CLI 示例 / 44 JSON 示例 0 issues；Skill 资源 current；本机安装同步并独立 `--check` current。

## 2026-11-17：第 3 步——把 profile 接进任务（B6，adapt 阶段接线）

- `spec.profile`：`{id, reason}` 二者必填、字段封闭；`flow-start`/`flow-replan` 校验 profile 存在且与任务 context 的 engine/model_family/mode 不冲突（`catalog.resolve_profile` 复用同一套路由规则），冲突即拒绝启动。选择 profile 不推进任何阶段。
- `flow.required_reports` 按 profile 派生：取 `catalog.derived_gates(profile)`；**profile 未覆盖的目标阶段回落全量 `flow.GATES`**（fail-closed），派生结果若比全量更宽直接抛错。因此分流只能减模块，不会减掉仍在范围阶段的证据；`llm-megatron` 派生 == 现状，行为零变化（回归锁死）。
- `flow.next_step` 的判定新增 `profile` 与 `expected_evidence`：后者列出该阶段应产出的**非门禁**证据（短基线资格、profile 摘要、改动记录、适配三件套），只是提示、不进 `required_reports`、不阻挡推进。
- `module-plan --stage <stage>`：只保留 `stage` 含该阶段的模块，`name` 追加 `:stage-<s>`，输出可直接 `module-run`。`--stage prepared` 就是 adapt 阶段的模块集：环境就绪 3 + 执行 3 + 适配三件套，门禁只有 `environment`，三份适配证据以 `evidence_reports` 形式并列。
- 适配模块的 `stage` 从 `environment_checked` 移到 `prepared`——适配工作发生在 adapt 阶段（state=prepared，推进到 environment_checked），证据型报告不参与门禁派生，所以移动不影响任何门禁。
- 生成器 `scripts/build_autonomous_task.py` 的 `TASK_KEYS` 增加 `profile`，自主任务也能声明子工作流。
- 文档：`contracts.md`（TaskSpec.profile）、`collaboration.md`（required_reports 与 expected_evidence）、`workflow-modules.md` §9/§11/§14、`autonomous-task.md`（可选 profile）。
- 验证：新增 9 项回归；全量 **1587 passed / 3 skipped**（507.57 秒）；受影响子集 147 项通过；文档 208 页 / 106 CLI 示例 / 44 JSON 示例 0 issues；Skill 资源 current；本机安装同步并独立 `--check` current；CLI 冒烟确认 `flow-next` 返回 profile、门禁 `environment` 与适配 `expected_evidence`。

## 2026-11-17：抗幻觉/抗漂移加固（先度量，再改）

- **先做度量**：`tests/test_integrity_guardrails.py` 用真实 Store 回放 7 类注入故障——借用他任务证据、跳过阶段的结论、超范围快照、数值改一位、profile 任务无 claims 的 pass、缺 brief、自主任务缺 turn 锚定。改前 **0/7 被拦**（全部静默通过），改后 **7/7**。
- **证据归属**：`Store.artifact_tasks()` 从 events / pipeline_steps / operations 归因；`report-add` 拒绝只属于其他任务的私有对象，`public` 对象仍可作共享基线（跨任务共用不误伤）。登记报告时写 `artifact-claimed` 事件，为下一次借用留下可查记录。
- **claims**：报告新增封闭字段 `claims`，机械校验四类——引用（对象存在且归属本任务）、数值（按 `source.path` 取原值比对，1e-9 相对容差，布尔不与数字互通）、流程（`stage` 必须在 profile 覆盖范围内）、范围（`candidate_snapshot` 必须与报告一致）。profile 任务的 Agent 撰写 pass 报告**必须**带 claims；capability/Pipeline 自算报告（`agent_authored=false`）不强制，但写出的 claims 照旧校验。`report-verify TASK KIND` 可事后重跑，不改状态。
- **状态锚点**：`flow-brief` 由 Store 拼装一页摘要（目标/验收指纹、`invariants`、candidate 快照、可用证据、未决问题、预算与降级剩余、最近事件、阅读入口）并返回 `brief_hash`；`--notes` 只作附注，不参与任何判定。`flow-submit`/`report-add` 带 `--brief-hash` 绑定状态，过期即 `stale-brief`；自主任务提交缺哈希为 `unverified-turn`，`autopilot.drive` 每轮重新取哈希后再提交。
- **漂移对账**：`flow-next` 每次重发 `invariants`（门禁、acceptance_edit 策略、预算硬顶、review 必需），不复用会话里的旧值；`flow-align` 对照存储 plan 输出 delta（验收/目标自起始改变、profile 与 context 不再匹配、阶段超出 profile、门禁被放宽），有 delta 记 `flow-aligned` 事件并要求 `flow-replan` 留理由。
- **交接协议**：`agent-send` 的 handoff 必须带 `{brief_hash, evidence_ids, open_questions}`，`evidence_ids ⊆ evidence`，用状态而不是叙述交接。
- 文档：`contracts.md`（ReportEnvelope.claims、StateBrief 与 turn 绑定）、`collaboration.md`（命令表 + 每轮的状态锚点）、`workflow-modules.md` §10 护栏表 +5 行、协调器 `SKILL.md`（每轮先读 brief、数字写 claims）。
- 验证：新增 23 项回归；全量 **1610 passed / 3 skipped**（516.22 秒）；`validate_knowledge` 22185 页 / 24 来源 / 0 errors；文档 208 页 / 107 CLI 示例 / 44 JSON 示例 0 issues；Skill 资源 current；本机安装同步后独立 `--check` current。

## 2026-11-17：用真实历史数据验证护栏（精度审计）

- 新增 `scripts/audit_report_history.py`：以 `mode=ro` 只读打开 store，用与写入路径同一套 `integrity` 检查重验已登记报告；大对象只核存在与大小，不重复摘要。
- **精度（误报）**：对 5 个真实 store（Qwen3 工作流各 lane）共 **17 份真实报告、5 个真实任务**审计，**0 条被误判**。旧任务未声明 profile，claims 不强制，因此这一轮验证的是"新规则不误伤历史结论"。
- **覆盖面（真问题）**：同一批 store 里有 **178 条证据处于无主状态**（73/35/4/63/3）。原因是报告写在归属机制之前，`artifact-claimed` 事件不存在。用真实 store 复本做"第二任务借真实证据"的回放：**第一次竟然通过了**——借用检查对旧数据完全是空的。
- 补 `evidence-backfill [TASK]`：从已登记报告正文回填归属事件，幂等；回填后同一回放变为 `Evidence ... belongs to another task`。审计脚本同时报告每个 store 的无主证据数，便于判断是否要先回填。
- 顺带修正 brief 哈希口径：只对"决定下一步动作"的字段取指纹（目标、验收、context、state/revision、profile、invariants、候选、未决问题、预算、降级），不含证据清单与最近事件尾部——否则每写一份报告都会挪动哈希，把正常步骤变成误报的 `stale-brief`。新增两条回归：同状态同哈希、读 brief 不改哈希、重规划必变。
- 验证：全量 **1612 passed / 3 skipped**（525.71 秒）；文档 208 页 0 issues；Skill 资源 current；本机安装同步后 `--check` current。

## 2026-11-17：验证第二轮（重放 / 影子 / 性能 / 残余风险）

- **1 决策重放**：新增 `scripts/replay_flow_decisions.py`，在 store 副本上重放历史——每条 `state-changed` 是否仍合法、无 profile 任务的 `required_reports` 是否仍等于 `flow.GATES`、`brief_token` 是否稳定、`flow-align` 是否干净。真实 5 个 store：2 个有 flow 的任务（profiling / optimizing）**9/9 迁移合法、gates_match=True、brief_stable=True、align=aligned**，另 3 个 draft 任务未挂 flow，跳过。配套新增 `tests/test_flow_machine_contract.py`，把 `NEXT`/`PIPELINE`/`GATES`/`llm-megatron` 派生门禁/`AGENT_AUTHORED` 的黄金值锁死。
- **2 影子模式**：`spec.shadow_guardrails: true`（建任务时声明，运行中不能自开）+ `report-add --shadow` + `integrity-shadow [TASK]`。被拒绝的理由改写成 `integrity-shadow` 事件、报告照常登记，用于真实任务上量误报率。CLI 冒烟：同一份无 claims 的 pass 报告，严格模式被拒、影子模式登记并列出 `PASS requires claims…`。
- **3 性能**：新增 `scripts/bench_report_path.py`。定位到写入慢的根因不在新检查，而是 `context_epoch` 对 events 的全表扫描（7.6ms/次）；补 `events(task,kind,seq)` 与 `events(json_extract(payload,'$.artifact'))`/`events(task,seq)` 索引后，2 万事件 / 100 份报告场景 **p50 55.7 → 50.0 ms、p95 82.0 → 78.5 ms**——新检查约 3ms，被索引收益覆盖。新增 `tests/test_report_performance.py`：事件量放大 10 倍，报告耗时不得超过 3 倍（防回归成扫描）。
- **4 残余风险**：`agent_authored` 只能由 runtime 传参，报告正文里写 `agent_authored:false` 不生效（测试锁定）；`report-verify` 现在返回 `unbound`（没有 `source` 的 claim）列表；复核硬规则写进 `collaboration.md` 与协调器 Skill——"没有 source 的 claim 不算覆盖验收项"。
- 验证：全量 **1621 passed / 3 skipped**（512.58 秒）；文档 208 页 / 107 CLI 示例 / 44 JSON 示例 0 issues；Skill 资源与安装 `--check` current。

## 2026-11-19：目录审计与三处修正

- 起因：审"模块与子工作流是否合理"时用 `catalog` 导出与 `plan.build` 实跑，发现三处与声明不符的问题（其余检查通过：24 模块无孤儿、三个训练 profile 派生门禁与 `flow.GATES` 逐项相等、`only-narrower` 成立）。
- **P1 整 profile 计划撞车**：`quality.qualify.analysis` 有两个候选产出者（`profiling.analyze`、`profiling.summarize`），`module-plan` 对 23 模块的 `llm-megatron` 报 `ambiguous-input`，即"选 profile 就能跑"实际需要手写绑定。按语义拆类型：`profiling.summarize` 保持 `analysis`（导出 `analysis_scope=hipprof-summary`，正是 `qualify_baseline` 的默认比对范围），`profiling.analyze` 改为 `analysis-report`。现在整 profile 计划只剩 `missing-input`（现场输入），`quality.qualify.analysis` 自动接摘要；要完整归因仍可显式绑定。`module-plan` 的多候选检查保留并有回归。
- **P3 profile 承诺跑不到的模块**：`analysis-only` 声明 `stages=("profiling",)`，却含 `environment.probe`（prepared/scale_ready）与 `source.transfer`（prepared），按阶段切分会静默丢模块。移除这两个成员（7 → 5），保留 `optimizing: [analysis]` 门禁不变；并新增 `catalog.validate_scope()` 在构造时校验"成员必须服务一个已声明阶段"，防止再犯。
- **P2 旧 preset 名失效**：`SUBWORKFLOW_ALIASES` 的键是字面量 `"quality.accept/assess"`，`quality.accept` 与 `quality.assess` 单独都解析失败，与"旧名仍可用"的声明不符。新增 `_legacy_names()` 按共享前缀展开（`quality.accept`、`quality.assess`），`subworkflow()` 同时查字面键与展开名。
- 文档：`workflow-modules.md` profile 表（20/20/16/7 → 23/23/19/5）、成员阶段校验说明、`ambiguous-input` 段落改写为"类型区分 + 显式绑定"、别名说明、阅读面 4/18、护栏表 +2 行。
- 验证：新增 `tests/test_catalog_scope.py`（6 项：成员阶段不变量、`validate_scope` 拒绝越界成员、整 profile 无歧义输入、analysis-only 清单与门禁、5 个旧名解析、未知名仍报错）；`tests/test_module_plan.py` 的歧义用例改为 monkeypatch 复现类型冲突，新增"默认接摘要"用例。全量回归与文档检查见下条。

## 2026-11-19：调用方式文档

- 新增 `docs/invocation-model.md`：三层（模块 / 子工作流 / 流程 profile）的四种调用形态、每层 JSON 字段表、`capability-run`/`module-plan`/`module-run`/`task-create`/`flow-*` 的真实示例、`problems[].kind` 与退出码语义、8 类常见入口措辞对应的 mode/profile/第一组调用、以及"人不需要写 JSON"的理由。
- 明确一条边界：入口措辞仍是人与主控的接口，JSON 是主控与执行层的接口；同一条措辞应落到同一份计划，便于重放与复核。
- 记录当前三处缺口（不隐去）：非 full 模式的 `invariants.gates` 与 `required_reports` 口径不一致；`analyze`/`diagnose` 带引擎时需要显式选 profile；`environment`/`operate` 尚无专属 profile。
- 导航：README 文档索引与 `workflow-modules.md` §9 各加一行入口。
- 验证：`check_documentation` 209 页 / 120 CLI 示例 / 50 JSON 示例 0 issues（新增的 13 条命令与 6 段 JSON 示例全部通过校验）。
- 追加 §7 修订与 §8：区分"谁写 JSON"（格式由主控生成，`objective`/`context`/`acceptance`/`permissions`/`budget`/`autonomy` 的内容由人负责，`flow-start` 暂不强制确认），并按模块（24）、子工作流（16）、profile 分阶段（4）逐一列出人必须提供的输入；输入分 H（只有人能定）/S（现场事实）/A（主控实测或内部接线）三类。结论：人实际只给六类值，其余由主控实测、抽取或上游接线。

## 2026-11-19：可复用 intake（示例 + 展开 + 校验）

- 背景：一份站点契约只服务一个任务；同一模型要跑"只检查环境""完整推进"时，设备、命令卡、契约、授权信封每次都要重填。
- `examples/intake.json`：把 `site`/`source`/`paths`/`contracts`/`observation`/`authority` 作为可复用块，`tasks[]` 只写每次变化的 `mode`/`objective`/`acceptance`/`budget`/`profile`/`use`。
- 新增 `src/hcu_trainflow/intake.py`：`load`（结构闭集）、`check`（阻断项 + 提示项）、`expand`（把一个任务展开成生成器输入）。校验覆盖：`revision` 格式、每个任务被 `validate_spec`+`validate_plan` 接受、**任务预算不得超过 `authority.budget`**、`use.contracts`/`use.commands` 必须存在、租约必须落在已准入设备（节点名仅在唯一时展开）、`profile` 必须与 `scope` 的 engine/model_family 一致。
- 生成器新增 `--intake` / `--task`：按任务展开到 `bundles/<task_id>/`，多写 `contracts/*.json`、`leases.json`（含 owner/ttl）、`inputs.json`；`--intake` 与站点契约二选一，站点契约路径的输出结构保持不变；`build()` 增加 `require_autonomy` 开关，站点契约仍强制 autonomy。
- 新增 `scripts/check_intake.py`：只读检查，退出码 0/2/1；文档新增 §9（复用粒度、两条命令、四条边界：复用≠长期授权、`revision` 只是标记、bundle 仍需人确认、人只给值）。
- 验证：`tests/test_intake.py` 11 项（展开只带声明的契约/命令、生成物被真实运行时接受、预算越界、未知契约/命令、租约匹配与节点歧义、profile 冲突、结构校验、CLI 逐任务布局与防覆盖、单任务展开、check 退出码）；`tests/test_autonomous_task.py` 既有 13 项仍通过。

## 2026-11-19：审计后的三轮加固（放宽通道 / 归属与门禁 / 不变量与 halt）

- 起因：全仓审计（store/report、flow、catalog、CLI/脚本四条线，逐条复现）后来按三批修复，先修我自己引入的 intake 漏洞（命令名路径穿越、预算替换而非收窄、check 与生成器校验不一致、空 lease 崩溃）。
- **第一批（放宽通道）**：
  - `max_regression` 只从 PLAN 读取（0–0.5），experiment 自带即 `experiment-declares-its-own-threshold`；此前候选写 1e9 可把 5 倍变慢判成通过。
  - claims 的强制条件从 `status=="pass"` 改为 `pass|complete`（capability 报告仍按 `agent_authored=False` 豁免）；`complete` 是 `analysis` 门禁可接受状态，此前可绕过引用校验。
  - shadow 模式不再为被拒证据写 `artifact-claimed`，避免一次测量把借来的证据永久变成自己的。
  - 授权/验收/负结果/取消四类问题移出 `options.resolve_question`，列入新的 `escalation_questions`，`flow-question-resolve` 也拒绝关闭。
  - `_stage_scope` 对未知 profile fail-closed；CLI 退出码补 `drift`/`select`。
- **第二批（归属与门禁）**：`artifact_owners` 用 `json_each` 归因 operations 与 pipeline_steps 结果里的 `evidence` 数组（此前标量比较匹配不到，真实执行证据全部无主）；`derived_gates` 在派生时强制 `missing_producers` 为空，profile 不能丢掉某阶段的模块门禁；`flow-align` 改以**当前**目标快照为锚，合法重规划不再永久 drift。
- **第三批（不变量、brief、halt 与 P2）**：`invariants.budget` 改为生效上限（无上限维度输出 `null`）；brief 新增 `limits` 并纳入 `brief_token`（改 `max_rounds` 会失效旧哈希）；`max_rounds` 也约束 repair 循环；driver 产出的 halt 补齐同一套 `options`；halt 去重键加入轮次与阻塞问题，避免两起事件合并；artifact 可见性在首次登记时确定（public 不会被后续 private 覆盖）；容差去掉 1e-9 绝对下限；审计脚本复制 DB 后读取（不再在 store 目录生成 `-wal/-shm`），报告正文不再受 8MiB 证据上限；`gates.derive/missing_producers` 接受 Profile；`interface()` 规范化顺序；空 `stages` 与越界 `stages` 报错；`python -m hcu_trainflow.cli` 可用。
- 回归：新增 `tests/test_relaxation_guards.py`（8）、`tests/test_attribution_and_gates.py`（6）、`tests/test_invariants_and_halts.py`（10），并更新受影响的期望（drift 语义、接口排序、可见性、合成 fixture 的 `executed`/`agent_authored`）。全量 **1673 passed / 5 skipped**（514 秒）。
- 未做（不在这三批）：`report-verify` 对 capability 报告的误报、`candidate_snapshot` 自引用、`artifact-add` 无法标记 public、profile 阶段替换的 CLI 入口、无效指令静默丢弃、`validate_catalog` 的两项缺检。
