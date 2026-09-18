# XuanJiQuant 模拟交易执行层全景图设计

## 1. 目标

建立一张聚焦 `paper_guarded` 模拟交易执行层的 ComfyUI 式交互图，用同一套节点和连线解释底层设施、Agent 决策、权限与风险门禁、订单生命周期、前后端映射、事实存储和状态诊断。

图用于架构理解、执行排障和状态分析，不是运行控制面；不触发模拟订单，不授予交易权限，不修改 verifier、风险配置、工具清单或 authority/session 数据。

## 2. 输出

1. Codex 会话内可交互 HTML 图，保存在本次任务的可视化目录。
2. 本设计说明以及相应实施计划，长期保存在项目 `docs/superpowers` 下。
3. 图中的每个关键节点带源码入口、责任、输入输出、失败关闭条件和证据类型。

## 3. 视图与节点粒度

采用一张总控画布和六个专题视图：

1. `全景闭环`：行情、因子、Agent、验证、权限、交易、审计和页面反馈。
2. `执行门禁`：`paper_guarded`、execution role、当前 run/decision 绑定、verifier、工具授权、authority lease、一次性 session、私有 capability、幂等与单任务锁。
3. `订单生命周期`：目标权重、先卖后买、A 股整手、事前风险、订单路由、部分成交、余量取消、终态与对账。
4. `前后端映射`：React 页面、Node router/route、Python runner/domain 与事实存储；页面不拥有自动执行权。
5. `存储与审计`：KV 投影、Agent run/tool/publication、authority/session/order claim、orders/trades/risk/audit/position facts 和 completion envelope。
6. `状态分析`：设计能力、当前运行证据、历史证据和待核验项分离。

节点粒度为模块、关键类/函数、API 和事实表，不直接铺开全部 AST 符号。

## 4. 连线语义

- 数据流：行情、上下文、目标权重和页面读取。
- 决策流：Agent 规划、决策、验证和发布。
- 控制流：模式、角色、工具授权、authority、session、私有 capability、互斥和幂等。
- 交易流：订单意图、风险决策、路由、成交、取消和持仓更新。
- 审计流：run/decision/tool/paper/order/trade/risk 的持久关联与回放。

只有当前源码、既有 Graphify 图或明确文档支持的关系才画成确定连线。

## 5. 当前状态证据边界

本轮为 2026-08-12 盘前，按项目执行层时间门禁，不检查端口、API、日志或交易服务。因此：

- 当前运行状态统一标记为 `盘前未采样`，不得推断为健康或故障。
- 代码存在的能力标记为 `源码验证`。
- 旧快照只标记为 `历史证据` 并保留时间，不升级为当前事实。
- 任何缺少当前 Agent Run、verified decision、authority/session 或硬风控许可的执行路径均显示为失败关闭。

## 6. 交互

- 切换六个视图。
- 选择节点查看职责、输入输出、边界、风险和源码位置。
- 支持关键字搜索、自动适配、缩放和平移。
- 状态和证据必须同时用文字与形状表达，不能只依赖颜色。
- 默认首屏展示完整权威链，并明确 `ExecutionPanel` 是读/控入口但不是订单执行 owner。

## 7. 完成判定

1. 六个视图均可切换，节点与边不出现悬空引用。
2. 核心权威链完整：`scheduler → AgentRuntime → verifier → publication → authority/session → private paper trader → pretrade risk → order router → durable facts`。
3. 目标组合优先、基础策略回退、单任务锁、幂等、最大每日次数、快速行情无下单权和 paper-only 边界均可见。
4. 当前状态未采样与源码能力严格分离。
5. 图在常见宽度下可读，键盘可操作，脚本无未定义引用。
6. 不修改业务代码、交易配置、数据库或冻结备份。
