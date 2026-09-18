# 十年成交记录复盘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将5张成交记录长截图重建为经过去重、代码补全、FIFO配对和交叉校验的十年成交数据库及复盘报告。

**Architecture:** 在独立工作目录中复用上一批OCR和证券主数据能力，但新建成交记录专用解析器、FIFO引擎和导出器。所有正式记录保留源图坐标，汇总结果由明细表和FIFO配对表计算生成。

**Tech Stack:** Python 3、RapidOCR、Pillow、pandas、openpyxl、python-docx、matplotlib、pytest。

---

### Task 1: 数据清点与证据固化

**Files:**
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\evidence\source_hashes.csv`
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\inventory.json`

- [ ] 计算5张图片的尺寸、SHA-256和与其他源图的重复关系。
- [ ] 固化输入文件清单，确认 `219` 与旧 `214` 的哈希关系。
- [ ] 记录输出目录和处理时间。

### Task 2: 成交记录OCR

**Files:**
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\extract_execution_ocr.py`
- Test: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\tests\test_extract_execution_ocr.py`

- [ ] 编写切片范围和坐标还原测试。
- [ ] 运行测试并确认失败。
- [ ] 实现长图分块OCR及原图坐标保存。
- [ ] 对5张图片生成OCR JSON和清单。
- [ ] 运行测试并确认通过。

### Task 3: 成交行重建与去重

**Files:**
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\parse_executions.py`
- Test: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\tests\test_parse_executions.py`

- [ ] 编写年月标题、日期时间、价格、数量、金额和操作类型解析测试。
- [ ] 编写真实分批成交保留及技术重复删除测试。
- [ ] 实现按时间锚点和列坐标重建成交行。
- [ ] 生成成交明细、重复记录、未解析记录和逐图对账。
- [ ] 验证可见时间锚点与解析结果一致。

### Task 4: 证券代码补全

**Files:**
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\security_codes.py`
- Test: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\tests\test_security_codes.py`

- [ ] 复用当前证券、TDX、行业和历史名称主数据。
- [ ] 编写当前名称、历史简称、N前缀和歧义名称测试。
- [ ] 生成证券代码映射表。
- [ ] 对所有未匹配和多匹配名称逐项复核。

### Task 5: FIFO配对

**Files:**
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\fifo_matching.py`
- Test: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\tests\test_fifo_matching.py`

- [ ] 编写完整卖出、部分卖出、跨批次卖出、库存不足和公司行为测试。
- [ ] 实现按证券代码和时间排序的FIFO库存引擎。
- [ ] 输出配对明细、未配对库存和异常记录。
- [ ] 计算配对覆盖率、估算毛盈亏、胜率、盈亏比和利润因子。

### Task 6: 汇总、图表和复盘文档

**Files:**
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\analyze_export.py`
- Test: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\tests\test_analysis.py`

- [ ] 编写年度、证券、时段、持仓周期和FIFO指标测试。
- [ ] 生成 Excel 多工作表。
- [ ] 生成年度、时段、高频证券、持仓周期和FIFO盈亏图表。
- [ ] 生成《交易记录复盘》Word文档，区分事实、FIFO估算和限制。

### Task 7: 视觉抽查与最终校验

**Files:**
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\trade_execution_work\verify_outputs.py`
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易记录\交易记录复盘成果\校验摘要.json`

- [ ] 每张图片抽查至少10条，覆盖顶部、中部、底部和随机位置。
- [ ] 专项复核低置信度、异常数量、未配对卖出和代码歧义。
- [ ] 校验记录ID、汇总求和、FIFO数量守恒和输出文件结构。
- [ ] 运行全部pytest与最终校验器，保存最终结果。

