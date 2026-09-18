# 全系统中文展示与驾驶舱可读性设计

日期：2026-08-01  
状态：已批准执行  
范围：`C:\Users\HYSHEN\XuanJiQuant`

## 1. 目标

本次改造解决三个用户可见问题：

1. 驾驶舱“最新目标组合”必须显示股票名称和代码，不能只显示代码。
2. “AI 与系统诊断”首次进入驾驶舱时默认展开，同时保留用户手动折叠能力。
3. 整个系统的界面标签、状态、操作反馈和系统生成提醒尽量使用中文。

改造只作用于展示与只读聚合层，不改变交易判断、数据源选择、数据库字段、缓存键、API 请求枚举或审计事实。

## 2. 不在范围内

以下内容保留原值，不做机械翻译：

- 股票代码、订单号、运行 ID、PID、文件路径和 URL。
- 模型及数据源品牌，例如 GLM、Qlib、TdxQuant、Jin10 MCP。
- 标准金融和研究缩写，例如 AI、API、CSV、K 线、IC、IR、VaR、ROE、ROA。
- API 字段、数据库字段、缓存键和内部协议枚举。
- 外部数据源原文、模型原始输出、历史日志、历史告警正文和审计记录。

历史事实不回写、不批量篡改。对于必须保留的英文技术值，界面优先显示中文解释；原值只在确有诊断价值时通过辅助说明或详情查看。

## 3. 现状与根因

### 3.1 目标组合缺少名称

`ai:portfolio:latest.target_weights` 当前只保存 `code`、权重、置信度和原因。驾驶舱虽然支持读取 `name` 或 `stock_name`，但 Workbench 返回的目标行没有这些字段，因此页面退化为只显示代码。

实时行情链路已经能够根据六位代码返回可靠的中文证券名称。名称补充应复用这条链路，不应修改历史组合计划或把名称写回审计数据。

### 3.2 诊断默认折叠

`components/DashboardPanel.tsx` 使用原生 `<details>` 渲染“AI 与系统诊断”，当前没有 `open` 属性，所以浏览器默认折叠。该结构本身适合保留，只需改变初始状态。

### 3.3 英文从两类位置泄漏到界面

- 静态文案直接写在组件中，例如 `K-line Trend`、`Train / Valid / Test`、本地身份页英文口号。
- API 返回的内部枚举被直接渲染，例如 `research_idle`、`paper_guarded`、`unknown`、`ok`、`no_new_position`、`true/false`。

已有 `lib/workbench-state.mjs::statusLabel` 提供部分集中映射，但覆盖范围不足，部分页面仍绕过映射直接显示原值。

## 4. 方案选择

采用“集中中文展示层 + 定向页面清理”。

不采用逐页重复硬编码，因为同一枚举会在多个页面产生不一致翻译；不采用后端全面中文化，因为内部协议和审计需要稳定、可机读的英文枚举。

## 5. 目标组合名称数据流

保持现有主链：

```text
DashboardPanel
  -> POST /api/workbench { action: status }
  -> server/routes/workbench.mjs
       -> paper_runner：读取目标组合
       -> execution_runner：读取持仓与账户
       -> data_runner(data-realtime)：仅为目标代码读取实时行情名称
  -> composeWorkbenchStatus：按代码合并展示名称
  -> DashboardPanel：显示“名称 代码”
```

实现约束：

1. `workbench.mjs` 复用 `PersistentRunner('data_runner.py', 'data-realtime')` 的现有单例键，不创建另一套行情协议。
2. 名称请求只包含驾驶舱实际展示的目标代码，最多 10 只；不请求全市场，不改变行情缓存策略。
3. `composeWorkbenchStatus` 接收独立的名称映射并复制目标组合响应，不能原地修改缓存读取结果。
4. 名称优先级为：目标行已有有效名称、实时行情中文名称、匹配持仓已有名称、股票代码。
5. 名称查询超时或失败时，Workbench 仍成功返回；错误只进入 `services.errors` 的辅助诊断，目标行继续显示代码。
6. 不把补充名称写回 `ai:portfolio:latest`、数据库、历史报告或审计记录。

## 6. 诊断默认展开

保留 `<details className="diagnostics">`，增加 `open` 初始属性。

这意味着每次新挂载驾驶舱时默认展开；用户仍可在当前页面会话中手动折叠。不增加本地存储，不跨会话记忆折叠状态。

## 7. 中文展示层

### 7.1 集中映射

在 `lib/workbench-state.mjs` 扩展或新增纯展示函数，按语义分组维护：

- `statusLabel`：运行、健康、数据新鲜度、任务和告警状态。
- `modeLabel`：`research_idle`、`paper_guarded`、`target_portfolio` 等运行模式。
- `policyLabel`：`normal`、`reduce_only`、`no_new_position` 等交易策略。
- `priorityLabel`：`high`、`medium`、`low`。
- `booleanLabel`：布尔值显示为“是/否”或“已启用/已禁用”，由调用语境选择。
- `segmentLabel`：`train`、`valid`、`test` 显示为“训练集、验证集、测试集”。

所有函数必须是纯函数。内部值保持原样用于条件判断、请求和审计；只有最终渲染文本调用映射。

未知枚举不伪造含义：显示“未识别状态”或中文字段说明，并在 `title` 等辅助信息中保留原始值供诊断。

### 7.2 静态文案清理

逐项检查 `components/` 下所有用户可见组件，优先处理已确认的英文显示：

- 驾驶舱和 AI Agent 运行轨迹中的模式、所有者、数据库状态、悬挂调用、布尔值。
- 市场浏览中的 `TOP100 by amount`、`live/daily`、`polling`、`K-line Trend`。
- 因子页面中的 `Train / Valid / Test`、`Segment`、`Date Range`、`Positive`、`Periods`。
- 本地身份页的英文口号。
- 告警规则级别、Qlib 任务状态及其他直接渲染的已知英文枚举。

品牌与标准缩写按“不在范围内”规则保留。

### 7.3 提醒和错误

- 前端自行生成的成功、失败、空状态、加载状态和操作确认统一使用中文。
- 服务端已知错误增加中文上下文，例如“请求失败”“数据层异常”，但不吞掉可诊断的原始错误码。
- 外部来源或历史审计正文保持原文；界面可增加中文类型标签，但不翻译或改写事实内容。
- 不使用一个通用字符串替换器处理任意文本，避免误改股票名称、代码、模型输出或 URL。

## 8. 影响文件与边界

预计主要修改：

- `server/routes/workbench.mjs`：目标代码名称补充及失败降级。
- `lib/workbench-state.mjs`：集中中文展示映射。
- `components/DashboardPanel.tsx`：名称显示、诊断默认展开、枚举中文展示。
- `components/AgentRuntimeStatus.tsx`、`components/DbPanel.tsx`、`components/FactorPanel.tsx`、`components/LocalProfileScreen.tsx`、`components/AlertPanel.tsx`、`components/qlib/*`：定向清理用户可见英文。
- 相关 Node 契约测试与 README。

除非测试证明必要，不修改 Python 交易执行、风控规则、AI 决策协议、SQLite schema、缓存键或历史数据。

## 9. 性能与失败处理

- 名称补充复用已有常驻数据进程和行情短缓存；最多处理 10 个目标代码。
- 名称查询设置有界超时，不能延长 Workbench 的核心账户与风险状态失败边界。
- 名称服务失败属于展示降级，不得导致 `/api/workbench` 返回 500。
- 中文映射均为本地纯函数，不增加网络请求或持久化写入。

## 10. 测试策略

按测试驱动顺序实施：

1. Node 先写失败测试，证明 Workbench 能按代码补充目标名称、保持原目标对象不变，并在名称源失败时继续返回。
2. 前端契约先写失败断言，要求诊断使用 `<details open>`，目标证券显示名称与代码。
3. 共享展示函数先写失败测试，覆盖状态、模式、策略、优先级、分段和布尔值。
4. 中文界面契约维护明确的禁止残留清单，覆盖本次确认的英文静态文案和直接枚举渲染；不以“源码不能出现任何英文字母”作为错误标准。
5. 最小实现逐项转绿，再运行现有 Workbench、驾驶舱、布局、性能和安全契约。
6. 运行 TypeScript、Vite 生产构建、全量 Python、Web 25 项和 UI 23 项验证。
7. 对实际 `/api/workbench` 做只读请求，核对目标行名称、响应成功和数据源失败降级边界。

## 11. README 交接要求

README 增加“展示层中文化与目标组合名称”说明，明确：

- 内部协议继续使用稳定英文枚举，中文只在展示层生成。
- `statusLabel` 等共享映射是新增状态翻译的唯一优先入口。
- 目标名称来自 Workbench 对现有实时行情链路的只读补充，不写回组合计划。
- 外部原文、模型原始输出和历史审计事实不得机械翻译。
- 新页面不得直接渲染已知内部枚举，必须通过共享展示函数。

## 12. 验收标准

- 最新目标组合的每个有效目标显示中文股票名称和代码；名称源失败时仍显示代码。
- “AI 与系统诊断”首次进入默认展开，仍可手动折叠。
- 已识别的系统状态、模式、策略、优先级、布尔值和系统生成提醒以中文显示。
- 已确认的英文静态文案被中文替代；允许范围内的品牌、缩写和技术标识保留。
- API、数据库、缓存和审计中的内部值不被中文化。
- 名称补充不改变目标权重、排序、交易许可或其他组合字段。
- 新增与现有契约、TypeScript、Vite、Python、Web 和 UI 验证全部通过。
