# XuanJiQuant AI Agent 全面退役设计

## 1. 目标

从活动项目中彻底删除自治 AI Agent 控制系统及其 Web/API/进程入口，把系统收敛为五个确定性领域：数据、因子、策略、风控、模拟执行账本。

删除后不得再出现第二套隐式控制器。自动模拟下单保持关闭，直到另行设计并批准一个不依赖 Agent 的确定性执行流程。

## 2. 删除范围

### 2.1 Python Agent 控制面

- 删除 `quant/agent/` 下运行时、规划器、上下文、事件、恢复、权限、会话、工具注册、回放和私有 paper controller。
- 删除 `scripts/agent_runner.py`、`scripts/agent_control.py`、`scripts/ai_scheduler.py`、`scripts/ai_action_executor.py`、`scripts/ai_verifier.py`、`scripts/ai_memory.py`、`scripts/ai_self_improver.py`。
- 删除 `ai_tools.json`。
- 删除 Agent 专属模拟执行入口和执行会话签发链；保留订单、成交、持仓、风险和审计历史表，只读展示历史事实。

### 2.2 旧 AI 五层与自治业务模块

- 删除 `ai_data_agent`、`ai_execution_agent`、`ai_risk_agent`、`ai_portfolio_planner`、`ai_stock_screener`、`ai_objective`、`ai_status`、`ai_validation_universe`。
- 删除以 Agent/LLM 名义运行的 `ai_factor_agent` 与 `ai_strategy_agent`。
- 把仍有价值的确定性因子 DSL 计算迁入 `quant/factor`；把固定日程因子/策略工厂改为直接调用普通研究函数，不再经过 Agent、LLM 或自治配置。
- 删除以 `ai:*` 当前状态作为业务许可、选股新鲜度、风险许可或执行资格的读取路径。

### 2.3 Node 生命周期与 API

- 删除 `server/ai_scheduler_manager.mjs`。
- watchdog 不再读取、启动或恢复 Agent 调度器。
- `/api/paper` 删除全部 `agent_*`、`ai_scheduler_*`、`ai_autonomous_*`、`ai_*_run/status`、工具、记忆、验证器和自改进入口。
- `/api/workbench` 不再调用 Agent runner/control/scheduler，不再返回 `agent_decision` 或 Agent 恢复状态。
- 保留风险摘要、数据质量、账户权益、目标/历史组合审计、系统健康和只读模拟账本。

### 2.4 Web

- 删除 `AgentRuntimeStatus`、Agent 生命周期辅助模块和自治调度抽屉。
- 驾驶舱移除“Agent 当前策略”“AI 调度”“Agent 专属执行权”“等待 Agent/自治恢复”等内容。
- 模拟盘页移除 Agent 工作轨迹、调度状态、Agent 选股证据和 Agent 理由；保留账户、持仓、订单、成交、报告和历史审计。
- 页面统一显示“自动模拟交易已关闭；当前为研究与只读账本模式”，该文案是产品模式，不是假装存在一个停用 Agent。

## 3. 保留范围

- `quant/data`、数据源、数据质量、`DataSnapshot`、SQLite 市场数据和独立 Qlib 数据域。
- 普通因子引擎、IC/IR、因子列表、市场榜单和确定性研究调度。
- 普通策略引擎、扫描、组合、回测和候选/影子研究门禁。
- `quant/risk` 硬风控、风险指标、告警和审计。
- `quant/execution`、订单/成交/持仓/现金事实及其只读 API；禁止自动创建新订单。
- 不具备控制权的普通 LLM 文本解释功能可保留，但不得命名为 Agent、不得生成许可、不得触发数据/训练/订单写入。
- 历史数据库中的 `agent_*` 表、`ai:*` 键和历史订单身份不机械改写，仅停止活动代码消费。

## 4. 目标架构

```text
外部数据源
  -> 数据层唯一采集/质量/版本化发布
  -> 因子研究（确定性日程，只读 DataSnapshot）
  -> 策略研究（确定性日程，只读因子和数据版本）
  -> 风控（只读市场与组合事实，计算指标和硬限制）
  -> 模拟执行账本（当前只读，无自动下单生产者）
  -> Web/API 只读呈现与显式研究操作
```

不存在 Agent、自治恢复、模型规划、工具调用、Agent authority/session 或 Agent-only paper controller。

## 5. 因子和策略迁移

- `ai_factor_agent.compute_factor` 中安全、确定性的 DSL 解释器迁入 `quant/factor/dsl.py`。
- `quant/factor/ai_factor_loader.py` 改名/改造为普通 `dynamic_factor_loader.py`，字段和状态改用 `dynamic_factor`/`research_factor`，不读取 Agent 状态。
- 固定研究调度器直接调用确定性因子评估和策略扫描函数；模型只可生成离线提案文件，未经人工评审不得进入动态 DSL 清单。
- 现有候选/影子/生产门禁保持，删除 `AI approved` 之类容易混淆的状态名。

## 6. 模拟执行状态

- Agent 退役后没有自动订单生产者。
- `/api/execution` 的查询动作继续工作。
- 任何 place/fill/cancel 写动作若仍对 Web 暴露，必须在本次退役中关闭或从路由白名单移除。
- 历史订单、成交、拒单和审计记录保留，可回放但不能重新派发。

## 7. 测试策略

先增加退役架构契约并确认红灯：

- 活动源码不存在 `quant.agent` 导入；
- Agent/AI 五层生产文件不存在；
- Node 不存在 Agent manager、路由 action 或 watchdog 重启；
- React 不存在 Agent 组件、文案、API 调用；
- 启动器只启动 Web、API、数据/研究确定性任务；
- 因子/策略研究调度不导入 `ai_factor_agent/ai_strategy_agent`；
- execution Web/API 不提供自动或手工写单入口；
- 数据、因子、策略、风险、账本只读功能继续通过。

然后运行全量 Python、全部 Node 契约、TypeScript、Vite、Web/UI 和浏览器控制台验证。与退役功能绑定的旧测试删除；历史账本和迁移兼容测试只有在不导入活动 Agent 代码时才保留。

## 8. 文档与可视化

- README、交接文档和系统工作流图删除 Agent 作为当前架构的描述。
- 历史章节必须明确标为“已退役历史”，不能作为当前运行说明。
- 交互式全景图若仍展示 Agent，标记为历史快照并生成新的无 Agent 版本；旧图不自动同步。

## 9. 完成判定

1. 生产源码、Web、API、启动生命周期均无 Agent 功能或入口。
2. 因子/策略确定性能力不依赖被删除模块。
3. 自动模拟下单没有活动生产者，写单入口不对 Web 开放。
4. 历史 Agent 数据保留但活动代码不消费。
5. 数据、因子、策略、风控和只读执行账本回归通过。
6. 全量测试和构建通过；服务未启动时在线验证必须明确阻断。
7. 文档与源码一致，不把已退役功能写成当前能力。

## 10. 非目标

- 本次不设计新的自动交易控制器。
- 不接入实盘，不放宽硬风控。
- 不清空或改写历史数据库。
- 不删除 Qlib、因子、策略、风险或模拟账本本身。
