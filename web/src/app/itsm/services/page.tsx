'use client';

import {
  ApartmentOutlined,
  EditOutlined,
  HistoryOutlined,
  PlusOutlined,
  ReloadOutlined,
  StopOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Segmented,
  Skeleton,
  Tag,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import CustomTable from '@/components/custom-table';
import MoreActionsDropdown from '@/components/more-actions-dropdown';
import SearchActionBar from '@/components/search-action-bar';
import ToolbarSplitShell from '@/components/toolbar-split-shell';
import { useUserInfoContext } from '@/context/userInfo';
import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
import { ITSMTableSurface } from '../components/table-surface';
import type {
  JsonSchema,
  PageResponse,
  ServiceRecord,
  ServiceVersionRecord,
  WorkflowConfig,
} from '../lib/types';

type ServiceStatusFilter = 'ALL' | 'PUBLISHED' | 'DRAFT' | 'DISABLED';

const defaultSchema: JsonSchema = {
  type: 'object',
  properties: {
    summary: {
      type: 'string',
      title: '申请摘要',
      maxLength: 120,
      'x-widget': 'input',
    },
    description: {
      type: 'string',
      title: '申请说明',
      maxLength: 2000,
      'x-widget': 'textarea',
    },
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
  const [statusFilter, setStatusFilter] = useState<ServiceStatusFilter>('ALL');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const [versionService, setVersionService] = useState<ServiceRecord>();
  const [versions, setVersions] = useState<ServiceVersionRecord[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const params = new URLSearchParams({
        page: String(pagination.current),
        page_size: String(pagination.pageSize),
      });
      if (query.trim()) params.set('search', query.trim());
      const response = await get<PageResponse<ServiceRecord>>(
        `/itsm/api/services/?${params.toString()}`,
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
  }, [get, pagination.current, pagination.pageSize, query]);

  useEffect(() => {
    void load();
  }, [load]);

  const openVersionDrawer = useCallback(
    async (service: ServiceRecord) => {
      setVersionService(service);
      setVersionsLoading(true);
      try {
        const res = await get<PageResponse<ServiceVersionRecord>>(
          `/itsm/api/services/${service.id}/versions/?page_size=50`,
        );
        setVersions(res.items ?? []);
      } catch {
        setVersions([]);
      } finally {
        setVersionsLoading(false);
      }
    },
    [get],
  );

  const create = async () => {
    const actorId = Number(userId);
    if (!name.trim() || !Number.isInteger(actorId) || actorId <= 0) return;
    const workflow: WorkflowConfig = {
      schemaVersion: 1,
      stages: [
        {
          key: 'approval_1',
          name: t('itsm.service.approval', '审批'),
          mode: 'serial',
          approverIds: [actorId],
          allowBeforeSign: true,
          allowAfterSign: true,
        },
      ],
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
            summary: {
              ...defaultSchema.properties.summary,
              title: t('itsm.service.requestSummary', '申请摘要'),
            },
            description: {
              ...defaultSchema.properties.description,
              title: t('itsm.service.requestDescription', '申请说明'),
            },
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

  const disableService = useCallback(
    async (service: ServiceRecord) => {
      await post<ServiceRecord>(`/itsm/api/services/${service.id}/disable/`, {});
      message.success(t('itsm.service.disableSuccess', '服务已停用'));
      await load();
    },
    [load, message, post, t],
  );

  const statusLabel = useCallback(
    (value: ServiceRecord['status']) => {
      if (value === 'PUBLISHED') return t('itsm.service.published', '已发布');
      if (value === 'DISABLED') return t('itsm.service.disabled', '已停用');
      return t('itsm.service.draft', '草稿');
    },
    [t],
  );

  const filteredRecords = useMemo(() => {
    if (statusFilter === 'ALL') return records;
    return records.filter((item) => item.status === statusFilter);
  }, [records, statusFilter]);

  const statusFilterOptions = useMemo(
    () => [
      { label: t('itsm.common.all', '全部'), value: 'ALL' },
      { label: t('itsm.service.published', '已发布'), value: 'PUBLISHED' },
      { label: t('itsm.service.draft', '草稿'), value: 'DRAFT' },
      { label: t('itsm.service.disabled', '已停用'), value: 'DISABLED' },
    ],
    [t],
  );

  const columns = useMemo<ColumnsType<ServiceRecord>>(
    () => [
      {
        title: t('itsm.service.name', '服务名称'),
        dataIndex: 'name',
        render: (value: string, record) => (
          <div className="min-w-0">
            <button
              className="block max-w-full truncate border-0 bg-transparent p-0 text-left text-sm font-semibold text-[var(--color-text-1)] hover:text-[var(--color-primary)] hover:underline"
              onClick={(event) => {
                event.stopPropagation();
                router.push(`/itsm/services/${record.id}`);
              }}
            >
              {value}
            </button>
            <div className="mt-0.5 max-w-xl truncate text-xs text-[var(--color-text-3)]">
              {record.description || '—'}
            </div>
          </div>
        ),
      },
      {
        title: t('itsm.service.status', '状态'),
        dataIndex: 'status',
        width: 190,
        render: (value: ServiceRecord['status'], record) => (
          <div className="flex flex-wrap gap-1">
            <Tag
              color={
                value === 'PUBLISHED'
                  ? 'success'
                  : value === 'DISABLED'
                    ? 'error'
                    : 'default'
              }
            >
              {statusLabel(value)}
            </Tag>
            {record.has_draft && record.current_version > 0 ? (
              <Tag color="gold">{t('itsm.service.hasDraft', '有未发布更改')}</Tag>
            ) : null}
          </div>
        ),
      },
      {
        title: t('itsm.service.designSummary', '设计内容'),
        key: 'design',
        width: 240,
        render: (_, record) => {
          const stages = record.workflow_config.stages;
          const stageNames = stages.map((stage) => stage.name).filter(Boolean);
          return (
            <div className="min-w-0">
              <div className="text-xs font-medium text-[var(--color-text-2)]">
                {t(
                  'itsm.service.designCounts',
                  '{fields} 个字段 · {stages} 个审批节点',
                  {
                    fields: Object.keys(record.form_schema.properties).length,
                    stages: stages.length,
                  },
                )}
              </div>
              {stageNames.length > 0 ? (
                <div className="mt-0.5 flex items-center gap-1 truncate text-[11px] text-[var(--color-text-3)]">
                  <ApartmentOutlined className="shrink-0 text-[10px]" />
                  <span className="truncate">{stageNames.join(' → ')}</span>
                </div>
              ) : null}
            </div>
          );
        },
      },
      {
        title: t('itsm.service.currentVersion', '当前版本'),
        dataIndex: 'current_version',
        width: 110,
        className: 'tabular-nums',
        render: (value: number) => (value > 0 ? `V${value}` : '—'),
      },
      {
        title: t('itsm.service.updatedAt', '更新时间'),
        dataIndex: 'updated_at',
        width: 180,
        className: 'tabular-nums',
        render: (value: string) => convertToLocalizedTime(value),
      },
      {
        title: t('itsm.service.actions', '操作'),
        key: 'action',
        width: 190,
        fixed: 'right',
        render: (_, record) => (
          <div
            className="flex items-center gap-1"
            onClick={(event) => event.stopPropagation()}
          >
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => router.push(`/itsm/services/${record.id}`)}
            >
              {t('itsm.service.edit', '编辑')}
            </Button>
            <Button
              type="link"
              size="small"
              icon={<HistoryOutlined />}
              onClick={() => void openVersionDrawer(record)}
            >
              {t('itsm.service.versions', '发布版本')}
            </Button>
            {record.status === 'PUBLISHED' ? (
              <MoreActionsDropdown
                labelAlign="start"
                stopPropagation
                items={[
                  {
                    key: 'disable',
                    label: t('itsm.service.disable', '停用'),
                    icon: <StopOutlined />,
                    danger: true,
                    confirm: {
                      title: t(
                        'itsm.service.disableConfirm',
                        '停用后将无法从服务目录发起新工单，确认继续？',
                      ),
                    },
                    onClick: () => disableService(record),
                  },
                ]}
              />
            ) : null}
          </div>
        ),
      },
    ],
    [convertToLocalizedTime, disableService, openVersionDrawer, router, statusLabel, t],
  );

  return (
    <ITSMPageShell
      title={t('itsm.service.title', '服务管理')}
      description={t(
        'itsm.service.description',
        '设计表单与人工审批流程，发布后进入服务目录',
      )}
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
      <ITSMTableSurface
        toolbar={
          <ToolbarSplitShell
            leading={
              <Segmented
                options={statusFilterOptions}
                value={statusFilter}
                onChange={(val) => setStatusFilter(val as ServiceStatusFilter)}
              />
            }
            trailing={
              <SearchActionBar
                className="!mb-0"
                searchProps={{
                  placeholder: t('itsm.service.search', '搜索服务名称'),
                  value: query,
                  onChange: (event) => setQuery(event.target.value),
                  onSearch: (value) => {
                    setPagination((current) => ({ ...current, current: 1 }));
                    setQuery(value);
                  },
                }}
                actions={
                  <>
                    <Button
                      aria-label={t('itsm.common.refresh', '刷新')}
                      icon={<ReloadOutlined />}
                      loading={loading}
                      onClick={() => void load()}
                    />
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => setCreateOpen(true)}
                    >
                      {t('common.new', '新建')}
                    </Button>
                  </>
                }
              />
            }
          />
        }
      >
        <CustomTable
          rowKey="id"
          scroll={{ y: 'auto' }}
          columns={columns}
          dataSource={filteredRecords}
          loading={loading}
          locale={{
            emptyText: (
              <Empty
                description={
                  query || statusFilter !== 'ALL'
                    ? t('itsm.service.noMatch', '没有匹配的服务')
                    : t('itsm.service.empty', '暂无服务')
                }
              />
            ),
          }}
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
          <Alert
            className="mb-4"
            type="info"
            showIcon
            message={t(
              'itsm.service.createHint',
              '先创建服务草稿，再配置表单、流程并发布。',
            )}
          />
          <Form.Item label={t('itsm.service.name', '服务名称')} required>
            <Input
              autoFocus
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Form.Item>
          <Form.Item label={t('itsm.service.descriptionLabel', '服务说明')}>
            <Input.TextArea
              rows={3}
              maxLength={500}
              showCount
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        open={Boolean(versionService)}
        title={
          versionService
            ? `${t('itsm.service.versions', '发布版本')} · ${versionService.name}`
            : ''
        }
        width={480}
        destroyOnClose
        onClose={() => setVersionService(undefined)}
      >
        {versionsLoading ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : versions.length ? (
          <div className="space-y-3">
            {versions.map((ver) => (
              <div
                key={ver.id}
                className="rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] p-3.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-bold text-[var(--color-text-1)] tabular-nums">
                      V{ver.version}
                    </span>
                    <Tag
                      color={
                        ver.publish_status === 'READY'
                          ? 'success'
                          : ver.publish_status === 'FAILED'
                            ? 'error'
                            : 'processing'
                      }
                    >
                      {ver.publish_status}
                    </Tag>
                    {versionService?.current_version === ver.version ? (
                      <Tag color="blue">{t('itsm.service.onlineVersion', '线上版本')}</Tag>
                    ) : null}
                  </div>
                  <span className="font-mono text-xs text-[var(--color-text-3)] tabular-nums">
                    {convertToLocalizedTime(ver.created_at)}
                  </span>
                </div>
                <div className="mt-2 flex items-center justify-between text-xs text-[var(--color-text-3)]">
                  <span>
                    {t(
                      'itsm.service.designCounts',
                      '{fields} 个字段 · {stages} 个审批节点',
                      {
                        fields: Object.keys(ver.form_schema?.properties ?? {}).length,
                        stages: ver.workflow_config?.stages?.length ?? 0,
                      },
                    )}
                  </span>
                  <span>{ver.created_by}</span>
                </div>
                {ver.publish_error ? (
                  <div className="mt-2 rounded bg-[color-mix(in_srgb,var(--color-fail)_10%,var(--color-bg))] px-2.5 py-1.5 text-xs text-[var(--color-fail)]">
                    {ver.publish_error}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <Empty description={t('itsm.service.noVersions', '尚未发布任何版本')} />
        )}
      </Drawer>
    </ITSMPageShell>
  );
}
