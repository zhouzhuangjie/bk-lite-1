'use client';
import React, { useEffect, useMemo, useState } from 'react';
import Masonry from 'react-masonry-css';
import assetsOverviewStyle from './index.module.scss';
import useApiClient from '@/utils/request';
import { useTranslation } from '@/utils/i18n';
import { GroupItem, ModelItem } from '@/app/cmdb/types/assetManage';
import { deepClone, getIconUrl } from '@/app/cmdb/utils/common';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
import { Button, Input } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import EllipsisWithTooltip from '@/components/ellipsis-with-tooltip';
import DataViewState, { DataViewStatus } from '@/components/data-view-state';
import PageHeader from '@/components/page-header';
import { useClassificationApi, useInstanceApi } from '@/app/cmdb/api';
import { useCommon } from '@/app/cmdb/context/common';

const AssetsOverview: React.FC = () => {
  const { isLoading } = useApiClient();
  const { t } = useTranslation();
  const router = useRouter();
  const commonContext = useCommon();
  const modelListFromContext = commonContext?.modelList || [];
  const [loading, setLoading] = useState<boolean>(false);
  const [overViewList, setOverViewList] = useState<GroupItem[]>([]);
  const [allOverViewList, setAllOverViewList] = useState<GroupItem[]>([]);
  const [searchText, setSearchText] = useState<string>('');
  const [loadError, setLoadError] = useState<boolean>(false);

  const { getClassificationList } = useClassificationApi();
  const { getModelInstanceCount } = useInstanceApi();

  useEffect(() => {
    if (isLoading || modelListFromContext.length === 0) return;
    fetchAssetsOverviewList();
  }, [isLoading, modelListFromContext]);

  const breakpointColumnsObj = {
    default: 4,
    1600: 4,
    1300: 3,
    1000: 3,
    700: 2,
    500: 1,
  };

  const handleTextChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchText(e.target.value);
  };

  const handleSearch = () => {
    const list = allOverViewList.filter((item) =>
      item.list.find((tex) =>
        tex.model_name.toLowerCase().includes(searchText.toLowerCase())
      )
    );
    setOverViewList(list);
  };

  const linkToDetial = (item: ModelItem) => {
    const params = new URLSearchParams({
      modelId: item.model_id,
      classificationId: item.classification_id,
    }).toString();
    router.push(`/cmdb/assetData?${params}`);
  };

  const handleClear = () => {
    setSearchText('');
    setOverViewList(allOverViewList);
  };

  const fetchAssetsOverviewList = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [groupData, instCount] = await Promise.all([
        getClassificationList(),
        getModelInstanceCount(),
      ]);

      const groups = deepClone(groupData).map((item: GroupItem) => ({
        ...item,
        list: [],
      }));

      modelListFromContext.forEach((modelItem: ModelItem) => {
        const target = groups.find(
          (item: GroupItem) =>
            item.classification_id === modelItem.classification_id
        );
        if (target) {
          modelItem.count = instCount[modelItem.model_id] || 0;
          target.list.push(modelItem);
        }
      });

      setOverViewList(groups);
      setAllOverViewList(groups);
    } catch {
      setOverViewList([]);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  const overviewStats = useMemo(() => {
    const models = allOverViewList.flatMap((group) => group.list);
    return {
      classificationCount: allOverViewList.length,
      modelCount: models.length,
      assetCount: models.reduce((total, model) => total + (model.count || 0), 0),
    };
  }, [allOverViewList]);

  const viewStatus: DataViewStatus = isLoading || loading
    ? 'loading'
    : loadError
      ? 'error'
      : overViewList.length > 0
        ? 'ready'
        : 'empty';

  return (
    <div className={assetsOverviewStyle.assetsOverview}>
      <PageHeader
        title={t('AssetOverview.title')}
        description={t('AssetOverview.description')}
        meta={(
          <>
            <span className={assetsOverviewStyle.statItem}>
              {t('AssetOverview.classificationCount')}
              <strong>{overviewStats.classificationCount}</strong>
            </span>
            <span className={assetsOverviewStyle.statItem}>
              {t('AssetOverview.modelCount')}
              <strong>{overviewStats.modelCount}</strong>
            </span>
            <span className={assetsOverviewStyle.statItem}>
              {t('AssetOverview.assetCount')}
              <strong>{overviewStats.assetCount.toLocaleString()}</strong>
            </span>
          </>
        )}
        actions={(
          <>
            <Input.Search
              className="w-80"
              size="large"
              value={searchText}
              allowClear
              placeholder={t('AssetOverview.searchPlaceholder')}
              onSearch={handleSearch}
              onClear={handleClear}
              onChange={handleTextChange}
            />
            <Button
              size="large"
              icon={<ReloadOutlined aria-hidden="true" />}
              loading={isLoading || loading}
              onClick={fetchAssetsOverviewList}
            >
              {t('common.refresh')}
            </Button>
          </>
        )}
      />
      <div className={assetsOverviewStyle.content}>
        <DataViewState
          status={viewStatus}
          title={loadError ? t('AssetOverview.errorTitle') : t('AssetOverview.emptyTitle')}
          description={loadError ? t('AssetOverview.errorDescription') : t('AssetOverview.emptyDescription')}
          retryLabel={t('common.retry')}
          onRetry={fetchAssetsOverviewList}
        >
          <Masonry
            breakpointCols={breakpointColumnsObj}
            className={assetsOverviewStyle['my-masonry-grid']}
            columnClassName="my-masonry-grid_column"
          >
            {overViewList.map((item) => (
              <div
                key={item.classification_id}
                className={`bg-[var(--color-bg-1)] p-[10px] mb-[20px] rounded`}
              >
                <h2
                  className={`${assetsOverviewStyle.title} text-[16px] font-[600]`}
                >
                  {item.classification_name}
                </h2>
                <ul className={assetsOverviewStyle.list}>
                  {item.list.map((sec) => (
                    <li
                      key={sec.model_id}
                    >
                      <button
                        type="button"
                        className={assetsOverviewStyle.listItem}
                        onClick={() => linkToDetial(sec)}
                      >
                        <span className={assetsOverviewStyle.leftSide}>
                          <Image
                            src={getIconUrl(sec)}
                            className="block w-auto h-10"
                            alt=""
                            width={20}
                            height={20}
                          />
                          <EllipsisWithTooltip
                            text={sec.model_name}
                            className="overflow-hidden text-ellipsis whitespace-nowrap"
                          />
                        </span>
                        <span className={assetsOverviewStyle.rightSide}>
                          {sec.count}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </Masonry>
        </DataViewState>
      </div>
    </div>
  );
};

export default AssetsOverview;
