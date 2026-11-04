'use client';

import { CheckOutlined, ReloadOutlined, StopOutlined, UserAddOutlined } from '@ant-design/icons';
import { Alert, App, Button, Descriptions, Empty, Form, Input, Modal, Select, Space, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useState } from 'react';

import CustomTable from '@/components/custom-table';
import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
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
      const response = await get<PageResponse<TaskRecord>>(
        `/itsm/api/tasks/?page=${pagination.current}&page_size=${pagination.pageSize}`,
      );
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
      const response = await get<UserListResponse>('/core/api/user_group/user_list/', {
        params: { page: 1, page_size: 100, search },
      });
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
      message.warning(t('itsm.todo.signUsers', '加签人员'));
      return;
    }
    if (requiresReason && !reason.trim()) {
      message.warning(t('itsm.todo.reason', '操作原因'));
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
      message.success(result.planned
        ? t('itsm.todo.planSuccess', '后加签计划已保存')
        : t('itsm.todo.submitSuccess', '操作已提交'));
      setOperation(undefined);
      await load();
    } finally {
      setSubmitting(false);
    }
  };

  const columns = useMemo<ColumnsType<TaskRecord>>(() => [
    { title: t('itsm.ticket.number', '工单编号'), dataIndex: 'ticket_number', width: 190 },
    { title: t('itsm.ticket.service', '服务'), dataIndex: 'service_name', ellipsis: true },
    { title: t('itsm.todo.currentNode', '当前节点'), dataIndex: 'title', ellipsis: true },
    {
      title: t('itsm.ticket.createdAt', '提交时间'),
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => convertToLocalizedTime(value),
    },
    {
      title: t('itsm.todo.actions', '操作'),
      key: 'actions',
      width: 360,
      render: (_, task) => task.status === 'SUBMITTING' ? <Tag color="processing">{t('itsm.todo.submitting', '提交中')}</Tag> : (
        <Space size={4} wrap>
          {task.task_type === 'APPROVAL' ? (
            <>
              <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => openAction(task, 'approve')}>{t('itsm.todo.approve', '通过')}</Button>
              <Button type="link" size="small" danger icon={<StopOutlined />} onClick={() => openAction(task, 'reject')}>{t('itsm.todo.reject', '驳回')}</Button>
              {task.allow_before_sign && !task.sign_parent_key ? <Button type="link" size="small" icon={<UserAddOutlined />} onClick={() => openAction(task, 'before_sign')}>{t('itsm.todo.beforeSign', '前加签')}</Button> : null}
              {task.allow_after_sign && !task.sign_parent_key ? <Button type="link" size="small" icon={<UserAddOutlined />} onClick={() => openAction(task, 'after_sign')}>{t('itsm.todo.afterSign', '后加签')}</Button> : null}
            </>
          ) : (
            <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => openAction(task, 'complete_handling')}>{t('itsm.todo.complete', '处理完成')}</Button>
          )}
        </Space>
      ),
    },
  ], [convertToLocalizedTime, t]);

  const requestItems = operation ? Object.entries(operation.task.form_data).map(([key, value]) => ({
    key,
    label: operation.task.form_schema.properties[key]?.title ?? key,
    children: Array.isArray(value) ? value.join('、') : String(value ?? '—'),
  })) : [];

  return (
    <ITSMPageShell
      title={t('itsm.todo.title', '我的待办')}
      description={t('itsm.todo.description', '处理审批、前后加签与执行任务')}
      actions={<Button aria-label={t('itsm.common.refresh', '刷新')} icon={<ReloadOutlined />} onClick={() => void load()} />}
    >
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" /> : null}
      <div className="rounded-md bg-[var(--color-bg)] p-4">
        <CustomTable
          rowKey="id"
          columns={columns}
          dataSource={records}
          loading={loading}
          locale={{ emptyText: <Empty description={t('itsm.todo.empty', '暂无待处理任务')} /> }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: count,
            showSizeChanger: true,
            onChange: (current, pageSize) => setPagination({ current, pageSize }),
          }}
        />
      </div>
      <Modal
        open={Boolean(operation)}
        title={operation ? t(`itsm.todo.${operation.action}`, actionLabels[operation.action]) : ''}
        okText={t('itsm.common.confirm', '确定')}
        cancelText={t('itsm.common.cancel', '取消')}
        confirmLoading={submitting}
        width={680}
        onOk={() => void submitAction()}
        onCancel={() => setOperation(undefined)}
      >
        {operation ? (
          <div className="max-h-[65vh] space-y-4 overflow-y-auto py-2">
            <Descriptions bordered column={1} size="small" items={requestItems} />
            <Form layout="vertical">
              {operation.action === 'before_sign' || operation.action === 'after_sign' ? (
                <Form.Item label={t('itsm.todo.signUsers', '加签人员')} required>
                  <Select
                    mode="multiple"
                    showSearch
                    filterOption={false}
                    loading={userLoading}
                    value={userIds}
                    options={users.map((user) => ({
                      value: user.id,
                      label: user.display_name ? `${user.display_name} (${user.username})` : user.username,
                    }))}
                    onSearch={(value) => void searchUsers(value)}
                    onChange={setUserIds}
                  />
                </Form.Item>
              ) : null}
              <Form.Item
                label={t('itsm.todo.reason', '操作原因')}
                required={operation.action === 'reject' || operation.action === 'before_sign' || operation.action === 'after_sign'}
              >
                <Input.TextArea rows={3} maxLength={500} showCount value={reason} onChange={(event) => setReason(event.target.value)} />
              </Form.Item>
            </Form>
          </div>
        ) : null}
      </Modal>
    </ITSMPageShell>
  );
}
