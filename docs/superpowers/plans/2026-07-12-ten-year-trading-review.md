# Ten-Year Trading Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert eight brokerage transaction screenshots into an audited transaction ledger, enrich stock codes, quantify supported trading behavior, and generate an Excel workbook plus a Chinese review document.

**Architecture:** A coordinate-aware OCR stage produces immutable JSON evidence. A parser reconstructs visible transaction rows and preserves source coordinates. Separate enrichment, validation, analysis, and export stages prevent OCR corrections or external stock metadata from overwriting source evidence.

**Tech Stack:** Python 3.14, RapidOCR, Pillow, OpenCV, pandas, openpyxl, python-docx, JSON, pytest.

---

## File Structure

- Create: `C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\extract_ocr.py`
  - Slice long images, run RapidOCR, map tile coordinates back to source images, and save OCR evidence.
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\parse_ledger.py`
  - Group OCR boxes into brokerage transaction records and normalize dates, times, amounts, fees, balances, names, and transaction types.
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\security_codes.py`
  - Resolve stock names to codes with provenance and ambiguity handling.
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\analyze_export.py`
  - Validate records, calculate supported metrics, and generate Excel and Word outputs.
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\tests\test_parse_ledger.py`
  - Test row grouping, date inheritance, negative signs, decimals, and overlap deduplication.
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\tests\test_analysis.py`
  - Test transaction classification, totals, reconciliation, and unsupported-metric guards.
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易复盘成果\交易数据汇总.xlsx`
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易复盘成果\交易复盘.docx`
- Create: `C:\Users\HYSHEN\Desktop\Trading Data\交易复盘成果\校验摘要.json`

## Task 1: Prepare an Isolated Working Area

- [ ] **Step 1: Create working and output directories**

Run:

```powershell
New-Item -ItemType Directory -Force -Path `
  'C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\tests', `
  'C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\evidence', `
  'C:\Users\HYSHEN\Desktop\Trading Data\交易复盘成果'
```

Expected: directories exist and all eight source JPG files remain unchanged.

- [ ] **Step 2: Install the missing document dependency**

Run:

```powershell
python -m pip install python-docx pytest
```

Expected: `python -c "import docx, pytest"` exits successfully.

- [ ] **Step 3: Record source hashes**

Run:

```powershell
Get-FileHash -Algorithm SHA256 'C:\Users\HYSHEN\Desktop\Trading Data\*.jpg' |
  Export-Csv -NoTypeInformation -Encoding UTF8 `
  'C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\evidence\source_hashes.csv'
```

Expected: eight hash rows.

## Task 2: Build Coordinate-Aware OCR Evidence

- [ ] **Step 1: Write an OCR smoke test**

The test must assert that one selected crop returns the visible header labels and at least one valid date, time, amount, and transaction type.

- [ ] **Step 2: Run the smoke test before implementation**

Run:

```powershell
python -m pytest 'C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\tests' -q
```

Expected: failure because `extract_ocr.py` is not implemented.

- [ ] **Step 3: Implement source-coordinate OCR**

Requirements:

- Tile height approximately 1800-2200 pixels with 250-350 pixel overlap.
- Retain OCR text, confidence, tile box, source-image box, image name, tile index, and engine version.
- Never flatten results to text-only data.
- Write one JSON file per source image plus `ocr_manifest.json`.
- Normalize only whitespace at this stage; preserve signs, decimals, and original text.

- [ ] **Step 4: Execute OCR for all images**

Run:

```powershell
python 'C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\extract_ocr.py'
```

Expected: eight evidence JSON files and an OCR manifest.

- [ ] **Step 5: Verify OCR coverage**

Check:

- Every image has boxes near its top and bottom.
- Every image contains year-month headings.
- Adjacent tiles have overlapping evidence.
- No image has an unexplained large vertical gap.

## Task 3: Reconstruct Transaction Records

- [ ] **Step 1: Add parser tests**

Tests must cover:

- A stock buy record with a negative cash amount.
- A stock sell record with a positive cash amount.
- Bank-to-broker and broker-to-bank transfers.
- Dividends, interest, tax, subscription/refund, and other visible non-trade flows.
- Year-month heading inheritance.
- Midnight/date boundary behavior.
- OCR confusion among `0/O`, `1/I`, minus signs, commas, and decimal points.
- Overlap duplicate removal based on source coordinates and normalized content.
- Same stock on different dates remains as separate records.

- [ ] **Step 2: Implement deterministic row grouping**

Each parsed record must contain:

```text
record_id
source_image
source_sequence
source_bbox
year_month_heading
date
time
raw_name
normalized_name
transaction_type
cash_amount
fee
account_balance
ocr_confidence
parse_status
review_notes
```

The parser must use spatial columns and row baselines rather than assuming a fixed text-line sequence.

- [ ] **Step 3: Export parsed and unresolved records**

Write:

```text
trade_review_work/evidence/parsed_records.csv
trade_review_work/evidence/unresolved_records.csv
trade_review_work/evidence/parser_reconciliation.json
```

- [ ] **Step 4: Reconcile per image**

For every image, compare:

- Visible transaction blocks.
- Parsed records.
- Technical overlap duplicates removed.
- Unresolved blocks.

Require:

```text
visible blocks = parsed records + unresolved blocks
```

## Task 4: Resolve Stock Codes

- [ ] **Step 1: Extract unique security names**

Exclude bank transfers, interest, taxes, fees, cash events, and other non-security transaction types.

- [ ] **Step 2: Build a name-to-code evidence table**

Required columns:

```text
raw_name
standard_name
code
exchange
match_status
evidence_source_1
evidence_source_2
notes
```

- [ ] **Step 3: Apply strict matching**

Rules:

- Accept a code only when the historical/current name and market evidence agree.
- Preserve historical names and ST prefixes separately from the standard name.
- Do not force a match for ambiguous, delisted, renamed, fund, bond, or subscription entries.
- Put unresolved candidates in the final pending-confirmation sheet.

- [ ] **Step 4: Check code uniqueness**

Run validations:

- One normalized name must not map to multiple accepted codes without dated name-history evidence.
- One code may have multiple historical names only when the mapping is documented.
- Codes must follow the relevant exchange format.

## Task 5: Validate and Quantify Trading Behavior

- [ ] **Step 1: Add analysis tests**

Tests must prove:

- Cash inflows, cash outflows, buys, sells, fees, dividends, transfers, and subscriptions reconcile to detail rows.
- Same-day repeated trades are retained.
- Technical OCR duplicates are excluded once.
- Unsupported metrics are returned as unavailable instead of fabricated.

- [ ] **Step 2: Classify transaction records**

Classification groups:

```text
证券买入
证券卖出
申购/中签/退款
红利/股息/利息
银证转入
银证转出
税费/手续费
其他
待确认
```

- [ ] **Step 3: Calculate supported metrics**

Calculate:

- Total and annual transaction counts.
- Buy and sell cash flow and activity frequency.
- Total visible fees and fee-to-turnover ratio where the denominator is supported.
- Deposit and withdrawal totals.
- Security, industry, and market concentration.
- Repeat-trading frequency by security.
- Time-of-day, weekday, month, and year activity patterns.
- Large-transaction concentration.
- Buy/sell sequence behavior and approximate holding intervals only where pair evidence is sufficient.
- Stock-level net visible cash flow with an explicit warning that it is not realized profit unless a complete closed lifecycle is proven.

- [ ] **Step 4: Block unsupported metrics**

Do not report exact win rate, profit factor, annualized return, maximum drawdown, or realized P&L unless the screenshots provide enough position and account-equity evidence to calculate them.

## Task 6: Generate the Excel Workbook

- [ ] **Step 1: Create workbook sheets**

Required sheets:

```text
使用说明
原始识别记录
交易明细
年度汇总
股票汇总
业务分类
市场行业分类
交易模式
待确认记录
校验报告
```

- [ ] **Step 2: Apply workbook usability formatting**

Requirements:

- Freeze headers and enable filters.
- Use numeric/date formats instead of text for parsed values.
- Color only status and exception cells.
- Add source-image and source-sequence columns to every detailed exception.
- Keep formulas or reproducible calculated values traceable to detail rows.

- [ ] **Step 3: Re-open and validate workbook**

Run:

```powershell
python -c "from openpyxl import load_workbook; p=r'C:\Users\HYSHEN\Desktop\Trading Data\交易复盘成果\交易数据汇总.xlsx'; w=load_workbook(p, data_only=False); print(w.sheetnames)"
```

Expected: all required sheets are listed and the workbook opens without repair warnings.

## Task 7: Generate the Chinese Trading Review

- [ ] **Step 1: Generate `交易复盘.docx`**

Required sections:

1. 数据范围与质量说明
2. 十年资金与交易活动总览
3. 年度和阶段变化
4. 买卖频率、金额和时间偏好
5. 标的、市场和行业集中度
6. 重复交易与追涨杀跌等可观察行为
7. 典型交易流水案例
8. 可计算与不可计算指标
9. 风险点和执行纪律建议

- [ ] **Step 2: Label evidence strength**

Every major conclusion must be tagged in prose as one of:

```text
事实统计
基于完整序列的推断
证据不足，不能下结论
```

- [ ] **Step 3: Re-open the document**

Run:

```powershell
python -c "from docx import Document; p=r'C:\Users\HYSHEN\Desktop\Trading Data\交易复盘成果\交易复盘.docx'; d=Document(p); print(len(d.paragraphs), len(d.tables))"
```

Expected: nonzero paragraph and table counts.

## Task 8: Final Audit

- [ ] **Step 1: Run all tests**

Run:

```powershell
python -m pytest 'C:\Users\HYSHEN\Desktop\Trading Data\trade_review_work\tests' -q
```

Expected: all tests pass.

- [ ] **Step 2: Perform arithmetic reconciliation**

Verify:

- Workbook detail count equals parser accepted count.
- Pending count equals unresolved and ambiguous records.
- Every summary count and amount recomputes from detail rows.
- No duplicate `record_id` exists.
- No source-image sequence is silently missing.

- [ ] **Step 3: Perform visual sampling**

Review at least the top, middle, and bottom of each image, plus:

- Largest positive and negative amounts.
- Every low-confidence record included in analysis.
- Every unresolved stock code.
- At least 10 random records per image, or all records if fewer.

- [ ] **Step 4: Write `校验摘要.json`**

Include source hashes, image count, visible row count, accepted count, pending count, technical duplicates removed, code-match counts, sample size, test result, and known limitations.

- [ ] **Step 5: Confirm source preservation**

Recompute source hashes and compare them with `source_hashes.csv`.

Expected: all eight image hashes are unchanged.
