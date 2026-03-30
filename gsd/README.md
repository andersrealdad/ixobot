# IxoGSD — Build Order Workflow

IxoGSD is a structured workflow for managing work through a promotion chain.
Every piece of work starts as a drafted build order and earns its way through stations.

## Promotion Chain

```
📝 drafted → 🔍 under-review → 🏢 cross-check → ✅ approved → 📋 queued → 🔨 building → 📦 deployed → done/
```

No skipping stations. Each promotion has a gate.

## Usage

```bash
# From the ixobot repo root:
cd gsd

# Show all build orders
bash manage.sh status

# Kanban board view
bash manage.sh board

# Create a new build order
cp templates/TEMPLATE.md buildorders/001-my-feature.md
# Edit the frontmatter: set id, title, assigned, etc.

# Promote through stations
bash manage.sh review 001        # drafted → under-review
bash manage.sh crosscheck 001    # under-review → cross-check
bash manage.sh approve 001 Name  # cross-check → approved
bash manage.sh queue 001         # approved → queued
bash manage.sh start 001         # queued → building
bash manage.sh done 001          # building → done/

# Block/unblock
bash manage.sh block 001 "reason"
bash manage.sh unblock 001
```

## Build Order Template

Build orders use YAML frontmatter. See `templates/TEMPLATE.md` for the full template.

Key fields:
- `id` — unique identifier (e.g., "001")
- `title` — what this build order delivers
- `status` — current station (managed by manage.sh, don't edit manually)
- `assigned` — who is working on it
- `tags` — categorization
