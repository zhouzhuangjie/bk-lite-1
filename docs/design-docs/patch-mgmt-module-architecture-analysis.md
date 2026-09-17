# 补丁管理架构与数据流（对照最新 master）

> 分析日期：2026-09-16
> 代码基准：`TencentBlueKing/bk-lite` `master` `048fce9f14dd71281c731272d6046483bebb9f49`（#5646 合并后）
> 范围：`server/apps/patch_mgmt/`、`web/src/app/patch-manager/`，以及 HTTP / Beat / Celery / Ansible / SSH / WinRM / WSUS 边界
> 前序：PR [#4929](https://github.com/TencentBlueKing/bk-lite/pull/4929) 已在 2026-08-21 落地模块分析；本稿按最新 master 复核。

## 术语

| 原文 | 中文 | 在本文里指什么 |
|---|---|---|
| control plane / data plane | 控制面 / 数据面 | 控制面是谁能下治理命令、锁定哪些主机；数据面是 SSH/WinRM/Ansible 真正改主机 |
| ScanSetting pk=1 | 全局扫描单例 | 主键固定为 1 的一条配置，周期任务读它而不是按团队各一份 |
| GovernanceTask | 治理任务 | 一次补丁安装/重启/验证的父任务 |
| GovernanceTaskHost | 主机执行行 | 父任务拆到每台主机的事实行，带 token 与心跳 |
| execution_token | 执行令牌 | 栅栏：过期/重复写回对不上令牌就丢弃 |
| durable transition intent | 持久化流转意图 | 终态事务里先写下「接下来必须做重启/验证/通知」，再异步投递；进程崩溃可重扫 |
| compare-and-set / CAS | 比较并交换 | `UPDATE ... WHERE status=PENDING` 这种原子认领，先读再 save 不是 |
| lease | 租约 | 带超时的占用标记；进程死后租约过期，别人才能接着干 |
| Beat | 定时调度 | Celery Beat 周期扫描、补投递、收割超时 |
| follow-up | 终态后续步骤 | 自动重启、安装后验证、通知；必须出箱化，不能只在事务后 `.delay()` |
| `.delay()` | 立即投递 Celery | 只把消息丢进队列；进程在 commit 与 delay 之间退出则消息从未存在 |
| waiting | 等待下发 | 主机行还没把命令送到远端；取消目前只停这一档 |
| reconciling | 对账中 | 超时后只读核验「现在主机怎样」，不把传输失败当成可重放安装 |
| pending_confirmation | 待人工确认 | 未知副作用后的人工闸门；不是 failed，也不是可自动重试 |
| sync_in_progress | 同步进行中 | 源仓库/WSUS 同步占用位；没有租约就会永久卡在同步中 |
| ingest | 入库任务 | 已把同步放进 Celery 的那条路径；`sync`/`preview_sync` 还堵在 HTTP |
| connectivity_revision | 连通性配置版本 | 探测结果必须带版本号写回，避免旧探测覆盖新配置 |
| N+1 | 逐条再查 | 列表每行再打一次库；应改成批量投影 |
| Port | 端口接口 | 对本模块稳定的依赖边界 |
| FK | 外键 | 数据库引用完整性；JSON 里存 ID 没有环检测 |
| WSUS / WinRM | Windows 补丁源 / Windows 远程管理 | Linux 走仓库 HTTP，Windows 走 WinRM 连 WSUS |
| fencing | 栅栏 | token 挡住陈旧回调 |

## 1. 一张图看完整构建

总控入口：左侧选 PatchMgmt，原三个 Tab 未改，后面是新增。

- [架构中心 · PatchMgmt](server-module-architecture-hub.html#patch-mgmt/current)
- 原 Tab：[现状架构](server-module-architecture-hub.html#patch-mgmt/current) · [治理数据流](server-module-architecture-hub.html#patch-mgmt/core) · [目标架构](server-module-architecture-hub.html#patch-mgmt/target)
- 新增 Tab：[控制面与数据面](server-module-architecture-hub.html#patch-mgmt/control) · [入参出参与存储](server-module-architecture-hub.html#patch-mgmt/io) · [目标控制面](server-module-architecture-hub.html#patch-mgmt/controlTarget)

单图：[现状控制面](patch-mgmt-control-data-plane.dataflow.html) · [入参出参](patch-mgmt-io-storage.dataflow.html) · [目标控制面](patch-mgmt-control-data-plane.target.dataflow.html)

**现状图只改中文标签，拓扑不变**（全局扫描、非原子认领、事务后重启/验证）。目标图按第 3 节修复方案改结构。

现状：

```text
Web 当前团队 ─┐                    源同步（无 lease）──→ 无版本基线
Beat 全局扫描 ─┴→ 治理命令
                              ↓
                    父任务非原子 claim 扇出
                              ↓
                    主机执行内核 ──→ SSH / WinRM / Ansible
                              ↓
                    GovernanceTaskHost（token / 心跳）
                              ↓
                    事务后 delay：重启 / 验证 / 通知
```

### 过程与关键代码

路径相对仓库根。对照图：源/Web/Beat → 治理任务 → Celery 扇出 → 主机内核 → host 行 → 终态 follow-up。

| 阶段 | 关键函数 | 位置 |
|---|---|---|
| HTTP 创建 | `GovernanceTaskViewSet.create` → `create_assess_task` / `create_reboot_task` / `create_remediation_task` → `_trigger_async` | `views/governance.py`、`services/governance_service.py` |
| 周期扫描 | `ScanSetting.get_singleton`（`pk=1`）→ `run_periodic_compliance_scan` 取全部 `PatchTarget.id`，`team` 为空 | `models/scan_setting.py`、`tasks.py` |
| 源同步 | `PatchSourceViewSet.sync` / `preview_sync` 同步跑；`ingest` 才 `ingest_patch_source.delay` | `views/patch_source.py`、`source_sync_service.py`、`tasks.py` |
| 父任务认领 | `execute_governance_task`：先 `get` PENDING 再 `save(RUNNING)`，无 CAS | `tasks.py` |
| 扇出 | 同函数里 `GovernanceTaskHost.objects.create(..., stage="waiting")` 后派主机子任务 | `tasks.py` |
| 主机领取 | `run_governance_host` → `_claim_waiting_host`（`filter(stage='waiting').update(...)`） | `patch_execution_service.py` |
| 远端 | `run_governance_host` 按 `task_type` 走 SSH / WinRM / Ansible | `patch_execution_service.py` |
| 超时 | 安装/重启写 `reconciling` 后 `reconcile_governance_host` | `patch_execution_service.py` |
| 父任务终态 | `_finalize_task_status` 返回首次终态后 `_run_terminal_followups`（事务外 `.delay()`） | `patch_execution_service.py` |
| 取消 | `GovernanceTaskViewSet.cancel`：文档写明不中断已下发 | `views/governance.py` |
| 风险列表 | `compute_risk_items()` 全量算完，ViewSet 再按授权 ID 过滤 | `risk_service.py`、`views/risk.py` |

周期扫描跨团队、空 `team`：

```66:94:server/apps/patch_mgmt/tasks.py
def run_periodic_compliance_scan() -> None:
    ...
    setting = ScanSetting.get_singleton()
    ...
    target_ids = list(PatchTarget.objects.values_list("id", flat=True))
    ...
    task = GovernanceTask.objects.create(
        name=f"周期性合规评估 ({timezone.now().strftime('%Y-%m-%d %H:%M')})",
        task_type=GovernanceTaskType.ASSESS,
        execution_mode="now",
        status=GovernanceTaskStatus.PENDING,
        target_list=target_ids,
        patch_list=[],
    )
```

父任务非原子 claim：

```101:130:server/apps/patch_mgmt/tasks.py
def execute_governance_task(task_id: int) -> None:
    ...
    task = GovernanceTask.objects.get(pk=task_id)
    ...
    if task.status not in (GovernanceTaskStatus.PENDING,):
        ...
        return
    ...
    task.status = GovernanceTaskStatus.RUNNING
    ...
    task.save(update_fields=["status", "started_at", *chain_fields, "updated_at"])
```

终态后才 follow-up（图上虚线）：

```1725:1946:server/apps/patch_mgmt/services/patch_execution_service.py
def _finalize_task_status(task: GovernanceTask) -> bool:
    '''根据所有主机结果汇总任务状态，返回是否首次进入终态。'''
    ...

def _run_terminal_followups(task: GovernanceTask) -> None:
    '''任务首次进入终态后触发后续治理链路。'''
    if task.task_type == GovernanceTaskType.INSTALL and task.auto_reboot:
        _schedule_auto_reboot(task)
    if task.task_type == GovernanceTaskType.INSTALL:
        _schedule_post_install_verify(task)
    ...

def finalize_governance_task(task_id: int) -> None:
    ...
    if task is not None and _finalize_task_status(task):
        _run_terminal_followups(task)
```

目标：

```text
Web 当前团队 ─┐                    源同步（Celery + lease）──→ versioned baseline
Beat per-team scan ─┴→ 治理命令
                              ↓
                    CAS claim 后扇出
                              ↓
                    主机执行内核 ──→ SSH / WinRM / Ansible
                              ↓
                    GovernanceTaskHost（token / log chunks）
                              ↓
                    事务内 Follow-up Outbox：重启 / 验证 / 通知
```

Web 页：`home` / `baseline` / `library` / `target` / `risk-pending` / `risk-execution` / `settings`。HTTP 8 个 Router（路由组）。NATS 只做数据权限可选实例，不承担治理执行。生产 Python 约 17,592 行。`PatchTarget` 注释明确：只支持 Ansible 型目标，**不复用** `job_mgmt.Target`。

## 2. 相对 8 月 21 日分析，master 上变了什么

| 主题 | 8/21 结论 | 2026-09-16 master |
|---|---|---|
| 风险 API 先全库再过滤 | P1 | **已收口**：`compute_risk_items(target_ids)`，ViewSet 先取授权主机 |
| 源连通性陈旧探测覆盖 | 未强调 | **已收口**：按 `connectivity_revision`（连通性配置版本）条件写回 |
| Windows 包上传锁 | 未强调 | **已收口**：上传与超时清理共用行锁 |
| Linux 仓库解压体积 | 未强调 | **已收口**：限制元数据解压体积 |
| 执行记录摘要 / 合规投影 N+1（逐行再查） | P1 读侧 | 多处改为批量投影、任务链索引 |
| 全局周期扫描 / 非原子父任务认领 / 事务后 follow-up | P0 | **未改结构** |

风险读侧仍是「授权范围内实时聚合再 Python 分页」，不是增量读模型；只是不再扫描未授权团队。

## 3. 风险与坏味道（按优先级）

### P0

1. **周期评估跨团队聚合。** `ScanSetting` 是 pk=1 全局单例（全站一条配置）。`run_periodic_compliance_scan` 读取全部 `PatchTarget.id`，创建一条 `team` 为空的 `GovernanceTask`。
   - **代码：** `ScanSetting.get_singleton`；`tasks.run_periodic_compliance_scan`。
   - **修复：** 扫描配置按团队拆分（至少 `ScanSetting` 带 `team`，禁止全局 pk=1）。Beat 只扇出「每团队一个扫描任务」，任务内再加目标上限；空团队任务直接拒绝落库。
   - **验收：** 团队 A 的周期扫描产生的治理任务 `team=A`，且不含团队 B 主机；全站主机数很大时单任务被切开而不是一条打完全库。

2. **治理链缺少 durable transition intent（持久化流转意图）。** `_finalize_task_status` 事务提交后才 `_run_terminal_followups`：自动重启、安装后验证即时 `.delay()`。通知若已有 delivery 表则只覆盖通知；重启/验证没有出箱。进程在两者之间退出会永久丢步骤。
   - **代码：** `patch_execution_service._finalize_task_status` / `_run_terminal_followups` / `_schedule_auto_reboot` / `_schedule_post_install_verify`；`finalize_governance_task`。
   - **修复：** 与通知同一模式：在写终态的同一事务里插入「重启/验证」出箱行（唯一键 + 租约 + 下次可投递时间）。提交后再投递；Beat 重扫未完成出箱。禁止只在内存里 `.delay()`。
   - **验收：** 终态提交后立刻杀进程，重启/验证仍会被 Beat 补上；同一 intent 不会双发（唯一键挡住）。

3. **父任务非原子 claim（认领）。** `execute_governance_task` 先读 PENDING 再 `save(RUNNING)`，没有 compare-and-set（比较并交换）。重复 Celery delivery 可能双扇出；逐主机 `_claim_waiting_host` 能挡住重复安装，但会放大 broker 与竞态。
   - **代码：** `tasks.execute_governance_task`；对比主机侧 `patch_execution_service._claim_waiting_host`（已是 `filter(stage='waiting').update`）。
   - **修复：** `filter(id=..., status=PENDING).update(status=RUNNING, ...)`，`updated==0` 则直接退出。子任务投递以主机行为幂等键，避免重复 delivery 再扇出一遍。
   - **验收：** 同一父任务投两次 Celery，只产生一套主机子任务；安装命令不会因双扇出翻倍（token 仍保留作第二道栅栏）。

### P1

4. **源同步仍堵在 HTTP 请求线程，且 `sync_in_progress` 无租约。** `PatchSourceViewSet.sync` / `preview_sync` 同步跑 Linux 仓库或 WSUS WinRM；`ingest`（入库）才进 Celery。进程在置位后退出，源会永久 syncing。
   - **代码：** `views/patch_source.PatchSourceViewSet.sync` / `preview_sync` / `ingest`；`SourceSyncService.sync_linux_repo` / `sync_wsus`；`tasks.ingest_patch_source`。
   - **修复：** `sync`/`preview_sync` 只创建带租约的同步任务并立即返回任务 ID；真正拉仓库/WinRM 进 Celery。租约过期由 Beat 清 `sync_in_progress`。HTTP 超时不得等于远端同步超时。
   - **验收：** 同步期间杀 gunicorn，源在租约到期后可再次同步；接口在秒级返回，不卡在 WinRM。

5. **取消只停 `waiting`（等待下发）主机。** `GovernanceTaskViewSet.cancel` 不收回已下发的安装/重启；与作业平台一样，取消不是远端终止证明。
   - **代码：** `views/governance.GovernanceTaskViewSet.cancel`（注释：取消尚未开始执行的主机，不中断已经下发的操作）。
   - **修复：** 产品语义写死：取消 = 停止尚未下发 + 对已下发主机标记 `cancelling`，并尽力发中止（能中止再核验，不能中止则进 `pending_confirmation`）。UI/API 不得显示成「已在远端停掉」。
   - **验收：** 已 SSH 执行中的主机取消后不会被当成 success；文档与前端文案区分「停止排队」和「远端已停」。

6. **基线无版本，合规快照每次评估删除重建。** 无法回答「某历史基线版本下为何合规」。
   - **代码：** `models/baseline.py`；评估写快照见 `patch_execution_service` / `execution_record_service`。
   - **修复：** 基线发布即不可变版本；评估引用 `baseline_version_id`。快照按评估批次追加，禁止删当前行来「重建」。
   - **验收：** 改基线条目后，旧评估仍能打开当时的要求列表。

7. **`patch_execution_service.py` 约 2,702 行**，协议 / OS / 解析 / 状态机 / 链路编排交叉。
   - **代码：** `run_governance_host`、`_claim_waiting_host`、`_finalize_task_status`、`_run_terminal_followups` 同文件。
   - **修复：** 按硬约束拆 seam：协议适配（SSH/WinRM/Ansible）、结果解析、主机状态机、父任务编排分成模块；新 OS 只加适配器，不在 2700 行里继续堆分支。
   - **验收：** 状态机单测不需要真实 SSH；新增一种 Linux 发行版不改父任务编排。

8. **主机日志 `TextField` 整行追加**，写放大接近 O(total_log²)。
   - **代码：** `GovernanceTaskHost.log`；`patch_execution_service._record_host_result` 回写 host 行。
   - **修复：** 日志改为追加型块（子表或对象存储），主行只保留指针与长度；禁止 `log = log + chunk` 回写整列。
   - **验收：** 长时间安装的日志写入次数与日志体积线性相关，而不是平方。

9. **风险计算仍在请求路径实时跑完授权范围内全部主机×要求**，分页只裁 Python list。
   - **代码：** `risk_service.compute_risk_items`；`views/risk.py` 先算再 `if item.host_id in target_ids` 过滤。
   - **修复：** 评估落库时物化风险行（主机×要求）；列表 API 只查投影表并在数据库分页。实时计算留给「立即刷新」显式动作。
   - **验收：** 万级主机列表接口耗时与 page_size 相关，而不是与全团队主机数相关。

### P2

10. **补丁依赖/替代仍是 JSON ID，无 FK / 环检测。**
    - **代码：** `Patch.dependency_ids` / `replacement_ids`；`risk_service.compute_risk_items` 读这两列。
    - **修复：** 依赖与替代改为外键表，写入时做环检测；废弃纯 JSON ID。
    - **验收：** 自依赖、A→B→A 在保存时 400。

11. **直接导入 Node / CloudRegion / Ansible resolver / S3 / SystemMgmt，没有 Port。**
    - **代码：** `target_execution_route.py`、`patch_execution_service.py` 内协议分支。
    - **修复：** 补丁模块只通过窄接口取节点凭证、云区域、对象存储、通知通道。
    - **验收：** 执行内核单测可 mock Port。

12. **不要把 `PatchTarget` 和 `job_mgmt.Target` 合表；先共享执行能力接口。**
    - **代码：** `models/patch_target.py` 注释约束 Ansible 型目标。
    - **修复：** 保持两表。若要复用，抽「按 Ansible 目标执行命令」的能力接口，而不是合并资产模型。
    - **验收：** 作业目标类型扩展不影响补丁目标约束（仅 Ansible 型）。

## 4. 应保留的内核

- `GovernanceTaskHost` 逐主机事实 + `_claim_waiting_host` CAS
- 安装/重启超时进入 `reconciling`（对账中）只读核验，不自动重放未知副作用
- 创建治理时 `create_remediation_task` / `create_assess_task` 锁定目标与绑定
- `_lock_and_assert_hosts_available` 创建前锁主机
- 周期评估入口已集中在 `run_periodic_compliance_scan`（便于改成按团队扇出）

## 5. 硬约束（给后续改动）

1. 终态事务里先写唯一 transition intent（流转意图），再异步投递。
2. 未知副作用只能核验或人工确认，不能当 transport 失败（传输失败）重试。
3. `pending_confirmation`（待人工确认）不是 failed，也不是可自动 retry。
4. 当前合规只是读模型，不是历史证据。
5. 周期扫描必须按可信 team 分区，并有单任务 target 上限。
6. 不要继续往 `patch_execution_service.py` 加协议分支。

## 6. 修复顺序建议

1. P0：父任务 CAS 认领 → 重启/验证出箱 → 周期扫描按团队拆分（先止血重复执行和丢步骤，再收信任边界）。
2. P1：源同步改 Celery + 租约；取消语义与前端对齐。
3. P1：风险投影表、日志外置、基线版本。
4. P2：依赖外键、Port、保持双 Target 表。
