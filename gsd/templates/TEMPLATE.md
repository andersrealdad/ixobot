---
id: "000"
title: ""
status: 📝 drafted
room: ""
workspace: ""
connects-to: []
assigned: ""
lanes: ""
context-sources: []
reviewed-by: []
approved-by: ""
discussion-id: ""
nlm-notebook: ""
tags:
  - automation

# Promotion Chain Tracking
promoted_by: ""
promoted_date: ""
tested: ""          # 🟢 pass | 🔴 fail | 🟡 partial
test_log: ""        # path to test output, e.g. workshop/043/test_smoke.py
test_remarks: ""    # brief note, set flagged: true if urgent
flagged: false
reviewed_sign: ""   # jan | astrid | table
review_date: ""
deployed_by: ""
deployed_date: ""
# Auto-Review Gate (BO #047)
review_level: ""        # auto | rubber-stamp | human | "" (auto-classify by Octopus)
auto_review_reason: "" # filled by Octopus when auto-classifying
# Memo Protocol (BO #053)
memo_chain_id: ""      # set by manage.sh on first station transition, e.g. memo:directive:dbo-053:{hash16}
---

<!-- PROMOTION CHAIN ──────────────────────────────────────────
Every build order starts at 📝 drafted and earns its way up.
No skipping stations. Each station has a gate that must pass.

  📝 drafted        — raw idea, just written down
  🔍 under-review   — Kitchen Table discussion open, agents reviewing
  🏢 cross-check    — affected departments have weighed in, innvendinger mapped
  ✅ approved        — human sign-off (Anders/Eirik/Jens)
  📋 queued          — ready to build, all dependencies resolved
  🔨 building        — actively being worked on
  📦 deployed        — live and monitored
  🚫 blocked         — stopped, needs resolution before re-entering chain

GATE RULES:
  drafted → under-review:   Discussion must exist in Kitchen Table
  under-review → cross-check: MIN 2 unique agents have commented
  cross-check → approved:    All innvendinger resolved or explicitly accepted
  approved → queued:         Human has signed off + all connects-to orders are ≥ queued
  queued → building:         manage.sh start <id> (or agent picks up)
  building → deployed:       Acceptance criteria met + manage.sh done <id>

ASTRID'S ROLE:
  When a build order is created, Astrid posts it to the Kitchen Table.
  She monitors the promotion chain and presents to Anders:
    "Approve this?" → [YES] [EXPLAIN]
  If [EXPLAIN] → NotebookLM generates: audio overview / debate / brief
  Anders decides based on the NLM content, not a text wall.
────────────────────────────────────────────────────────────── -->

# Build Order: [title]

## Execution Lanes

<!-- LANE NOTATION ─────────────────────────────────────────────────
Each row = one execution level. Tasks on the same row run IN PARALLEL.
Rows execute top-to-bottom (sequential between levels).

Format: | Level | Tasks | Department | Mode |
Colors map to departments:
  cyan    = WhisperCRM  (HR & Kundeservice)
  purple  = BrandFungi  (Branding & Content)
  blue    = TheAgency   (DevOps & Infra)
  orange  = TheVantage  (Market Analysis)
  pink    = Ixobot      (Agent Orchestration)
  red     = IxoSynth    (Prediction Pipeline)
  green   = Meme-it     (E-commerce)

COMPACT NOTATION:
  1-1-1         = 3 tasks at same level (parallel)
  1-2-3         = 3 tasks sequential (each depends on previous)
  1-1-1-2-2-4-4 = level1(3 parallel) → level2(2 parallel) → level3(2 parallel)
  Two lines     = two independent streams that merge

EXAMPLES:
  Graphic design → web dev:
    | 1 | design-brief    | `purple:BrandFungi`             | sequential |
    | 2 | mockup, review  | `purple:BrandFungi` + `cyan:WhisperCRM` | parallel |
    | 3 | implement       | `blue:TheAgency`                | sequential |
    | 4 | deploy, announce| `blue:TheAgency` + `cyan:WhisperCRM`    | parallel |
  Compact: 1-1-1-2-2-4-4 (pretty in cyan→purple→pink)
────────────────────────────────────────────────────────────────── -->

| Level | Tasks | Department | Mode |
|-------|-------|------------|------|
| 1 | ... | `color:Dept` | parallel/sequential |

**Compact notation:** `...`

## What to build
<!-- one paragraph, plain language -->

## Why
<!-- what problem does this solve? link to issue/debate/proposal -->

## Workspace dispatch
<!-- which garage room(s) should Claude Code spawn subagents in? -->
- **Primary:** `{{workspace}}/`
- **Supporting:** <!-- optional secondary rooms -->

## Acceptance criteria
<!-- when is this done? -->
- [ ] ...

## Prior art
<!-- past commits, issues, or solutions that are relevant -->

## Notes
<!-- constraints, context, links -->

## Builder Notes
<!-- When building starts, copy BUILDER_NOTES_TEMPLATE.md to workshop/<id>/builder_notes.md
     Builder fills it out at delivery. Michael reads. Jan signs off. -->

## References
<!-- Obsidian backlinks — do not remove -->
<!-- [[GSD-REFERENCE]] | [[DEVBOX-REFERENCE]] | [[gsd-config SKILL]] | [[tool_map]] | [[WORKSHOP]] -->
