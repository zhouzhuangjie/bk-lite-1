'use client';

import {
  ApartmentOutlined,
  ArrowLeftOutlined,
  AuditOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  CopyOutlined,
  FileTextOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  Popconfirm,
  Segmented,
  Select,
  Skeleton,
  Tag,
  Timeline,
} from 'antd';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../../components/page-shell';
import {
  TicketCompactProgressBanner,
  TicketFlowDrawer,
} from '../../components/ticket-process-steps';
import { TicketStatusTag } from '../../components/ticket-status-tag';
import {
  WorkbenchPropertyList,
  WorkbenchSection,
} from '../../components/workbench-section';
import { newRequestKey } from '../../lib/status';
import type { PageResponse, TaskRecord, TicketRecord, UserOption } from '../../lib/types';

type TaskAction = 'approve' | 'reject' | 'before_sign' | 'after_sign' | 'complete_handling';

interface UserListResponse {
  users: UserOption[];
  count: number;
}

const actionLabels: Record<TaskAction, string> = {
  approve: '通过',
  reject: '驳回',
  before_sign: '前加签',
  after_sign: '后加签',
  complete_handling: '处理完成',
};

export default function TicketDetailPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { convertToLocalizedTime } = useLocalizedTime();
  const { get, post } = useApiClient();
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [ticket, setTicket] = useState<TicketRecord>();
  const [myTasks, setMyTasks] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [closing, setClosing] = useState(false);
  const [flowDrawerOpen, setFlowDrawerOpen] = useState(false);

  const [selectedAction, setSelectedAction] = useState<TaskAction>('approve');
  const [reason, setReason] = useState('');
  const [userIds, setUserIds] = useState<number[]>([]);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [userLoading, setUserLoading] = useState(false);
  const [submittingTask, setSubmittingTask] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const [ticketRes, taskRes] = await Promise.all([
        get<TicketRecord>(`/itsm/api/tickets/${params.id}/`),
        get<PageResponse<TaskRecord>>(
          `/itsm/api/tasks/?ticket_id=${encodeURIComponent(params.id)}&page_size=20`,
        ).catch(() => ({ count: 0, items: [] })),
      ]);
      setTicket(ticketRes);
      const pendingTasks = (taskRes.items ?? []).filter(
        (item) => item.ticket_id === params.id,
      );
      setMyTasks(pendingTasks);
      const firstTask = pendingTasks[0];
      if (firstTask) {
        setSelectedAction(
          firstTask.task_type === 'APPROVAL' ? 'approve' : 'complete_handling',
        );
      }
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [get, params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const searchUsers = useCallback(
    async (search = '') => {
      setUserLoading(true);
      try {
        const response = await get<UserListResponse>('/core/api/user_group/user_list/', {
          params: { page: 1, page_size: 100, search },
        });
        setUsers(response.users ?? []);
      } finally {
        setUserLoading(false);
      }
    },
    [get],
  );

  const activeTask = myTasks[0];

  const handleActionChange = (nextAction: TaskAction) => {
    setSelectedAction(nextAction);
    if (nextAction === 'before_sign' || nextAction === 'after_sign') {
      void searchUsers();
    }
  };

  const submitTaskAction = async () => {
    if (!activeTask) return;
    const requiresUsers =
      selectedAction === 'before_sign' || selectedAction === 'after_sign';
    const requiresReason = selectedAction === 'reject' || requiresUsers;
    if (requiresUsers && !userIds.length) {
      message.warning(t('itsm.todo.signUsers', '请选择加签人员'));
      return;
    }
    if (requiresReason && !reason.trim()) {
      message.warning(t('itsm.todo.reasonRequired', '请填写操作原因'));
      return;
    }
    setSubmittingTask(true);
    try {
      const result = await post<{ planned: boolean }>(
        `/itsm/api/tasks/${activeTask.id}/act/`,
        {
          request_id: newRequestKey('task-action'),
          action: selectedAction,
          user_ids: userIds,
          reason,
        },
      );
      message.success(
        result.planned
          ? t('itsm.todo.planSuccess', '后加签计划已保存')
          : t('itsm.todo.submitSuccess', '操作已提交'),
      );
      setReason('');
      setUserIds([]);
      await load();
    } finally {
      setSubmittingTask(false);
    }
  };

  const formItems = useMemo(() => {
    if (!ticket) return [];
    return Object.entries(ticket.form_data).map(([key, value]) => {
      const fieldDef = ticket.form_schema.properties[key];
      const isLongText =
        fieldDef?.['x-widget'] === 'textarea' || String(value ?? '').length > 60;
      return {
        key,
        label: fieldDef?.title ?? key,
        value: Array.isArray(value) ? value.join('、') : String(value ?? '—'),
        isLongText,
      };
    });
  }, [ticket]);

  const close = async () => {
    if (!ticket) return;
    setClosing(true);
    try {
      setTicket(await post<TicketRecord>(`/itsm/api/tickets/${ticket.id}/close/`, {}));
      message.success(t('itsm.ticket.closeSuccess', '工单已关闭'));
    } finally {
      setClosing(false);
    }
  };

  const copyTicketNumber = async () => {
    if (!ticket?.number || typeof navigator === 'undefined' || !navigator.clipboard)
      return;
    await navigator.clipboard.writeText(ticket.number);
    message.success(t('itsm.ticket.copied', '工单编号已复制'));
  };

  const taskActionOptions = useMemo(() => {
    if (!activeTask) return [];
    if (activeTask.task_type !== 'APPROVAL') {
      return [
        {
          label: t('itsm.todo.complete', '处理完成'),
          value: 'complete_handling' as TaskAction,
        },
      ];
    }
    const opts: Array<{ label: string; value: TaskAction }> = [
      { label: t('itsm.todo.approve', '通过'), value: 'approve' },
      { label: t('itsm.todo.reject', '驳回'), value: 'reject' },
    ];
    if (activeTask.allow_before_sign && !activeTask.sign_parent_key) {
      opts.push({ label: t('itsm.todo.beforeSign', '前加签'), value: 'before_sign' });
    }
    if (activeTask.allow_after_sign && !activeTask.sign_parent_key) {
      opts.push({ label: t('itsm.todo.afterSign', '后加签'), value: 'after_sign' });
    }
    return opts;
  }, [activeTask, t]);

  const quickReasons = useMemo(() => {
    if (selectedAction === 'approve') {
      return [
        t('itsm.todo.quickApprove1', '同意，请按标准规范执行'),
        t('itsm.todo.quickApprove2', '已核实业务需求，审批通过'),
      ];
    }
    if (selectedAction === 'reject') {
      return [
        t('itsm.todo.quickReject1', '申请信息不完整，请补充后重新发起'),
        t('itsm.todo.quickReject2', '不符合当前资源/安全基线要求'),
      ];
    }
    if (selectedAction === 'before_sign' || selectedAction === 'after_sign') {
      return [
        t('itsm.todo.quickSign1', '请相关负责人协同评估确认'),
        t('itsm.todo.quickSign2', '涉及跨团队资源，请补充会审意见'),
      ];
    }
    return [t('itsm.todo.quickComplete1', '已按申请要求完成交付，请提单人确认')];
  }, [selectedAction, t]);

  const requiresUsers =
    selectedAction === 'before_sign' || selectedAction === 'after_sign';
  const actionLabel = t(`itsm.todo.${selectedAction}`, actionLabels[selectedAction]);

  return (
    <ITSMPageShell
      title={ticket?.number ?? t('itsm.ticket.detail', '工单详情')}
      description={
        ticket
          ? `${ticket.service_name} · ${String(
              ticket.form_data.summary ?? t('itsm.ticket.request', '服务申请'),
            )}`
          : undefined
      }
      actions={
        <>
          {ticket?.number ? (
            <Button
              size="middle"
              icon={<CopyOutlined />}
              onClick={() => void copyTicketNumber()}
            >
              {t('itsm.ticket.copyNumber', '复制单号')}
            </Button>
          ) : null}
          <Button
            aria-label={t('itsm.common.refresh', '刷新')}
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => void load()}
          />
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/itsm/tickets')}>
            {t('itsm.common.back', '返回')}
          </Button>
          {ticket?.status === 'WAITING_CONFIRMATION' ? (
            <Popconfirm
              title={t('itsm.ticket.closeHint', '确认处理结果符合预期并关闭工单？')}
              onConfirm={() => void close()}
            >
              <Button type="primary" icon={<CheckCircleOutlined />} loading={closing}>
                {t('itsm.ticket.close', '确认关闭')}
              </Button>
            </Popconfirm>
          ) : null}
        </>
      }
    >
      {failed ? (
        <Alert
          showIcon
          type="error"
          message={t('itsm.common.loadingFailed', '加载失败，请重试')}
          className="mb-4"
          action={
            <Button size="small" onClick={() => void load()}>
              {t('itsm.common.retry', '重试')}
            </Button>
          }
        />
      ) : null}
      {loading ? (
        <div className="space-y-4">
          <div className="rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] p-4">
            <Skeleton active title={{ width: '35%' }} paragraph={{ rows: 1 }} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <WorkbenchSection title={t('itsm.ticket.requestInfo', '申请内容')}>
              <Skeleton active paragraph={{ rows: 8 }} />
            </WorkbenchSection>
            <WorkbenchSection title={t('itsm.ticket.basicInfo', '工单信息')}>
              <Skeleton active paragraph={{ rows: 6 }} />
            </WorkbenchSection>
          </div>
        </div>
      ) : ticket ? (
        <div className="space-y-4">
          <TicketCompactProgressBanner
            status={ticket.status}
            workflow={ticket.workflow_config}
            activeStageKey={activeTask?.stage_key}
            auditEvents={ticket.audit_events}
            onOpenCanvasDrawer={() => setFlowDrawerOpen(true)}
          />

          <div className="flex min-w-0 flex-col items-start gap-4 lg:flex-row">
            <div className="min-w-0 w-full flex-1 space-y-4">
              {activeTask && activeTask.status === 'PENDING' ? (
                <WorkbenchSection
                  title={`${t('itsm.todo.operation', '处理操作')} · ${activeTask.title}`}
                  subtitle={
                    activeTask.task_type === 'APPROVAL'
                      ? t('itsm.todo.approvalTask', '审批任务')
                      : t('itsm.todo.handlingTask', '处理任务')
                  }
                  icon={<AuditOutlined />}
                  extra={
                    taskActionOptions.length > 1 ? (
                      <Segmented
                        size="small"
                        options={taskActionOptions}
                        value={selectedAction}
                        onChange={(val) => handleActionChange(val as TaskAction)}
                      />
                    ) : null
                  }
                >
                  <Form layout="vertical">
                    {requiresUsers ? (
                      <Form.Item label={t('itsm.todo.signUsers', '加签人员')} required>
                        <Select
                          mode="multiple"
                          showSearch
                          filterOption={false}
                          placeholder={t(
                            'itsm.todo.signUsersPlaceholder',
                            '请选择需要加签的人员',
                          )}
                          loading={userLoading}
                          value={userIds}
                          options={users.map((user) => ({
                            value: user.id,
                            label: user.display_name
                              ? `${user.display_name} (${user.username})`
                              : user.username,
                          }))}
                          onSearch={(val) => void searchUsers(val)}
                          onChange={setUserIds}
                        />
                      </Form.Item>
                    ) : null}
                    <Form.Item
                      label={t('itsm.todo.reason', '操作原因')}
                      required={selectedAction === 'reject' || requiresUsers}
                      extra={
                        selectedAction === 'approve'
                          ? t(
                              'itsm.todo.reasonOptional',
                              '可选，填写后将记录在工单流转记录中',
                            )
                          : undefined
                      }
                      className="mb-3"
                    >
                      <div className="mb-2 flex flex-wrap gap-1.5">
                        {quickReasons.map((preset) => (
                          <button
                            key={preset}
                            type="button"
                            className="cursor-pointer rounded border border-[var(--color-border-1)] bg-[var(--color-fill-1)]/50 px-2 py-0.5 text-xs text-[var(--color-text-2)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-primary)]"
                            onClick={() => setReason(preset)}
                          >
                            {preset}
                          </button>
                        ))}
                      </div>
                      <Input.TextArea
                        rows={3}
                        maxLength={500}
                        showCount
                        placeholder={t(
                          'itsm.todo.reasonPlaceholder',
                          '请输入审批或处理说明',
                        )}
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </Form.Item>
                    <div className="flex justify-end gap-2">
                      <Button
                        type="primary"
                        danger={selectedAction === 'reject'}
                        icon={
                          selectedAction === 'approve' ? (
                            <CheckOutlined />
                          ) : (
                            <SendOutlined />
                          )
                        }
                        loading={submittingTask}
                        onClick={() => void submitTaskAction()}
                      >
                        {actionLabel}
                      </Button>
                    </div>
                  </Form>
                </WorkbenchSection>
              ) : null}

              <WorkbenchSection
                title={t('itsm.ticket.requestInfo', '申请内容')}
                icon={<FileTextOutlined />}
                count={formItems.length}
              >
                <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
                  {formItems.map((item) => (
                    <div
                      key={item.key}
                      className={`min-w-0 rounded-md border border-[var(--color-border-1)] bg-[var(--color-fill-1)]/30 px-3.5 py-2.5 ${
                        item.isLongText ? 'md:col-span-2' : ''
                      }`}
                    >
                      <div className="text-xs font-medium text-[var(--color-text-3)]">
                        {item.label}
                      </div>
                      <div className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-[var(--color-text-1)]">
                        {item.value}
                      </div>
                    </div>
                  ))}
                </div>
              </WorkbenchSection>

              <WorkbenchSection
                title={t('itsm.ticket.auditTrail', '流转记录')}
                icon={<HistoryOutlined />}
                count={ticket.audit_events.length}
              >
                {ticket.audit_events.length ? (
                  <Timeline
                    items={ticket.audit_events.map((event) => ({
                      color:
                        event.to_status === 'REJECTED'
                          ? 'red'
                          : event.to_status === 'CLOSED'
                            ? 'green'
                            : 'blue',
                      children: (
                        <div className="pb-2">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-semibold text-[var(--color-text-1)]">
                                {t(`itsm.audit.${event.action}`, event.action)}
                              </span>
                              <span className="inline-flex items-center gap-1 rounded bg-[var(--color-fill-1)] px-2 py-0.5 text-xs text-[var(--color-text-2)]">
                                <UserOutlined className="text-[10px]" />
                                {event.actor_username ||
                                  t('itsm.ticket.system', '系统')}
                              </span>
                              {event.to_status ? (
                                <Tag className="!m-0 !text-[11px]">
                                  {t(
                                    `itsm.status.${event.to_status}`,
                                    event.to_status,
                                  )}
                                </Tag>
                              ) : null}
                            </div>
                            <span className="font-mono text-xs text-[var(--color-text-3)] tabular-nums">
                              {convertToLocalizedTime(event.created_at)}
                            </span>
                          </div>
                          {event.reason ? (
                            <div className="mt-2 rounded-md border border-[var(--color-border-1)] bg-[var(--color-fill-1)]/40 px-3 py-2 text-sm text-[var(--color-text-2)]">
                              {event.reason}
                            </div>
                          ) : null}
                        </div>
                      ),
                    }))}
                  />
                ) : (
                  <div className="py-6 text-center text-sm text-[var(--color-text-3)]">
                    {t('itsm.ticket.noAudit', '暂无流转记录')}
                  </div>
                )}
              </WorkbenchSection>
            </div>

            <div className="w-full shrink-0 space-y-4 lg:w-80">
              <WorkbenchSection
                title={t('itsm.ticket.basicInfo', '工单信息')}
                icon={<ApartmentOutlined />}
                bodyClassName="p-0"
                extra={<TicketStatusTag status={ticket.status} />}
              >
                <WorkbenchPropertyList
                  items={[
                    {
                      key: 'number',
                      label: t('itsm.ticket.number', '工单编号'),
                      value: ticket.number,
                      mono: true,
                    },
                    {
                      key: 'service',
                      label: t('itsm.ticket.service', '服务'),
                      value: ticket.service_name,
                    },
                    {
                      key: 'requester',
                      label: t('itsm.ticket.requester', '提单人'),
                      value: ticket.requester_username,
                    },
                    {
                      key: 'version',
                      label: t('itsm.ticket.version', '版本'),
                      value: `V${ticket.service_version_number}`,
                      mono: true,
                    },
                    {
                      key: 'created',
                      label: t('itsm.ticket.createdAt', '提交时间'),
                      value: convertToLocalizedTime(ticket.created_at),
                      mono: true,
                    },
                    {
                      key: 'updated',
                      label: t('itsm.ticket.updatedAt', '最近更新'),
                      value: convertToLocalizedTime(ticket.updated_at),
                      mono: true,
                    },
                  ]}
                />
              </WorkbenchSection>
            </div>
          </div>

          <TicketFlowDrawer
            open={flowDrawerOpen}
            onClose={() => setFlowDrawerOpen(false)}
            ticketNumber={ticket.number}
            serviceName={ticket.service_name}
            status={ticket.status}
            workflow={ticket.workflow_config}
            activeStageKey={activeTask?.stage_key}
            auditEvents={ticket.audit_events}
          />
        </div>
      ) : null}
    </ITSMPageShell>
  );
}
