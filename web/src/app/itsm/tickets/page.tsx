'use client';

import { ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Empty } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import CustomTable from '@/components/custom-table';
import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
import { TicketStatusTag } from '../components/ticket-status-tag';
import type { PageResponse, TicketRecord } from '../lib/types';

export default function TicketListPage() {
  const { t } = useTranslation();
  const { convertToLocalizedTime } = useLocalizedTime();
  const { get } = useApiClient();
  const router = useRouter();
  const [records, setRecords] = useState<TicketRecord[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const response = await get<PageResponse<TicketRecord>>(
        `/itsm/api/tickets/?page=${pagination.current}&page_size=${pagination.pageSize}`,
      );
      setRecords(response.items ?? []);
      setCount(response.count ?? 0);
    } catch {
      setRecords([]);
      setCount(0);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [get, pagination.current, pagination.pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns = useMemo<ColumnsType<TicketRecord>>(() => [
    {
      title: t('itsm.ticket.number', '工单编号'),
      dataIndex: 'number',
      width: 190,
      render: (value: string, record) => <Button type="link" onClick={() => router.push(`/itsm/tickets/${record.id}`)}>{value}</Button>,
    },
    { title: t('itsm.ticket.service', '服务'), dataIndex: 'service_name', ellipsis: true },
    { title: t('itsm.ticket.status', '状态'), dataIndex: 'status', width: 130, render: (value: TicketRecord['status']) => <TicketStatusTag status={value} /> },
    { title: t('itsm.ticket.createdAt', '提交时间'), dataIndex: 'created_at', width: 180, render: (value: string) => convertToLocalizedTime(value) },
  ], [convertToLocalizedTime, router, t]);

  return (
    <ITSMPageShell
      title={t('itsm.ticket.title', '我的工单')}
      description={t('itsm.ticket.description', '查看我发起的工单和处理进度')}
      actions={<Button aria-label={t('itsm.common.refresh', '刷新')} icon={<ReloadOutlined />} onClick={() => void load()} />}
    >
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" /> : null}
      <div className="rounded-md bg-[var(--color-bg)] p-4">
        <CustomTable
          rowKey="id"
          columns={columns}
          dataSource={records}
          loading={loading}
          locale={{ emptyText: <Empty description={t('itsm.ticket.empty', '暂无工单')} /> }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: count,
            showSizeChanger: true,
            onChange: (current, pageSize) => setPagination({ current, pageSize }),
          }}
        />
      </div>
    </ITSMPageShell>
  );
}
