import menu from '../constants/menu.json';
import { missingRequiredFields } from '../components/schema-form';
import { newRequestKey } from '../lib/status';
import type { JsonSchema } from '../lib/types';

const schema: JsonSchema = {
  type: 'object',
  properties: {
    summary: { type: 'string', title: '摘要', maxLength: 120 },
    enabled: { type: 'boolean', title: '启用' },
  },
  required: ['summary'],
  additionalProperties: false,
};

describe('ITSM frontend contracts', () => {
  it('exposes catalog, ticket, todo, and service management routes in both locales', () => {
    expect(menu.zh.map((item) => item.name)).toEqual(['catalog', 'ticket', 'todo', 'service_management', 'itsm_entry']);
    expect(menu.en.map((item) => item.name)).toEqual(menu.zh.map((item) => item.name));
  });

  it('detects missing required values without rejecting valid false values', () => {
    expect(missingRequiredFields(schema, { enabled: false })).toEqual(['summary']);
    expect(missingRequiredFields(schema, { summary: '数据库申请', enabled: false })).toEqual([]);
  });

  it('creates bounded idempotency keys for browser submissions', () => {
    const key = newRequestKey('submit');
    expect(key).toMatch(/^submit:\d+:[0-9a-f-]+$/);
    expect(key.length).toBeLessThanOrEqual(128);
  });
});
