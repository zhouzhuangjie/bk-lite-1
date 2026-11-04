import type { ReactNode } from 'react';

export function ITSMTableSurface({
  toolbar,
  summaryBar,
  children,
}: {
  toolbar: ReactNode;
  summaryBar?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
      {summaryBar ? (
        <div className="border-b border-[var(--color-border-1)] bg-[var(--color-fill-1)]/35 px-4 py-2.5">
          {summaryBar}
        </div>
      ) : null}
      <div className="border-b border-[var(--color-border-1)] px-4 py-3">{toolbar}</div>
      <div className="min-h-0 flex-1 [&_.ant-pagination]:m-4">{children}</div>
    </section>
  );
}
