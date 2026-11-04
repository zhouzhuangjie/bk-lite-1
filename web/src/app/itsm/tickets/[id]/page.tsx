'use client';

import { ArrowLeftOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { Alert, App, Button, Card, Descriptions, Popconfirm, Skeleton, Timeline } from 'antd';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../../components/page-shell';
import { TicketStatusTag } from '../../components/ticket-status-tag';
import type { TicketRecord } from '../../lib/types';

export default function TicketDetailPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { convertToLocalizedTime } = useLocalizedTime();
  const { get, post } = useApiClient();
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [ticket, setTicket] = useState<TicketRecord>();
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [closing, setClosing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setTicket(await get<TicketRecord>(`/itsm/api/tickets/${params.id}/`));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [get, params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const formItems = useMemo(() => {
    if (!ticket) return [];
    return Object.entries(ticket.form_data).map(([key, value]) => ({
      key,
      label: ticket.form_schema.properties[key]?.title ?? key,
      children: Array.isArray(value) ? value.join('、') : String(value ?? '—'),
    }));
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

  return (
    <ITSMPageShell
      title={ticket?.number ?? t('itsm.ticket.detail', '工单详情')}
      description={ticket?.service_name}
      actions={(
        <>
          {ticket?.status === 'WAITING_CONFIRMATION' ? (
            <Popconfirm
              title={t('itsm.ticket.closeHint', '确认处理结果符合预期并关闭工单？')}
              onConfirm={() => void close()}
            >
              <Button type="primary" icon={<CheckCircleOutlined />} loading={closing}>{t('itsm.ticket.close', '确认关闭')}</Button>
            </Popconfirm>
          ) : null}
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/itsm/tickets')}>{t('itsm.common.back', '返回')}</Button>
        </>
      )}
    >
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} /> : null}
      {loading ? (
        <Card><Skeleton active paragraph={{ rows: 8 }} /></Card>
      ) : ticket ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
          <div className="space-y-4">
            <Card title={t('itsm.ticket.detail', '工单详情')} className="border-[var(--color-border)] bg-[var(--color-bg)]">
              <Descriptions column={{ xs: 1, md: 2 }} items={[
                { key: 'status', label: t('itsm.ticket.status', '状态'), children: <TicketStatusTag status={ticket.status} /> },
                { key: 'requester', label: t('itsm.ticket.requester', '提单人'), children: ticket.requester_username },
                { key: 'created', label: t('itsm.ticket.createdAt', '提交时间'), children: convertToLocalizedTime(ticket.created_at) },
                { key: 'version', label: t('itsm.ticket.version', '版本'), children: String(ticket.service_version_number) },
              ]} />
            </Card>
            <Card title={ticket.service_name} className="border-[var(--color-border)] bg-[var(--color-bg)]">
              <Descriptions bordered column={1} items={formItems} />
            </Card>
          </div>
          <Card title={t('itsm.ticket.auditTrail', '流转记录')} className="border-[var(--color-border)] bg-[var(--color-bg)]">
            <Timeline items={ticket.audit_events.map((event) => ({
              children: (
                <div>
                  <div className="font-medium text-[var(--color-text-1)]">{event.action}</div>
                  {event.reason ? <div className="mt-1 text-sm text-[var(--color-text-2)]">{event.reason}</div> : null}
                  <div className="mt-1 text-xs text-[var(--color-text-3)]">
                    {[event.actor_username, convertToLocalizedTime(event.created_at)].filter(Boolean).join(' · ')}
                  </div>
                </div>
              ),
            }))} />
          </Card>
        </div>
      ) : null}
    </ITSMPageShell>
  );
}
