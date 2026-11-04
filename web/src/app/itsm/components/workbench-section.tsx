'use client';

import type { ReactNode } from 'react';

export function WorkbenchSection({
  title,
  subtitle,
  icon,
  count,
  extra,
  children,
  className = '',
  bodyClassName = 'p-4',
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  count?: number;
  extra?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={`min-w-0 overflow-hidden rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] shadow-[0_1px_3px_rgba(0,0,0,0.03)] ${className}`.trim()}
    >
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border-1)] bg-[var(--color-fill-1)]/40 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          {icon ? (
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[var(--color-primary-bg-active)] text-xs text-[var(--color-primary)]">
              {icon}
            </span>
          ) : null}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="m-0 truncate text-[13px] font-semibold text-[var(--color-text-1)]">
                {title}
              </h2>
              {typeof count === 'number' && count > 0 ? (
                <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--color-primary)_12%,var(--color-bg))] px-1.5 text-xs font-semibold tabular-nums text-[var(--color-primary)]">
                  {count}
                </span>
              ) : null}
            </div>
            {subtitle ? (
              <div className="mt-0.5 truncate text-[11px] text-[var(--color-text-3)]">
                {subtitle}
              </div>
            ) : null}
          </div>
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
    <div className="divide-y divide-[var(--color-border-1)] px-4 py-1 text-xs">
      {items.map((item) => (
        <div
          key={item.key}
          className="flex items-center justify-between gap-3 py-2.5"
        >
          <span className="shrink-0 text-xs text-[var(--color-text-3)]">{item.label}</span>
          <span
            className={`min-w-0 truncate text-right font-medium text-[var(--color-text-1)] ${item.mono ? 'font-mono tabular-nums' : ''}`}
          >
            {item.value || '—'}
          </span>
        </div>
      ))}
    </div>
  );
}

export function WorkbenchMetric({
  label,
  value,
  hint,
  icon,
  tone = 'primary',
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: 'primary' | 'success' | 'warning' | 'error';
}) {
  const toneColor = {
    primary: 'var(--color-primary)',
    success: 'var(--color-success)',
    warning: 'var(--color-warning)',
    error: 'var(--color-fail)',
  }[tone];
  return (
    <div
      className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-[var(--color-border-1)] p-3.5 shadow-[0_1px_3px_rgba(0,0,0,0.03)]"
      style={{
        background: `linear-gradient(180deg, color-mix(in srgb, ${toneColor} 3%, var(--color-bg)) 0%, var(--color-bg) 56%)`,
      }}
    >
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-[var(--color-text-3)]">{label}</div>
        <div className="mt-1 truncate font-mono text-lg font-bold tracking-tight text-[var(--color-text-1)] tabular-nums">
          {value}
        </div>
        {hint ? (
          <div className="mt-0.5 truncate text-[11px] text-[var(--color-text-3)]">{hint}</div>
        ) : null}
      </div>
      {icon ? (
        <span
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-base"
          style={{
            color: toneColor,
            backgroundColor: `color-mix(in srgb, ${toneColor} 10%, var(--color-bg))`,
          }}
        >
          {icon}
        </span>
      ) : null}
    </div>
  );
}
