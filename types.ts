
// 智能体角色枚举
export enum AgentRole {
  MACRO = 'MACRO',
  INDUSTRY = 'INDUSTRY',
  TECHNICAL = 'TECHNICAL',
  FUNDS = 'FUNDS',
  FUNDAMENTAL = 'FUNDAMENTAL',
  SENTIMENT = 'SENTIMENT',
  SUPPLY_CHAIN = 'SUPPLY_CHAIN',
  ALTERNATIVE_DATA = 'ALTERNATIVE_DATA',
  MANAGER_FUNDAMENTAL = 'MANAGER_FUNDAMENTAL',
  MANAGER_MOMENTUM = 'MANAGER_MOMENTUM',
  RISK_SYSTEM = 'RISK_SYSTEM',
  RISK_PORTFOLIO = 'RISK_PORTFOLIO',
  GM = 'GM'
}

// 分析流程状态
export enum AnalysisStatus {
  IDLE = 'IDLE',          // 空闲
  FETCHING_DATA = 'FETCHING_DATA', // 正在获取API数据
  RUNNING = 'RUNNING',    // AI分析进行中
  COMPLETED = 'COMPLETED',// 完成
  ERROR = 'ERROR'         // 出错
}

// 模型提供商
export enum ModelProvider {
  GEMINI = 'GEMINI',
  DEEPSEEK = 'DEEPSEEK',
  QWEN = 'QWEN'
}

// 智能体配置接口
export interface AgentConfig {
  id: AgentRole;
  name: string;        // 英文名
  title: string;       // 中文展示名
  description: string; // 职责描述
  icon: string;        // 图标名
  color: string;       // 主题色
  temperature: number; // 随机性参数
  systemPrompt: string;// 系统提示词
  modelProvider: ModelProvider; // 使用的模型厂商
  modelName: string;   // 具体模型名称
  crossValidate?: boolean; // 是否启用多模型交叉验证
}

// 智能体输出结果
export interface AgentOutput {
  role: AgentRole;
  content: string;
  timestamp: number;
}

// API 密钥存储
export interface ApiKeys {
  gemini?: string;
  deepseek?: string;
  qwen?: string;
  juhe?: string;
}

// 市场情绪数据
export interface MarketSentiment {
  fearGreedIndex: number;    // 恐惧贪婪指数 0-100
  bullBearRatio: string;     // 多空比
  marginBalance: string;     // 融资余额
  netInflow: string;         // 主力净流入
  volumeRatio: number;       // 量比
}

// 板块资金流
export interface SectorFlow {
  name: string;
  inflow: number;   // 净流入（亿）
  changePct: number; // 涨跌幅
}

// 全局工作流状态
export interface WorkflowState {
  status: AnalysisStatus;
  currentStep: number; // 0: Idle, 1: Analysts, 2: Specialists, 3: Managers, 4: Risk, 5: GM
  stockSymbol: string;
  stockDataContext: string; // 存储格式化后的聚合数据
  sentiment?: MarketSentiment;
  sectorFlows?: SectorFlow[];

  outputs: Partial<Record<AgentRole, string>>; // 各智能体的输出内容
  error?: string;
  agentConfigs: Record<AgentRole, AgentConfig>; // 可动态修改的配置
  apiKeys: ApiKeys;
  trackingMode?: boolean; // 持续跟踪模式
  trackInterval?: number; // 跟踪间隔（分钟）
}

// 历史记录项
export interface HistoryItem {
  id: string;
  stockSymbol: string;
  status: AnalysisStatus;
  currentStep: number;
  timestamp: number;
  completedAt?: number;
  gmDecision?: string; // 总经理的决策（买入/观望/卖出）
  outputs: Partial<Record<AgentRole, string>>;
}