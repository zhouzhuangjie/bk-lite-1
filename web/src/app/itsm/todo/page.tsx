'use client';

import { CheckOutlined, DownOutlined, ReloadOutlined, StopOutlined, UserAddOutlined } from '@ant-design/icons';
import { Alert, App, Button, Drawer, Dropdown, Empty, Form, Input, Select, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import CustomTable from '@/components/custom-table';
import EllipsisWithTooltip from '@/components/ellipsis-with-tooltip';
import ToolbarSplitShell from '@/components/toolbar-split-shell';
import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
import { ITSMTableSurface } from '../components/table-surface';
import { WorkbenchPropertyList, WorkbenchSection } from '../components/workbench-section';
import { newRequestKey } from '../lib/status';
import type { PageResponse, TaskRecord, UserOption } from '../lib/types';

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

export default function TodoPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { convertToLocalizedTime } = useLocalizedTime();
  const { get, post } = useApiClient();
  const router = useRouter();
  const [records, setRecords] = useState<TaskRecord[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [operation, setOperation] = useState<{ task: TaskRecord; action: TaskAction }>();
  const [reason, setReason] = useState('');
  const [userIds, setUserIds] = useState<number[]>([]);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [userLoading, setUserLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const response = await get<PageResponse<TaskRecord>>(`/itsm/api/tasks/?page=${pagination.current}&page_size=${pagination.pageSize}`);
      setRecords(response.items ?? []);
      setCount(response.count ?? 0);
    } catch {
      setFailed(true);
      setRecords([]);
      setCount(0);
    } finally {
      setLoading(false);
    }
  }, [get, pagination.current, pagination.pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const searchUsers = useCallback(async (search = '') => {
    setUserLoading(true);
    try {
      const response = await get<UserListResponse>('/core/api/user_group/user_list/', { params: { page: 1, page_size: 100, search } });
      setUsers(response.users ?? []);
    } finally {
      setUserLoading(false);
    }
  }, [get]);

  const openAction = (task: TaskRecord, action: TaskAction) => {
    setReason('');
    setUserIds([]);
    setOperation({ task, action });
    if (action === 'before_sign' || action === 'after_sign') void searchUsers();
  };

  const submitAction = async () => {
    if (!operation) return;
    const requiresUsers = operation.action === 'before_sign' || operation.action === 'after_sign';
    const requiresReason = operation.action === 'reject' || requiresUsers;
    if (requiresUsers && !userIds.length) {
      message.warning(t('itsm.todo.signUsers', '请选择加签人员'));
      return;
    }
    if (requiresReason && !reason.trim()) {
      message.warning(t('itsm.todo.reasonRequired', '请填写操作原因'));
      return;
    }
    setSubmitting(true);
    try {
      const result = await post<{ planned: boolean }>(`/itsm/api/tasks/${operation.task.id}/act/`, {
        request_id: newRequestKey('task-action'),
        action: operation.action,
        user_ids: userIds,
        reason,
      });
      message.success(result.planned ? t('itsm.todo.planSuccess', '后加签计划已保存') : t('itsm.todo.submitSuccess', '操作已提交'));
      setOperation(undefined);
      await load();
    } finally {
      setSubmitting(false);
    }
  };

  const columns = useMemo<ColumnsType<TaskRecord>>(() => [
    {
      title: t('itsm.ticket.number', '工单编号'),
      dataIndex: 'ticket_number',
      width: 230,
      render: (value: string, task) => (
        <div className="min-w-0">
          <button className="block max-w-full truncate border-0 bg-transparent p-0 text-left font-mono text-sm font-medium text-[var(--color-text-1)] hover:text-[var(--color-primary)] hover:underline" onClick={(event) => { event.stopPropagation(); router.push(`/itsm/tickets/${task.ticket_id}`); }}>
            {value}
          </button>
          <div className="mt-0.5 truncate text-xs text-[var(--color-text-3)]">{String(task.form_data.summary ?? task.service_name)}</div>
        </div>
      ),
    },
    { title: t('itsm.ticket.service', '服务'), dataIndex: 'service_name', render: (value: string) => <EllipsisWithTooltip text={value} className="block truncate" /> },
    {
      title: t('itsm.todo.currentNode', '当前节点'),
      dataIndex: 'title',
      width: 180,
      render: (value: string, task) => (
        <div>
          <div className="text-sm text-[var(--color-text-1)]">{value}</div>
          <div className="mt-0.5 text-xs text-[var(--color-text-3)]">{task.task_type === 'APPROVAL' ? t('itsm.todo.approvalTask', '审批任务') : t('itsm.todo.handlingTask', '处理任务')}</div>
        </div>
      ),
    },
    { title: t('itsm.ticket.requester', '提单人'), dataIndex: 'requester_username', width: 120 },
    { title: t('itsm.ticket.createdAt', '提交时间'), dataIndex: 'created_at', width: 180, className: 'tabular-nums', render: (value: string) => convertToLocalizedTime(value) },
    {
      title: t('itsm.todo.actions', '操作'),
      key: 'actions',
      width: 250,
      fixed: 'right',
      render: (_, task) => task.status === 'SUBMITTING' ? <Tag color="processing">{t('itsm.todo.submitting', '提交中')}</Tag> : (
        <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
          {task.task_type === 'APPROVAL' ? (
            <>
              <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => openAction(task, 'approve')}>{t('itsm.todo.approve', '通过')}</Button>
              <Button type="link" size="small" danger icon={<StopOutlined />} onClick={() => openAction(task, 'reject')}>{t('itsm.todo.reject', '驳回')}</Button>
              {(task.allow_before_sign || task.allow_after_sign) && !task.sign_parent_key ? (
                <Dropdown
                  menu={{ items: [
                    ...(task.allow_before_sign ? [{ key: 'before', label: t('itsm.todo.beforeSign', '前加签'), onClick: () => openAction(task, 'before_sign') }] : []),
                    ...(task.allow_after_sign ? [{ key: 'after', label: t('itsm.todo.afterSign', '后加签'), onClick: () => openAction(task, 'after_sign') }] : []),
                  ] }}
                >
                  <Button type="link" size="small" icon={<UserAddOutlined />}>{t('itsm.todo.sign', '加签')} <DownOutlined className="text-[10px]" /></Button>
                </Dropdown>
              ) : null}
            </>
          ) : <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => openAction(task, 'complete_handling')}>{t('itsm.todo.complete', '处理完成')}</Button>}
        </div>
      ),
    },
  ], [convertToLocalizedTime, router, t]);

  const requestItems = operation ? Object.entries(operation.task.form_data).map(([key, value]) => ({
    key,
    label: operation.task.form_schema.properties[key]?.title ?? key,
    value: Array.isArray(value) ? value.join('、') : String(value ?? '—'),
  })) : [];
  const requiresUsers = operation?.action === 'before_sign' || operation?.action === 'after_sign';
  const actionLabel = operation ? t(`itsm.todo.${operation.action}`, actionLabels[operation.action]) : '';

  return (
    <ITSMPageShell title={t('itsm.todo.title', '我的待办')} description={t('itsm.todo.description', '处理审批、前后加签与执行任务')}>
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" action={<Button size="small" onClick={() => void load()}>{t('itsm.common.retry', '重试')}</Button>} /> : null}
      <ITSMTableSurface toolbar={
        <ToolbarSplitShell
          leading={<span className="text-xs text-[var(--color-text-3)]">{t('itsm.todo.pendingCount', '当前共有 {count} 条待处理任务', { count })}</span>}
          trailing={<Button aria-label={t('itsm.common.refresh', '刷新')} icon={<ReloadOutlined />} loading={loading} onClick={() => void load()} />}
        />
      }>
        <CustomTable
          rowKey="id"
          scroll={{ y: 'auto' }}
          columns={columns}
          dataSource={records}
          loading={loading}
          locale={{ emptyText: <Empty description={t('itsm.todo.empty', '暂无待处理任务')} /> }}
          onRow={(record) => ({
            onClick: () => router.push(`/itsm/tickets/${record.ticket_id}`),
            className: 'cursor-pointer transition-colors hover:bg-[var(--color-fill-2)]',
          })}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: count,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: (total) => t('itsm.common.total', '共 {total} 条', { total }),
            onChange: (current, pageSize) => setPagination({ current, pageSize }),
          }}
        />
      </ITSMTableSurface>
      <Drawer
        open={Boolean(operation)}
        title={operation ? `${actionLabel} · ${operation.task.ticket_number}` : ''}
        width={560}
        destroyOnClose
        onClose={() => setOperation(undefined)}
        footer={(
          <div className="flex justify-end gap-2">
            <Button onClick={() => setOperation(undefined)}>{t('itsm.common.cancel', '取消')}</Button>
            <Button type="primary" danger={operation?.action === 'reject'} loading={submitting} onClick={() => void submitAction()}>{actionLabel}</Button>
          </div>
        )}
      >
        {operation ? (
          <div className="space-y-4">
            <WorkbenchSection title={t('itsm.todo.taskOverview', '任务概览')} bodyClassName="p-0">
              <WorkbenchPropertyList items={[
                { key: 'service', label: t('itsm.ticket.service', '服务'), value: operation.task.service_name },
                { key: 'node', label: t('itsm.todo.currentNode', '当前节点'), value: operation.task.title },
                { key: 'requester', label: t('itsm.ticket.requester', '提单人'), value: operation.task.requester_username },
                { key: 'created', label: t('itsm.ticket.createdAt', '提交时间'), value: convertToLocalizedTime(operation.task.created_at), mono: true },
              ]} />
            </WorkbenchSection>
            <WorkbenchSection title={t('itsm.ticket.requestInfo', '申请内容')} count={requestItems.length}>
              <div className="space-y-4">
                {requestItems.map((item) => (
                  <div key={item.key}>
                    <div className="text-xs font-medium text-[var(--color-text-3)]">{item.label}</div>
                    <div className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-[var(--color-text-1)]">{item.value}</div>
                  </div>
                ))}
              </div>
            </WorkbenchSection>
            <WorkbenchSection title={t('itsm.todo.operation', '处理操作')}>
              <Form layout="vertical">
                {requiresUsers ? (
                  <Form.Item label={t('itsm.todo.signUsers', '加签人员')} required>
                    <Select
                      mode="multiple"
                      showSearch
                      filterOption={false}
                      placeholder={t('itsm.todo.signUsersPlaceholder', '请选择需要加签的人员')}
                      loading={userLoading}
                      value={userIds}
                      options={users.map((user) => ({ value: user.id, label: user.display_name ? `${user.display_name} (${user.username})` : user.username }))}
                      onSearch={(value) => void searchUsers(value)}
                      onChange={setUserIds}
                    />
                  </Form.Item>
                ) : null}
                <Form.Item
                  label={t('itsm.todo.reason', '操作原因')}
                  required={operation.action === 'reject' || requiresUsers}
                  extra={operation.action === 'approve' ? t('itsm.todo.reasonOptional', '可选，填写后将记录在工单流转记录中') : undefined}
                  className="mb-0"
                >
                  <Input.TextArea rows={4} maxLength={500} showCount value={reason} onChange={(event) => setReason(event.target.value)} />
                </Form.Item>
              </Form>
            </WorkbenchSection>
          </div>
        ) : null}
      </Drawer>
    </ITSMPageShell>
  );
}
