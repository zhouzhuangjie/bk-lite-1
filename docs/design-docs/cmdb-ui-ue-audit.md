# CMDB UI/UE 一致性审查

- 审查日期：2026-10-10
- 跟踪 Issue：[#6349](https://github.com/TencentBlueKing/bk-lite/issues/6349)
- 相对基准：OpsPilot = 100 分（用户指定的跨 App 风格样板）
- 审查范围：`web/src/app/cmdb`、`web/src/components`、`web/DESIGN.md`、`web/src/app/cmdb/DESIGN.md`
- 当前评分：**71 / 100**

## 产品判断

CMDB 已具备完整业务信息架构和多数基础控件，不需要推倒重做。主要差距不是颜色或圆角，而是同类页面的结构、五态反馈和交互语义没有稳定落到共享组件。先补平台能力，再按页面类型批量刷新，可以保持最小 diff，并让 alarm、monitor、log 等 App 继承同一标准。

## 评分明细

| 维度 | 权重 | 得分 | 仓库证据与判断 |
|---|---:|---:|---|
| 视觉 token 与主题 | 15 | 12 | `web/DESIGN.md` 与 `globals.css` 已定义完整基础色阶；CMDB 仍存在散落颜色和 arbitrary value。 |
| 全局壳与导航 | 10 | 9 | 根布局、`top-menu`、`sub-layout` 已共享；深层页面导航形态仍有局部差异。 |
| 信息架构与任务闭环 | 15 | 13 | 搜索、概览、资产、模型管理、自动发现、日志形成主闭环；页面入口和下一步提示不总是明确。 |
| 组件复用与页面结构 | 15 | 10 | 已复用 `CustomTable`、`OperateModal`、权限和省略组件；缺少统一页头与数据视图状态边界。 |
| 数据状态与反馈 | 15 | 8 | 多数页面有 Empty/Alert，但首次加载、空、失败经常合并，CMDB 代码中缺少 Skeleton 的系统使用。 |
| 操作一致性与安全 | 10 | 8 | 删除 danger、二次确认、权限包装已有专项修复；部分异步按钮仍缺 loading，错误信息仍偏泛化。 |
| 可访问性与 i18n | 10 | 7 | 已有双语与部分 aria 修复；仍有点击容器、焦点环、表格 `aria-sort` 等缺口。 |
| 响应式、暗色与验证 | 10 | 4 | token 支持主题，但全局仍 `min-width: 1280px`；Storybook/视觉回归未形成稳定门禁。 |
| **合计** | **100** | **71** | 适合增量统一，不适合一次性视觉重写。 |

## 现有组件覆盖

### 已覆盖，可直接按标准刷新

- 全局壳与一、二级导航：`top-menu`、`sub-layout`。
- 表格与字段设置：`CustomTable`。
- 创建/编辑弹窗：`OperateModal`。
- 详情抽屉：`content-drawer` + Ant Design Drawer。
- 权限、长文本、时间筛选：`PermissionWrapper`、`EllipsisWithTooltip`、`TimeSelector`。
- 基础表单、按钮、标签、提示：直接使用 Ant Design。

### 本次补齐

- `PageHeader`：统一标题、任务说明、metadata 和操作区。
- `DataViewState`：统一 initial / loading / empty / error / ready 五态。
- CMDB 资产概览样板：统一页头、搜索/刷新、统计信息、Skeleton/Empty/Error、键盘可达资产入口。

### 尚未覆盖，需后续 Issue 分阶段补齐

| 优先级 | 缺口 | 建议 |
|---|---|---|
| P0 | `OperateModal` 标题/副标题 DOM 未分层 | 修共享组件并补 a11y 测试。 |
| P0 | `CustomTable` 数字列未全局启用 tabular nums | 在共享样式中统一，移除业务页逐列补丁。 |
| P0 | 可点击卡片/目录项键盘语义不统一 | 优先改为 `button`/`a`，必要时提供共享可交互容器。 |
| P1 | 语义状态展示分散 | 当三个以上 App 出现相同状态词汇后提炼 `StatusBadge`，避免过早抽象领域状态。 |
| P1 | 筛选工具栏布局不一致 | 先沉淀组合规范；只有重复稳定后再封装 `FilterToolbar`。 |
| P1 | Storybook 与视觉回归门禁不可稳定运行 | 修复依赖和 auth/theme mock，固化 1440×900 截图基线。 |
| P2 | 全局 1280px 最小宽度与“移动优先”文档冲突 | 明确桌面控制台边界；若要窄屏再单独立项。 |

## 是否能按标准刷一轮

可以，但应按以下顺序，而不是逐页手工改颜色：

1. 平台层：完成 P0 共享组件修复和状态契约。
2. 样板层：资产概览、资产列表、模型管理各选择一个典型页面验收。
3. 扩散层：按“列表 / 详情 / 工作台”三类模板批量迁移 CMDB 其余页面。
4. 门禁层：lint、type-check、状态契约测试、双语和固定视口视觉回归。
5. 跨 App：alarm、monitor、log、ops-analysis 复用同一组件与验收清单，只保留领域特例。

## 验收标准

- 页面结构、操作层级和五态符合 `web/DESIGN.md`。
- 不新增硬编码品牌/语义色；新增文案中英文齐全。
- 可点击对象键盘可达，图标按钮有可访问名称，focus 可见。
- 异步操作有 loading 防重；错误提示包含下一步。
- `pnpm lint`、`pnpm type-check` 和相关行为契约测试通过。
