'use client';

import { ApartmentOutlined, ArrowLeftOutlined, DeleteOutlined, EyeOutlined, FileTextOutlined, PlusOutlined, SaveOutlined, SendOutlined } from '@ant-design/icons';
import { Alert, App, Button, Form, Input, Popconfirm, Select, Skeleton, Space, Switch, Tabs, Tag } from 'antd';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from '@/utils/i18n';
import useApiClient from '@/utils/request';
import { ITSMPageShell } from '../../components/page-shell';
import { ITSMSchemaForm } from '../../components/schema-form';
import { WorkbenchPropertyList, WorkbenchSection } from '../../components/workbench-section';
import { WorkflowPreview } from '../../components/workflow-preview';
import type { JsonSchemaField, ServiceRecord, UserOption, WorkflowStage } from '../../lib/types';

interface UserListResponse {
  users: UserOption[];
}

type EditableFieldType = 'string' | 'textarea' | 'integer' | 'number' | 'boolean' | 'select' | 'multiselect';

function fieldType(field: JsonSchemaField): EditableFieldType {
  if (field.type === 'array') return 'multiselect';
  if (field.enum) return 'select';
  if (field['x-widget'] === 'textarea') return 'textarea';
  if (field.type === 'integer') return 'integer';
  if (field.type === 'number') return 'number';
  if (field.type === 'boolean') return 'boolean';
  return 'string';
}

export default function ServiceEditorPage() {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const { get, patch, post } = useApiClient();
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [service, setService] = useState<ServiceRecord>();
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [userLoading, setUserLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setService(await get<ServiceRecord>(`/itsm/api/services/${params.id}/`));
      setDirty(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [get, params.id]);

  const searchUsers = useCallback(async (search = '') => {
    setUserLoading(true);
    try {
      const response = await get<UserListResponse>('/core/api/user_group/user_list/', {
        params: { page: 1, page_size: 100, search },
      });
      setUsers(response.users ?? []);
    } finally {
      setUserLoading(false);
    }
  }, [get]);

  useEffect(() => {
    void load();
    void searchUsers();
  }, [load, searchUsers]);

  useEffect(() => {
    const preventAccidentalExit = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
    };
    window.addEventListener('beforeunload', preventAccidentalExit);
    return () => window.removeEventListener('beforeunload', preventAccidentalExit);
  }, [dirty]);

  const leaveEditor = () => {
    if (!dirty) {
      router.push('/itsm/services');
      return;
    }
    modal.confirm({
      title: t('itsm.service.unsavedTitle', '存在未保存更改'),
      content: t('itsm.service.unsavedContent', '离开后本次更改将丢失，确认继续？'),
      okText: t('itsm.service.leave', '离开'),
      cancelText: t('itsm.common.cancel', '取消'),
      onOk: () => router.push('/itsm/services'),
    });
  };

  const mutate = (updater: (current: ServiceRecord) => ServiceRecord) => {
    setService((current) => current ? updater(current) : current);
    setDirty(true);
  };

  const saveDraft = async (): Promise<ServiceRecord | undefined> => {
    if (!service) return undefined;
    setSaving(true);
    try {
      const updated = await patch<ServiceRecord>(`/itsm/api/services/${service.id}/`, {
        name: service.name,
        description: service.description,
        form_schema: service.form_schema,
        workflow_config: service.workflow_config,
        draft_revision: service.draft_revision,
      });
      setService(updated);
      setDirty(false);
      message.success(t('itsm.service.saveSuccess', '草稿已保存'));
      return updated;
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    if (!service) return;
    setPublishing(true);
    try {
      const target = dirty ? await saveDraft() : service;
      if (!target) return;
      await post(`/itsm/api/services/${target.id}/publish/`, {});
      message.success(t('itsm.service.publishSuccess', '发布任务已提交'));
      await load();
    } finally {
      setPublishing(false);
    }
  };

  const updateField = (key: string, nextKey: string, patchValue: Partial<JsonSchemaField>) => {
    mutate((current) => {
      const nextProperties = { ...current.form_schema.properties };
      const field = { ...nextProperties[key], ...patchValue };
      delete nextProperties[key];
      nextProperties[nextKey] = field;
      return {
        ...current,
        form_schema: {
          ...current.form_schema,
          properties: nextProperties,
          required: current.form_schema.required.map((item) => item === key ? nextKey : item),
        },
      };
    });
  };

  const changeFieldType = (key: string, type: EditableFieldType) => {
    let next: JsonSchemaField;
    const title = service?.form_schema.properties[key]?.title ?? key;
    if (type === 'textarea') next = { type: 'string', title, maxLength: 2000, 'x-widget': 'textarea' };
    else if (type === 'integer') next = { type: 'integer', title, 'x-widget': 'number' };
    else if (type === 'number') next = { type: 'number', title, 'x-widget': 'number' };
    else if (type === 'boolean') next = { type: 'boolean', title, 'x-widget': 'switch' };
    else if (type === 'select') next = { type: 'string', title, enum: [t('itsm.service.optionOne', '选项 1'), t('itsm.service.optionTwo', '选项 2')], 'x-widget': 'select' };
    else if (type === 'multiselect') next = { type: 'array', title, items: { type: 'string', enum: [t('itsm.service.optionOne', '选项 1'), t('itsm.service.optionTwo', '选项 2')] }, maxItems: 20, 'x-widget': 'multiselect' };
    else next = { type: 'string', title, maxLength: 120, 'x-widget': 'input' };
    updateField(key, key, next);
  };

  const updateChoices = (key: string, rawValue: string) => {
    const choices = [...new Set(rawValue.split(',').map((item) => item.trim()).filter(Boolean))];
    const field = service?.form_schema.properties[key];
    if (!field) return;
    if (field.type === 'array') updateField(key, key, { items: { type: 'string', enum: choices } });
    else updateField(key, key, { enum: choices });
  };

  const addField = () => {
    if (!service) return;
    let index = Object.keys(service.form_schema.properties).length + 1;
    let key = `field_${index}`;
    while (service.form_schema.properties[key]) {
      index += 1;
      key = `field_${index}`;
    }
    mutate((current) => ({
      ...current,
      form_schema: {
        ...current.form_schema,
        properties: {
          ...current.form_schema.properties,
          [key]: { type: 'string', title: t('itsm.service.fieldDefault', '字段 {index}', { index }), maxLength: 120, 'x-widget': 'input' },
        },
      },
    }));
  };

  const deleteField = (key: string) => {
    mutate((current) => {
      const properties = { ...current.form_schema.properties };
      delete properties[key];
      return {
        ...current,
        form_schema: {
          ...current.form_schema,
          properties,
          required: current.form_schema.required.filter((item) => item !== key),
        },
      };
    });
  };

  const setRequired = (key: string, required: boolean) => {
    mutate((current) => ({
      ...current,
      form_schema: {
        ...current.form_schema,
        required: required
          ? [...new Set([...current.form_schema.required, key])]
          : current.form_schema.required.filter((item) => item !== key),
      },
    }));
  };

  const updateStage = (index: number, patchValue: Partial<WorkflowStage>) => {
    mutate((current) => ({
      ...current,
      workflow_config: {
        ...current.workflow_config,
        stages: current.workflow_config.stages.map((stage, itemIndex) => itemIndex === index ? { ...stage, ...patchValue } : stage),
      },
    }));
  };

  const addStage = () => {
    mutate((current) => {
      const index = current.workflow_config.stages.length + 1;
      const fallbackApprover = current.workflow_config.stages.at(-1)?.approverIds[0] ?? current.workflow_config.handlerIds[0];
      return {
        ...current,
        workflow_config: {
          ...current.workflow_config,
          stages: [...current.workflow_config.stages, {
            key: `approval_${Date.now()}`,
            name: t('itsm.service.approvalDefault', '审批 {index}', { index }),
            mode: 'serial',
            approverIds: fallbackApprover ? [fallbackApprover] : [],
            allowBeforeSign: true,
            allowAfterSign: true,
          }],
        },
      };
    });
  };

  const deleteStage = (index: number) => {
    mutate((current) => ({
      ...current,
      workflow_config: {
        ...current.workflow_config,
        stages: current.workflow_config.stages.filter((_, itemIndex) => itemIndex !== index),
      },
    }));
  };

  const userOptions = useMemo(() => users.map((user) => ({
    value: user.id,
    label: user.display_name ? `${user.display_name} (${user.username})` : user.username,
  })), [users]);

  if (loading) {
    return (
      <div className="h-full min-h-0 w-full p-4">
        <div className="mb-4 flex items-center justify-between"><Skeleton.Input active className="!w-52" /><Skeleton.Button active /></div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <WorkbenchSection title={t('itsm.service.designWorkbench', '服务设计工作台')}><Skeleton active paragraph={{ rows: 12 }} /></WorkbenchSection>
          <WorkbenchSection title={t('itsm.service.publishOverview', '发布概览')}><Skeleton active paragraph={{ rows: 8 }} /></WorkbenchSection>
        </div>
      </div>
    );
  }

  return (
    <ITSMPageShell
      title={service?.name ?? t('itsm.service.edit', '编辑服务')}
      description={service?.description}
      actions={(
        <>
          <Button icon={<ArrowLeftOutlined />} onClick={leaveEditor}>{t('itsm.common.back', '返回')}</Button>
          <Button icon={<SaveOutlined />} loading={saving} disabled={!service || !dirty} onClick={() => void saveDraft()}>{t('itsm.service.save', '保存草稿')}</Button>
          <Button type="primary" icon={<SendOutlined />} loading={publishing} disabled={!service} onClick={() => void publish()}>{t('itsm.service.publish', '发布')}</Button>
        </>
      )}
    >
      {failed ? <Alert showIcon type="error" message={t('itsm.common.loadingFailed', '加载失败，请重试')} className="mb-4" action={<Button size="small" onClick={() => void load()}>{t('itsm.common.retry', '重试')}</Button>} /> : null}
      {service ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] px-4 py-3 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
            <div className="flex flex-wrap items-center gap-2">
              <Tag color={service.status === 'PUBLISHED' ? 'success' : service.status === 'DISABLED' ? 'error' : 'default'}>
                {service.status === 'PUBLISHED' ? t('itsm.service.published', '已发布') : service.status === 'DISABLED' ? t('itsm.service.disabled', '已停用') : t('itsm.service.draft', '草稿')}
              </Tag>
              <span className="text-xs text-[var(--color-text-3)]">{t('itsm.service.versionAndRevision', '当前版本 V{version} · 草稿修订 {revision}', { version: service.current_version, revision: service.draft_revision })}</span>
              {dirty ? <span className="inline-flex items-center gap-1 text-xs text-[var(--color-warning)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--color-warning)]" />{t('itsm.service.unsaved', '有未保存更改')}</span> : <span className="inline-flex items-center gap-1 text-xs text-[var(--color-success)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />{t('itsm.service.saved', '已保存')}</span>}
            </div>
            <span className="text-xs text-[var(--color-text-3)]">{t('itsm.service.publishHint', '保存草稿后发布，服务目录将使用新的只读版本')}</span>
          </div>
          <WorkbenchSection title={t('itsm.service.basicSettings', '基础设置')} icon={<ApartmentOutlined />}>
            <Form layout="vertical">
              <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                <Form.Item label={t('itsm.service.name', '服务名称')} required className="mb-0">
                  <Input maxLength={120} value={service.name} onChange={(event) => mutate((current) => ({ ...current, name: event.target.value }))} />
                </Form.Item>
                <Form.Item label={t('itsm.service.descriptionLabel', '服务说明')} className="mb-0">
                  <Input maxLength={500} value={service.description} onChange={(event) => mutate((current) => ({ ...current, description: event.target.value }))} />
                </Form.Item>
              </div>
            </Form>
          </WorkbenchSection>
          <div className="overflow-hidden rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
            <Tabs
              className="[&_.ant-tabs-nav]:!mb-0 [&_.ant-tabs-nav]:px-4 [&_.ant-tabs-content]:h-full"
              items={[
              {
                key: 'form',
                label: t('itsm.service.formDesign', '表单设计'),
                children: (
                  <div className="grid min-h-[520px] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="min-w-0 space-y-3 p-4 lg:border-r lg:border-[var(--color-border-1)]">
                      <div className="mb-1 flex items-center justify-between gap-3">
                        <div>
                          <div className="text-[13px] font-semibold text-[var(--color-text-1)]">{t('itsm.service.fieldConfiguration', '字段配置')}</div>
                          <div className="mt-1 text-xs text-[var(--color-text-3)]">{t('itsm.service.fieldConfigurationHint', '字段顺序即提单页展示顺序，标识用于后端数据存储')}</div>
                        </div>
                        <Button type="primary" ghost size="small" icon={<PlusOutlined />} onClick={addField}>{t('itsm.service.addField', '添加字段')}</Button>
                      </div>
                      {Object.entries(service.form_schema.properties).map(([key, field], index) => (
                        <div key={key} className="rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] p-3 transition-colors hover:border-[var(--color-primary)]">
                          <div className="mb-3 flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2">
                              <span className="grid h-6 min-w-6 place-items-center rounded-md bg-[var(--color-fill-1)] px-1 text-xs font-semibold text-[var(--color-text-2)] tabular-nums">{index + 1}</span>
                              <span className="text-sm font-medium text-[var(--color-text-1)]">{field.title || key}</span>
                              {service.form_schema.required.includes(key) ? <Tag color="blue">{t('itsm.service.required', '必填')}</Tag> : null}
                            </div>
                            <Popconfirm title={t('itsm.service.deleteField', '确认删除该字段？')} onConfirm={() => deleteField(key)}>
                              <Button type="text" danger size="small" aria-label={t('itsm.service.deleteFieldLabel', '删除字段')} icon={<DeleteOutlined />} />
                            </Popconfirm>
                          </div>
                          <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-2 xl:grid-cols-[1fr_1fr_160px_96px]">
                            <Form.Item label={t('itsm.service.fieldName', '字段标识')} className="mb-0">
                              <Input defaultValue={key} onBlur={(event) => {
                                const nextKey = event.target.value.trim();
                                if (nextKey && nextKey !== key) updateField(key, nextKey, {});
                              }} />
                            </Form.Item>
                            <Form.Item label={t('itsm.service.fieldTitle', '字段名称')} className="mb-0">
                              <Input value={field.title} onChange={(event) => updateField(key, key, { title: event.target.value })} />
                            </Form.Item>
                            <Form.Item label={t('itsm.service.fieldType', '字段类型')} className="mb-0">
                              <Select value={fieldType(field)} options={[
                                { value: 'string', label: t('itsm.service.fieldText', '文本') },
                                { value: 'textarea', label: t('itsm.service.fieldTextarea', '多行文本') },
                                { value: 'integer', label: t('itsm.service.fieldInteger', '整数') },
                                { value: 'number', label: t('itsm.service.fieldNumber', '数字') },
                                { value: 'boolean', label: t('itsm.service.fieldBoolean', '开关') },
                                { value: 'select', label: t('itsm.service.fieldSelect', '单选') },
                                { value: 'multiselect', label: t('itsm.service.fieldMultiselect', '多选') },
                              ]} onChange={(value) => changeFieldType(key, value)} />
                            </Form.Item>
                            <Form.Item label={t('itsm.service.required', '必填')} className="mb-0">
                              <Switch checked={service.form_schema.required.includes(key)} onChange={(value) => setRequired(key, value)} />
                            </Form.Item>
                            {field.enum || field.type === 'array' ? (
                              <Form.Item label={t('itsm.service.options', '候选项')} extra={t('itsm.service.optionsHint', '使用英文逗号分隔，至少填写一项')} className="mb-0 md:col-span-2 xl:col-span-4">
                                <Input value={(field.type === 'array' ? field.items?.enum : field.enum)?.join(', ') ?? ''} onChange={(event) => updateChoices(key, event.target.value)} />
                              </Form.Item>
                            ) : null}
                          </div>
                        </div>
                      ))}
                      {!Object.keys(service.form_schema.properties).length ? <div className="rounded-lg border border-dashed border-[var(--color-border-1)] py-16 text-center text-sm text-[var(--color-text-3)]">{t('itsm.service.noFields', '暂无字段，请先添加字段')}</div> : null}
                    </div>
                    <div className="bg-[var(--color-fill-1)]/35 p-4">
                      <div className="sticky top-4 overflow-hidden rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)]">
                        <div className="flex items-center gap-2 border-b border-[var(--color-border-1)] bg-[var(--color-fill-1)]/35 px-4 py-2.5">
                          <EyeOutlined className="text-[var(--color-primary)]" />
                          <span className="text-[13px] font-semibold text-[var(--color-text-1)]">{t('itsm.service.formPreview', '提单页预览')}</span>
                        </div>
                        <div className="p-4"><ITSMSchemaForm schema={service.form_schema} value={{}} onChange={() => undefined} disabled /></div>
                      </div>
                    </div>
                  </div>
                ),
              },
              {
                key: 'workflow',
                label: t('itsm.service.workflowDesign', '流程设计'),
                children: (
                  <div className="space-y-4 p-4">
                    <WorkbenchSection title={t('itsm.service.processPreview', '流程预览')} icon={<ApartmentOutlined />} bodyClassName="p-0">
                      <WorkflowPreview config={service.workflow_config} />
                    </WorkbenchSection>
                    <div className="flex items-center justify-between gap-3 pt-1">
                      <div>
                        <div className="text-[13px] font-semibold text-[var(--color-text-1)]">{t('itsm.service.nodeConfiguration', '节点配置')}</div>
                        <div className="mt-1 text-xs text-[var(--color-text-3)]">{t('itsm.service.nodeConfigurationHint', '审批节点按下方顺序流转；每个节点可单独开放前加签或后加签')}</div>
                      </div>
                      <Button type="primary" ghost size="small" icon={<PlusOutlined />} onClick={addStage}>{t('itsm.service.addStage', '添加审批节点')}</Button>
                    </div>
                    {service.workflow_config.stages.map((stage, index) => (
                      <div key={stage.key} className="rounded-lg border border-[var(--color-border-1)] p-4 transition-colors hover:border-[var(--color-primary)]">
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <span className="grid h-6 min-w-6 place-items-center rounded-md bg-[var(--color-primary-bg-active)] px-1 text-xs font-semibold text-[var(--color-primary)] tabular-nums">{index + 1}</span>
                            <span className="text-sm font-semibold text-[var(--color-text-1)]">{stage.name || t('itsm.service.approvalNode', '审批节点 {index}', { index: index + 1 })}</span>
                            <Tag>{stage.mode === 'serial' ? t('itsm.service.serial', '依次审批') : t('itsm.service.parallel', '并行会签')}</Tag>
                          </div>
                          {service.workflow_config.stages.length > 1 ? (
                            <Popconfirm title={t('itsm.service.deleteStage', '确认删除该审批节点？')} onConfirm={() => deleteStage(index)}>
                              <Button type="text" danger size="small" icon={<DeleteOutlined />}>{t('itsm.service.delete', '删除')}</Button>
                            </Popconfirm>
                          ) : null}
                        </div>
                        <div className="grid grid-cols-1 gap-x-4 lg:grid-cols-2">
                          <Form.Item label={t('itsm.service.stageName', '节点名称')} required>
                            <Input value={stage.name} onChange={(event) => updateStage(index, { name: event.target.value })} />
                          </Form.Item>
                          <Form.Item label={t('itsm.service.approvalMode', '审批方式')} required>
                            <Select value={stage.mode} options={[
                              { value: 'serial', label: t('itsm.service.serial', '依次审批') },
                              { value: 'parallel', label: t('itsm.service.parallel', '并行会签') },
                            ]} onChange={(value) => updateStage(index, { mode: value })} />
                          </Form.Item>
                          <Form.Item label={t('itsm.service.approvers', '审批人')} required>
                            <Select
                              mode="multiple"
                              showSearch
                              filterOption={false}
                              loading={userLoading}
                              value={stage.approverIds}
                              options={userOptions}
                              onSearch={(value) => void searchUsers(value)}
                              onChange={(value) => updateStage(index, { approverIds: value })}
                            />
                          </Form.Item>
                          <Form.Item label={t('itsm.service.signing', '加签能力')}>
                            <Space wrap>
                              <Switch checked={stage.allowBeforeSign} checkedChildren={t('itsm.service.allowBefore', '允许前加签')} unCheckedChildren={t('itsm.service.allowBefore', '允许前加签')} onChange={(value) => updateStage(index, { allowBeforeSign: value })} />
                              <Switch checked={stage.allowAfterSign} checkedChildren={t('itsm.service.allowAfter', '允许后加签')} unCheckedChildren={t('itsm.service.allowAfter', '允许后加签')} onChange={(value) => updateStage(index, { allowAfterSign: value })} />
                            </Space>
                          </Form.Item>
                        </div>
                      </div>
                    ))}
                    <WorkbenchSection title={t('itsm.service.handlingNode', '工单处理节点')} icon={<FileTextOutlined />}>
                      <Form.Item label={t('itsm.service.handlers', '处理人')} required className="mb-0 max-w-2xl">
                          <Select showSearch filterOption={false} loading={userLoading} value={service.workflow_config.handlerIds[0]} options={userOptions} onSearch={(value) => void searchUsers(value)} onChange={(value) => mutate((current) => ({ ...current, workflow_config: { ...current.workflow_config, handlerIds: [value] } }))} />
                        </Form.Item>
                    </WorkbenchSection>
                  </div>
                ),
              },
            ]}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="rounded-lg border border-[var(--color-border-1)] bg-[var(--color-bg)] px-4 py-3 text-xs leading-5 text-[var(--color-text-3)]">
              {t('itsm.service.saveFooterHint', '服务设计保存为草稿后不会影响线上版本；只有发布成功，服务目录中的新工单才会使用新版本。')}
            </div>
            <WorkbenchSection title={t('itsm.service.publishOverview', '发布概览')} bodyClassName="p-0">
              <WorkbenchPropertyList items={[
                { key: 'fields', label: t('itsm.service.formFields', '表单字段'), value: Object.keys(service.form_schema.properties).length, mono: true },
                { key: 'stages', label: t('itsm.service.approvalStages', '审批节点'), value: service.workflow_config.stages.length, mono: true },
                { key: 'version', label: t('itsm.service.onlineVersion', '线上版本'), value: service.current_version > 0 ? `V${service.current_version}` : '—', mono: true },
              ]} />
            </WorkbenchSection>
          </div>
        </div>
      ) : null}
    </ITSMPageShell>
  );
}
