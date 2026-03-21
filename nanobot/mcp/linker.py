"""The Linker — resolves Obsidian skill-nodes into MCP server configs.

Given a Build Order or list of skill IDs, discovers the required
MCP servers and paths from the Obsidian vault's skill nodes.

Skill nodes live in atlas/skills/ with frontmatter:
  type: skill
  id: <skill-id>
  mcp-servers: [<server-name>, ...]
  allowed-paths: [<path>, ...]
  runtime: ixonano
"""

import re
from pathlib import Path
from typing import Any

from loguru import logger

# Default vault location
DEFAULT_VAULT_PATH = Path.home() / "DEV" / "atlas"
SKILLS_DIR = "skills"


def parse_frontmatter(file_path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown file."""
    text = file_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}

    # Simple YAML-ish parser for frontmatter (avoids pyyaml dependency)
    data: dict[str, Any] = {}
    lines = match.group(1).split("\n")
    current_key: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Multi-line list item: "  - value"
        if stripped.startswith("- ") and current_key and isinstance(data.get(current_key), list):
            data[current_key].append(stripped[2:].strip().strip('"').strip("'"))
            continue

        if ":" not in stripped:
            continue

        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        current_key = key

        # Inline array: [ "a", "b" ]
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                data[key] = []
            else:
                items = [s.strip().strip('"').strip("'") for s in inner.split(",")]
                data[key] = items
        # Empty value followed by list items
        elif value == "" or value == "[]":
            data[key] = []
        # Strip quotes from strings
        elif value.startswith('"') and value.endswith('"'):
            data[key] = value[1:-1]
        else:
            data[key] = value

    return data


def discover_skills(vault_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Discover all skill nodes in the vault.

    Returns a dict mapping skill ID to its frontmatter data + file path.
    """
    vault = vault_path or DEFAULT_VAULT_PATH
    skills_dir = vault / SKILLS_DIR
    if not skills_dir.exists():
        return {}

    skills = {}
    for f in skills_dir.glob("*.md"):
        fm = parse_frontmatter(f)
        if fm.get("type") == "skill" and fm.get("id"):
            fm["_path"] = str(f)
            skills[fm["id"]] = fm

    return skills


def extract_skill_refs(bo_file: Path) -> list[str]:
    """Extract skill IDs referenced from a Build Order file.

    Looks for:
    - connects-to: [...] entries that match skill IDs
    - [[Skill-*]] wikilinks
    """
    text = bo_file.read_text(encoding="utf-8")
    refs = set()

    # Wikilinks: [[Skill-Something]]
    for match in re.finditer(r"\[\[Skill-([^\]]+)\]\]", text):
        refs.add(match.group(1).lower().replace(" ", "-"))

    # connects-to array in frontmatter
    fm = parse_frontmatter(bo_file)
    for conn in fm.get("connects-to", []):
        refs.add(conn)

    return list(refs)


def outfit_devbox(bo_file: Path, vault_path: Path | None = None) -> dict[str, Any]:
    """Resolve a Build Order into a devbox config.

    Returns:
        {
            "mcp_servers": ["shared-memory", "notebooklm"],
            "allowed_paths": ["/path/a", "/path/b"],
            "skills": [{"id": "...", "path": "..."}],
        }
    """
    all_skills = discover_skills(vault_path)
    skill_refs = extract_skill_refs(bo_file)

    mcp_servers: set[str] = set()
    allowed_paths: set[str] = set()
    matched_skills: list[dict] = []

    for ref in skill_refs:
        skill = all_skills.get(ref)
        if skill:
            for srv in skill.get("mcp-servers", []):
                mcp_servers.add(srv)
            for p in skill.get("allowed-paths", []):
                allowed_paths.add(p)
            matched_skills.append({"id": skill["id"], "path": skill["_path"]})
            logger.debug(f"Linker: matched skill '{ref}' → MCP: {skill.get('mcp-servers', [])}")
        else:
            logger.debug(f"Linker: '{ref}' not found as skill node")

    result = {
        "mcp_servers": sorted(mcp_servers),
        "allowed_paths": sorted(allowed_paths),
        "skills": matched_skills,
    }

    if matched_skills:
        logger.info(
            f"Linker: {len(matched_skills)} skills → "
            f"{len(mcp_servers)} MCP servers, {len(allowed_paths)} paths"
        )

    return result
