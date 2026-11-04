import type { ReactNode } from 'react';

export function ITSMTableSurface({ toolbar, children }: { toolbar: ReactNode; children: ReactNode }) {
  return (
    <section className="min-w-0 overflow-hidden rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)]">
      <div className="px-4 pt-4">{toolbar}</div>
      <div className="[&_.ant-pagination]:m-4">{children}</div>
    </section>
  );
}
