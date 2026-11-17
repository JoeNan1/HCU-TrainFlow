# 自主任务：一次输入，无人值守

本页说明如何把一次人工输入变成可无人值守推进的任务：人只写一份站点契约并启动，之后由 Agent 按已声明的策略闭环；越界时以 `halt` + 证据停下，而不是等人回答。门禁、复核与证据要求不变，行为语义见[协作循环的自主模式](collaboration.md#自主模式无人工通道)。

适用范围：**技术判断与流程推进**不需要人。仍然只有人能做的四类决定是——扩大授权（新主机/凭据/权限）、目标达不到时的方向、放宽验收标准、主动放弃任务。

## 1. 一次性输入：站点契约

契约分四段，字段封闭、未知字段报错：

| 段 | 内容 |
| --- | --- |
| `task` | `task_id`、`mode`、`objective`、`context`（模型/源码 commit/环境/数据/初始基线/质量契约身份）、`permissions`、`recovery_owner`、`external_job`、`budget`；可选 `profile`（`{id, reason}`）声明子工作流 |
| `autonomy` | `reviewers` 评审池、`question_answers` 常见问题答案、`escalation`（降级阶梯、预算追加上限、验收是否可追加） |
| `plan` | `acceptance`（键必须是 ASCII 安全 ID）与轮次/停滞/复核失败/轮询间隔 |
| `site` | `ssh_target`、`container`、`cwd`、`commands`（执行命令卡）、`devices`（准入设备与空载基线）、`occupancy`、`leases` |

模板见 [autonomous-site.json](../examples/autonomous-site.json)。`leases` 只能落在已准入设备上（`hcu:<node>:<identity>`），命令卡按真实执行契约校验，`plan` 按 `flow-start` 的同一套规则校验。

## 2. 生成可审阅的 bundle

```bash
python scripts/build_autonomous_task.py /private/task-a/site.json --output /private/task-a/bundle
```

生成 `task.json`、`plan.json`、`admission.json` 与 `cards/*.json`，并打印后续命令。生成器**不执行任何命令、不连现场、不覆盖已存在的目录**；`admission.json` 的 `context` 由任务 context 自动派生，无需手工粘贴哈希——相应地，用 `task-context` 更换上下文后必须重新生成准入契约，否则占用证据与任务上下文不匹配。

## 3. 启动与无人推进

```bash
hcu-trainflow --workspace /private/task-a/store task-create /private/task-a/bundle/task.json
hcu-trainflow --workspace /private/task-a/store flow-start <TASK> /private/task-a/bundle/plan.json
hcu-trainflow --workspace /private/task-a/store lease-acquire hcu:<node>:<identity> agent:coordinator --ttl 86400
hcu-trainflow --workspace /private/task-a/store flow-drive <TASK> --worker <module:factory>
```

`flow-drive` 自动执行 `advance`，把 `work/repair/review` 交给 worker，遇到 `halt` 记录原因并以退出码 2 收口。

### worker 契约

worker 是调用方（主控 Agent）提供的可信代码，工厂函数签名为 `factory(store, tid)`，返回具备下列可选方法的对象：

```python
class Worker:
    def work(self, store, tid, decision):
        """返回 flow.submit 需要的候选文档；返回 None 表示无法处理。"""
    def review(self, store, tid, decision):
        """返回 flow.review 需要的复核文档；返回 None 表示无法处理。"""
```

- `decision` 是当前判定，含 `goal`、`round`、`required_reports`、`reasons`、`candidate`，worker 据此组装证据、候选或复核。
- worker 模块必须能被 CLI 导入（安装到环境或用 `PYTHONPATH` 指定）；它属于调用方的可信代码，仓库不内置通用 worker，具体候选与复核由主控 Agent 按任务实现。
- 抛 `autopilot.Handoff("原因")` 立即停机并保留该原因；其他异常记为 `worker-error`，连续 `--max-worker-errors`（默认 3）次后停机，避免 worker 缺陷空转。
- worker 只准备文档，校验仍由 `flow.submit`/`flow.review` 完成；被拒时事件记为 `worker-rejected`，状态不前进。

## 4. halt 的处置矩阵

`halt` 判定自带机器可读的选项菜单，Agent 不需要另查一份清单：

```json
{
  "halt_reason": "blocking-human-question",
  "options": {
    "degrade": [{"action": "micro_batch_down", "min": 1, "used": 0}],
    "budget_extension": {"remaining_additions": 1, "operations_per_addition": 40,
                         "operations_until_hard_ceiling": 100},
    "resolve_question": ["q-topology"],
    "must_escalate": ["authorization: ...", "acceptance: ...", "objective: ...", "cancel: ..."]
  }
}
```

`degrade` 只列策略允许且未用尽的动作（含已用次数），`budget_extension` 在次数或硬顶用尽时为 `null`，`resolve_question` 只列阻塞问题；`must_escalate` 是永远不由 Agent 自决的四类。据此选好动作后按下表执行：

| `halt_reason` | 处置 |
| --- | --- |
| 未覆盖的问题 | `flow-question` 后由主控决定：`flow-question-resolve`（归因 Agent）留痕继续 |
| 显存不足 / 通信配置不可用 | `flow-degrade TASK <action> --reason ...` 沿 `degrade_ladder` 执行，阶梯用尽才停 |
| 预算耗尽，但策略还有 headroom | `budget-extend TASK FILE`（operations/seconds/reason），超硬顶或次数上限即拒 |
| 复核失败数 / 轮次 / 停滞到顶 | 换假设后重试；方向性改变需人重新陈述目标 |
| 授权、新增权限、站点资源 | 人扩权后继续；策略不覆盖的授权不做自动扩张 |
| 目标本身达不到 | 负结果交付（`autopilot.stop_report` 或报告），放宽标准必须新建任务 |

## 5. 停机告警

`halt` 以 `flow-halted` 事件写入现有 outbox（`channel=agent`），可由既有链路消费：

```bash
hcu-trainflow --workspace /private/task-a/store halt-list            # 有未处理停机时退出码 2
hcu-trainflow --workspace /private/task-a/store inbox --action list  # 通用收件箱视图
hcu-trainflow --workspace /private/task-a/store inbox --action claim --event <ID> --owner <OWNER>
hcu-trainflow --workspace /private/task-a/store inbox --action complete --event <ID> --owner <OWNER>
```

无人值守环境把 `halt-list` 接进既有 watch/systemd 或监控脚本，即可在停机时收到通知；同一停机原因重复驱动不会重复刷事件。

## 6. 验证边界

本页描述的是软件与契约能力。真实硬件上的无人值守整链（环境→适配→优化→扩容→完成）仍需现场演练：设备授权、真实训练证据与容错归属都不在契约生成器的能力范围内，不能把生成成功或合成数据当硬件验收。
