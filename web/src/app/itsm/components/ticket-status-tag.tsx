'use client';

import { Tag } from 'antd';

import { useTranslation } from '@/utils/i18n';
import type { TicketStatus } from '../lib/types';

const colors: Record<TicketStatus, string> = {
  SUBMITTING: 'processing',
  APPROVING: 'processing',
  PROCESSING: 'warning',
  WAITING_CONFIRMATION: 'gold',
  CLOSED: 'success',
  REJECTED: 'error',
};

const defaults: Record<TicketStatus, string> = {
  SUBMITTING: '提交中',
  APPROVING: '审批中',
  PROCESSING: '处理中',
  WAITING_CONFIRMATION: '待确认',
  CLOSED: '已关闭',
  REJECTED: '已驳回',
};

export function TicketStatusTag({ status }: { status: TicketStatus }) {
  const { t } = useTranslation();
  return <Tag color={colors[status]}>{t(`itsm.status.${status}`, defaults[status])}</Tag>;
}
