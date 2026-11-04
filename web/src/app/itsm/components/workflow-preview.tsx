'use client';

import { Background, BackgroundVariant, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo } from 'react';

import { useTranslation } from '@/utils/i18n';
import type { WorkflowConfig } from '../lib/types';

interface PreviewNodeData extends Record<string, unknown> {
  label: string;
  kind: 'start' | 'approval' | 'handling' | 'end';
  meta?: string;
}

function PreviewNode({ data }: NodeProps<Node<PreviewNodeData>>) {
  const tone = data.kind === 'approval'
    ? 'border-[var(--color-primary)] bg-[var(--color-primary-bg-active)]'
    : 'border-[var(--color-border)] bg-[var(--color-bg)]';
  return (
    <div className={`relative min-w-36 rounded-lg border px-4 py-3 text-center ${tone}`}>
      {data.kind !== 'start' ? <Handle type="target" position={Position.Left} className="opacity-0" /> : null}
      <div className="text-sm font-medium text-[var(--color-text-1)]">{data.label}</div>
      {data.meta ? <div className="mt-1 text-xs text-[var(--color-text-3)]">{data.meta}</div> : null}
      {data.kind !== 'end' ? <Handle type="source" position={Position.Right} className="opacity-0" /> : null}
    </div>
  );
}

const nodeTypes = { preview: PreviewNode };

export function WorkflowPreview({ config }: { config: WorkflowConfig }) {
  const { t } = useTranslation();
  const { nodes, edges } = useMemo(() => {
    const sequence: PreviewNodeData[] = [
      { label: t('itsm.workflow.submit', '提单'), kind: 'start' },
      ...config.stages.map((stage) => ({
        label: stage.name,
        kind: 'approval' as const,
        meta: `${stage.mode === 'serial' ? t('itsm.service.serial', '依次审批') : t('itsm.service.parallel', '并行会签')} · ${t('itsm.workflow.people', '{count} 人', { count: stage.approverIds.length })}`,
      })),
      { label: t('itsm.workflow.handling', '工单处理'), kind: 'handling', meta: t('itsm.workflow.people', '{count} 人', { count: config.handlerIds.length }) },
      { label: t('itsm.workflow.close', '确认关闭'), kind: 'end' },
    ];
    const nextNodes: Node<PreviewNodeData>[] = sequence.map((data, index) => ({
      id: `node-${index}`,
      type: 'preview',
      position: { x: index * 220, y: 100 },
      data,
      draggable: false,
      selectable: false,
    }));
    const nextEdges: Edge[] = sequence.slice(1).map((_, index) => ({
      id: `edge-${index}`,
      source: `node-${index}`,
      target: `node-${index + 1}`,
      animated: false,
    }));
    return { nodes: nextNodes, edges: nextEdges };
  }, [config, t]);

  return (
    <div className="h-80 overflow-hidden rounded-md border border-[var(--color-border)] bg-[var(--color-fill-1)]">
      <ReactFlow
        fitView
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag
        zoomOnScroll
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
      </ReactFlow>
    </div>
  );
}
