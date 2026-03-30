#!/bin/bash
# manage.sh — Buildorder lifecycle manager (promotion chain)
# Usage:
#   manage.sh status              — Show all buildorders with status
#   manage.sh board               — Kanban-style board view
#   manage.sh trainline           — Trainline gradient view (all orders)
#   manage.sh review <id>         — Promote: drafted → under-review
#   manage.sh crosscheck <id>     — Promote: under-review → cross-check
#   manage.sh approve <id> <by>   — Promote: cross-check → approved (requires human name)
#   manage.sh queue <id>          — Promote: approved → queued
#   manage.sh start <id>          — Promote: queued → building
#   manage.sh done <id>           — Promote: building → done + move to done/
#   manage.sh block <id> <reason> — Mark as 🚫 blocked (any station)
#   manage.sh unblock <id>        — Return blocked order to previous station
#   manage.sh sync                — Sync registry.yaml with actual files
#   manage.sh next                — Show highest-priority approved/queued buildorder

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILDORDERS_DIR="$SCRIPT_DIR/buildorders"
DONE_DIR="$BUILDORDERS_DIR/done"
REGISTRY="${GSD_REGISTRY:-}"
SYNC_KANBAN="${GSD_SYNC_KANBAN:-}"

# Auto-sync Obsidian Kanban after any status change
sync_board() {
    [ -n "$SYNC_KANBAN" ] && [ -x "$SYNC_KANBAN" ] && "$SYNC_KANBAN" >/dev/null 2>&1 || true
}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Parse frontmatter field from a buildorder file
get_field() {
    local file="$1" field="$2"
    sed -n '/^---$/,/^---$/p' "$file" | grep "^${field}:" | head -1 | sed "s/^${field}:[[:space:]]*//" | sed 's/^"//' | sed 's/"$//'
}

# Update frontmatter field in a buildorder file
set_field() {
    local file="$1" field="$2" value="$3"
    if grep -q "^${field}:" "$file"; then
        sed -i "s|^${field}:.*|${field}: \"${value}\"|" "$file"
    else
        # Add field before the closing --- (last line of frontmatter)
        # Find the second --- (closing marker) and insert before it
        sed -i "0,/^---$/!{0,/^---$/s/^---$/${field}: \"${value}\"\n---/}" "$file"
    fi
}

cmd_status() {
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║  BUILDORDER STATUS — $(date '+%Y-%m-%d %H:%M')                        ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    local drafted=0 review=0 crosscheck=0 approved=0 queued=0 building=0 done=0 blocked=0

    # Active buildorders
    for f in "$BUILDORDERS_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        local status=$(get_field "$f" "status")
        local workspace=$(get_field "$f" "workspace")

        case "$status" in
            *drafted*)
                echo -e "  ${PURPLE}📝${NC} ${BOLD}#${id}${NC} ${title}"
                echo -e "     ${CYAN}${workspace}${NC}"
                drafted=$((drafted + 1))
                ;;
            *under-review*)
                echo -e "  ${YELLOW}🔍${NC} ${BOLD}#${id}${NC} ${title}"
                echo -e "     ${CYAN}${workspace}${NC}"
                review=$((review + 1))
                ;;
            *cross-check*)
                echo -e "  ${CYAN}🏢${NC} ${BOLD}#${id}${NC} ${title}"
                echo -e "     ${CYAN}${workspace}${NC}"
                crosscheck=$((crosscheck + 1))
                ;;
            *approved*)
                echo -e "  ${GREEN}✅${NC} ${BOLD}#${id}${NC} ${title}"
                echo -e "     ${CYAN}${workspace}${NC}"
                approved=$((approved + 1))
                ;;
            *queued*)
                echo -e "  ${YELLOW}📋${NC} ${BOLD}#${id}${NC} ${title}"
                echo -e "     ${CYAN}${workspace}${NC}"
                queued=$((queued + 1))
                ;;
            *building*)
                echo -e "  ${BLUE}🔨${NC} ${BOLD}#${id}${NC} ${title}"
                echo -e "     ${CYAN}${workspace}${NC}"
                building=$((building + 1))
                ;;
            *blocked*)
                echo -e "  ${RED}🚫${NC} ${BOLD}#${id}${NC} ${title}"
                echo -e "     ${CYAN}${workspace}${NC}"
                blocked=$((blocked + 1))
                ;;
            *done*)
                echo -e "  ${GREEN}✅${NC} ${BOLD}#${id}${NC} ${title}"
                done=$((done + 1))
                ;;
        esac
    done

    # Done buildorders
    for f in "$DONE_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        echo -e "  ${GREEN}📦${NC} ${BOLD}#${id}${NC} ${title}"
        done=$((done + 1))
    done

    echo ""
    echo -e "  ${BOLD}Summary:${NC} ${PURPLE}${drafted} drafted${NC} | ${YELLOW}${review} review${NC} | ${CYAN}${crosscheck} cross-check${NC} | ${GREEN}${approved} approved${NC} | ${YELLOW}${queued} queued${NC} | ${BLUE}${building} building${NC} | ${RED}${blocked} blocked${NC} | ${GREEN}${done} done${NC}"
    echo ""
}

cmd_board() {
    echo -e "${BOLD}┌─────────────┬──────────────┬──────────────┬──────────────┐${NC}"
    echo -e "${BOLD}│  📋 QUEUED   │  🔨 BUILDING  │  🚫 BLOCKED  │  ✅ DONE      │${NC}"
    echo -e "${BOLD}├─────────────┼──────────────┼──────────────┼──────────────┤${NC}"

    local col_queued="" col_building="" col_blocked="" col_done=""

    for f in "$BUILDORDERS_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        local status=$(get_field "$f" "status")
        local short="${title:0:12}"

        case "$status" in
            *queued*)   col_queued+="#${id} ${short}\n" ;;
            *building*) col_building+="#${id} ${short}\n" ;;
            *blocked*)  col_blocked+="#${id} ${short}\n" ;;
            *done*)     col_done+="#${id} ${short}\n" ;;
        esac
    done

    for f in "$DONE_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        local short="${title:0:12}"
        col_done+="#${id} ${short}\n"
    done

    # Print columns (simplified — just list under headers)
    echo -e "${BOLD}│${NC} ${YELLOW}$(echo -e "$col_queued" | head -1)${NC}"
    echo -e "${BOLD}└─────────────┴──────────────┴──────────────┴──────────────┘${NC}"
    echo ""
    echo -e "${YELLOW}QUEUED:${NC}"
    echo -e "$col_queued"
    echo -e "${BLUE}BUILDING:${NC}"
    echo -e "$col_building"
    echo -e "${RED}BLOCKED:${NC}"
    echo -e "$col_blocked"
    echo -e "${GREEN}DONE:${NC}"
    echo -e "$col_done"
}

# Check for duplicate BO IDs across active and done directories
check_id_unique() {
    local -A seen_ids
    local dupes=""
    for f in "$BUILDORDERS_DIR"/[0-9]*.md "$DONE_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        [ -z "$id" ] && continue
        if [ -n "${seen_ids[$id]:-}" ]; then
            dupes+="  ${RED}DUPLICATE #${id}${NC}: $(basename "${seen_ids[$id]}") AND $(basename "$f")\n"
        fi
        seen_ids[$id]="$f"
    done
    if [ -n "$dupes" ]; then
        echo -e "${RED}${BOLD}ID COLLISION DETECTED:${NC}"
        echo -e "$dupes"
        return 1
    fi
    return 0
}

# Find a buildorder file by ID
find_order() {
    local id="$1"
    local file=$(find "$BUILDORDERS_DIR" -maxdepth 1 -name "${id}-*.md" -o -name "0${id}-*.md" 2>/dev/null | head -1)
    if [ -z "$file" ]; then
        file=$(find "$BUILDORDERS_DIR" -maxdepth 1 -name "0*${id}-*.md" 2>/dev/null | head -1)
    fi
    echo "$file"
}

# Promote with gate check
promote() {
    local id="$1" from_status="$2" to_status="$3" to_emoji="$4"
    local file=$(find_order "$id")

    if [ -z "$file" ] || [ ! -f "$file" ]; then
        echo -e "${RED}ERROR: No buildorder found with id ${id}${NC}"
        exit 1
    fi

    # Pre-flight: check for ID collisions before any promotion
    if ! check_id_unique; then
        echo -e "${RED}Resolve ID collisions before promoting.${NC}"
        exit 1
    fi

    local current=$(get_field "$file" "status")
    if ! echo "$current" | grep -qi "$from_status"; then
        echo -e "${RED}GATE FAILED: #${id} is at '${current}', not '${from_status}'${NC}"
        echo -e "${RED}Orders must promote through the chain — no skipping stations.${NC}"
        exit 1
    fi

    set_field "$file" "status" "${to_emoji} ${to_status}"
    local title=$(get_field "$file" "title")
    echo -e "${GREEN}⬆${NC} Promoted: ${BOLD}#${id}${NC} ${title}"
    echo -e "  ${current} → ${to_emoji} ${to_status}"

    # Emit memo for station transition (best-effort, never blocks promotion)
    python3 "$BUILDORDERS_DIR/memo-emit.py" "$id" "$from_status" "$to_status" "$file" 2>&1 || true

    sync_board
}

cmd_review() {
    promote "$1" "drafted" "under-review" "🔍"
}

cmd_crosscheck() {
    promote "$1" "under-review" "cross-check" "🏢"
}

cmd_approve() {
    local id="$1"
    local by="${2:?Usage: manage.sh approve <id> <human-name>}"
    promote "$id" "cross-check" "approved" "✅"
    local file=$(find_order "$id")
    set_field "$file" "approved-by" "$by"
    echo -e "  Approved by: ${BOLD}${by}${NC}"
}

cmd_queue() {
    promote "$1" "approved" "queued" "📋"
}

cmd_start() {
    promote "$1" "queued" "building" "🔨"
    local file=$(find_order "$1")
    set_field "$file" "started" "$(date -Iseconds)"
}

cmd_done() {
    local id="$1"
    local file=$(find_order "$id")

    if [ -z "$file" ] || [ ! -f "$file" ]; then
        echo -e "${RED}ERROR: No buildorder found with id ${id}${NC}"
        exit 1
    fi

    local current=$(get_field "$file" "status")
    if ! echo "$current" | grep -qi "building"; then
        echo -e "${RED}GATE FAILED: #${id} is at '${current}', not 'building'${NC}"
        echo -e "${RED}Only building orders can be marked done.${NC}"
        exit 1
    fi

    set_field "$file" "status" "📦 deployed"
    set_field "$file" "completed" "$(date -Iseconds)"

    # Emit memo before move (file path changes after mv)
    python3 "$BUILDORDERS_DIR/memo-emit.py" "$id" "building" "deployed" "$file" 2>&1 || true

    mv "$file" "$DONE_DIR/"
    local title=$(get_field "$DONE_DIR/$(basename "$file")" "title")
    echo -e "${GREEN}📦${NC} Deployed: ${BOLD}#${id}${NC} ${title} → moved to done/"
    sync_board
}

cmd_block() {
    local id="$1"
    local reason="${2:-no reason given}"
    local file=$(find_order "$id")

    if [ -z "$file" ] || [ ! -f "$file" ]; then
        echo -e "${RED}ERROR: No buildorder found with id ${id}${NC}"
        exit 1
    fi

    # Save previous status so we can unblock later
    local prev_status=$(get_field "$file" "status")
    set_field "$file" "status" "🚫 blocked"
    set_field "$file" "blocker" "$reason"
    set_field "$file" "blocked-from" "$prev_status"
    local title=$(get_field "$file" "title")
    echo -e "${RED}🚫${NC} Blocked: ${BOLD}#${id}${NC} ${title} — ${reason}"

    # Emit red-severity memo for blocks
    python3 "$BUILDORDERS_DIR/memo-emit.py" "$id" "$prev_status" "blocked" "$file" 2>&1 || true

    sync_board
}

cmd_unblock() {
    local id="$1"
    local file=$(find_order "$id")

    if [ -z "$file" ] || [ ! -f "$file" ]; then
        echo -e "${RED}ERROR: No buildorder found with id ${id}${NC}"
        exit 1
    fi

    local prev=$(get_field "$file" "blocked-from")
    if [ -z "$prev" ]; then
        echo -e "${RED}ERROR: #${id} has no blocked-from record — set status manually${NC}"
        exit 1
    fi

    set_field "$file" "status" "$prev"
    local title=$(get_field "$file" "title")
    echo -e "${GREEN}⬆${NC} Unblocked: ${BOLD}#${id}${NC} ${title} → ${prev}"
    sync_board
}

cmd_trainline() {
    echo -e "${BOLD}BUILDBOARD — Trainline Dashboard${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    # Station map
    declare -A STATION_NUM
    STATION_NUM[drafted]=0
    STATION_NUM[under-review]=1
    STATION_NUM[cross-check]=2
    STATION_NUM[approved]=3
    STATION_NUM[queued]=4
    STATION_NUM[building]=5
    STATION_NUM[deployed]=6
    STATION_NUM[done]=6
    STATION_NUM[blocked]=-1

    for f in "$BUILDORDERS_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        local status=$(get_field "$f" "status")
        local workspace=$(get_field "$f" "workspace")
        local assigned=$(get_field "$f" "assigned")

        # Determine station
        local station=0
        for key in drafted under-review cross-check approved queued building deployed done blocked; do
            if echo "$status" | grep -qi "$key"; then
                station=${STATION_NUM[$key]}
                break
            fi
        done

        # Build trainline bar (30 chars wide, 7 stations = ~4.3 chars each)
        local bar=""
        local labels="  📝───🔍───🏢───✅───📋───🔨───📦"

        if [ "$station" -eq -1 ]; then
            bar="  ▓▓▓▓XX▓▓▓▓XX▓▓▓▓XX░░░░░░░░░░"
        else
            local filled=$((station * 5))
            local current=4
            local empty=$((30 - filled - current))
            [ $empty -lt 0 ] && empty=0

            bar="  "
            for ((i=0; i<filled; i++)); do bar+="█"; done
            for ((i=0; i<current; i++)); do bar+="▓"; done
            for ((i=0; i<empty; i++)); do bar+="░"; done
        fi

        local station_label=""
        case "$station" in
            0) station_label="📝 drafted" ;;
            1) station_label="🔍 under-review" ;;
            2) station_label="🏢 cross-check" ;;
            3) station_label="✅ approved" ;;
            4) station_label="📋 queued" ;;
            5) station_label="🔨 building" ;;
            6) station_label="📦 deployed" ;;
            -1) station_label="🚫 blocked" ;;
        esac

        echo -e "${BOLD}#${id}${NC} ${title}"
        echo -e "$labels"
        echo -e "$bar  Station ${station}/6: ${station_label}"
        echo -e "  └── ${CYAN}${workspace}${NC} │ assigned: ${assigned}"
        echo ""
    done
}

cmd_next() {
    echo -e "${BOLD}Next actions available:${NC}"
    echo ""

    # Show orders that can be promoted, grouped by current station
    local found=0

    echo -e "  ${PURPLE}📝 DRAFTED — ready for review:${NC}"
    for f in "$BUILDORDERS_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local status=$(get_field "$f" "status")
        echo "$status" | grep -qi "drafted" || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        echo -e "    #${id} ${title}  →  ${CYAN}./manage.sh review ${id}${NC}"
        found=$((found + 1))
    done
    [ $found -eq 0 ] && echo -e "    (none)"

    found=0
    echo ""
    echo -e "  ${GREEN}✅ APPROVED — ready to queue:${NC}"
    for f in "$BUILDORDERS_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local status=$(get_field "$f" "status")
        echo "$status" | grep -qi "approved" || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        echo -e "    #${id} ${title}  →  ${CYAN}./manage.sh queue ${id}${NC}"
        found=$((found + 1))
    done
    [ $found -eq 0 ] && echo -e "    (none)"

    found=0
    echo ""
    echo -e "  ${YELLOW}📋 QUEUED — ready to start:${NC}"
    for f in "$BUILDORDERS_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local status=$(get_field "$f" "status")
        echo "$status" | grep -qi "queued" || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        echo -e "    #${id} ${title}  →  ${CYAN}./manage.sh start ${id}${NC}"
        found=$((found + 1))
    done
    [ $found -eq 0 ] && echo -e "    (none)"
    echo ""
}

cmd_sync() {
    echo -e "${BOLD}Syncing registry.yaml with buildorder files...${NC}"

    # Build the build-orders section from actual files
    local yaml_section="build-orders:"

    for f in "$BUILDORDERS_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        local status=$(get_field "$f" "status")
        local priority=$(get_field "$f" "priority")

        yaml_section+="\n  - id: \"${id}\""
        yaml_section+="\n    title: \"${title}\""
        yaml_section+="\n    status: \"${status}\""
        yaml_section+="\n    priority: ${priority}"
    done

    for f in "$DONE_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        local completed=$(get_field "$f" "completed")

        yaml_section+="\n  - id: \"${id}\""
        yaml_section+="\n    title: \"${title}\""
        yaml_section+="\n    status: \"✅ done\""
        yaml_section+="\n    completed: \"${completed}\""
    done

    # Replace the build-orders section in registry.yaml
    if [ -z "$REGISTRY" ]; then
        echo -e "${YELLOW}GSD_REGISTRY not set — skipping registry sync${NC}"
    elif [ -f "$REGISTRY" ]; then
        # Remove old build-orders section and append new one
        sed -i '/^# Active Build Orders/,$d' "$REGISTRY"
        sed -i '/^build-orders:/,$d' "$REGISTRY"
        echo -e "\n# Active Build Orders (gsd/buildorders/) — auto-synced $(date '+%Y-%m-%d %H:%M')" >> "$REGISTRY"
        echo -e "$yaml_section" >> "$REGISTRY"
        echo -e "${GREEN}✅ Registry synced${NC}"
    else
        echo -e "${RED}Registry not found at ${REGISTRY}${NC}"
    fi
}

cmd_export() {
    local id="$1"
    local file=$(find_order "$id")

    if [ -z "$file" ] || [ ! -f "$file" ]; then
        echo -e "${RED}ERROR: No buildorder found with id ${id}${NC}"
        exit 1
    fi

    local title=$(get_field "$file" "title")
    local status=$(get_field "$file" "status")
    local workspace=$(get_field "$file" "workspace")

    echo -e "${BOLD}Exporting #${id} to Astrid...${NC}"
    echo -e "  Title: ${title}"
    echo -e "  Status: ${status}"

    # --- Create Matrix room for this buildorder ---
    local room_name="BO-${id} ${title}"
    local topic="Buildorder #${id}: ${title} | Workspace: ${workspace}"
    local astrid_user="@astrid:matrix.ixobot.com"
    local homeserver="http://127.0.0.1:8448"

    # Fetch Anders' Matrix access token from vault (creates room as @anders)
    local token
    token=$(~/bin/bw-fetch-secret matrix-credentials anders_token 2>/dev/null || echo "")
    if [ -z "$token" ]; then
        echo -e "${RED}ERROR: Could not fetch matrix-credentials:anders_token from vault${NC}"
        echo -e "${YELLOW}Skipping Matrix room creation. Export the buildorder manually.${NC}"
        return 1
    fi

    # Create the room via Matrix API
    local create_resp
    create_resp=$(curl -s -X POST "${homeserver}/_matrix/client/v3/createRoom" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"${room_name}\",
            \"topic\": \"${topic}\",
            \"invite\": [\"${astrid_user}\"],
            \"preset\": \"private_chat\",
            \"initial_state\": []
        }" 2>/dev/null)

    local room_id
    room_id=$(echo "$create_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('room_id',''))" 2>/dev/null)

    if [ -z "$room_id" ]; then
        local error_msg
        error_msg=$(echo "$create_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','unknown'))" 2>/dev/null)
        echo -e "${RED}ERROR: Matrix room creation failed: ${error_msg}${NC}"
        return 1
    fi

    echo -e "${GREEN}✅ Matrix room created:${NC} ${room_name}"
    echo -e "  Room ID: ${CYAN}${room_id}${NC}"
    echo -e "  Invited: ${astrid_user}"

    # Store room ID in the buildorder frontmatter
    set_field "$file" "matrix-room" "$room_id"

    # Send the buildorder content into the room as initial context
    local bo_content
    bo_content=$(cat "$file" | python3 -c "
import sys, json
content = sys.stdin.read()
# Escape for JSON
print(json.dumps(content))
" 2>/dev/null)

    curl -s -X PUT "${homeserver}/_matrix/client/v3/rooms/${room_id}/send/m.room.message/$(date +%s%N)" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "{
            \"msgtype\": \"m.text\",
            \"body\": ${bo_content}
        }" >/dev/null 2>&1

    echo -e "${GREEN}📨 Buildorder content posted to room${NC}"
    echo ""
    echo -e "  ${BOLD}Astrid can now discuss this buildorder in the Matrix room.${NC}"
}

WORKSHOP_DIR="$HOME/shared-data/DEV/garage/workshop"
OCTOPUS_LOGS="$HOME/DEV/garage/infra/octopus/logs"

cmd_logs() {
    local filter_id="${1:-}"

    # Collect log files (newest first)
    local -a log_files=()
    for f in $(ls -t "$OCTOPUS_LOGS"/*.json 2>/dev/null); do
        if [ -n "$filter_id" ]; then
            local log_order=$(python3 -c "import json; print(json.load(open('$f')).get('order_id',''))" 2>/dev/null)
            [ "$log_order" != "$filter_id" ] && continue
        fi
        log_files+=("$f")
    done

    if [ ${#log_files[@]} -eq 0 ]; then
        echo -e "${DIM:-}No logs found${filter_id:+ for #$filter_id}.${NC}"
        return
    fi

    local selected=0
    local page_size=20

    while true; do
        clear

        # Header
        local total=${#log_files[@]}
        if [ -n "$filter_id" ]; then
            echo -e "${BOLD}╔══ LOGS — #${filter_id} ══════════════════════════════════════════════╗${NC}"
        else
            echo -e "${BOLD}╔══ OCTOPUS LOGS ════════════════════════════════════════════╗${NC}"
        fi
        echo ""

        # List view (left column) — show all logs with selector
        for i in "${!log_files[@]}"; do
            local f="${log_files[$i]}"
            local oid=$(python3 -c "import json; print(json.load(open('$f')).get('order_id','?'))" 2>/dev/null || echo "?")
            local status=$(python3 -c "import json; r=json.load(open('$f')).get('result',{}); print(r.get('status','?') if isinstance(r,dict) else '?')" 2>/dev/null || echo "?")
            local ts=$(basename "$f" .json | cut -d- -f1-2)
            local cost=$(python3 -c "import json; r=json.load(open('$f')).get('result',{}); c=r.get('cost_usd',0) if isinstance(r,dict) else 0; print(f'\${c:.2f}' if c else '')" 2>/dev/null || echo "")

            local icon=""
            case "$status" in
                completed) icon="${GREEN}✅${NC}" ;;
                error)     icon="${RED}❌${NC}" ;;
                flagged)   icon="${YELLOW}🚩${NC}" ;;
                *)         icon="${CYAN}?${NC}" ;;
            esac

            local key=$(( (i % 26) + 1 ))
            local label=""
            if [ $key -le 9 ]; then
                label="$key"
            else
                # a=10, b=11, ...
                label=$(printf "\\x$(printf '%02x' $((key + 86)))")
            fi

            if [ "$i" -eq "$selected" ]; then
                echo -e "  ${BOLD}${CYAN}▸ [${label}]${NC} ${icon} ${BOLD}#${oid}${NC}  ${ts}  ${cost}"
            else
                echo -e "    ${DIM:-}[${label}]${NC} ${icon} #${oid}  ${ts}  ${cost}"
            fi

            # Only show first page_size entries in list
            if [ $i -ge $((page_size - 1)) ] && [ $i -lt $((total - 1)) ]; then
                echo -e "    ${DIM:-}... $(( total - page_size )) more${NC}"
                break
            fi
        done

        echo ""
        echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
        echo ""

        # Detail for selected log
        local sel_file="${log_files[$selected]}"
        python3 -c "
import json, textwrap
with open('$sel_file') as fh:
    log = json.load(fh)

oid = log.get('order_id', '?')
title = log.get('title', '?')
ts = log.get('timestamp', '?')
r = log.get('result', {}) if isinstance(log.get('result'), dict) else {}
status = r.get('status', '?')
cost = r.get('cost_usd', 0)
model = r.get('model', '?')
mode = r.get('mode', '?')
commits = r.get('commits', 0)
git_stat = r.get('git_stat', '')
gsd = r.get('gsd_state', '')
result_text = r.get('result', '')
stderr = log.get('stderr', '')
devbox_exit = log.get('devbox_exit_code', '?')
claude_exit = r.get('claude_exit_code', '?')

# Status color (ANSI)
sc = {'completed': '\033[0;32m', 'error': '\033[0;31m', 'flagged': '\033[1;33m'}.get(status, '\033[0;36m')
NC = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'

print(f'{BOLD}#{oid} — {title}{NC}')
print(f'  Timestamp:  {ts}')
print(f'  Status:     {sc}{status}{NC}')
print(f'  Model:      {model} ({mode})')
print(f'  Cost:       \${cost:.2f}')
print(f'  Commits:    {commits}   {git_stat}')
print(f'  GSD:        {gsd or \"n/a\"}')
print(f'  Exit codes: devbox={devbox_exit} claude={claude_exit}')
print()

if result_text:
    print(f'{BOLD}── Result ──{NC}')
    # Wrap long lines
    for line in str(result_text)[:800].split(chr(10)):
        print(f'  {line}')
    if len(str(result_text)) > 800:
        print(f'  {DIM}... truncated ({len(str(result_text))} chars total){NC}')
    print()

# Show last 10 lines of stderr (most useful)
if stderr:
    lines = stderr.strip().split(chr(10))
    tail = lines[-10:]
    print(f'{BOLD}── Stderr (last {len(tail)} lines) ──{NC}')
    for line in tail:
        print(f'  {DIM}{line}{NC}')
" 2>/dev/null

        echo ""
        echo -e "${DIM:-}[1-9/a-z] select  [n/p] next/prev  [f] full stderr  [q] quit${NC}"

        read -rsn1 -t 30 key || true

        case "${key:-}" in
            [1-9])
                local idx=$((key - 1))
                [ "$idx" -lt "${#log_files[@]}" ] && selected=$idx
                ;;
            [a-z])
                # a=10, b=11, ...
                local idx=$(( $(printf '%d' "'$key") - 87 ))
                [ "$idx" -ge 0 ] && [ "$idx" -lt "${#log_files[@]}" ] && selected=$idx
                ;;
            n|N)
                selected=$(( (selected + 1) % ${#log_files[@]} ))
                ;;
            p|P)
                selected=$(( (selected - 1 + ${#log_files[@]}) % ${#log_files[@]} ))
                ;;
            f|F)
                # Full stderr in pager
                local sel_file="${log_files[$selected]}"
                python3 -c "
import json
with open('$sel_file') as fh:
    log = json.load(fh)
print(log.get('stderr', '(no stderr)'))
" 2>/dev/null | less
                ;;
            q|Q) return ;;
            "") ;; # timeout — refresh
        esac
    done
}

cmd_live() {
    local now=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${BOLD}╔══ OCTOPUS LIVE ══════════════════════════════════ ${now} ══╗${NC}"
    echo ""

    # Collect by status
    local -a queued_items=() building_items=() blocked_items=() drafted_items=() review_items=()

    for f in "$BUILDORDERS_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local title=$(get_field "$f" "title")
        local status=$(get_field "$f" "status")
        local short="${title:0:45}"

        case "$status" in
            *drafted*)      drafted_items+=("$id|$short|$f") ;;
            *under-review*) review_items+=("$id|$short|$f") ;;
            *queued*)       queued_items+=("$id|$short|$f") ;;
            *building*)     building_items+=("$id|$short|$f") ;;
            *blocked*)      blocked_items+=("$id|$short|$f") ;;
        esac
    done

    # Count done
    local done_count=0
    if [ -d "$DONE_DIR" ]; then
        done_count=$(find "$DONE_DIR" -maxdepth 1 -name "[0-9]*.md" 2>/dev/null | wc -l)
    fi

    # ── Summary line ──
    local total=$(( ${#drafted_items[@]} + ${#review_items[@]} + ${#queued_items[@]} + ${#building_items[@]} + ${#blocked_items[@]} + done_count ))
    echo -e "  ${PURPLE}📝 ${#drafted_items[@]}${NC} │ ${YELLOW}🔍 ${#review_items[@]}${NC} │ ${YELLOW}📋 ${#queued_items[@]}${NC} │ ${BLUE}🔨 ${#building_items[@]}${NC} │ ${RED}🚫 ${#blocked_items[@]}${NC} │ ${GREEN}📦 ${done_count}${NC}  (${total} total)"
    echo ""

    # ── Building (enriched with sandbox state) ──
    if [ ${#building_items[@]} -gt 0 ]; then
        echo -e "  ${BLUE}${BOLD}🔨 BUILDING${NC}"
        for item in "${building_items[@]}"; do
            IFS='|' read -r id short file <<< "$item"
            local sandbox="$WORKSHOP_DIR/$id"
            local elapsed=""
            local gsd_state=""
            local agent_status=""

            # Elapsed time
            local started=$(get_field "$file" "started")
            if [ -n "$started" ]; then
                local start_epoch=$(date -d "$started" +%s 2>/dev/null || echo "")
                if [ -n "$start_epoch" ]; then
                    local now_epoch=$(date +%s)
                    local diff=$((now_epoch - start_epoch))
                    local mins=$((diff / 60))
                    local secs=$((diff % 60))
                    if [ $mins -gt 60 ]; then
                        local hrs=$((mins / 60))
                        mins=$((mins % 60))
                        elapsed="${hrs}h${mins}m"
                    else
                        elapsed="${mins}m${secs}s"
                    fi
                fi
            fi

            # Sandbox state
            if [ -d "$sandbox" ]; then
                if [ -f "$sandbox/result.json" ]; then
                    agent_status=$(python3 -c "import json; r=json.load(open('$sandbox/result.json')); print(r.get('status','?'))" 2>/dev/null || echo "?")
                    case "$agent_status" in
                        completed) agent_status="${GREEN}done${NC}" ;;
                        error)
                            local err=$(python3 -c "import json; r=json.load(open('$sandbox/result.json')); print(r.get('result','?')[:40])" 2>/dev/null || echo "?")
                            agent_status="${RED}ERR: ${err}${NC}" ;;
                        flagged)   agent_status="${YELLOW}flagged${NC}" ;;
                        *)         agent_status="${CYAN}${agent_status}${NC}" ;;
                    esac
                elif [ -f "$sandbox/DONE.md" ]; then
                    agent_status="${GREEN}DONE.md present${NC}"
                elif [ -f "$sandbox/FLAG.md" ]; then
                    agent_status="${YELLOW}FLAG.md present${NC}"
                else
                    agent_status="${CYAN}running...${NC}"
                fi

                # GSD state
                if [ -d "$sandbox/.planning" ]; then
                    local phase_count=$(find "$sandbox/.planning" -maxdepth 1 -name "phase-*" -type d 2>/dev/null | wc -l)
                    local latest_phase=$(find "$sandbox/.planning" -maxdepth 1 -name "phase-*" -type d 2>/dev/null | sort -V | tail -1)
                    if [ -n "$latest_phase" ]; then
                        local phase_name=$(basename "$latest_phase")
                        # Check for PLAN.md or VERIFICATION.md
                        if [ -f "$latest_phase/VERIFICATION.md" ]; then
                            gsd_state="GSD: ${phase_name} ${GREEN}verified${NC}"
                        elif [ -f "$latest_phase/PLAN.md" ]; then
                            gsd_state="GSD: ${phase_name} (${phase_count} phases)"
                        else
                            gsd_state="GSD: ${phase_name} planning..."
                        fi
                    else
                        gsd_state="GSD: initializing"
                    fi
                elif [ -f "$sandbox/instruks.md" ]; then
                    gsd_state="pre-GSD"
                fi
            else
                agent_status="${PURPLE}no sandbox${NC}"
            fi

            # Print enriched line
            local time_str=""
            [ -n "$elapsed" ] && time_str="⏳ ${elapsed}  "
            local gsd_str=""
            [ -n "$gsd_state" ] && gsd_str="  ${CYAN}${gsd_state}${NC}"
            echo -e "    ${BOLD}#${id}${NC} ${short}"
            echo -e "         ${time_str}${agent_status}${gsd_str}"
        done
        echo ""
    fi

    # ── Blocked (with reason) ──
    if [ ${#blocked_items[@]} -gt 0 ]; then
        echo -e "  ${RED}${BOLD}🚫 BLOCKED${NC}"
        for item in "${blocked_items[@]}"; do
            IFS='|' read -r id short file <<< "$item"
            local blocker=$(get_field "$file" "blocker")
            [ -z "$blocker" ] && blocker="no reason recorded"
            echo -e "    ${BOLD}#${id}${NC} ${short}"
            echo -e "         ${RED}${blocker:0:55}${NC}"
        done
        echo ""
    fi

    # ── Queued ──
    if [ ${#queued_items[@]} -gt 0 ]; then
        echo -e "  ${YELLOW}${BOLD}📋 QUEUED${NC}"
        for item in "${queued_items[@]}"; do
            IFS='|' read -r id short file <<< "$item"
            echo -e "    ${BOLD}#${id}${NC} ${short}"
        done
        echo ""
    fi

    # ── Drafted / Review (compact) ──
    if [ ${#drafted_items[@]} -gt 0 ] || [ ${#review_items[@]} -gt 0 ]; then
        echo -e "  ${PURPLE}${BOLD}📝 PIPELINE${NC}"
        for item in "${drafted_items[@]}"; do
            IFS='|' read -r id short file <<< "$item"
            echo -e "    ${BOLD}#${id}${NC} ${short}  ${PURPLE}drafted${NC}"
        done
        for item in "${review_items[@]}"; do
            IFS='|' read -r id short file <<< "$item"
            echo -e "    ${BOLD}#${id}${NC} ${short}  ${YELLOW}review${NC}"
        done
        echo ""
    fi

    # ── Last 3 log entries ──
    echo -e "  ${BOLD}RECENT LOGS${NC}"
    local log_count=0
    for logfile in $(ls -t "$OCTOPUS_LOGS"/*.json 2>/dev/null | head -3); do
        local log_id=$(python3 -c "import json; print(json.load(open('$logfile')).get('order_id','?'))" 2>/dev/null || echo "?")
        local log_status=$(python3 -c "import json; r=json.load(open('$logfile')).get('result',{}); print(r.get('status','?') if isinstance(r,dict) else '?')" 2>/dev/null || echo "?")
        local log_ts=$(basename "$logfile" .json | cut -d- -f1-2)
        case "$log_status" in
            completed) echo -e "    ${GREEN}✅${NC} #${log_id}  ${log_ts}" ;;
            error)     echo -e "    ${RED}❌${NC} #${log_id}  ${log_ts}" ;;
            flagged)   echo -e "    ${YELLOW}🚩${NC} #${log_id}  ${log_ts}" ;;
            *)         echo -e "    ${CYAN}?${NC}  #${log_id}  ${log_ts}" ;;
        esac
        log_count=$((log_count + 1))
    done
    [ $log_count -eq 0 ] && echo -e "    ${CYAN}(no logs)${NC}"

    echo ""
    echo -e "${BOLD}╚═══════════════════════════════════════════════════════════════╝${NC}"
}

cmd_check() {
    echo -e "${BOLD}Checking buildorder integrity...${NC}"
    local ok=true

    # Check for duplicate IDs
    if ! check_id_unique; then
        ok=false
    fi

    # Check for filename/frontmatter ID mismatch
    for f in "$BUILDORDERS_DIR"/[0-9]*.md "$DONE_DIR"/[0-9]*.md; do
        [ -f "$f" ] || continue
        local id=$(get_field "$f" "id")
        local basename_id=$(basename "$f" | grep -oP '^\d+')
        if [ -n "$id" ] && [ -n "$basename_id" ] && [ "$id" != "$basename_id" ]; then
            echo -e "  ${YELLOW}MISMATCH${NC}: $(basename "$f") has id: \"${id}\" in frontmatter"
            ok=false
        fi
    done

    if $ok; then
        echo -e "${GREEN}All checks passed.${NC}"
    fi
}

# Main dispatch
case "${1:-status}" in
    status)     cmd_status ;;
    board)      cmd_board ;;
    live)       cmd_live ;;
    trainline)  cmd_trainline ;;
    check)      cmd_check ;;
    review)     cmd_review "${2:?Usage: manage.sh review <id>}" ;;
    crosscheck) cmd_crosscheck "${2:?Usage: manage.sh crosscheck <id>}" ;;
    approve)    cmd_approve "${2:?Usage: manage.sh approve <id> <name>}" "${3:-}" ;;
    queue)      cmd_queue "${2:?Usage: manage.sh queue <id>}" ;;
    start)      cmd_start "${2:?Usage: manage.sh start <id>}" ;;
    done)       cmd_done "${2:?Usage: manage.sh done <id>}" ;;
    block)      cmd_block "${2:?Usage: manage.sh block <id> <reason>}" "${3:-}" ;;
    unblock)    cmd_unblock "${2:?Usage: manage.sh unblock <id>}" ;;
    next)       cmd_next ;;
    sync)       cmd_sync ;;
    export)     cmd_export "${2:?Usage: manage.sh export <id>}" ;;
    detail)     exec bash "$HOME/DEV/garage/infra/octopus/detail-viewer.sh" ;;
    logs)       cmd_logs "${2:-}" ;;
    *)
        echo "Usage: manage.sh {status|board|trainline|detail|logs|check|review|crosscheck|approve|queue|start|done|block|unblock|next|sync}"
        echo ""
        echo "  ${BOLD}Views:${NC}"
        echo "  status           Show all buildorders with status"
        echo "  board            Kanban-style board view"
        echo "  live             Live enriched view (sandbox progress + blockers)"
        echo "  detail           Interactive detail viewer (station-aware, press 1-9)"
        echo "  logs [id]        Interactive log viewer (all logs, or filter by BO id)"
        echo "  trainline        Trainline gradient view (dark→bright)"
        echo ""
        echo "  ${BOLD}Promotion chain:${NC} (must follow order — no skipping)"
        echo "  review <id>      📝 drafted → 🔍 under-review"
        echo "  crosscheck <id>  🔍 under-review → 🏢 cross-check"
        echo "  approve <id> <n> 🏢 cross-check → ✅ approved (requires human name)"
        echo "  queue <id>       ✅ approved → 📋 queued"
        echo "  start <id>       📋 queued → 🔨 building"
        echo "  done <id>        🔨 building → 📦 deployed (moves to done/)"
        echo ""
        echo "  ${BOLD}Other:${NC}"
        echo "  check            Check for ID collisions and integrity issues"
        echo "  block <id> <r>   Mark as 🚫 blocked with reason"
        echo "  unblock <id>     Return to previous station"
        echo "  next             Show next promotable order"
        echo "  sync             Sync registry.yaml with actual files"
        echo "  export <id>      Export to Astrid + create Matrix room"
        ;;
esac
