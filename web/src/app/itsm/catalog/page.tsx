'use client';

import {
  ApartmentOutlined,
  AppstoreOutlined,
  FileAddOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { Alert, Button, Empty, Segmented } from 'antd';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import CardGridSkeleton from '@/components/card-grid-skeleton';
import GridEntityCard from '@/components/grid-entity-card';
import SearchActionBar from '@/components/search-action-bar';
import ToolbarSplitShell from '@/components/toolbar-split-shell';
import { useLocalizedTime } from '@/hooks/useLocalizedTime';
import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../components/page-shell';
import type { CatalogService, PageResponse } from '../lib/types';

type CatalogFilter = 'ALL' | 'MULTI_STAGE' | 'SIGN_ENABLED';

export default function CatalogPage() {
  const { t } = useTranslation();
  const { convertToLocalizedTime } = useLocalizedTime();
  const { get } = useApiClient();
  const router = useRouter();
  const [records, setRecords] = useState<CatalogService[]>([]);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<CatalogFilter>('ALL');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const params = new URLSearchParams({ page_size: '100' });
      if (query.trim()) params.set('search', query.trim());
      const response = await get<PageResponse<CatalogService>>(
        `/itsm/api/catalog/?${params.toString()}`,
      );
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

  const filteredRecords = useMemo(() => {
    if (category === 'MULTI_STAGE') {
      return records.filter((item) => (item.workflow_config?.stages?.length ?? 0) > 1);
    }
    if (category === 'SIGN_ENABLED') {
      return records.filter((item) =>
        item.workflow_config?.stages?.some(
          (stage) => stage.allowBeforeSign || stage.allowAfterSign,
        ),
      );
    }
    return records;
  }, [category, records]);

  const filterOptions = useMemo(
    () => [
      {
        label: `${t('itsm.common.all', '全部')} (${records.length})`,
        value: 'ALL',
      },
      {
        label: t('itsm.catalog.multiStageFilter', '多级审批'),
        value: 'MULTI_STAGE',
      },
      {
        label: t('itsm.catalog.signFilter', '支持加签'),
        value: 'SIGN_ENABLED',
      },
    ],
    [records.length, t],
  );

  return (
    <ITSMPageShell
      title={t('itsm.catalog.title', '服务目录')}
      description={t('itsm.catalog.description', '选择标准服务，快速发起申请并跟踪处理进度')}
    >
      <div className="mb-4 rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] px-4 py-3 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
        <ToolbarSplitShell
          leading={
            <Segmented
              options={filterOptions}
              value={category}
              onChange={(val) => setCategory(val as CatalogFilter)}
            />
          }
          trailing={
            <SearchActionBar
              className="!mb-0"
              searchProps={{
                placeholder: t('itsm.catalog.search', '搜索服务'),
                value: query,
                onChange: (event) => setQuery(event.target.value),
                onSearch: setQuery,
              }}
              actions={
                <Button
                  aria-label={t('itsm.common.refresh', '刷新')}
                  icon={<ReloadOutlined />}
                  loading={loading}
                  onClick={() => void load()}
                />
              }
            />
          }
        />
      </div>

      {failed ? (
        <Alert
          showIcon
          type="error"
          message={t('itsm.common.loadingFailed', '加载失败，请重试')}
          className="mb-4"
          action={
            <Button size="small" onClick={() => void load()}>
              {t('itsm.common.retry', '重试')}
            </Button>
          }
        />
      ) : null}

      {loading ? (
        <CardGridSkeleton count={6} className="grid-cols-1 md:grid-cols-2 xl:grid-cols-3" />
      ) : filteredRecords.length ? (
        <div className="grid auto-rows-max grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredRecords.map((service) => {
            const fieldCount = Object.keys(service.form_schema?.properties ?? {}).length;
            const stages = service.workflow_config?.stages ?? [];
            const stageNames = stages.map((stage) => stage.name).filter(Boolean);
            const flowSummary = stageNames.length
              ? stageNames.join(' → ')
              : t('itsm.catalog.standardProcess', '标准化流程');

            return (
              <GridEntityCard
                key={service.id}
                name={service.name}
                description={
                  service.description ||
                  t('itsm.catalog.defaultDesc', '点击进入服务表单填写申请信息并启动标准审批流转')
                }
                icon={<AppstoreOutlined className="text-xl text-[var(--color-primary)]" />}
                statusTone="ok"
                statusLabel={t('itsm.catalog.available', '可申请')}
                updatedAt={convertToLocalizedTime(service.updated_at)}
                metaLabels={[
                  `V${service.current_version}`,
                  t('itsm.catalog.fieldBadge', '{count} 个表单项', { count: fieldCount }),
                  ...(stages.length
                    ? [
                        t('itsm.catalog.stageBadge', '{count} 级审批', {
                          count: stages.length,
                        }),
                      ]
                    : []),
                ]}
                onClick={() => router.push(`/itsm/catalog/${service.id}`)}
                footer={
                  <div className="flex w-full items-center justify-between gap-3">
                    <span className="inline-flex min-w-0 items-center gap-1.5 truncate text-xs text-[var(--color-text-3)]">
                      {stages.length ? <ApartmentOutlined /> : <FileTextOutlined />}
                      <span className="truncate">{flowSummary}</span>
                    </span>
                    <span className="inline-flex shrink-0 items-center gap-1 font-medium text-[var(--color-primary)]">
                      <FileAddOutlined />
                      {t('itsm.catalog.submit', '发起申请')}
                    </span>
                  </div>
                }
                wash
              />
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-[var(--color-border-1)] bg-[var(--color-bg)] py-20">
          <Empty
            description={
              query || category !== 'ALL'
                ? t('itsm.catalog.noMatch', '没有匹配的服务')
                : t('itsm.catalog.empty', '当前组织暂无已发布服务')
            }
          />
        </div>
      )}
    </ITSMPageShell>
  );
}
