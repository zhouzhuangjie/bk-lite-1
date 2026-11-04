'use client';

import {
  AuditOutlined,
  CheckCircleFilled,
  ClockCircleFilled,
  CloseCircleFilled,
  SendOutlined,
  ToolOutlined,
  UserAddOutlined,
} from '@ant-design/icons';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo } from 'react';

import { useTranslation } from '@/utils/i18n';
import type { WorkflowConfig } from '../lib/types';
import type { ProcessStepItem } from './ticket-process-steps';

interface PreviewNodeData extends Record<string, unknown> {
  stepNumber: number;
  label: string;
  kind: 'start' | 'approval' | 'handling' | 'end';
  state?: ProcessStepItem['state'];
  modeLabel?: string;
  peopleLabel?: string;
  signBadges?: string[];
  active?: boolean;
}

function PreviewNode({ data }: NodeProps<Node<PreviewNodeData>>) {
  const isApproval = data.kind === 'approval';
  const isHandling = data.kind === 'handling';
  const isStart = data.kind === 'start';
  const isEnd = data.kind === 'end';

  const runtimeState = data.state;
  const accentColor =
    runtimeState === 'rejected'
      ? 'var(--color-fail)'
      : runtimeState === 'active'
        ? 'var(--color-primary)'
        : runtimeState === 'done'
          ? 'var(--color-success)'
          : isApproval
            ? 'var(--color-primary)'
            : isHandling
              ? 'var(--color-warning)'
              : isEnd
                ? 'var(--color-success)'
                : 'var(--color-text-2)';

  const iconNode =
    runtimeState === 'rejected' ? (
      <CloseCircleFilled />
    ) : runtimeState === 'done' ? (
      <CheckCircleFilled />
    ) : runtimeState === 'active' ? (
      <ClockCircleFilled />
    ) : isStart ? (
      <SendOutlined />
    ) : isApproval ? (
      <AuditOutlined />
    ) : isHandling ? (
      <ToolOutlined />
    ) : (
      <CheckCircleFilled />
    );

  return (
    <div
      className="relative min-w-48 max-w-56 rounded-lg bg-[var(--color-bg)] px-3.5 py-3 shadow-[0_2px_6px_rgba(0,0,0,0.04)] transition-all"
      style={{
        border:
          data.active || runtimeState === 'active'
            ? '1.5px solid var(--color-primary)'
            : '1px solid var(--color-border-1)',
        borderTop: `3px solid ${accentColor}`,
      }}
    >
      {!isStart ? (
        <Handle
          type="target"
          position={Position.Left}
          className="!h-2 !w-2 !border-0 !bg-[var(--color-border-2)]"
        />
      ) : null}
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <span
            className="grid h-5 w-5 shrink-0 place-items-center rounded text-xs"
            style={{
              color: accentColor,
              backgroundColor: `color-mix(in srgb, ${accentColor} 12%, var(--color-bg))`,
            }}
          >
            {iconNode}
          </span>
          <span className="truncate text-xs font-semibold text-[var(--color-text-1)]">
            {data.label}
          </span>
        </div>
        <span className="shrink-0 rounded bg-[var(--color-fill-1)] px-1.5 py-0.2 font-mono text-[10px] font-medium text-[var(--color-text-3)] tabular-nums">
          #{data.stepNumber}
        </span>
      </div>

      {data.modeLabel || data.peopleLabel ? (
        <div className="mt-2 flex flex-wrap items-center gap-1 text-[11px] text-[var(--color-text-2)]">
          {data.modeLabel ? (
            <span className="rounded bg-[var(--color-fill-1)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-text-2)]">
              {data.modeLabel}
            </span>
          ) : null}
          {data.peopleLabel ? (
            <span className="text-[11px] text-[var(--color-text-3)]">{data.peopleLabel}</span>
          ) : null}
        </div>
      ) : null}

      {data.signBadges && data.signBadges.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-1 border-t border-[var(--color-border-1)] pt-1.5">
          <UserAddOutlined className="text-[10px] text-[var(--color-primary)]" />
          {data.signBadges.map((badge) => (
            <span
              key={badge}
              className="rounded bg-[var(--color-primary-bg-active)] px-1.5 py-0.2 text-[10px] text-[var(--color-primary)]"
            >
              {badge}
            </span>
          ))}
        </div>
      ) : null}

      {!isEnd ? (
        <Handle
          type="source"
          position={Position.Right}
          className="!h-2 !w-2 !border-0 !bg-[var(--color-border-2)]"
        />
      ) : null}
    </div>
  );
}

const nodeTypes = { preview: PreviewNode };

export function WorkflowPreview({
  config,
  runtimeSteps,
  activeStageIndex,
  selectedStepKey,
  onSelectStage,
  onSelectStepKey,
  heightClassName = 'h-72',
  showControls = true,
}: {
  config: WorkflowConfig;
  runtimeSteps?: ProcessStepItem[];
  activeStageIndex?: number;
  selectedStepKey?: string;
  onSelectStage?: (stageIndex: number) => void;
  onSelectStepKey?: (stepKey: string) => void;
  heightClassName?: string;
  showControls?: boolean;
}) {
  const { t } = useTranslation();
  const { nodes, edges } = useMemo(() => {
    const stateByKey = new Map(runtimeSteps?.map((step) => [step.key, step.state]) ?? []);

    const sequence: Array<PreviewNodeData & { stageIndex?: number; stepKey: string }> = [
      {
        stepKey: 'submit',
        stepNumber: 1,
        label: t('itsm.workflow.submit', '提单'),
        kind: 'start',
        state: stateByKey.get('submit'),
        peopleLabel: t('itsm.ticket.requester', '提单人'),
        active: selectedStepKey === 'submit',
      },
      ...config.stages.map((stage, idx) => {
        const signBadges: string[] = [];
        if (stage.allowBeforeSign) signBadges.push(t('itsm.todo.beforeSign', '前加签'));
        if (stage.allowAfterSign) signBadges.push(t('itsm.todo.afterSign', '后加签'));
        const stepKey = stage.key || `stage-${idx}`;
        return {
          stepKey,
          stepNumber: idx + 2,
          stageIndex: idx,
          label:
            stage.name ||
            t('itsm.service.approvalNode', '审批节点 {index}', { index: idx + 1 }),
          kind: 'approval' as const,
          state: stateByKey.get(stepKey),
          modeLabel:
            stage.mode === 'serial'
              ? t('itsm.service.serial', '依次审批')
              : t('itsm.service.parallel', '并行会签'),
          peopleLabel: t('itsm.workflow.people', '{count} 人', {
            count: stage.approverIds.length,
          }),
          signBadges,
          active: activeStageIndex === idx || selectedStepKey === stepKey,
        };
      }),
      {
        stepKey: 'handling',
        stepNumber: config.stages.length + 2,
        label: t('itsm.workflow.handling', '工单处理'),
        kind: 'handling',
        state: stateByKey.get('handling'),
        modeLabel: t('itsm.todo.handlingTask', '人工执行'),
        peopleLabel: t('itsm.workflow.people', '{count} 人', {
          count: config.handlerIds.length,
        }),
        active: selectedStepKey === 'handling',
      },
      {
        stepKey: 'close',
        stepNumber: config.stages.length + 3,
        label: t('itsm.workflow.close', '确认关闭'),
        kind: 'end',
        state: stateByKey.get('close'),
        peopleLabel: t('itsm.workflow.requesterConfirm', '提单人确认'),
        active: selectedStepKey === 'close',
      },
    ];

    // 自动蛇形/多行折行排布：当节点数 > 4 时按每行 3 个节点排布，避免无限横向拉伸
    const colsPerRow = sequence.length > 5 ? 3 : sequence.length;
    const nextNodes: Node<PreviewNodeData>[] = sequence.map((data, index) => {
      const row = Math.floor(index / colsPerRow);
      const col = index % colsPerRow;
      return {
        id: `node-${index}`,
        type: 'preview',
        position: { x: col * 248, y: 48 + row * 136 },
        data,
        draggable: false,
        selectable: Boolean(onSelectStage || onSelectStepKey),
      };
    });

    const nextEdges: Edge[] = sequence.slice(1).map((item, index) => {
      const prevState = sequence[index].state;
      const isActiveEdge = prevState === 'done' && item.state === 'active';
      const isDoneEdge = prevState === 'done' && item.state === 'done';
      return {
        id: `edge-${index}`,
        source: `node-${index}`,
        target: `node-${index + 1}`,
        animated: Boolean(isActiveEdge),
        style: {
          stroke: isActiveEdge
            ? 'var(--color-primary)'
            : isDoneEdge
              ? 'var(--color-success)'
              : 'var(--color-border-2)',
          strokeWidth: isActiveEdge ? 2 : 1.5,
        },
      };
    });
    return { nodes: nextNodes, edges: nextEdges };
  }, [activeStageIndex, config, onSelectStage, onSelectStepKey, runtimeSteps, selectedStepKey, t]);

  return (
    <div
      className={`${heightClassName} overflow-hidden rounded-md border border-[var(--color-border-1)] bg-[var(--color-fill-1)]/45`}
    >
      <ReactFlow
        fitView
        fitViewOptions={{ padding: 0.24, maxZoom: 1 }}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesConnectable={false}
        elementsSelectable={Boolean(onSelectStage || onSelectStepKey)}
        onNodeClick={(_, node) => {
          const payload = node.data as PreviewNodeData & {
            stageIndex?: number;
            stepKey?: string;
          };
          if (typeof payload.stageIndex === 'number' && onSelectStage) {
            onSelectStage(payload.stageIndex);
          }
          if (payload.stepKey && onSelectStepKey) {
            onSelectStepKey(payload.stepKey);
          }
        }}
        panOnDrag
        zoomOnScroll
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
        {showControls ? <Controls showInteractive={false} /> : null}
      </ReactFlow>
    </div>
  );
}
