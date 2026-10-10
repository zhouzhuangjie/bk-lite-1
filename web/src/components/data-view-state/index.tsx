'use client';

import React from 'react';
import { Button, Empty, Result, Skeleton } from 'antd';

export type DataViewStatus = 'initial' | 'loading' | 'empty' | 'error' | 'ready';

interface DataViewStateProps {
  status: DataViewStatus;
  children?: React.ReactNode;
  title?: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  onRetry?: () => void;
  retryLabel?: React.ReactNode;
  loadingRows?: number;
  className?: string;
}

const DataViewState: React.FC<DataViewStateProps> = ({
  status,
  children,
  title,
  description,
  action,
  onRetry,
  retryLabel,
  loadingRows = 6,
  className = '',
}) => {
  if (status === 'ready') return <>{children}</>;

  if (status === 'loading') {
    return (
      <div className={`rounded-lg border border-(--color-border) bg-(--color-bg) p-6 ${className}`} aria-busy="true">
        <Skeleton active paragraph={{ rows: loadingRows }} />
      </div>
    );
  }

  if (status === 'error') {
    const retryAction = onRetry ? (
      <Button type="primary" onClick={onRetry}>
        {retryLabel}
      </Button>
    ) : null;

    return (
      <Result
        className={className}
        status="error"
        title={title}
        subTitle={description}
        extra={action || retryAction}
      />
    );
  }

  return (
    <div className={`flex min-h-60 items-center justify-center ${className}`}>
      <Empty
        image={status === 'initial' ? Empty.PRESENTED_IMAGE_DEFAULT : Empty.PRESENTED_IMAGE_SIMPLE}
        description={(
          <div>
            {title && <div className="font-medium text-(--color-text-2)">{title}</div>}
            {description && <div className="mt-1 text-xs text-(--color-text-3)">{description}</div>}
          </div>
        )}
      >
        {action}
      </Empty>
    </div>
  );
};

export default DataViewState;
