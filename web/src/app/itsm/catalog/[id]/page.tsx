'use client';

import { ArrowLeftOutlined, CheckCircleOutlined, FileTextOutlined, SendOutlined } from '@ant-design/icons';
import { Alert, App, Button, Skeleton, Steps } from 'antd';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../../components/page-shell';
import { ITSMSchemaForm, missingRequiredFields } from '../../components/schema-form';
import { WorkbenchPropertyList, WorkbenchSection } from '../../components/workbench-section';
import { newRequestKey } from '../../lib/status';
import type { CatalogService, TicketRecord } from '../../lib/types';

export default function CatalogSubmitPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { get, post } = useApiClient();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [service, setService] = useState<CatalogService>();
  const [value, setValue] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setService(await get<CatalogService>(`/itsm/api/catalog/${params.id}/`));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [get, params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async () => {
    if (!service || missingRequiredFields(service.form_schema, value).length) {
      message.warning(t('itsm.common.required', '请填写必填项'));
      return;
    }
    setSubmitting(true);
    try {
      const ticket = await post<TicketRecord>('/itsm/api/tickets/', {
        service_id: service.id,
        request_key: newRequestKey('submit'),
        form_data: value,
      });
      message.success(t('itsm.ticket.submitSuccess', '工单已提交'));
      router.push(`/itsm/tickets/${ticket.id}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ITSMPageShell
      title={service?.name ?? t('itsm.catalog.submit', '发起申请')}
      description={service?.description}
      actions={<Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/itsm/catalog')}>{t('itsm.common.back', '返回')}</Button>}
    >
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} action={<Button size="small" onClick={() => void load()}>{t('itsm.common.retry', '重试')}</Button>} /> : null}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <WorkbenchSection title={t('itsm.catalog.requestInfo', '申请信息')}><Skeleton active paragraph={{ rows: 7 }} /></WorkbenchSection>
          <WorkbenchSection title={t('itsm.catalog.guide', '提单指引')}><Skeleton active paragraph={{ rows: 5 }} /></WorkbenchSection>
        </div>
      ) : service ? (
        <div className="flex min-w-0 flex-col items-start gap-4 lg:flex-row">
          <WorkbenchSection
            title={t('itsm.catalog.requestInfo', '申请信息')}
            icon={<FileTextOutlined />}
            className="w-full flex-1"
            extra={<span className="text-xs text-[var(--color-text-3)]">{t('itsm.catalog.requiredHint', '* 为必填项')}</span>}
          >
            <ITSMSchemaForm schema={service.form_schema} value={value} onChange={setValue} disabled={submitting} />
            <div className="flex items-center justify-between gap-3 border-t border-[var(--color-border-1)] pt-4">
              <span className="text-xs text-[var(--color-text-3)]">{t('itsm.catalog.submitHint', '提交后可在“我的工单”中持续查看进度')}</span>
              <Button type="primary" icon={<SendOutlined />} loading={submitting} onClick={() => void submit()}>
                {t('itsm.catalog.submit', '发起申请')}
              </Button>
            </div>
          </WorkbenchSection>
          <div className="w-full shrink-0 space-y-4 lg:w-80">
            <WorkbenchSection title={t('itsm.catalog.guide', '提单指引')} icon={<CheckCircleOutlined />} bodyClassName="p-4">
              <Steps
                direction="vertical"
                size="small"
                current={0}
                items={[
                  { title: t('itsm.catalog.stepFill', '填写申请信息'), description: t('itsm.catalog.stepFillDesc', '按服务表单补充必要内容') },
                  { title: t('itsm.catalog.stepProcess', '进入审批与处理'), description: t('itsm.catalog.stepProcessDesc', '系统按已发布流程自动流转') },
                  { title: t('itsm.catalog.stepTrack', '跟踪并确认结果'), description: t('itsm.catalog.stepTrackDesc', '处理完成后由提单人确认关闭') },
                ]}
              />
            </WorkbenchSection>
            <WorkbenchSection title={t('itsm.catalog.serviceInfo', '服务信息')} bodyClassName="p-0">
              <WorkbenchPropertyList items={[
                { key: 'service', label: t('itsm.ticket.service', '服务'), value: service.name },
                { key: 'version', label: t('itsm.ticket.version', '版本'), value: `V${service.current_version}`, mono: true },
                { key: 'fields', label: t('itsm.catalog.fieldCount', '表单字段'), value: Object.keys(service.form_schema.properties).length, mono: true },
              ]} />
            </WorkbenchSection>
          </div>
        </div>
      ) : null}
    </ITSMPageShell>
  );
}
