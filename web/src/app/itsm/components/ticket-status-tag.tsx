'use client';

import {
  CheckCircleFilled,
  ClockCircleFilled,
  CloseCircleFilled,
  ExclamationCircleFilled,
  SyncOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';

import { useTranslation } from '@/utils/i18n';
import type { TicketStatus } from '../lib/types';

const statusMeta: Record<
  TicketStatus,
  {
    tone: string;
    bg: string;
    border: string;
    icon: ReactNode;
    defaultLabel: string;
  }
> = {
  SUBMITTING: {
    tone: 'var(--color-primary)',
    bg: 'color-mix(in srgb, var(--color-primary) 10%, var(--color-bg))',
    border: 'color-mix(in srgb, var(--color-primary) 26%, var(--color-border-1))',
    icon: <SyncOutlined spin className="text-[11px]" />,
    defaultLabel: '提交中',
  },
  APPROVING: {
    tone: 'var(--color-primary)',
    bg: 'color-mix(in srgb, var(--color-primary) 10%, var(--color-bg))',
    border: 'color-mix(in srgb, var(--color-primary) 28%, var(--color-border-1))',
    icon: <ClockCircleFilled className="text-[11px]" />,
    defaultLabel: '审批中',
  },
  PROCESSING: {
    tone: 'var(--color-warning)',
    bg: 'color-mix(in srgb, var(--color-warning) 12%, var(--color-bg))',
    border: 'color-mix(in srgb, var(--color-warning) 30%, var(--color-border-1))',
    icon: <SyncOutlined className="text-[11px]" />,
    defaultLabel: '处理中',
  },
  WAITING_CONFIRMATION: {
    tone: 'var(--color-warning)',
    bg: 'color-mix(in srgb, var(--color-warning) 14%, var(--color-bg))',
    border: 'color-mix(in srgb, var(--color-warning) 34%, var(--color-border-1))',
    icon: <ExclamationCircleFilled className="text-[11px]" />,
    defaultLabel: '待确认',
  },
  CLOSED: {
    tone: 'var(--color-success)',
    bg: 'color-mix(in srgb, var(--color-success) 12%, var(--color-bg))',
    border: 'color-mix(in srgb, var(--color-success) 28%, var(--color-border-1))',
    icon: <CheckCircleFilled className="text-[11px]" />,
    defaultLabel: '已关闭',
  },
  REJECTED: {
    tone: 'var(--color-fail)',
    bg: 'color-mix(in srgb, var(--color-fail) 12%, var(--color-bg))',
    border: 'color-mix(in srgb, var(--color-fail) 28%, var(--color-border-1))',
    icon: <CloseCircleFilled className="text-[11px]" />,
    defaultLabel: '已驳回',
  },
};

export function TicketStatusTag({ status }: { status: TicketStatus }) {
  const { t } = useTranslation();
  const meta = statusMeta[status] ?? statusMeta.APPROVING;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium leading-5 whitespace-nowrap"
      style={{
        color: meta.tone,
        backgroundColor: meta.bg,
        border: `1px solid ${meta.border}`,
      }}
    >
      {meta.icon}
      <span>{t(`itsm.status.${status}`, meta.defaultLabel)}</span>
    </span>
  );
}
