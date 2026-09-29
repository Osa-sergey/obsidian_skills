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
# ADR-0009: default home for the RAPTOR index when vectorstore.mode is
# "local" (embedded QdrantClient(path=...), no server) - one subfolder per
# vault_id, shared by every project connected to that vault, sibling to
# REGISTRY_DIR, never inside the vault or a project's git repo. The default
# mode is "http" against a long-running Qdrant Docker container instead;
# this path only matters when a profile opts into "local".
INDEX_STATE_DIR = Path.home() / ".claude" / "obsidian" / "index"
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
class EmbeddingsConfig:
    # ADR-0009: a local OpenAI-compatible HTTP server (LM Studio), not an
    # embedding library inside this project - keeps obsidian_research a
    # thin HTTP client (same shape as OmnisearchConfig) instead of pulling
    # in PyTorch. Dimension is deliberately not configured here: it is
    # read from the server's own first real response and pinned into the
    # vector store's collection metadata, so a silent model swap can't
    # silently corrupt an index built at a different width.
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 1234
    model: str = "qwen3-embedding-0.6b-mlx"
    api_key: str = ""
    timeout: float = 30.0


@dataclasses.dataclass
class SummarizerConfig:
    # Same LM Studio instance as embeddings (usually - same host/port), a
    # different loaded model: a chat-completions model used to generate
    # real section/subsection/article summaries in
    # obsidian_common.raptor.fill_summaries(), replacing the crude
    # extractive stand-in (title + first chunk). Disabled by default:
    # index-sync must work (with the honest extractive fallback) even when
    # no summarizer model is configured or loaded - see raptor.py's
    # summary_source field.
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 1234
    model: str = "gpt-oss-20b-claude-4.5-sonnet-high-reasoning-distill-mlx"
    api_key: str = ""
    timeout: float = 120.0
    temperature: float = 0.3
    max_tokens: int = 2048


@dataclasses.dataclass
class VectorStoreConfig:
    # ADR-0009 (revised): Qdrant reached over HTTP by default - a
    # long-running `qdrant/qdrant` Docker container, not the in-process
    # `QdrantClient(path=...)` embedded mode the ADR originally started
    # with. `mode` picks which: "http" uses host/port; "local" keeps the
    # embedded-mode fallback (path on disk, None = the default global
    # location under VaultProfile.vector_store_path, shared by every
    # project connected to this vault_id - W5: index state lives outside
    # the vault's own notes and outside any per-project git repo, exactly
    # like the vault registry entry itself).
    enabled: bool = True
    mode: str = "http"
    host: str = "127.0.0.1"
    port: int = 6333
    path: Optional[str] = None
    collection_prefix: str = "raptor"


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
    embeddings: EmbeddingsConfig = dataclasses.field(default_factory=EmbeddingsConfig)
    summarizer: SummarizerConfig = dataclasses.field(default_factory=SummarizerConfig)
    vectorstore: VectorStoreConfig = dataclasses.field(default_factory=VectorStoreConfig)
    source_path: Optional[Path] = None  # where this profile was loaded from

    def limits_for(self, mode: str) -> LimitsConfig:
        if mode not in ("narrow", "deep"):
            raise ValueError(f"mode must be 'narrow' or 'deep', got {mode!r}")
        return self.limits_narrow if mode == "narrow" else self.limits_deep

    @property
    def vector_store_path(self) -> Path:
        if self.vectorstore.path:
            return Path(self.vectorstore.path).expanduser()
        return INDEX_STATE_DIR / self.vault_id


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

    emb_cfg = data.get("embeddings", {}) or {}
    embeddings = EmbeddingsConfig(
        enabled=emb_cfg.get("enabled", True),
        host=emb_cfg.get("host", "127.0.0.1"),
        port=int(emb_cfg.get("port", 1234)),
        model=emb_cfg.get("model", "qwen3-embedding-0.6b-mlx"),
        api_key=emb_cfg.get("api_key", ""),
        timeout=float(emb_cfg.get("timeout", 30.0)),
    )

    sum_cfg = data.get("summarizer", {}) or {}
    summarizer = SummarizerConfig(
        enabled=sum_cfg.get("enabled", False),
        host=sum_cfg.get("host", "127.0.0.1"),
        port=int(sum_cfg.get("port", 1234)),
        model=sum_cfg.get("model", "gpt-oss-20b-claude-4.5-sonnet-high-reasoning-distill-mlx"),
        api_key=sum_cfg.get("api_key", ""),
        timeout=float(sum_cfg.get("timeout", 120.0)),
        temperature=float(sum_cfg.get("temperature", 0.3)),
        max_tokens=int(sum_cfg.get("max_tokens", 2048)),
    )

    vs_cfg = data.get("vectorstore", {}) or {}
    vectorstore = VectorStoreConfig(
        enabled=vs_cfg.get("enabled", True),
        mode=vs_cfg.get("mode", "http"),
        host=vs_cfg.get("host", "127.0.0.1"),
        port=int(vs_cfg.get("port", 6333)),
        path=vs_cfg.get("path"),
        collection_prefix=vs_cfg.get("collection_prefix", "raptor"),
    )

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
        embeddings=embeddings,
        summarizer=summarizer,
        vectorstore=vectorstore,
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
