'use client';

import { FileAddOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Empty, Input, Skeleton, Tag } from 'antd';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
import type { CatalogService, PageResponse } from '../lib/types';

export default function CatalogPage() {
  const { t } = useTranslation();
  const { get } = useApiClient();
  const router = useRouter();
  const [records, setRecords] = useState<CatalogService[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const params = new URLSearchParams({ page_size: '100' });
      if (query.trim()) params.set('search', query.trim());
      const response = await get<PageResponse<CatalogService>>(`/itsm/api/catalog/?${params.toString()}`);
      setRecords(response.items ?? []);
    } catch {
      setFailed(true);
      setRecords([]);
    } finally {
      setLoading(false);
    }
  }, [get, query]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <ITSMPageShell
      title={t('itsm.catalog.title', '服务目录')}
      description={t('itsm.catalog.description', '选择服务并提交标准化申请')}
      actions={(
        <>
          <Input.Search
            allowClear
            className="w-60"
            placeholder={t('itsm.catalog.search', '搜索服务')}
            onSearch={setQuery}
          />
          <Button aria-label={t('itsm.common.refresh', '刷新')} icon={<ReloadOutlined />} onClick={() => void load()} />
        </>
      )}
    >
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" /> : null}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {[1, 2, 3].map((item) => <Card key={item}><Skeleton active paragraph={{ rows: 3 }} /></Card>)}
        </div>
      ) : records.length ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {records.map((service) => (
            <Card
              key={service.id}
              className="border-[var(--color-border)] bg-[var(--color-bg)]"
              actions={[
                <Button key="submit" type="link" icon={<FileAddOutlined />} onClick={() => router.push(`/itsm/catalog/${service.id}`)}>
                  {t('itsm.catalog.submit', '发起申请')}
                </Button>,
              ]}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="m-0 truncate text-sm font-semibold text-[var(--color-text-1)]">{service.name}</h2>
                  <p className="mb-0 mt-2 line-clamp-3 min-h-15 text-sm leading-5 text-[var(--color-text-3)]">
                    {service.description || '—'}
                  </p>
                </div>
                <Tag>{t('itsm.common.version', '版本 {version}', { version: service.current_version })}</Tag>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <div className="rounded-md bg-[var(--color-bg)] py-16"><Empty description={t('itsm.catalog.empty', '当前组织暂无已发布服务')} /></div>
      )}
    </ITSMPageShell>
  );
}
