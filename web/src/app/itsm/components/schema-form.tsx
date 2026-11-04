'use client';

import { Checkbox, Form, Input, InputNumber, Radio, Select, Switch } from 'antd';

import type { JsonSchema } from '../lib/types';

export function missingRequiredFields(schema: JsonSchema, value: Record<string, unknown>): string[] {
  return schema.required.filter((key) => {
    const item = value[key];
    return item === undefined || item === null || item === '' || (Array.isArray(item) && item.length === 0);
  });
}

export function ITSMSchemaForm({
  schema,
  value,
  onChange,
  disabled = false,
}: {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  return (
    <Form layout="vertical">
      {Object.entries(schema.properties).map(([key, field]) => {
        const required = schema.required.includes(key);
        const choices = field.type === 'array' ? field.items?.enum : field.enum;
        const setValue = (next: unknown) => onChange({ ...value, [key]: next });
        const controlId = `itsm-form-${key}`;

        if (choices && field['x-widget'] === 'radio') {
          return (
            <Form.Item key={key} label={field.title} htmlFor={controlId} help={field.description} required={required}>
              <Radio.Group
                id={controlId}
                disabled={disabled}
                value={value[key]}
                options={choices.map((item) => ({ value: item, label: String(item) }))}
                onChange={(event) => setValue(event.target.value)}
              />
            </Form.Item>
          );
        }
        if (choices) {
          return (
            <Form.Item key={key} label={field.title} htmlFor={controlId} help={field.description} required={required}>
              <Select
                id={controlId}
                disabled={disabled}
                mode={field.type === 'array' ? 'multiple' : undefined}
                value={value[key] as string | string[] | undefined}
                options={choices.map((item) => ({ value: item, label: String(item) }))}
                onChange={setValue}
              />
            </Form.Item>
          );
        }
        if (field.type === 'boolean') {
          return (
            <Form.Item key={key} label={field.title} htmlFor={controlId} help={field.description} required={required}>
              {field['x-widget'] === 'switch' ? (
                <Switch id={controlId} disabled={disabled} checked={Boolean(value[key])} onChange={setValue} />
              ) : (
                <Checkbox
                  id={controlId}
                  disabled={disabled}
                  checked={Boolean(value[key])}
                  onChange={(event) => setValue(event.target.checked)}
                />
              )}
            </Form.Item>
          );
        }
        if (field.type === 'number' || field.type === 'integer') {
          return (
            <Form.Item key={key} label={field.title} htmlFor={controlId} help={field.description} required={required}>
              <InputNumber
                id={controlId}
                disabled={disabled}
                className="w-full"
                value={typeof value[key] === 'number' ? value[key] : undefined}
                min={field.minimum}
                max={field.maximum}
                onChange={setValue}
              />
            </Form.Item>
          );
        }
        if (field['x-widget'] === 'textarea') {
          return (
            <Form.Item key={key} label={field.title} htmlFor={controlId} help={field.description} required={required}>
              <Input.TextArea
                id={controlId}
                disabled={disabled}
                rows={4}
                maxLength={field.maxLength}
                showCount
                value={String(value[key] ?? '')}
                onChange={(event) => setValue(event.target.value)}
              />
            </Form.Item>
          );
        }
        return (
          <Form.Item key={key} label={field.title} htmlFor={controlId} help={field.description} required={required}>
            <Input
              id={controlId}
              disabled={disabled}
              maxLength={field.maxLength}
              value={String(value[key] ?? '')}
              onChange={(event) => setValue(event.target.value)}
            />
          </Form.Item>
        );
      })}
    </Form>
  );
}
