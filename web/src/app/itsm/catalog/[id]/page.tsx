'use client';

import { ArrowLeftOutlined, SendOutlined } from '@ant-design/icons';
import { Alert, App, Button, Card, Skeleton } from 'antd';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../../components/page-shell';
import { ITSMSchemaForm, missingRequiredFields } from '../../components/schema-form';
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
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} /> : null}
      {loading ? (
        <Card><Skeleton active paragraph={{ rows: 6 }} /></Card>
      ) : service ? (
        <Card className="mx-auto max-w-3xl border-[var(--color-border)] bg-[var(--color-bg)]">
          <ITSMSchemaForm schema={service.form_schema} value={value} onChange={setValue} disabled={submitting} />
          <div className="flex justify-end border-t border-[var(--color-border-1)] pt-4">
            <Button type="primary" icon={<SendOutlined />} loading={submitting} onClick={() => void submit()}>
              {t('itsm.catalog.submit', '发起申请')}
            </Button>
          </div>
        </Card>
      ) : null}
    </ITSMPageShell>
  );
}
