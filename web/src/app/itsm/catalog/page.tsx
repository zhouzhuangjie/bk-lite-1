'use client';

import { AppstoreOutlined, FileAddOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Empty } from 'antd';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import CardGridSkeleton from '@/components/card-grid-skeleton';
import GridEntityCard from '@/components/grid-entity-card';
import SearchActionBar from '@/components/search-action-bar';
import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
import type { CatalogService, PageResponse } from '../lib/types';

export default function CatalogPage() {
  const { t } = useTranslation();
  const { convertToLocalizedTime } = useLocalizedTime();
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
      description={t('itsm.catalog.description', '选择标准服务，快速发起申请并跟踪处理进度')}
    >
      <SearchActionBar
        searchProps={{
          placeholder: t('itsm.catalog.search', '搜索服务'),
          value: query,
          onChange: (event) => setQuery(event.target.value),
          onSearch: setQuery,
        }}
        actions={(
          <Button aria-label={t('itsm.common.refresh', '刷新')} icon={<ReloadOutlined />} loading={loading} onClick={() => void load()} />
        )}
      />
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" action={<Button size="small" onClick={() => void load()}>{t('itsm.common.retry', '重试')}</Button>} /> : null}
      {loading ? (
        <CardGridSkeleton count={6} className="grid-cols-1 md:grid-cols-2 xl:grid-cols-3" />
      ) : records.length ? (
        <div className="grid auto-rows-max grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {records.map((service) => (
            <GridEntityCard
              key={service.id}
              name={service.name}
              description={service.description}
              icon={<AppstoreOutlined className="text-xl text-[var(--color-primary)]" />}
              statusTone="ok"
              statusLabel={t('itsm.catalog.available', '可申请')}
              updatedAt={convertToLocalizedTime(service.updated_at)}
              metaLabels={[t('itsm.common.version', '版本 {version}', { version: service.current_version })]}
              onClick={() => router.push(`/itsm/catalog/${service.id}`)}
              footer={(
                <div className="flex w-full items-center justify-between gap-3">
                  <span>{t('itsm.catalog.standardProcess', '标准化流程')}</span>
                  <span className="inline-flex items-center gap-1 font-medium text-[var(--color-primary)]">
                    <FileAddOutlined />
                    {t('itsm.catalog.submit', '发起申请')}
                  </span>
                </div>
              )}
              wash
            />
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-[var(--color-border-1)] bg-[var(--color-bg)] py-20">
          <Empty description={query ? t('itsm.catalog.noMatch', '没有匹配的服务') : t('itsm.catalog.empty', '当前组织暂无已发布服务')} />
        </div>
      )}
    </ITSMPageShell>
  );
}
