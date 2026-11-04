'use client';

import type { ReactNode } from 'react';

import ListPageHeader from '@/components/list-page-header';

export function ITSMPageShell({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="h-full min-h-0 w-full p-4">
      <ListPageHeader title={title} description={description} actions={actions} />
      {children}
    </div>
  );
}
