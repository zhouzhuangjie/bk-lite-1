import React from 'react';

interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  description,
  meta,
  actions,
  className = '',
}) => (
  <header
    className={`flex flex-wrap items-start justify-between gap-4 border-b border-(--color-border) bg-(--color-bg) px-6 py-4 ${className}`}
  >
    <div className="min-w-0 flex-1">
      <h1 className="text-base font-semibold leading-6 text-(--color-text-1)">{title}</h1>
      {description && (
        <div className="mt-1 text-xs leading-5 text-(--color-text-3)">{description}</div>
      )}
      {meta && <div className="mt-3 flex flex-wrap items-center gap-4">{meta}</div>}
    </div>
    {actions && <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div>}
  </header>
);

export default PageHeader;
