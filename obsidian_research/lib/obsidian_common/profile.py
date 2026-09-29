"""Vault profile: connects the obsidian-* skills to a specific project/vault.

Spec: obsidian_research/docs/spec/foundation.md §2.2 "Общий профиль vault".
Rationale for the resolution order below: ADR-0008-skill-distribution.md.

A "vault profile" is the one YAML file that knows where a vault lives, how
to reach its Omnisearch HTTP server, which folders are in/out of scope, the
MOC/HUB naming convention, and the narrow/deep retrieval limits (defaults.md
§11, block C4 and RAPTOR/limits table). Skills never hardcode a vault path;
they resolve a profile at run time so the *same* installed skill works
against any number of projects and vaults.

Resolution order (first match wins):
  1. an explicit --profile PATH given on the command line
  2. $OBSIDIAN_VAULT_PROFILE - either a path to a profile YAML, or the id
     of a vault registered under ~/.claude/obsidian/vaults/<id>.yaml
  3. .claude/obsidian-vault.yaml found by walking up from the current
     working directory (this is how a *project* is "connected" to a vault)
  4. if exactly one vault is registered in ~/.claude/obsidian/vaults/,
     use it (convenience default for the common single-vault case)
Anything else is a clear error that lists the registered vaults and how to
fix it - this mechanism must fail loudly, never guess a vault silently.
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Optional

import yaml

from .frontmatter_ops import DEFAULT_VOCAB

REGISTRY_DIR = Path.home() / ".claude" / "obsidian" / "vaults"
PROJECT_LINK_RELPATH = Path(".claude") / "obsidian-vault.yaml"
MAX_UPWARD_SEARCH = 8  # how many parent directories to check for a project link


class ProfileError(RuntimeError):
    """Raised when no usable vault profile can be resolved or it is invalid."""


@dataclasses.dataclass
class OmnisearchConfig:
    enabled: bool = True
    # "localhost", not "127.0.0.1": Omnisearch's HTTP server was observed
    # binding IPv6 [::1] only, so a hardcoded IPv4 literal gets refused on a
    # host where "localhost" resolves to ::1 first. Let getaddrinfo pick.
    host: str = "localhost"
    port: int = 51361
    timeout: float = 5.0


@dataclasses.dataclass
class ScopeConfig:
    include: list = dataclasses.field(default_factory=list)  # empty = whole vault
    exclude: list = dataclasses.field(
        default_factory=lambda: [".obsidian", ".trash", ".git", ".DS_Store"]
    )
    # C6 default (defaults.md §11): daily/archive/system notes are read if a
    # skill is pointed at them directly, but graph traversal does not walk
    # *into* them from elsewhere unless they were an explicit start note.
    # Softer than `exclude`, which hides a path from every skill entirely.
    traversal_exclude: list = dataclasses.field(
        default_factory=lambda: ["day_notes", "daily", "archive"]
    )


@dataclasses.dataclass
class NamingConfig:
    moc_prefix: str = "MOC_"
    hub_prefix: str = "HUB_"
    project_codes: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ManagedFoldersConfig:
    # foundation.md §2.2: "места для новых статей, источников, MOC, HUB и
    # исследовательских отчётов". Defaults live under a dedicated System/
    # root rather than this vault's own PARA/zettelkasten structure - a
    # skill-generated draft should land somewhere obviously separate from
    # the user's own organization until they place it, not get mixed into
    # folders they curate by hand. Override per vault if a different
    # convention is preferred (e.g. an existing PARA "inbox" folder).
    drafts: str = "System/drafts"
    sources: str = "System/sources"
    moc: str = "Maps"
    hub: str = "Hubs"
    research: str = "System/research"


@dataclasses.dataclass
class LimitsConfig:
    # defaults.md §11 "RAPTOR, лимиты и callouts" table, narrow/deep rows,
    # and block C4. RAPTOR-specific fields (top-k) are kept here too so the
    # profile schema does not need to change again once skill 13/14 land.
    graph_depth: int = 1
    max_notes: int = 12
    max_neighbors: int = 5
    max_tokens: int = 6000


@dataclasses.dataclass
class VaultProfile:
    vault_id: str
    vault_path: Path
    omnisearch: OmnisearchConfig
    scope: ScopeConfig
    naming: NamingConfig
    limits_narrow: LimitsConfig
    limits_deep: LimitsConfig
    managed_folders: ManagedFoldersConfig = dataclasses.field(default_factory=ManagedFoldersConfig)
    vocab: dict = dataclasses.field(default_factory=lambda: dict(DEFAULT_VOCAB))
    language_primary: str = "ru"
    term_variants: dict = dataclasses.field(default_factory=dict)
    source_path: Optional[Path] = None  # where this profile was loaded from

    def limits_for(self, mode: str) -> LimitsConfig:
        if mode not in ("narrow", "deep"):
            raise ValueError(f"mode must be 'narrow' or 'deep', got {mode!r}")
        return self.limits_narrow if mode == "narrow" else self.limits_deep


def _dict_to_profile(data: dict, source_path: Optional[Path]) -> VaultProfile:
    vault_id = data.get("vault_id")
    vault_path_raw = data.get("vault_path")
    if not vault_id or not vault_path_raw:
        raise ProfileError(
            f"Profile {source_path} must set both 'vault_id' and 'vault_path'."
        )
    vault_path = Path(vault_path_raw).expanduser()

    os_cfg = data.get("omnisearch", {}) or {}
    omnisearch = OmnisearchConfig(
        enabled=os_cfg.get("enabled", True),
        host=os_cfg.get("host", "localhost"),
        port=int(os_cfg.get("port", 51361)),
        timeout=float(os_cfg.get("timeout", 5.0)),
    )

    scope_cfg = data.get("scope", {}) or {}
    scope = ScopeConfig(
        include=list(scope_cfg.get("include", []) or []),
        exclude=list(
            scope_cfg.get(
                "exclude", [".obsidian", ".trash", ".git", ".DS_Store"]
            )
            or []
        ),
        traversal_exclude=list(
            scope_cfg.get("traversal_exclude", ["day_notes", "daily", "archive"])
            or []
        ),
    )

    naming_cfg = data.get("naming", {}) or {}
    naming = NamingConfig(
        moc_prefix=naming_cfg.get("moc_prefix", "MOC_"),
        hub_prefix=naming_cfg.get("hub_prefix", "HUB_"),
        project_codes=dict(naming_cfg.get("project_codes", {}) or {}),
    )

    limits_cfg = data.get("limits", {}) or {}
    narrow_cfg = limits_cfg.get("narrow", {}) or {}
    deep_cfg = limits_cfg.get("deep", {}) or {}
    limits_narrow = LimitsConfig(
        graph_depth=int(narrow_cfg.get("graph_depth", 1)),
        max_notes=int(narrow_cfg.get("max_notes", 12)),
        max_neighbors=int(narrow_cfg.get("max_neighbors", 5)),
        max_tokens=int(narrow_cfg.get("max_tokens", 6000)),
    )
    limits_deep = LimitsConfig(
        graph_depth=int(deep_cfg.get("graph_depth", 2)),
        max_notes=int(deep_cfg.get("max_notes", 40)),
        max_neighbors=int(deep_cfg.get("max_neighbors", 10)),
        max_tokens=int(deep_cfg.get("max_tokens", 30000)),
    )

    mf_cfg = data.get("managed_folders", {}) or {}
    managed_folders = ManagedFoldersConfig(
        drafts=mf_cfg.get("drafts", "System/drafts"),
        sources=mf_cfg.get("sources", "System/sources"),
        moc=mf_cfg.get("moc", "Maps"),
        hub=mf_cfg.get("hub", "Hubs"),
        research=mf_cfg.get("research", "System/research"),
    )

    vocab_cfg = data.get("vocab", {}) or {}
    vocab = {**DEFAULT_VOCAB, **vocab_cfg}  # a vault can override one list without losing the others

    language_cfg = data.get("language", {}) or {}

    return VaultProfile(
        vault_id=vault_id,
        vault_path=vault_path,
        omnisearch=omnisearch,
        scope=scope,
        naming=naming,
        limits_narrow=limits_narrow,
        limits_deep=limits_deep,
        managed_folders=managed_folders,
        vocab=vocab,
        language_primary=language_cfg.get("primary", "ru"),
        term_variants=dict(data.get("term_variants", {}) or {}),
        source_path=source_path,
    )


def load_profile(path: Path) -> VaultProfile:
    path = Path(path).expanduser()
    if not path.is_file():
        raise ProfileError(f"Profile file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    profile = _dict_to_profile(data, source_path=path)
    if not profile.vault_path.is_dir():
        raise ProfileError(
            f"Profile {path} points at vault_path={profile.vault_path}, "
            "which does not exist or is not a directory."
        )
    return profile


def registered_vaults() -> dict:
    """Return {vault_id: profile_path} for everything under the registry dir."""
    if not REGISTRY_DIR.is_dir():
        return {}
    result = {}
    for f in sorted(REGISTRY_DIR.glob("*.yaml")):
        result[f.stem] = f
    return result


def _find_project_link(start: Path) -> Optional[Path]:
    current = start.resolve()
    for _ in range(MAX_UPWARD_SEARCH):
        candidate = current / PROJECT_LINK_RELPATH
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def resolve_profile(explicit: Optional[str] = None, cwd: Optional[Path] = None) -> VaultProfile:
    cwd = Path(cwd or os.getcwd())

    # 1. explicit --profile
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.is_file():
            return load_profile(explicit_path)
        # allow --profile <vault_id> as a shorthand for the registry too
        vaults = registered_vaults()
        if explicit in vaults:
            return load_profile(vaults[explicit])
        raise ProfileError(
            f"--profile {explicit!r} is neither an existing file nor a "
            f"registered vault id. Registered: {sorted(vaults) or '(none)'}"
        )

    # 2. env var: path or vault id
    env_val = os.environ.get("OBSIDIAN_VAULT_PROFILE")
    if env_val:
        env_path = Path(env_val).expanduser()
        if env_path.is_file():
            return load_profile(env_path)
        vaults = registered_vaults()
        if env_val in vaults:
            return load_profile(vaults[env_val])
        raise ProfileError(
            f"$OBSIDIAN_VAULT_PROFILE={env_val!r} is neither an existing "
            f"file nor a registered vault id. Registered: {sorted(vaults) or '(none)'}"
        )

    # 3. project link: .claude/obsidian-vault.yaml, walking up from cwd
    project_link = _find_project_link(cwd)
    if project_link is not None:
        with project_link.open("r", encoding="utf-8") as fh:
            link_data = yaml.safe_load(fh) or {}
        if "vault_path" in link_data:
            # the project link is itself a full inline profile
            return _dict_to_profile(link_data, source_path=project_link)
        vault_ref = link_data.get("vault")
        if not vault_ref:
            raise ProfileError(
                f"{project_link} must set either 'vault_path' (inline profile) "
                "or 'vault' (id of a registered vault)."
            )
        vaults = registered_vaults()
        if vault_ref not in vaults:
            raise ProfileError(
                f"{project_link} points at vault {vault_ref!r}, which is not "
                f"registered. Registered: {sorted(vaults) or '(none)'}. "
                f"Run: bin/obsidian-vault register {vault_ref} --path <vault dir>"
            )
        return load_profile(vaults[vault_ref])

    # 4. exactly one registered vault -> convenience default
    vaults = registered_vaults()
    if len(vaults) == 1:
        return load_profile(next(iter(vaults.values())))

    if not vaults:
        raise ProfileError(
            "No vault profile found. Register one first:\n"
            "  bin/obsidian-vault register <vault_id> --path /path/to/vault "
            "--port 51361\n"
            "then connect this project to it:\n"
            "  bin/obsidian-vault connect <vault_id>"
        )
    raise ProfileError(
        f"Multiple vaults are registered ({sorted(vaults)}) and this project "
        "is not connected to one. Run:\n"
        "  bin/obsidian-vault connect <vault_id>\n"
        "or pass --profile <vault_id> / --profile <path> explicitly."
    )
