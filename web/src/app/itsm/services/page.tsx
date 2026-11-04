'use client';

import { EditOutlined, PlusOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons';
import { Alert, App, Button, Empty, Form, Input, Modal, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import CustomTable from '@/components/custom-table';
import MoreActionsDropdown from '@/components/more-actions-dropdown';
import SearchActionBar from '@/components/search-action-bar';
import { useUserInfoContext } from '@/context/userInfo';
import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
import { ITSMTableSurface } from '../components/table-surface';
import type { JsonSchema, PageResponse, ServiceRecord, WorkflowConfig } from '../lib/types';

const defaultSchema: JsonSchema = {
  type: 'object',
  properties: {
    summary: { type: 'string', title: '申请摘要', maxLength: 120, 'x-widget': 'input' },
    description: { type: 'string', title: '申请说明', maxLength: 2000, 'x-widget': 'textarea' },
  },
  required: ['summary'],
  additionalProperties: false,
};

export default function ServiceListPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { convertToLocalizedTime } = useLocalizedTime();
  const { userId } = useUserInfoContext();
  const { get, post } = useApiClient();
  const router = useRouter();
  const [records, setRecords] = useState<ServiceRecord[]>([]);
  const [count, setCount] = useState(0);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const params = new URLSearchParams({ page: String(pagination.current), page_size: String(pagination.pageSize) });
      if (query.trim()) params.set('search', query.trim());
      const response = await get<PageResponse<ServiceRecord>>(`/itsm/api/services/?${params.toString()}`);
      setRecords(response.items ?? []);
      setCount(response.count ?? 0);
    } catch {
      setFailed(true);
      setRecords([]);
      setCount(0);
    } finally {
      setLoading(false);
    }
  }, [get, pagination.current, pagination.pageSize, query]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    const actorId = Number(userId);
    if (!name.trim() || !Number.isInteger(actorId) || actorId <= 0) return;
    const workflow: WorkflowConfig = {
      schemaVersion: 1,
      stages: [{
        key: 'approval_1',
        name: t('itsm.service.approval', '审批'),
        mode: 'serial',
        approverIds: [actorId],
        allowBeforeSign: true,
        allowAfterSign: true,
      }],
      handlerIds: [actorId],
    };
    setCreating(true);
    try {
      const service = await post<ServiceRecord>('/itsm/api/services/', {
        name: name.trim(),
        description: description.trim(),
        form_schema: {
          ...defaultSchema,
          properties: {
            summary: { ...defaultSchema.properties.summary, title: t('itsm.service.requestSummary', '申请摘要') },
            description: { ...defaultSchema.properties.description, title: t('itsm.service.requestDescription', '申请说明') },
          },
        },
        workflow_config: workflow,
      });
      message.success(t('itsm.service.saveSuccess', '草稿已保存'));
      setCreateOpen(false);
      setName('');
      setDescription('');
      router.push(`/itsm/services/${service.id}`);
    } finally {
      setCreating(false);
    }
  };

  const disableService = async (service: ServiceRecord) => {
    await post<ServiceRecord>(`/itsm/api/services/${service.id}/disable/`, {});
    message.success(t('itsm.service.disableSuccess', '服务已停用'));
    await load();
  };

  const statusLabel = useCallback((value: ServiceRecord['status']) => {
    if (value === 'PUBLISHED') return t('itsm.service.published', '已发布');
    if (value === 'DISABLED') return t('itsm.service.disabled', '已停用');
    return t('itsm.service.draft', '草稿');
  }, [t]);

  const columns = useMemo<ColumnsType<ServiceRecord>>(() => [
    {
      title: t('itsm.service.name', '服务名称'),
      dataIndex: 'name',
      render: (value: string, record) => (
        <div className="min-w-0">
          <button className="block max-w-full truncate border-0 bg-transparent p-0 text-left text-sm font-medium text-[var(--color-text-1)] hover:text-[var(--color-primary)] hover:underline" onClick={(event) => { event.stopPropagation(); router.push(`/itsm/services/${record.id}`); }}>
            {value}
          </button>
          <div className="mt-0.5 max-w-xl truncate text-xs text-[var(--color-text-3)]">{record.description || '—'}</div>
        </div>
      ),
    },
    {
      title: t('itsm.service.status', '状态'),
      dataIndex: 'status',
      width: 180,
      render: (value: ServiceRecord['status'], record) => (
        <div className="flex flex-wrap gap-1">
          <Tag color={value === 'PUBLISHED' ? 'success' : value === 'DISABLED' ? 'error' : 'default'}>{statusLabel(value)}</Tag>
          {record.has_draft && record.current_version > 0 ? <Tag color="gold">{t('itsm.service.hasDraft', '有未发布更改')}</Tag> : null}
        </div>
      ),
    },
    {
      title: t('itsm.service.designSummary', '设计内容'),
      key: 'design',
      width: 210,
      render: (_, record) => (
        <span className="text-xs text-[var(--color-text-2)]">
          {t('itsm.service.designCounts', '{fields} 个字段 · {stages} 个审批节点', {
            fields: Object.keys(record.form_schema.properties).length,
            stages: record.workflow_config.stages.length,
          })}
        </span>
      ),
    },
    {
      title: t('itsm.service.currentVersion', '当前版本'),
      dataIndex: 'current_version',
      width: 110,
      className: 'tabular-nums',
      render: (value: number) => value > 0 ? `V${value}` : '—',
    },
    { title: t('itsm.service.updatedAt', '更新时间'), dataIndex: 'updated_at', width: 180, className: 'tabular-nums', render: (value: string) => convertToLocalizedTime(value) },
    {
      title: t('itsm.service.actions', '操作'),
      key: 'action',
      width: 120,
      fixed: 'right',
      render: (_, record) => (
        <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => router.push(`/itsm/services/${record.id}`)}>{t('itsm.service.edit', '编辑')}</Button>
          {record.status === 'PUBLISHED' ? (
            <MoreActionsDropdown
              labelAlign="start"
              stopPropagation
              items={[{
                key: 'disable',
                label: t('itsm.service.disable', '停用'),
                icon: <StopOutlined />,
                danger: true,
                confirm: { title: t('itsm.service.disableConfirm', '停用后将无法从服务目录发起新工单，确认继续？') },
                onClick: () => disableService(record),
              }]}
            />
          ) : null}
        </div>
      ),
    },
  ], [convertToLocalizedTime, router, statusLabel, t]);

  return (
    <ITSMPageShell title={t('itsm.service.title', '服务管理')} description={t('itsm.service.description', '设计表单与人工审批流程，发布后进入服务目录')}>
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" action={<Button size="small" onClick={() => void load()}>{t('itsm.common.retry', '重试')}</Button>} /> : null}
      <ITSMTableSurface toolbar={
        <SearchActionBar
          searchProps={{
            placeholder: t('itsm.service.search', '搜索服务名称'),
            value: query,
            onChange: (event) => setQuery(event.target.value),
            onSearch: (value) => { setPagination((current) => ({ ...current, current: 1 })); setQuery(value); },
          }}
          actions={(
            <>
              <Button aria-label={t('itsm.common.refresh', '刷新')} icon={<ReloadOutlined />} loading={loading} onClick={() => void load()} />
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>{t('common.new', '新建')}</Button>
            </>
          )}
        />
      }>
        <CustomTable
          rowKey="id"
          scroll={{ y: 'auto' }}
          columns={columns}
          dataSource={records}
          loading={loading}
          locale={{ emptyText: <Empty description={query ? t('itsm.service.noMatch', '没有匹配的服务') : t('itsm.service.empty', '暂无服务')} /> }}
          onRow={(record) => ({
            onClick: () => router.push(`/itsm/services/${record.id}`),
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
      <Modal
        open={createOpen}
        title={t('itsm.service.create', '新建服务')}
        okText={t('itsm.common.confirm', '确定')}
        cancelText={t('itsm.common.cancel', '取消')}
        confirmLoading={creating}
        okButtonProps={{ disabled: !name.trim() || !userId }}
        onOk={() => void create()}
        onCancel={() => setCreateOpen(false)}
      >
        <Form layout="vertical" className="pt-2">
          <Alert className="mb-4" type="info" showIcon message={t('itsm.service.createHint', '先创建服务草稿，再配置表单、流程并发布。')} />
          <Form.Item label={t('itsm.service.name', '服务名称')} required>
            <Input autoFocus maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
          </Form.Item>
          <Form.Item label={t('itsm.service.descriptionLabel', '服务说明')}>
            <Input.TextArea rows={3} maxLength={500} showCount value={description} onChange={(event) => setDescription(event.target.value)} />
          </Form.Item>
        </Form>
      </Modal>
    </ITSMPageShell>
  );
}
