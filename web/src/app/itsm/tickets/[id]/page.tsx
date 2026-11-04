'use client';

import { ApartmentOutlined, ArrowLeftOutlined, CheckCircleOutlined, ClockCircleOutlined, FileTextOutlined, HistoryOutlined, UserOutlined } from '@ant-design/icons';
import { Alert, App, Button, Popconfirm, Skeleton, Timeline } from 'antd';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../../components/page-shell';
import { TicketStatusTag } from '../../components/ticket-status-tag';
import { WorkbenchMetric, WorkbenchPropertyList, WorkbenchSection } from '../../components/workbench-section';
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
      value: Array.isArray(value) ? value.join('、') : String(value ?? '—'),
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

  const currentStep = ticket ? ({
    SUBMITTING: t('itsm.status.SUBMITTING', '提交中'),
    APPROVING: t('itsm.status.APPROVING', '审批中'),
    PROCESSING: t('itsm.status.PROCESSING', '处理中'),
    WAITING_CONFIRMATION: t('itsm.status.WAITING_CONFIRMATION', '待确认'),
    CLOSED: t('itsm.status.CLOSED', '已关闭'),
    REJECTED: t('itsm.status.REJECTED', '已驳回'),
  })[ticket.status] : '—';

  return (
    <ITSMPageShell
      title={ticket?.number ?? t('itsm.ticket.detail', '工单详情')}
      description={ticket ? `${ticket.service_name} · ${String(ticket.form_data.summary ?? t('itsm.ticket.request', '服务申请'))}` : undefined}
      actions={(
        <>
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/itsm/tickets')}>{t('itsm.common.back', '返回')}</Button>
          {ticket?.status === 'WAITING_CONFIRMATION' ? (
            <Popconfirm title={t('itsm.ticket.closeHint', '确认处理结果符合预期并关闭工单？')} onConfirm={() => void close()}>
              <Button type="primary" icon={<CheckCircleOutlined />} loading={closing}>{t('itsm.ticket.close', '确认关闭')}</Button>
            </Popconfirm>
          ) : null}
        </>
      )}
    >
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" action={<Button size="small" onClick={() => void load()}>{t('itsm.common.retry', '重试')}</Button>} /> : null}
      {loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">{[1, 2, 3].map((item) => <div key={item} className="rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] p-4"><Skeleton active title={{ width: '45%' }} paragraph={{ rows: 1 }} /></div>)}</div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <WorkbenchSection title={t('itsm.ticket.requestInfo', '申请内容')}><Skeleton active paragraph={{ rows: 8 }} /></WorkbenchSection>
            <WorkbenchSection title={t('itsm.ticket.basicInfo', '工单信息')}><Skeleton active paragraph={{ rows: 6 }} /></WorkbenchSection>
          </div>
        </div>
      ) : ticket ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <WorkbenchMetric label={t('itsm.ticket.currentStep', '当前环节')} value={currentStep} tone={ticket.status === 'REJECTED' ? 'error' : ticket.status === 'CLOSED' ? 'success' : ticket.status === 'WAITING_CONFIRMATION' ? 'warning' : 'primary'} />
            <WorkbenchMetric label={t('itsm.ticket.version', '服务版本')} value={`V${ticket.service_version_number}`} />
            <WorkbenchMetric label={t('itsm.ticket.auditCount', '流转记录')} value={ticket.audit_events.length} />
          </div>
          <div className="flex min-w-0 flex-col items-start gap-4 lg:flex-row">
            <div className="min-w-0 flex-1 space-y-4">
              <WorkbenchSection title={t('itsm.ticket.requestInfo', '申请内容')} icon={<FileTextOutlined />} count={formItems.length}>
                <div className="grid grid-cols-1 gap-x-8 gap-y-5 md:grid-cols-2">
                  {formItems.map((item) => (
                    <div key={item.key} className="min-w-0">
                      <div className="text-xs font-medium text-[var(--color-text-3)]">{item.label}</div>
                      <div className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-[var(--color-text-1)]">{item.value}</div>
                    </div>
                  ))}
                </div>
              </WorkbenchSection>
              <WorkbenchSection title={t('itsm.ticket.auditTrail', '流转记录')} icon={<HistoryOutlined />} count={ticket.audit_events.length}>
                {ticket.audit_events.length ? (
                  <Timeline items={ticket.audit_events.map((event) => ({
                    color: event.to_status === 'REJECTED' ? 'red' : event.to_status === 'CLOSED' ? 'green' : 'blue',
                    children: (
                      <div className="pb-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-medium text-[var(--color-text-1)]">{t(`itsm.audit.${event.action}`, event.action)}</span>
                          <span className="text-xs text-[var(--color-text-3)] tabular-nums">{convertToLocalizedTime(event.created_at)}</span>
                        </div>
                        {event.reason ? <div className="mt-1 rounded-md bg-[var(--color-fill-1)]/35 px-3 py-2 text-sm text-[var(--color-text-2)]">{event.reason}</div> : null}
                        <div className="mt-1 text-xs text-[var(--color-text-3)]">{event.actor_username || t('itsm.ticket.system', '系统')}</div>
                      </div>
                    ),
                  }))} />
                ) : <div className="py-6 text-center text-sm text-[var(--color-text-3)]">{t('itsm.ticket.noAudit', '暂无流转记录')}</div>}
              </WorkbenchSection>
            </div>
            <div className="w-full shrink-0 space-y-4 lg:w-80">
              <WorkbenchSection title={t('itsm.ticket.basicInfo', '工单信息')} icon={<ApartmentOutlined />} bodyClassName="p-0" extra={<TicketStatusTag status={ticket.status} />}>
                <WorkbenchPropertyList items={[
                  { key: 'number', label: t('itsm.ticket.number', '工单编号'), value: ticket.number, mono: true },
                  { key: 'service', label: t('itsm.ticket.service', '服务'), value: ticket.service_name },
                  { key: 'requester', label: t('itsm.ticket.requester', '提单人'), value: ticket.requester_username },
                  { key: 'version', label: t('itsm.ticket.version', '版本'), value: `V${ticket.service_version_number}`, mono: true },
                  { key: 'created', label: t('itsm.ticket.createdAt', '提交时间'), value: convertToLocalizedTime(ticket.created_at), mono: true },
                  { key: 'updated', label: t('itsm.ticket.updatedAt', '最近更新'), value: convertToLocalizedTime(ticket.updated_at), mono: true },
                ]} />
              </WorkbenchSection>
              <WorkbenchSection title={t('itsm.ticket.currentProcessing', '当前处理')} icon={<UserOutlined />}>
                <div className="flex items-start gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-[var(--color-primary-bg-active)] text-[var(--color-primary)]"><ClockCircleOutlined /></span>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-[var(--color-text-1)]">{currentStep}</div>
                    <p className="mb-0 mt-1 text-xs leading-5 text-[var(--color-text-3)]">
                      {ticket.status === 'WAITING_CONFIRMATION'
                        ? t('itsm.ticket.confirmTip', '处理人已完成操作，请核对结果后确认关闭。')
                        : t('itsm.ticket.processingTip', '流程将按已发布服务版本继续推进，状态变化会记录在左侧。')}
                    </p>
                  </div>
                </div>
              </WorkbenchSection>
            </div>
          </div>
        </div>
      ) : null}
    </ITSMPageShell>
  );
}
