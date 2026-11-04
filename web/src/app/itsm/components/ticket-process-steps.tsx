'use client';

import {
  ApartmentOutlined,
  AuditOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { Button, Tag } from 'antd';
import { useState, type ReactNode } from 'react';

import OperateDrawer from '@/components/operate-drawer';
import { useTranslation } from '@/utils/i18n';
import type { AuditEventRecord, TicketStatus, WorkflowConfig } from '../lib/types';
import { WorkflowPreview } from './workflow-preview';

export interface ProcessStepItem {
  key: string;
  title: string;
  subtitle: string;
  state: 'done' | 'active' | 'rejected' | 'upcoming';
  icon: ReactNode;
  badge?: string;
}

const DEFAULT_WORKFLOW: WorkflowConfig = {
  schemaVersion: 1,
  stages: [
    {
      key: 'approval',
      name: '审批中',
      mode: 'serial',
      approverIds: [],
      allowBeforeSign: false,
      allowAfterSign: false,
    },
  ],
  handlerIds: [],
};

export function buildTicketProcessSteps({
  status,
  workflow,
  activeStageKey,
  auditEvents = [],
  t,
}: {
  status: TicketStatus;
  workflow?: WorkflowConfig;
  activeStageKey?: string;
  auditEvents?: AuditEventRecord[];
  t: (
    key: string,
    fallback?: string,
    values?: Record<string, string | number>,
  ) => string;
}): ProcessStepItem[] {
  const stages = workflow?.stages?.length
    ? workflow.stages
    : [
        {
          key: 'approval',
          name: t('itsm.status.APPROVING', '审批中'),
          mode: 'serial' as const,
          approverIds: [],
          allowBeforeSign: false,
          allowAfterSign: false,
        },
      ];

  const approvedCount = auditEvents.filter(
    (event) => event.action === 'APPROVE_APPLIED',
  ).length;
  const activeStageIndex = activeStageKey
    ? Math.max(
        0,
        stages.findIndex((stage) => stage.key === activeStageKey),
      )
    : Math.min(approvedCount, Math.max(0, stages.length - 1));

  const submitStep: ProcessStepItem = {
    key: 'submit',
    title: t('itsm.workflow.submit', '发起申请'),
    subtitle:
      status === 'SUBMITTING'
        ? t('itsm.status.SUBMITTING', '提交中')
        : t('itsm.workflow.submitted', '已提交工单'),
    state: status === 'SUBMITTING' ? 'active' : 'done',
    icon: <SendOutlined />,
  };

  const approvalSteps: ProcessStepItem[] = stages.map((stage, index) => {
    let state: ProcessStepItem['state'] = 'upcoming';
    if (status === 'SUBMITTING') {
      state = 'upcoming';
    } else if (status === 'APPROVING') {
      if (index < activeStageIndex) state = 'done';
      else if (index === activeStageIndex) state = 'active';
      else state = 'upcoming';
    } else if (status === 'REJECTED') {
      if (index < activeStageIndex) state = 'done';
      else if (index === activeStageIndex) state = 'rejected';
      else state = 'upcoming';
    } else {
      state = 'done';
    }

    const modeLabel =
      stage.mode === 'parallel'
        ? t('itsm.service.parallel', '并行会签')
        : t('itsm.service.serial', '依次审批');
    const peopleCount = stage.approverIds?.length ?? 0;

    return {
      key: stage.key || `stage-${index}`,
      title:
        stage.name ||
        t('itsm.service.approvalNode', '审批节点 {index}', { index: index + 1 }),
      subtitle:
        peopleCount > 0
          ? `${modeLabel} · ${t('itsm.workflow.people', '{count} 人', {
              count: peopleCount,
            })}`
          : modeLabel,
      state,
      icon: <AuditOutlined />,
      badge:
        stage.allowBeforeSign || stage.allowAfterSign
          ? t('itsm.todo.sign', '可加签')
          : undefined,
    };
  });

  const handlingState: ProcessStepItem['state'] =
    status === 'PROCESSING'
      ? 'active'
      : status === 'WAITING_CONFIRMATION' || status === 'CLOSED'
        ? 'done'
        : 'upcoming';

  const handlingStep: ProcessStepItem = {
    key: 'handling',
    title: t('itsm.workflow.handling', '工单处理'),
    subtitle: workflow?.handlerIds?.length
      ? t('itsm.workflow.handlerCount', '处理人 · {count} 人', {
          count: workflow.handlerIds.length,
        })
      : t('itsm.todo.handlingTask', '人工执行与交付'),
    state: handlingState,
    icon: <ToolOutlined />,
  };

  const closeState: ProcessStepItem['state'] =
    status === 'WAITING_CONFIRMATION'
      ? 'active'
      : status === 'CLOSED'
        ? 'done'
        : 'upcoming';

  const closeStep: ProcessStepItem = {
    key: 'close',
    title: t('itsm.workflow.close', '确认关闭'),
    subtitle:
      status === 'CLOSED'
        ? t('itsm.status.CLOSED', '已关闭')
        : status === 'WAITING_CONFIRMATION'
          ? t('itsm.status.WAITING_CONFIRMATION', '待确认')
          : t('itsm.workflow.requesterConfirm', '提单人验收结单'),
    state: closeState,
    icon: <SafetyCertificateOutlined />,
  };

  return [submitStep, ...approvalSteps, handlingStep, closeStep];
}

export function TicketFlowCanvasWorkbench({
  status,
  workflow,
  activeStageKey,
  auditEvents,
  heightClassName = 'h-[440px]',
}: {
  status: TicketStatus;
  workflow?: WorkflowConfig;
  activeStageKey?: string;
  auditEvents?: AuditEventRecord[];
  heightClassName?: string;
}) {
  const { t } = useTranslation();
  const steps = buildTicketProcessSteps({
    status,
    workflow,
    activeStageKey,
    auditEvents,
    t,
  });
  const activeOrFirstKey =
    steps.find((step) => step.state === 'active' || step.state === 'rejected')?.key ??
    steps[0]?.key ??
    'submit';
  const [selectedKey, setSelectedKey] = useState<string>(activeOrFirstKey);

  const selectedStep = steps.find((item) => item.key === selectedKey) ?? steps[0];
  const selectedIndex = Math.max(
    0,
    steps.findIndex((item) => item.key === selectedStep?.key),
  );

  const stateTag = (state: ProcessStepItem['state']) => {
    if (state === 'done') {
      return (
        <Tag color="success" className="!m-0">
          {t('itsm.ticket.stepDone', '已完成')}
        </Tag>
      );
    }
    if (state === 'active') {
      return (
        <Tag color="processing" className="!m-0">
          {t('itsm.ticket.currentStepBadge', '当前环节')}
        </Tag>
      );
    }
    if (state === 'rejected') {
      return (
        <Tag color="error" className="!m-0">
          {t('itsm.status.REJECTED', '已驳回')}
        </Tag>
      );
    }
    return <Tag className="!m-0">{t('itsm.ticket.stepUpcoming', '未到达')}</Tag>;
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
      <div className="flex max-h-[440px] flex-col overflow-hidden rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)]">
        <div className="flex items-center justify-between border-b border-[var(--color-border-1)] bg-[var(--color-fill-1)]/40 px-3.5 py-2.5">
          <span className="text-xs font-semibold text-[var(--color-text-1)]">
            {t('itsm.ticket.stageList', '流程节点列表')}
          </span>
          <span className="font-mono text-xs text-[var(--color-text-3)] tabular-nums">
            {steps.filter((s) => s.state === 'done').length}/{steps.length}
          </span>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto p-2.5">
          {steps.map((step, idx) => {
            const isSelected = step.key === selectedStep?.key;
            const accent =
              step.state === 'rejected'
                ? 'var(--color-fail)'
                : step.state === 'active'
                  ? 'var(--color-primary)'
                  : step.state === 'done'
                    ? 'var(--color-success)'
                    : 'var(--color-border-3)';
            return (
              <button
                key={step.key}
                type="button"
                onClick={() => setSelectedKey(step.key)}
                className={`flex w-full cursor-pointer items-start gap-2.5 rounded-md border border-l-[3px] px-3 py-2 text-left transition-colors ${
                  isSelected
                    ? 'border-[var(--color-primary)] bg-[var(--color-fill-1)]'
                    : 'border-[var(--color-border-1)] bg-[var(--color-bg)] hover:bg-[var(--color-fill-1)]/60'
                }`}
                style={{ borderLeftColor: accent }}
              >
                <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border border-[var(--color-border-2)] font-mono text-[11px] text-[var(--color-text-2)] tabular-nums">
                  {idx + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-1.5">
                    <span className="truncate text-xs font-semibold text-[var(--color-text-1)]">
                      {step.title}
                    </span>
                    {stateTag(step.state)}
                  </span>
                  <span className="mt-1 block truncate text-[11px] text-[var(--color-text-3)]">
                    {step.subtitle}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-3">
        <WorkflowPreview
          config={workflow ?? DEFAULT_WORKFLOW}
          runtimeSteps={steps}
          selectedStepKey={selectedStep?.key}
          onSelectStepKey={setSelectedKey}
          heightClassName={heightClassName}
          showControls
        />
        {selectedStep ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-border-1)] bg-[var(--color-fill-1)]/35 px-4 py-2.5 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[var(--color-text-3)]">
                #{selectedIndex + 1}
              </span>
              <span className="font-semibold text-[var(--color-text-1)]">
                {selectedStep.title}
              </span>
              {stateTag(selectedStep.state)}
              {selectedStep.badge ? (
                <Tag color="blue" className="!m-0">
                  {selectedStep.badge}
                </Tag>
              ) : null}
            </div>
            <span className="text-[var(--color-text-3)]">{selectedStep.subtitle}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** 顶部唯一流程进度条：左侧展示当前阶段与分段进度，右侧单一按钮拉出流程图抽屉 */
export function TicketCompactProgressBanner({
  status,
  workflow,
  activeStageKey,
  auditEvents,
  onOpenCanvasDrawer,
}: {
  status: TicketStatus;
  workflow?: WorkflowConfig;
  activeStageKey?: string;
  auditEvents?: AuditEventRecord[];
  onOpenCanvasDrawer: () => void;
}) {
  const { t } = useTranslation();
  const steps = buildTicketProcessSteps({
    status,
    workflow,
    activeStageKey,
    auditEvents,
    t,
  });

  const doneCount = steps.filter((step) => step.state === 'done').length;
  const activeIdx = steps.findIndex(
    (step) => step.state === 'active' || step.state === 'rejected',
  );
  const currentIndex = activeIdx >= 0 ? activeIdx : steps.length - 1;
  const currentStep = steps[currentIndex];

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] px-4 py-3 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[var(--color-primary-bg-active)] text-sm text-[var(--color-primary)]">
          <ApartmentOutlined />
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-[var(--color-text-3)]">
              {t('itsm.ticket.currentStep', '当前环节')}:
            </span>
            <span className="text-sm font-semibold text-[var(--color-text-1)]">
              #{currentIndex + 1} {currentStep?.title}
            </span>
            <span className="text-xs text-[var(--color-text-3)]">
              ({currentStep?.subtitle})
            </span>
          </div>
          <div className="mt-1.5 flex items-center gap-1.5">
            {steps.map((step, index) => {
              const color =
                step.state === 'rejected'
                  ? 'var(--color-fail)'
                  : step.state === 'active'
                    ? 'var(--color-primary)'
                    : step.state === 'done'
                      ? 'var(--color-success)'
                      : 'var(--color-border-2)';
              return (
                <span
                  key={step.key}
                  title={`${index + 1}. ${step.title} (${step.subtitle})`}
                  className="h-1.5 w-6 rounded-full transition-colors sm:w-8"
                  style={{ backgroundColor: color }}
                />
              );
            })}
            <span className="ml-1 font-mono text-[11px] text-[var(--color-text-3)] tabular-nums">
              {doneCount}/{steps.length}
            </span>
          </div>
        </div>
      </div>

      <Button
        size="small"
        type="primary"
        ghost
        icon={<ApartmentOutlined />}
        onClick={onOpenCanvasDrawer}
      >
        {t('itsm.ticket.openFlowDrawer', '查看流程图')}
      </Button>
    </div>
  );
}

export function TicketFlowDrawer({
  open,
  onClose,
  ticketNumber,
  serviceName,
  status,
  workflow,
  activeStageKey,
  auditEvents,
}: {
  open: boolean;
  onClose: () => void;
  ticketNumber?: string;
  serviceName?: string;
  status: TicketStatus;
  workflow?: WorkflowConfig;
  activeStageKey?: string;
  auditEvents?: AuditEventRecord[];
}) {
  const { t } = useTranslation();
  return (
    <OperateDrawer
      open={open}
      onClose={onClose}
      width={920}
      title={t('itsm.ticket.flowDrawerTitle', '流程图画布')}
      subTitle={
        ticketNumber && serviceName ? `${ticketNumber} · ${serviceName}` : ticketNumber
      }
      destroyOnClose
    >
      <TicketFlowCanvasWorkbench
        status={status}
        workflow={workflow}
        activeStageKey={activeStageKey}
        auditEvents={auditEvents}
        heightClassName="h-[460px]"
      />
    </OperateDrawer>
  );
}
