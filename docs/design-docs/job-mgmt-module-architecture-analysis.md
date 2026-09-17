# 作业平台架构与数据流（对照最新 master）

> 分析日期：2026-09-16
> 代码基准：`TencentBlueKing/bk-lite` `master` `048fce9f14dd71281c731272d6046483bebb9f49`（#5646 合并后）
> 范围：`server/apps/job_mgmt/`、`web/src/app/job/`，以及相连的 OpenAPI / NATS / Celery / NodeMgmt 边界
> 前序：PR [#4929](https://github.com/TencentBlueKing/bk-lite/pull/4929) 已在 2026-08-21 落地模块分析；本稿按最新 master 复核，不沿用当时的 revision（修订结论）。

## 术语

| 原文 | 中文 | 在本文里指什么 |
|---|---|---|
| control plane / data plane | 控制面 / 数据面 | 控制面决定谁能下命令、用哪个团队、写哪条任务；数据面负责真正派发、远端执行和回传 |
| payload | 消息体 | NATS/OpenAPI 请求里调用方自己带上来的 JSON 字段，不能当授权事实 |
| trusted_actor | 可信调用主体 | 网关校验后注入的身份；只有它能决定团队，不能被消息体覆盖 |
| fail-closed | 失败即拒绝 | 校验不通过就拒绝，而不是默认放行 |
| Sidecar | 边车执行器 | 本仓库 `nats-executor` 路径：进程内线程池直连目标，不走 Ansible |
| Completion Outbox | 完成出箱 | 终态副作用的可靠投递表：先落库再异步发回调，崩溃可重扫 |
| claim | 认领 | worker 用行锁把 `PENDING` 抢成 `RUNNING`，保证同一条执行只被一个 worker 接手 |
| principal | 主体 | 真正发起执行的身份（用户/系统账号），不是消息体里的 `team` 字符串 |
| reducer | 唯一归约器 | 只允许一个模块写 `JobExecution.status`，避免两路同时改终态 |
| fencing | 栅栏/防陈旧写回 | 用 attempt、token 挡住过期回调覆盖当前事实 |
| Beat reaper | 定时收割任务 | Celery Beat 周期扫超时、失联、未投递出箱 |
| Port | 端口接口 | 对本模块稳定的依赖边界；不要直接 import 邻域 Django 模型 |
| sandbox | 沙箱 | 真正隔离执行环境；字符串匹配高危命令不是沙箱 |
| exactly-once | 恰好一次 | 远端副作用做不到；失联时命令可能已执行 |
| SSE / Webhook / JetStream | 服务端推送 / HTTP 回调 / NATS 持久流 | 三种回传通道，都必须从出箱投递，不能随进程内存消失 |
| OpenAPI 包装层 | 网关封装 | 对外 OpenAPI 会事后过滤；NATS 直连入口没有这层保护 |
| driver | 执行驱动 | 目标用 Sidecar 还是 Ansible；不能只看第一个目标 |
| stdout / stderr | 标准输出 / 标准错误 | 远端命令打印；不应整批塞进主表 JSON |
| legacy | 遗留入口 | 旧 NATS handler，仍被告警等内部调用方使用 |

## 1. 一张图看完整构建

总控入口：左侧选 JobMgmt，原三个 Tab 未改，后面是新增。

- [架构中心 · JobMgmt](server-module-architecture-hub.html#job-mgmt/current)
- 原 Tab：[现状架构](server-module-architecture-hub.html#job-mgmt/current) · [执行生命周期](server-module-architecture-hub.html#job-mgmt/core) · [目标架构](server-module-architecture-hub.html#job-mgmt/target)
- 新增 Tab：[控制面与数据面](server-module-architecture-hub.html#job-mgmt/control) · [入参出参与存储](server-module-architecture-hub.html#job-mgmt/io) · [目标控制面](server-module-architecture-hub.html#job-mgmt/controlTarget)

单图：[现状控制面](job-mgmt-control-data-plane.dataflow.html) · [入参出参](job-mgmt-io-storage.dataflow.html) · [目标控制面](job-mgmt-control-data-plane.target.dataflow.html)

控制面（接入 + 编排）和数据面（派发 + 远端执行 + 回传）在同一张图上。**现状图只改中文标签，拓扑不变**（边车仍直接发回调、NATS 仍自报团队）。目标图按第 3 节修复方案改结构。

现状：

```text
Web 登录用户 ─┐
NATS 自报 team ─┴→ 策略（双轨）→ JobExecution（results JSON）
                                      ↓
                               Celery 行锁 claim
                          ┌───────────┴───────────┐
                    Sidecar Runner           Ansible 异步
                          │                       │
                    直接 send_callback      Completion Outbox
                          └───────────┬───────────┘
                                SSE / Webhook / JetStream
```

### 过程与关键代码

路径相对仓库根。对照图上从左到右：接入 → 校验落库 → 派发 claim → Sidecar/Ansible → 出参。

| 阶段 | 关键函数 | 位置 |
|---|---|---|
| HTTP 接入 | `JobExecutionViewSet.quick_execute` → `ExecutionService.create_quick_execution` | `server/apps/job_mgmt/views/execution.py`、`services/execution_service.py` |
| NATS 接入 | `job_script_execute`：`team = data.get("team")` 后 `JobExecution.objects.create` | `server/apps/job_mgmt/nats_api.py` |
| 告警调用 | `JobActionHandler.execute` → `JobMgmt().job_script_execute` | `server/apps/alerts/action/handlers/job.py`、`server/apps/rpc/job_mgmt.py` |
| 高危校验 | `DangerousChecker.check_command` | `server/apps/job_mgmt/services/dangerous_checker.py` |
| 派发 | `dispatch_celery_task` → `execute_script_task` / `distribute_files_task` / `execute_playbook_task`（`max_retries=0`） | `services/celery_dispatch.py`、`tasks.py` |
| worker 入口 | `ScriptExecutionRunner.run` → `prepare_execution`（PENDING→RUNNING） | `services/script_execution_runner.py`、`execution_base_service.py` |
| 选路 | `_should_use_ansible` 只看 `target_ids[0]` | `execution_base_service.py` |
| Sidecar | `_run_via_sidecar` → `execute_script_on_target` → `finalize_execution` → **`send_callback`（无 Outbox）** | `script_execution_runner.py`、`execution_base_service.py`、`callback_service.py` |
| Ansible | `_execute_script_via_ansible`；写回 `ansible_task_callback` | `execution_base_service.py`、`nats_api.py` |
| 出参 | `build_callback_payload`（NATS 带 `execution_results`）；`_send_web_callback` 只有 counts；`do_callback_task` / `do_nats_callback_task` | `callback_service.py`、`tasks.py` |
| 取消兜底 | `finalize_cancelling_execution` | `tasks.py` |
| 批查 / 资产枚举 | `job_status_batch_query`、`job_target_list`（`Target.objects.all()`，`page_size=-1`） | `nats_api.py` |

NATS 把消息体 `team` 当授权事实：

```372:400:server/apps/job_mgmt/nats_api.py
def job_script_execute(data: dict):
    """
    脚本执行（NATS 开放接口）
    ...
            - team: 团队ID列表（必填）
    """
    name = data.get("name")
    target_source = data.get("target_source")
    target_list = data.get("target_list")
    script_type = data.get("script_type")
    script_content = data.get("script_content")
    team = data.get("team", [])
```

Sidecar 终态直发回调（图上虚线）：

```123:146:server/apps/job_mgmt/services/execution_base_service.py
    def finalize_execution(cls, execution: JobExecution, task_name: str, results: list):
        execution.execution_results = results
        execution.save(update_fields=["execution_results", "updated_at"])
        ...
        # 回调通知（如有 callback_url）
        execution.refresh_from_db()
        send_callback(execution)
```

选路只看第一个手动目标：

```148:172:server/apps/job_mgmt/services/execution_base_service.py
    def _should_use_ansible(target_source: str, target_list: list) -> bool:
        ...
        # 检查第一个目标的驱动类型
        target_ids = [t.get("target_id") for t in target_list if t.get("target_id")]
        ...
        target = Target.objects.filter(id=target_ids[0]).first()
        ...
        return target.driver == ExecutorDriver.ANSIBLE
```

目标：

```text
Web 登录用户 ─┐
NATS trusted_actor ─┴→ 策略（单轨）→ JobExecution（摘要 + pointer）
                                      ↓
                               delay / 行锁 claim
                          ┌───────────┴───────────┐
                    Sidecar（同 driver 一批）  Ansible（同区域一批）
                          └───────────┬───────────┘
                               Completion Outbox
                                      ↓
                                SSE / Webhook / JetStream
```

Web 页：`home` / `template` / `execution` / `target` / `settings`。HTTP 有 9 组 Router（路由组）+ 一组 OpenAPI；NATS 注册 12 个 handler（消息处理函数）。生产 Python 约 11,977 行。补丁管理**不复用** `job_mgmt.Target` 表。

## 2. 相对 8 月 21 日分析，master 上变了什么

| 主题 | 8/21 结论 | 2026-09-16 master |
|---|---|---|
| 失联 RUNNING（执行中卡住） | 已有 `converge_deadline_at`（收敛截止时间）+ Beat 收割 | 仍在；后续又修了取消长时间卡在 CANCELLING（取消中）、超时结果不得覆盖终态 |
| 文件分发跨团队 | 已按 file.team fail-closed（文件不属于声明团队则拒绝） | 仍在；legacy NATS 入口默认仍开启（`JOB_FILE_DISTRIBUTE_NATS_ENABLED=1`） |
| 子组织执行记录 | 未强调 | 管理员开启 Include Subgroup Data（含下级组织数据）后可看深层子组织记录 |
| 信任边界 / 双终态 / 单行 JSON | P0/P1 | **未改结构**，见下表 |

## 3. 风险与坏味道（按优先级）

### P0

1. **遗留远程执行仍把消息体 `team` 当授权事实。** `job_script_execute` 忽略 NATS kwargs（网关附加参数），`team = data.get("team")` 后写入 `JobExecution` 并用于高危规则。OpenAPI 网关才传 `trusted_actor`（可信主体）。仓内真实调用方是告警 `JobActionHandler`（`JobMgmt().job_script_execute`），同样走这条「消息体自报团队」路径。`job_file_distribute` 默认兼容开启；文件是否属于声明团队已在 ORM 上 fail-closed（不属于则拒绝），但**调用主体仍不可信**。
   - **代码：** `nats_api.job_script_execute` / `job_file_distribute`；`rpc/job_mgmt.JobMgmt.job_script_execute`；`alerts/action/handlers/job.JobActionHandler.execute`。
   - **修复：** NATS 与内部 SDK 一律只接受网关/服务身份注入的团队；消息体 `team` 最多作对照，不一致则拒绝。告警动作改走带 `trusted_actor` 的同一入口。`JOB_FILE_DISTRIBUTE_NATS_ENABLED` 默认关闭，打开必须同时有可信主体。
   - **验收：** 伪造消息体 `team` 不能创建/执行他团队作业；告警回调写入的执行记录团队等于告警所属团队，而不是 payload 字段。

2. **终态双轨。** Sidecar（边车）`finalize_execution` 直接 `send_callback`（发回调）；Ansible 回调、取消、超时才走可恢复路径。当前工作区 Sidecar 与 `ansible_task_callback` 都收口到 `send_callback`；GitHub master 另有 `enqueue_terminal_effects` / `JobCompletionOutbox`，Sidecar 仍不走它。崩溃窗口：Sidecar 终态已提交但 callback 未入队则丢失。
   - **代码：** `ExecutionTaskBaseService.finalize_execution` → `callback_service.send_callback`；`nats_api.ansible_task_callback`；`tasks.do_callback_task` / `do_nats_callback_task`；`tasks.finalize_cancelling_execution`。
   - **修复：** 所有 Runner（执行器）禁止直接改状态或直接发回调。终态只经唯一 reducer 写 `JobExecution.status`，副作用只经 `JobCompletionOutbox`。Sidecar 与 Ansible 共用同一条出箱重扫。
   - **验收：** 杀掉 Sidecar 进程后，Beat 仍能补发 SSE/Webhook/JetStream；超时结果不能覆盖已取消/已成功。

### P1

3. **`job_status_batch_query` 按任意 `task_ids` 读状态，无身份/团队范围。** OpenAPI 包装层事后过滤，NATS 入口本身没有。
   - **代码：** `nats_api.job_status_batch_query`：`JobExecution.objects.filter(id__in=task_ids)`。
   - **修复：** handler 内先取可信主体，再按团队过滤 `task_ids`；越权 ID 当作不存在，不回传状态。OpenAPI 与 NATS 共用同一查询函数。
   - **验收：** 他团队 `task_id` 在 NATS 直连下返回空/404，而不是真实状态。

4. **`job_target_list` 用 `Target.objects.all()`，`page_size=-1` 返回全部。** 资产枚举入口。
   - **代码：** `nats_api.job_target_list`。
   - **修复：** 列表必须按授权团队（含明确开启的下级组织）过滤；禁止无上限分页，给硬顶（例如 200）并对 `-1` 拒绝。
   - **验收：** 非授权团队主机不出现；`page_size=-1` 返回 400。

5. **第一个手动目标的 driver（执行驱动）决定整批路径；多云区域只执行第一组。** `_should_use_ansible` 只看 `target_ids[0]`。
   - **代码：** `ExecutionTaskBaseService._should_use_ansible`；`ScriptExecutionRunner._run_via_ansible_if_needed`。
   - **修复：** 按目标拆批：同一 driver + 同一云区域一组；混合批次在控制面拒绝或自动拆成多条 `JobExecution`。禁止静默丢掉后续云区域。
   - **验收：** Sidecar 目标与 Ansible 目标混选时报错或拆成两条；两个云区域的目标都会被执行。

6. **全部目标 stdout/stderr（标准输出/错误）聚合在 `execution_results` JSON。** Sidecar 内存持有整批结果后一次写回。
   - **代码：** `ScriptExecutionRunner._run_via_sidecar` 累积 `results` 后 `finalize_execution` 整表写回；`build_callback_payload` 把 `execution_results` 放进 NATS。
   - **修复：** 每目标一份结果对象（表或对象存储）；主表只留摘要、退出码、对象指针。默认回调不带完整日志。
   - **验收：** 大输出作业主表行大小稳定；回调 payload 不含完整 stdout。

7. **并发只约束单 execution（默认 10 线程），无团队/区域/执行器共享预算。**
   - **代码：** `ExecutionTaskBaseService.MAX_WORKERS`（`EXECUTION_MAX_WORKERS`）；`_run_via_sidecar` 按 `min(MAX_WORKERS, len(target_list))` 分批。
   - **修复：** 增加团队、云区域、执行器三维信号量；超预算排队而不是在单任务内加线程。
   - **验收：** 同一云区域多作业并行时，远端连接数不超过预算。

8. **`nats_api.py` 仍是第二应用层**，与 HTTP `ExecutionService` 行为容易漂移。
   - **代码：** HTTP 走 `ExecutionService.create_quick_execution`；NATS `job_script_execute` 自己 `objects.create` + `dispatch_celery_task`。
   - **修复：** NATS handler 只做鉴权与参数映射，业务一律进 `ExecutionService`；删掉平行实现。
   - **验收：** 脚本执行、文件分发、取消在 HTTP 与 NATS 的状态机测试共用同一组 fixture。

### P2

9. **普通执行 `.delay()` 与 scheduled `send_task` 派发语义仍不统一。**
   - **代码：** `dispatch_celery_task` 用 `.delay()`；`tasks.execute_scheduled_task` 对 `ScheduledTask` `select_for_update`。
   - **修复：** 立即执行与定时执行走同一投递辅助函数（队列名、重试、幂等键一致）。
   - **验收：** 定时作业与立即作业的 worker 参数、认领条件相同。

10. **直接导入 NodeMgmt `Node`/`CloudRegion`、S3 helper、SystemMgmt token，没有稳定 Port。**
    - **代码：** `execution_base_service` 引用 `apps.rpc.ansible.AnsibleExecutor`、`apps.rpc.node_mgmt.NodeMgmt`；`tasks.py` 调 `node_mgmt.utils.s3.delete_s3_files`。
    - **修复：** 作业模块只依赖窄接口（查节点凭证、查云区域、签发回调 token、存日志对象）；邻域模型变更不穿透进来。
    - **验收：** `job_mgmt` 单测可 mock Port，不必加载 NodeMgmt 全模型。

11. **高危命令字符串匹配不是 sandbox（沙箱）。**
    - **代码：** `DangerousChecker.check_command`；`ScriptExecutionRunner._handle_dangerous_command`。
    - **修复：** 匹配只作告警/二次确认，不宣称隔离。真正危险命令走审批或拒绝；需要隔离时用独立执行环境，而不是正则。
    - **验收：** 绕过字符串匹配的等价命令仍走高危策略；文档不再把匹配写成沙箱。

## 4. 应保留的内核

- worker 入口 `prepare_execution`（PENDING→RUNNING）+ 取消 `finalize_cancelling_execution`
- 取消 `CANCELLING`（取消中）+ 超时兜底
- Ansible 回调 `ansible_task_callback` 的 attempt/token fencing（防陈旧写回）
- HTTP 编排 `ExecutionService.create_quick_execution`（NATS 不要平行再写一份）
- `DangerousChecker.check_command`（只作策略，不当 sandbox）

## 5. 硬约束（给后续改动）

1. 调用方不得用 payload（消息体）覆盖 principal/team（主体/团队）。
2. 新 Runner（执行器）不得自己写 `JobExecution.status`；终态只经唯一 reducer + Outbox（出箱）。
3. 不要用 Celery task state（队列任务状态）当业务真相。
4. 不要把完整 stdout 放进主表或默认 callback。
5. 远端执行不是 exactly-once（恰好一次）；失联时副作用可能已发生。

## 6. 修复顺序建议

1. P0：可信主体 + Sidecar 并入出箱（安全与丢回调）。
2. P1：批查/目标列表收口，再拆混合 driver 批次。
3. P1：结果外置与 NATS 去平行实现。
4. P2：投递语义、Port、高危策略文档化。
