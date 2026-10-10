import * as assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(here, '..');
const repoRoot = resolve(webRoot, '..');
const readWeb = (path: string) => readFileSync(resolve(webRoot, path), 'utf8');
const readRepo = (path: string) => readFileSync(resolve(repoRoot, path), 'utf8');

const pageHeader = readWeb('src/components/page-header/index.tsx');
assert.match(pageHeader, /title:\s*React\.ReactNode/, 'PageHeader should accept a semantic title');
assert.match(pageHeader, /description\?:\s*React\.ReactNode/, 'PageHeader should support guidance copy');
assert.match(pageHeader, /actions\?:\s*React\.ReactNode/, 'PageHeader should keep page actions in one stable region');
assert.match(pageHeader, /meta\?:\s*React\.ReactNode/, 'PageHeader should support compact operational metadata');
assert.match(pageHeader, /<header/, 'PageHeader should render a semantic header element');

const dataViewState = readWeb('src/components/data-view-state/index.tsx');
for (const state of ['initial', 'loading', 'empty', 'error', 'ready']) {
  assert.ok(dataViewState.includes(`'${state}'`), `DataViewState should cover the ${state} state`);
}
assert.match(dataViewState, /<Skeleton/, 'loading should preserve page structure with Skeleton');
assert.match(dataViewState, /<Empty/, 'initial and empty states should use the shared Empty vocabulary');
assert.match(dataViewState, /<Result/, 'error state should remain visually distinct and actionable');
assert.match(dataViewState, /onRetry/, 'error state should support a retry action');

const overview = readWeb('src/app/cmdb/(pages)/assetOverview/page.tsx');
assert.match(overview, /PageHeader/, 'CMDB asset overview should use the shared page hierarchy');
assert.match(overview, /DataViewState/, 'CMDB asset overview should use the shared five-state boundary');
assert.match(overview, /setLoadError\(true\)/, 'request failures should produce an actionable error state');
assert.doesNotMatch(overview, /<Spin/, 'the pilot page should not collapse loading, empty and error into a spinner');
assert.match(overview, /<button[\s\S]*className=\{assetsOverviewStyle\.listItem\}/, 'asset entries should be keyboard-native buttons');

for (const locale of ['zh', 'en']) {
  const messages = JSON.parse(readWeb(`src/app/cmdb/locales/${locale}.json`));
  for (const key of ['title', 'description', 'searchPlaceholder', 'emptyTitle', 'emptyDescription', 'errorTitle', 'errorDescription']) {
    assert.equal(typeof messages.AssetOverview?.[key], 'string', `${locale} should define AssetOverview.${key}`);
  }
}

const design = readWeb('DESIGN.md');
assert.match(design, /## 7\. Page Patterns/, 'the design source of truth should define reusable page patterns');
assert.match(design, /DataViewState/, 'the design source of truth should define the five-state contract');

const audit = readRepo('docs/design-docs/cmdb-ui-ue-audit.md');
assert.match(audit, /71\s*\/\s*100/, 'the CMDB audit should retain the reviewed baseline score');
assert.match(audit, /OpsPilot.*100/, 'the score should stay explicitly relative to the OpsPilot baseline');

console.log('CMDB UI consistency contract passed');
