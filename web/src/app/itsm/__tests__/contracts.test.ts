import menu from '../constants/menu.json';
import { missingRequiredFields } from '../components/schema-form';
import { buildTicketProcessSteps } from '../components/ticket-process-steps';
import { newRequestKey } from '../lib/status';
import type { JsonSchema, WorkflowConfig } from '../lib/types';

const schema: JsonSchema = {
  type: 'object',
  properties: {
    summary: { type: 'string', title: '摘要', maxLength: 120 },
    enabled: { type: 'boolean', title: '启用' },
  },
  required: ['summary'],
  additionalProperties: false,
};

const workflow: WorkflowConfig = {
  schemaVersion: 1,
  stages: [
    {
      key: 'manager',
      name: '主管审批',
      mode: 'serial',
      approverIds: [101],
      allowBeforeSign: true,
      allowAfterSign: true,
    },
    {
      key: 'security',
      name: '安全会签',
      mode: 'parallel',
      approverIds: [201, 202],
      allowBeforeSign: false,
      allowAfterSign: false,
    },
  ],
  handlerIds: [301],
};

describe('ITSM frontend contracts', () => {
  it('exposes unified 3 top-level menus (catalog, ticket, service_management) in both locales', () => {
    const visibleZh = menu.zh.filter((item) => !item.isNotMenuItem).map((item) => item.name);
    const visibleEn = menu.en.filter((item) => !item.isNotMenuItem).map((item) => item.name);
    expect(visibleZh).toEqual(['catalog', 'ticket', 'service_management']);
    expect(visibleEn).toEqual(visibleZh);
  });

  it('detects missing required values without rejecting valid false values', () => {
    expect(missingRequiredFields(schema, { enabled: false })).toEqual(['summary']);
    expect(
      missingRequiredFields(schema, { summary: '数据库申请', enabled: false }),
    ).toEqual([]);
  });

  it('creates bounded idempotency keys for browser submissions', () => {
    const key = newRequestKey('submit');
    expect(key).toMatch(/^submit:\d+:[0-9a-f-]+$/);
    expect(key.length).toBeLessThanOrEqual(128);
  });

  it('builds stage-accurate process steps for ticket workbench', () => {
    const steps = buildTicketProcessSteps({
      status: 'APPROVING',
      workflow,
      activeStageKey: 'security',
      auditEvents: [],
      t: (_key, fallback = '') => fallback,
    });
    expect(steps.map((item) => [item.key, item.state])).toEqual([
      ['submit', 'done'],
      ['manager', 'done'],
      ['security', 'active'],
      ['handling', 'upcoming'],
      ['close', 'upcoming'],
    ]);
  });
});
