'use client';

import { ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Empty, Segmented } from 'antd';
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
import { TicketStatusTag } from '../components/ticket-status-tag';
import type { PageResponse, TicketRecord, TicketStatus } from '../lib/types';

type StatusFilter = 'ALL' | TicketStatus;

export default function TicketListPage() {
  const { t } = useTranslation();
  const { convertToLocalizedTime } = useLocalizedTime();
  const { get } = useApiClient();
  const router = useRouter();
  const [records, setRecords] = useState<TicketRecord[]>([]);
  const [count, setCount] = useState(0);
  const [status, setStatus] = useState<StatusFilter>('ALL');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const params = new URLSearchParams({ page: String(pagination.current), page_size: String(pagination.pageSize) });
      if (status !== 'ALL') params.set('status', status);
      const response = await get<PageResponse<TicketRecord>>(`/itsm/api/tickets/?${params.toString()}`);
      setRecords(response.items ?? []);
      setCount(response.count ?? 0);
    } catch {
      setRecords([]);
      setCount(0);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [get, pagination.current, pagination.pageSize, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const statusOptions = useMemo(() => [
    { label: t('itsm.common.all', '全部'), value: 'ALL' },
    { label: t('itsm.status.APPROVING', '审批中'), value: 'APPROVING' },
    { label: t('itsm.status.PROCESSING', '处理中'), value: 'PROCESSING' },
    { label: t('itsm.status.WAITING_CONFIRMATION', '待确认'), value: 'WAITING_CONFIRMATION' },
    { label: t('itsm.status.CLOSED', '已关闭'), value: 'CLOSED' },
    { label: t('itsm.status.REJECTED', '已驳回'), value: 'REJECTED' },
  ], [t]);

  const columns = useMemo<ColumnsType<TicketRecord>>(() => [
    {
      title: t('itsm.ticket.number', '工单编号'),
      dataIndex: 'number',
      width: 230,
      render: (value: string, record) => (
        <div className="min-w-0">
          <button className="block max-w-full truncate border-0 bg-transparent p-0 text-left font-mono text-sm font-medium text-[var(--color-text-1)] hover:text-[var(--color-primary)] hover:underline" onClick={(event) => { event.stopPropagation(); router.push(`/itsm/tickets/${record.id}`); }}>
            {value}
          </button>
          <div className="mt-0.5 truncate text-xs text-[var(--color-text-3)]">{String(record.form_data.summary ?? record.service_name)}</div>
        </div>
      ),
    },
    { title: t('itsm.ticket.service', '服务'), dataIndex: 'service_name', render: (value: string) => <EllipsisWithTooltip text={value} className="block truncate" /> },
    { title: t('itsm.ticket.status', '状态'), dataIndex: 'status', width: 130, render: (value: TicketRecord['status']) => <TicketStatusTag status={value} /> },
    { title: t('itsm.ticket.version', '版本'), dataIndex: 'service_version_number', width: 100, className: 'tabular-nums', render: (value: number) => `V${value}` },
    { title: t('itsm.ticket.createdAt', '提交时间'), dataIndex: 'created_at', width: 180, className: 'tabular-nums', render: (value: string) => convertToLocalizedTime(value) },
    {
      title: t('itsm.ticket.actions', '操作'),
      key: 'actions',
      width: 90,
      fixed: 'right',
      render: (_, record) => <Button type="link" size="small" onClick={(event) => { event.stopPropagation(); router.push(`/itsm/tickets/${record.id}`); }}>{t('itsm.common.view', '查看')}</Button>,
    },
  ], [convertToLocalizedTime, router, t]);

  return (
    <ITSMPageShell title={t('itsm.ticket.title', '我的工单')} description={t('itsm.ticket.description', '查看我发起的工单和处理进度')}>
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" action={<Button size="small" onClick={() => void load()}>{t('itsm.common.retry', '重试')}</Button>} /> : null}
      <ITSMTableSurface toolbar={
        <ToolbarSplitShell
          leading={<Segmented options={statusOptions} value={status} onChange={(value) => { setStatus(value as StatusFilter); setPagination((current) => ({ ...current, current: 1 })); }} />}
          trailing={<Button aria-label={t('itsm.common.refresh', '刷新')} icon={<ReloadOutlined />} loading={loading} onClick={() => void load()} />}
        />
      }>
        <CustomTable
          rowKey="id"
          scroll={{ y: 'auto' }}
          columns={columns}
          dataSource={records}
          loading={loading}
          locale={{ emptyText: <Empty description={t('itsm.ticket.empty', '暂无工单')} /> }}
          onRow={(record) => ({
            onClick: () => router.push(`/itsm/tickets/${record.id}`),
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
    </ITSMPageShell>
  );
}
