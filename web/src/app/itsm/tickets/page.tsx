'use client';

import {
  AuditOutlined,
  CheckCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Alert, App, Badge, Button, Empty, Popconfirm, Segmented, Tabs, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import CustomTable from '@/components/custom-table';
import EllipsisWithTooltip from '@/components/ellipsis-with-tooltip';
import SearchActionBar from '@/components/search-action-bar';
import ToolbarSplitShell from '@/components/toolbar-split-shell';
import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
import { ITSMTableSurface } from '../components/table-surface';
import { TicketStatusTag } from '../components/ticket-status-tag';
import type { PageResponse, TaskRecord, TicketRecord, TicketStatus } from '../lib/types';

type TicketViewMode = 'mine' | 'todo';
type StatusFilter = 'ALL' | TicketStatus;
type TaskTypeFilter = 'ALL' | 'APPROVAL' | 'HANDLING';

export default function TicketListPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { convertToLocalizedTime } = useLocalizedTime();
  const { get, post } = useApiClient();
  const router = useRouter();
  const searchParams = useSearchParams();

  const initialView = searchParams.get('view') === 'todo' ? 'todo' : 'mine';
  const [viewMode, setViewMode] = useState<TicketViewMode>(initialView);

  const [tickets, setTickets] = useState<TicketRecord[]>([]);
  const [ticketCount, setTicketCount] = useState(0);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [taskCount, setTaskCount] = useState(0);

  const [status, setStatus] = useState<StatusFilter>('ALL');
  const [taskType, setTaskType] = useState<TaskTypeFilter>('ALL');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [closingId, setClosingId] = useState<string>();
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  useEffect(() => {
    const paramView = searchParams.get('view');
    if (paramView === 'todo' || paramView === 'mine') {
      setViewMode(paramView);
    }
  }, [searchParams]);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      if (viewMode === 'mine') {
        const params = new URLSearchParams({
          page: String(pagination.current),
          page_size: String(pagination.pageSize),
        });
        if (status !== 'ALL') params.set('status', status);
        if (query.trim()) params.set('search', query.trim());
        const [ticketRes, todoCountRes] = await Promise.all([
          get<PageResponse<TicketRecord>>(`/itsm/api/tickets/?${params.toString()}`),
          get<PageResponse<TaskRecord>>('/itsm/api/tasks/?page=1&page_size=1').catch(
            () => ({ count: 0, items: [] }),
          ),
        ]);
        setTickets(ticketRes.items ?? []);
        setTicketCount(ticketRes.count ?? 0);
        setTaskCount(todoCountRes.count ?? 0);
      } else {
        const params = new URLSearchParams({
          page: String(pagination.current),
          page_size: String(pagination.pageSize),
        });
        if (taskType !== 'ALL') params.set('task_type', taskType);
        if (query.trim()) params.set('search', query.trim());
        const [todoRes, myCountRes] = await Promise.all([
          get<PageResponse<TaskRecord>>(`/itsm/api/tasks/?${params.toString()}`),
          get<PageResponse<TicketRecord>>('/itsm/api/tickets/?page=1&page_size=1').catch(
            () => ({ count: 0, items: [] }),
          ),
        ]);
        setTasks(todoRes.items ?? []);
        setTaskCount(todoRes.count ?? 0);
        setTicketCount(myCountRes.count ?? 0);
      }
    } catch {
      setFailed(true);
      setTickets([]);
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, [get, pagination.current, pagination.pageSize, query, status, taskType, viewMode]);

  useEffect(() => {
    void load();
  }, [load]);

  const closeTicket = useCallback(
    async (ticketId: string) => {
      setClosingId(ticketId);
      try {
        await post<TicketRecord>(`/itsm/api/tickets/${ticketId}/close/`, {});
        message.success(t('itsm.ticket.closeSuccess', '工单已关闭'));
        await load();
      } finally {
        setClosingId(undefined);
      }
    },
    [load, message, post, t],
  );

  const statusOptions = useMemo(
    () => [
      { label: t('itsm.common.all', '全部'), value: 'ALL' },
      { label: t('itsm.status.APPROVING', '审批中'), value: 'APPROVING' },
      { label: t('itsm.status.PROCESSING', '处理中'), value: 'PROCESSING' },
      { label: t('itsm.status.WAITING_CONFIRMATION', '待确认'), value: 'WAITING_CONFIRMATION' },
      { label: t('itsm.status.CLOSED', '已关闭'), value: 'CLOSED' },
      { label: t('itsm.status.REJECTED', '已驳回'), value: 'REJECTED' },
    ],
    [t],
  );

  const taskFilterOptions = useMemo(
    () => [
      { label: t('itsm.common.all', '全部'), value: 'ALL' },
      { label: t('itsm.todo.approvalTask', '审批任务'), value: 'APPROVAL' },
      { label: t('itsm.todo.handlingTask', '处理任务'), value: 'HANDLING' },
    ],
    [t],
  );

  const ticketColumns = useMemo<ColumnsType<TicketRecord>>(
    () => [
      {
        title: t('itsm.ticket.number', '工单编号'),
        dataIndex: 'number',
        width: 240,
        render: (value: string, record) => (
          <div className="min-w-0">
            <button
              className="block max-w-full truncate border-0 bg-transparent p-0 text-left font-mono text-sm font-semibold text-[var(--color-text-1)] hover:text-[var(--color-primary)] hover:underline"
              onClick={(event) => {
                event.stopPropagation();
                router.push(`/itsm/tickets/${record.id}`);
              }}
            >
              {value}
            </button>
            <div className="mt-0.5 truncate text-xs text-[var(--color-text-3)]">
              {String(record.form_data.summary ?? record.service_name)}
            </div>
          </div>
        ),
      },
      {
        title: t('itsm.ticket.service', '服务'),
        dataIndex: 'service_name',
        width: 200,
        render: (value: string, record) => (
          <div className="min-w-0">
            <EllipsisWithTooltip
              text={value}
              className="block truncate font-medium text-[var(--color-text-1)]"
            />
            <span className="mt-0.5 inline-block font-mono text-[11px] text-[var(--color-text-3)] tabular-nums">
              V{record.service_version_number}
            </span>
          </div>
        ),
      },
      {
        title: t('itsm.ticket.status', '状态'),
        dataIndex: 'status',
        width: 140,
        render: (value: TicketRecord['status']) => <TicketStatusTag status={value} />,
      },
      {
        title: t('itsm.ticket.latestActivity', '最新动态'),
        key: 'latest',
        width: 210,
        render: (_, record) => {
          const lastEvent = record.audit_events?.at(-1);
          if (!lastEvent) {
            return <span className="text-xs text-[var(--color-text-3)]">—</span>;
          }
          return (
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-[var(--color-text-2)]">
                {t(`itsm.audit.${lastEvent.action}`, lastEvent.action)}
              </div>
              <div className="mt-0.5 truncate text-[11px] text-[var(--color-text-3)]">
                {lastEvent.actor_username || t('itsm.ticket.system', '系统')}
              </div>
            </div>
          );
        },
      },
      {
        title: t('itsm.ticket.createdAt', '提交时间'),
        dataIndex: 'created_at',
        width: 176,
        className: 'tabular-nums',
        render: (value: string) => convertToLocalizedTime(value),
      },
      {
        title: t('itsm.ticket.actions', '操作'),
        key: 'actions',
        width: 150,
        fixed: 'right',
        render: (_, record) => (
          <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
            <Button
              type="link"
              size="small"
              onClick={() => router.push(`/itsm/tickets/${record.id}`)}
            >
              {t('itsm.common.view', '查看')}
            </Button>
            {record.status === 'WAITING_CONFIRMATION' ? (
              <Popconfirm
                title={t('itsm.ticket.closeHint', '确认处理结果符合预期并关闭工单？')}
                onConfirm={() => void closeTicket(record.id)}
              >
                <Button
                  type="link"
                  size="small"
                  icon={<CheckCircleOutlined />}
                  loading={closingId === record.id}
                >
                  {t('itsm.ticket.close', '确认关闭')}
                </Button>
              </Popconfirm>
            ) : null}
          </div>
        ),
      },
    ],
    [closeTicket, closingId, convertToLocalizedTime, router, t],
  );

  const todoColumns = useMemo<ColumnsType<TaskRecord>>(
    () => [
      {
        title: t('itsm.ticket.number', '工单编号'),
        dataIndex: 'ticket_number',
        width: 240,
        render: (value: string, task) => (
          <div className="min-w-0">
            <button
              className="block max-w-full truncate border-0 bg-transparent p-0 text-left font-mono text-sm font-semibold text-[var(--color-text-1)] hover:text-[var(--color-primary)] hover:underline"
              onClick={(event) => {
                event.stopPropagation();
                router.push(`/itsm/tickets/${task.ticket_id}`);
              }}
            >
              {value}
            </button>
            <div className="mt-0.5 truncate text-xs text-[var(--color-text-3)]">
              {String(task.form_data.summary ?? task.service_name)}
            </div>
          </div>
        ),
      },
      {
        title: t('itsm.ticket.service', '服务'),
        dataIndex: 'service_name',
        width: 190,
        render: (value: string) => (
          <EllipsisWithTooltip
            text={value}
            className="block truncate font-medium text-[var(--color-text-1)]"
          />
        ),
      },
      {
        title: t('itsm.todo.currentNode', '当前节点'),
        dataIndex: 'title',
        width: 210,
        render: (value: string, task) => (
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-sm font-medium text-[var(--color-text-1)]">
                {value}
              </span>
              {task.sign_parent_key ? (
                <Tag color="blue" className="!m-0 !text-[10px]">
                  {t('itsm.todo.sign', '加签')}
                </Tag>
              ) : null}
            </div>
            <div className="mt-0.5 flex items-center gap-1 text-xs text-[var(--color-text-3)]">
              {task.task_type === 'APPROVAL' ? (
                <AuditOutlined className="text-[11px] text-[var(--color-primary)]" />
              ) : (
                <ToolOutlined className="text-[11px] text-[var(--color-warning)]" />
              )}
              <span>
                {task.task_type === 'APPROVAL'
                  ? t('itsm.todo.approvalTask', '审批任务')
                  : t('itsm.todo.handlingTask', '处理任务')}
              </span>
            </div>
          </div>
        ),
      },
      {
        title: t('itsm.ticket.requester', '提单人'),
        dataIndex: 'requester_username',
        width: 130,
        render: (value: string) => (
          <span className="inline-flex items-center gap-1.5 text-xs text-[var(--color-text-2)]">
            <UserOutlined className="text-[var(--color-text-3)]" />
            <span>{value}</span>
          </span>
        ),
      },
      {
        title: t('itsm.ticket.createdAt', '提交时间'),
        dataIndex: 'created_at',
        width: 176,
        className: 'tabular-nums',
        render: (value: string) => convertToLocalizedTime(value),
      },
      {
        title: t('itsm.todo.actions', '操作'),
        key: 'actions',
        width: 120,
        fixed: 'right',
        render: (_, task) =>
          task.status === 'SUBMITTING' ? (
            <Tag color="processing">{t('itsm.todo.submitting', '提交中')}</Tag>
          ) : (
            <Button
              type="link"
              size="small"
              onClick={(event) => {
                event.stopPropagation();
                router.push(`/itsm/tickets/${task.ticket_id}`);
              }}
            >
              {t('itsm.todo.handleNow', '去处理')}
            </Button>
          ),
      },
    ],
    [convertToLocalizedTime, router, t],
  );

  const switchView = (nextView: string) => {
    const mode = nextView === 'todo' ? 'todo' : 'mine';
    setViewMode(mode);
    setPagination((current) => ({ ...current, current: 1 }));
    router.replace(mode === 'todo' ? '/itsm/tickets?view=todo' : '/itsm/tickets');
  };

  return (
    <ITSMPageShell
      title={t('itsm.ticket.title', '我的工单')}
      description={t(
        'itsm.ticket.unifiedDescription',
        '统一查看我发起的申请单与待我处理的审批/执行任务',
      )}
      actions={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => router.push('/itsm/catalog')}
        >
          {t('itsm.catalog.submit', '发起申请')}
        </Button>
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

      <ITSMTableSurface
        summaryBar={
          <Tabs
            activeKey={viewMode}
            onChange={switchView}
            className="[&_.ant-tabs-nav]:!mb-0 [&_.ant-tabs-nav::before]:!border-0"
            items={[
              {
                key: 'mine',
                label: (
                  <span className="inline-flex items-center gap-1.5">
                    <SendOutlined />
                    <span>{t('itsm.ticket.mySubmittedTab', '我发起的')}</span>
                    <span className="font-mono text-xs text-[var(--color-text-3)] tabular-nums">
                      ({ticketCount})
                    </span>
                  </span>
                ),
              },
              {
                key: 'todo',
                label: (
                  <span className="inline-flex items-center gap-2">
                    <AuditOutlined />
                    <span>{t('itsm.ticket.myTodoTab', '待我处理')}</span>
                    <Badge
                      count={taskCount}
                      size="small"
                      showZero
                      style={{
                        backgroundColor:
                          taskCount > 0
                            ? 'var(--color-primary)'
                            : 'var(--color-fill-2)',
                        color:
                          taskCount > 0 ? '#fff' : 'var(--color-text-3)',
                      }}
                    />
                  </span>
                ),
              },
            ]}
          />
        }
        toolbar={
          <ToolbarSplitShell
            leading={
              viewMode === 'mine' ? (
                <Segmented
                  options={statusOptions}
                  value={status}
                  onChange={(value) => {
                    setStatus(value as StatusFilter);
                    setPagination((current) => ({ ...current, current: 1 }));
                  }}
                />
              ) : (
                <Segmented
                  options={taskFilterOptions}
                  value={taskType}
                  onChange={(val) => {
                    setTaskType(val as TaskTypeFilter);
                    setPagination((current) => ({ ...current, current: 1 }));
                  }}
                />
              )
            }
            trailing={
              <SearchActionBar
                className="!mb-0"
                searchProps={{
                  placeholder:
                    viewMode === 'mine'
                      ? t('itsm.ticket.searchPlaceholder', '搜索工单编号或服务')
                      : t('itsm.todo.searchPlaceholder', '搜索单号、服务或节点'),
                  value: query,
                  onChange: (event) => setQuery(event.target.value),
                  onSearch: (val) => {
                    setPagination((current) => ({ ...current, current: 1 }));
                    setQuery(val);
                  },
                }}
                actions={
                  <Button
                    aria-label={t('itsm.common.refresh', '刷新')}
                    icon={<ReloadOutlined />}
                    loading={loading}
                    onClick={() => void load()}
                  />
                }
              />
            }
          />
        }
      >
        {viewMode === 'mine' ? (
          <CustomTable
            rowKey="id"
            scroll={{ y: 'auto' }}
            columns={ticketColumns}
            dataSource={tickets}
            loading={loading}
            locale={{
              emptyText: (
                <Empty
                  description={
                    query || status !== 'ALL'
                      ? t('itsm.ticket.noMatch', '没有匹配的工单')
                      : t('itsm.ticket.empty', '暂无工单')
                  }
                />
              ),
            }}
            onRow={(record) => ({
              onClick: () => router.push(`/itsm/tickets/${record.id}`),
              className: 'cursor-pointer transition-colors hover:bg-[var(--color-fill-2)]',
            })}
            pagination={{
              current: pagination.current,
              pageSize: pagination.pageSize,
              total: ticketCount,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (total) => t('itsm.common.total', '共 {total} 条', { total }),
              onChange: (current, pageSize) => setPagination({ current, pageSize }),
            }}
          />
        ) : (
          <CustomTable
            rowKey="id"
            scroll={{ y: 'auto' }}
            columns={todoColumns}
            dataSource={tasks}
            loading={loading}
            locale={{
              emptyText: (
                <Empty
                  description={
                    query || taskType !== 'ALL'
                      ? t('itsm.todo.noMatch', '没有匹配的待办任务')
                      : t('itsm.todo.empty', '暂无待处理任务')
                  }
                />
              ),
            }}
            onRow={(record) => ({
              onClick: () => router.push(`/itsm/tickets/${record.ticket_id}`),
              className: 'cursor-pointer transition-colors hover:bg-[var(--color-fill-2)]',
            })}
            pagination={{
              current: pagination.current,
              pageSize: pagination.pageSize,
              total: taskCount,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (total) => t('itsm.common.total', '共 {total} 条', { total }),
              onChange: (current, pageSize) => setPagination({ current, pageSize }),
            }}
          />
        )}
      </ITSMTableSurface>
    </ITSMPageShell>
  );
}
