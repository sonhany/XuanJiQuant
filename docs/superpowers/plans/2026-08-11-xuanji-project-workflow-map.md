# XuanJiQuant Project Workflow Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a source-traceable ComfyUI-style interactive map and a permanent Chinese architecture analysis for the complete XuanJiQuant system.

**Architecture:** Use a curated semantic graph instead of rendering every AST symbol. One standalone HTML fragment owns the visual data model, rendering and interactions; one Markdown document owns the durable architecture narrative and source map. Runtime health is a timestamped read-only overlay and is never treated as design truth.

**Tech Stack:** HTML, CSS, vanilla JavaScript, SVG, Graphify graph evidence, Markdown, PowerShell, Playwright/browser verification.

---

## File structure

- Create `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`: durable Chinese architecture, responsibility, workflow, evidence and debt analysis.
- Modify `README.md`: add one entry pointing to the architecture map document.
- Create `C:\Users\HYSHEN\.codex\visualizations\2026\08\01\019fbb5b-d4d2-7610-b1ae-c566df1932a4\xuanji-project-workflow-map.html`: interactive ComfyUI-style visualization fragment.
- Do not modify application source, trading configuration, databases or frozen-backup files.

### Task 1: Build the verified architecture inventory

**Files:**
- Read: `App.tsx`
- Read: `components/*.tsx`
- Read: `server/index.mjs`
- Read: `server/router.mjs`
- Read: `server/routes/*.mjs`
- Read: `server/persistent_runner.mjs`
- Read: `scripts/*_runner.py`
- Read: `quant/**/*.py`
- Read: `README.md`
- Read: `docs/XUANJI_HANDOFF.md`
- Read: `graphify-out/graph.json`

- [ ] **Step 1: Extract frontend, API, runner and domain ownership**

Run:

```powershell
rg -n "fetch\(|/api/|action:" App.tsx components lib
rg -n "handle[A-Z]|createRouter|PersistentRunner|new PersistentRunner" server
rg -n "def action_|class |def run_|def handle_" scripts quant
```

Expected: named frontend panels, API routes, runner actions and domain classes with current source locations.

- [ ] **Step 2: Extract storage, schedulers and authority boundaries**

Run:

```powershell
rg -n "quant\.db|qlib_meta\.db|mlflow\.db|Redis|cache|scheduler|verifier|risk gateway|fencing|lease|authority|shadow" README.md docs server scripts quant
```

Expected: evidence for SQLite/Qlib stores, deterministic research schedule, Agent-only authority, verifier and risk gateway.

- [ ] **Step 3: Capture a read-only runtime snapshot**

Run PowerShell requests against `http://127.0.0.1:8888` and `http://127.0.0.1:8880`, enumerate only processes whose command line resolves under `C:\Users\HYSHEN\XuanJiQuant`, and call read-only status actions discovered from the current router.

Expected: timestamped Web/API reachability, response times, project process list and status payloads. Any unavailable field is recorded as `未知`, never inferred from cached logs.

### Task 2: Write the durable architecture analysis

**Files:**
- Create: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`
- Modify: `README.md`

- [ ] **Step 1: Create the document with the agreed sections**

The document must contain these exact top-level sections:

```markdown
# XuanJiQuant 全景架构与工作流
## 1. 阅读方法与证据等级
## 2. 系统总览
## 3. 技术底座与进程模型
## 4. 前端结构
## 5. Node API 与控制层
## 6. Python 量化内核
## 7. 数据与 Qlib 研究底座
## 8. 因子和策略研究流水线
## 9. Agent 自治决策链
## 10. 模拟交易执行链
## 11. 风险、告警与审计链
## 12. 页面到后端的职责映射
## 13. 当前运行快照
## 14. 架构冲突、债务与改造优先级
## 15. 交接与修改规则
```

- [ ] **Step 2: Add exact page-to-backend mappings**

For every major panel, record the React component, API route, Node handler, Python runner/domain module and fact store. Missing or indirect links must be labelled `待核实`.

- [ ] **Step 3: Add one README entry without rewriting existing content**

Insert a concise link near the architecture introduction:

```markdown
> 交互式全景图及模块、流程、职责和源码映射见 [XuanJiQuant 全景架构与工作流](docs/XUANJI_SYSTEM_WORKFLOW_MAP.md)。
```

- [ ] **Step 4: Scan the documentation for unsupported completion claims**

Run:

```powershell
rg -n "100%|完全实时|已全部完成|可实盘|生产就绪" docs/XUANJI_SYSTEM_WORKFLOW_MAP.md
```

Expected: no unsupported claim; any occurrence is explicitly qualified as a target or gap.

### Task 3: Build the interactive ComfyUI-style graph

**Files:**
- Create: `C:\Users\HYSHEN\.codex\visualizations\2026\08\01\019fbb5b-d4d2-7610-b1ae-c566df1932a4\xuanji-project-workflow-map.html`

- [ ] **Step 1: Define the semantic graph data model**

Use these structures inside the HTML fragment:

```javascript
const views = [{ id, label, description, nodes, edges }];
const node = {
  id, title, subtitle, layer, x, y, width, status,
  evidence, source, responsibilities, inputs, outputs, boundaries, risks
};
const edge = { from, to, type, label, evidence };
```

The view IDs are `overview`, `foundation`, `data`, `research`, `agent`, `execution`, `risk`, `mapping`, and `runtime`. `overview` is the default; the other eight are focused filters over the same verified vocabulary.

- [ ] **Step 2: Implement deterministic SVG rendering**

Render nodes as grouped cards with explicit coordinates and edges as SVG paths with arrow markers. Use one marker/color per edge type: `data`, `decision`, `control`, `trade`, `schedule`, `audit`.

- [ ] **Step 3: Implement interactions**

Required element IDs and behavior:

```text
#xq-view-tabs       switch active view
#xq-search          filter by title, responsibility and source
#xq-layer-filter    filter layer
#xq-edge-filter     filter edge type
#xq-zoom-in         increase scale
#xq-zoom-out        decrease scale
#xq-fit             fit active graph
#xq-reset           reset all filters and viewport
#xq-canvas          pan by pointer drag; select nodes
#xq-node-detail     show source, responsibility, I/O, boundary and risk
```

Keyboard focus, visible focus styles and button labels are required. Search and filters must preserve the current view.

- [ ] **Step 4: Add the runtime overlay**

Embed the read-only snapshot as data with `sampledAt`, `status`, `latencyMs`, `source` and `note`. Do not make network requests from the visualization; stale snapshots remain visibly timestamped.

- [ ] **Step 5: Keep the artifact standalone**

Run:

```powershell
rg -n "fetch\(|https?://|<iframe|<script src=" "C:\Users\HYSHEN\.codex\visualizations\2026\08\01\019fbb5b-d4d2-7610-b1ae-c566df1932a4\xuanji-project-workflow-map.html"
```

Expected: no external fetch, iframe or script dependency.

### Task 4: Verify content, interaction and delivery

**Files:**
- Verify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`
- Verify: `README.md`
- Verify: `C:\Users\HYSHEN\.codex\visualizations\2026\08\01\019fbb5b-d4d2-7610-b1ae-c566df1932a4\xuanji-project-workflow-map.html`

- [ ] **Step 1: Validate artifact shape and size**

Run:

```powershell
$p='C:\Users\HYSHEN\.codex\visualizations\2026\08\01\019fbb5b-d4d2-7610-b1ae-c566df1932a4\xuanji-project-workflow-map.html'
(Get-Item -LiteralPath $p).Length
rg -n "xq-view-tabs|xq-search|xq-layer-filter|xq-edge-filter|xq-node-detail|overview|runtime" $p
```

Expected: file is under 1 MB and all required controls/views exist.

- [ ] **Step 2: Open through a local HTTP server and run browser checks**

Start a temporary local server rooted at the visualization directory, open the page, switch every view, search for `AgentRuntime`, filter edge types, zoom, pan, select a node and reset.

Expected: every interaction changes visible state correctly; no browser console error; node detail remains readable at 1280×720 and 1920×1080.

- [ ] **Step 3: Reconcile graph and document coverage**

Check that the document and visualization both cover data, research, Agent, risk, execution, audit, frontend, backend and runtime status, and that source paths use the same names.

- [ ] **Step 4: Record repository limitation**

Run:

```powershell
Test-Path -LiteralPath .git
```

Expected: `False`; report that files were saved but no Git commit was possible. Do not fabricate a commit.

