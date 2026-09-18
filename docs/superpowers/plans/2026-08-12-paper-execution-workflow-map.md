# Paper Execution Workflow Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a source-traceable ComfyUI-style interactive map focused on XuanJiQuant's `paper_guarded` simulated execution layer.

**Architecture:** Use a curated semantic graph rather than the entire AST. A standalone HTML fragment owns six filtered views over one verified node/edge vocabulary; runtime evidence is a separate timestamped layer and is never inferred from architecture.

**Tech Stack:** HTML fragment, CSS, vanilla JavaScript, SVG, Graphify evidence, Markdown, PowerShell.

---

## File structure

- Create `C:\Users\HYSHEN\.codex\visualizations\2026\08\10\019fe926-d942-7e30-ba3e-e50ddb1999ce\paper-execution-workflow-map.html`: interactive graph.
- Keep `docs/superpowers/specs/2026-08-12-paper-execution-workflow-map-design.md`: approved scope and evidence contract.
- Keep this plan: exact build and verification checklist.
- Do not modify application source, trading configuration, databases or the frozen backup.

### Task 1: Build the source inventory

- [ ] Extract the Agent-only execution chain from `quant/agent/runtime.py`, `quant/agent/paper_controller.py`, `scripts/paper_trader.py` and `quant/agent/policies.py`.
- [ ] Extract target-weight, risk, routing and reconciliation semantics from `scripts/paper/*.py`, `quant/risk/*.py` and `quant/data/audit.py`.
- [ ] Extract React → Node → Python → store mappings from `components/*.tsx`, `server/router.mjs` and `server/routes/*.mjs`.
- [ ] Record the current time-gate outcome without probing services outside the intraday window.

### Task 2: Implement the semantic graph

- [ ] Define one node collection with `id`, title, layer, source, responsibility, inputs, outputs, boundary, evidence and status.
- [ ] Define edges with `from`, `to`, `type`, label and evidence.
- [ ] Define view membership for `overview`, `gates`, `orders`, `mapping`, `audit` and `status`.
- [ ] Validate every edge endpoint against the node ID set before rendering.

### Task 3: Implement the interaction

- [ ] Render deterministic SVG paths and node groups with readable labels.
- [ ] Add view switching, search, fit, zoom, pan and node-detail selection.
- [ ] Keep the status legend and source/evidence label visible.
- [ ] Support narrow layouts by stacking details below the graph.

### Task 4: Verify and deliver

- [ ] Check that the fragment has no document wrapper, external requests, iframe or script dependency.
- [ ] Check HTML size is below 1 MB and all six view IDs exist.
- [ ] Parse embedded JavaScript and verify all edge endpoints and queried DOM IDs.
- [ ] Render locally and inspect desktop and narrow viewport behavior.
- [ ] Report that the workspace has no Git metadata, so no commit was created.
