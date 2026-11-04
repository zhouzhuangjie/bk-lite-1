'use client';

import type { ReactNode } from 'react';

export function WorkbenchSection({
  title,
  icon,
  count,
  extra,
  children,
  className = '',
  bodyClassName = 'p-4',
}: {
  title: ReactNode;
  icon?: ReactNode;
  count?: number;
  extra?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`min-w-0 overflow-hidden rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] shadow-[0_1px_3px_rgba(0,0,0,0.03)] ${className}`.trim()}>
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border-1)] bg-[var(--color-fill-1)]/35 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          {icon ? <span className="shrink-0 text-sm text-[var(--color-primary)]">{icon}</span> : null}
          <h2 className="m-0 truncate text-[13px] font-semibold text-[var(--color-text-1)]">{title}</h2>
          {typeof count === 'number' && count > 0 ? (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--color-primary)_12%,var(--color-bg))] px-1.5 text-xs font-semibold tabular-nums text-[var(--color-primary)]">
              {count}
            </span>
          ) : null}
        </div>
        {extra ? <div className="flex shrink-0 items-center gap-2">{extra}</div> : null}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function WorkbenchPropertyList({
  items,
}: {
  items: Array<{ key: string; label: ReactNode; value: ReactNode; mono?: boolean }>;
}) {
  return (
    <div className="space-y-2 p-3 text-xs">
      {items.map((item) => (
        <div key={item.key} className="flex items-center justify-between gap-3 rounded-md bg-[var(--color-fill-1)]/35 px-3 py-2 transition-colors hover:bg-[var(--color-fill-1)]/60">
          <span className="shrink-0 text-[11px] font-medium text-[var(--color-text-3)]">{item.label}</span>
          <span className={`min-w-0 truncate text-right font-medium text-[var(--color-text-1)] ${item.mono ? 'font-mono tabular-nums' : ''}`}>
            {item.value || '—'}
          </span>
        </div>
      ))}
    </div>
  );
}

export function WorkbenchMetric({ label, value, tone = 'primary' }: { label: string; value: ReactNode; tone?: 'primary' | 'success' | 'warning' | 'error' }) {
  const toneColor = {
    primary: 'var(--color-primary)',
    success: 'var(--color-success)',
    warning: 'var(--color-warning)',
    error: 'var(--color-fail)',
  }[tone];
  return (
    <div
      className="min-w-0 rounded-lg border border-[var(--color-border-1)] p-3 shadow-[0_1px_3px_rgba(0,0,0,0.03)] sm:px-3.5 sm:py-3"
      style={{ background: `linear-gradient(180deg, color-mix(in srgb, ${toneColor} 1.5%, var(--color-bg)) 0%, var(--color-bg) 32%)` }}
    >
      <div className="text-xs font-medium text-[var(--color-text-3)]">{label}</div>
      <div className="mt-1 truncate font-mono text-xl font-bold tracking-tight text-[var(--color-text-1)] tabular-nums">{value}</div>
    </div>
  );
}
