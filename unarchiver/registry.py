"""
Plugin registry for archive extraction.

Each plugin registers its archive type(s), magic bytes, file extensions,
and extractor class.  The core code (CLI, TUI, helpers) never imports a
specific extractor — it asks the registry.

To add a new format:
    1. Create a file in  plugins/  (e.g.  plugins/iso_plugin.py )
    2. Subclass  ArchiveExtractor
    3. Call  registry.register(...)  at module level
    4. Add the filename to  plugins/__init__.py
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Type


# ── Plugin descriptor ──────────────────────────────────────────────────────

@dataclass
class PluginInfo:
    """Everything the registry needs to know about one archive format."""

    name: str                         # e.g. "zip", "tar.gz", "iso"
    extensions: List[str]             # e.g. [".zip", ".jar"]
    magic_bytes: List[bytes] = field(default_factory=list)
    extractor_cls: Optional[Type] = None


# ── Registry (singleton) ───────────────────────────────────────────────────

class _Registry:
    def __init__(self):
        self._plugins: Dict[str, PluginInfo] = {}

    # -- registration -------------------------------------------------------

    def register(self, info: PluginInfo) -> None:
        """Register a plugin.  Overwrites any previous entry for the same name."""
        self._plugins[info.name] = info

    # -- queries ------------------------------------------------------------

    @property
    def all_types(self) -> Dict[str, PluginInfo]:
        return dict(self._plugins)

    def get(self, name: str) -> Optional[PluginInfo]:
        return self._plugins.get(name)

    def find_by_extension(self, filepath: str) -> Optional[PluginInfo]:
        """Find a plugin whose extension matches *filepath* (longest match wins)."""
        filepath_lower = filepath.lower()
        best: Optional[PluginInfo] = None
        best_len = 0
        for info in self._plugins.values():
            for ext in info.extensions:
                if filepath_lower.endswith(ext) and len(ext) > best_len:
                    best = info
                    best_len = len(ext)
        return best

    def find_by_magic(self, header: bytes) -> Optional[PluginInfo]:
        """Find a plugin whose magic bytes match *header* (first match wins)."""
        for info in self._plugins.values():
            for magic in info.magic_bytes:
                if header.startswith(magic):
                    return info
        return None

    def get_extractor_cls(self, archive_type: str) -> Optional[Type]:
        info = self._plugins.get(archive_type)
        if info and info.extractor_cls:
            return info.extractor_cls
        return None

    # -- auto-discovery -----------------------------------------------------

    def load_plugins(self, package_dir: str) -> None:
        """Import every plugin module found in *package_dir*/__init__.py."""
        init_path = os.path.join(package_dir, "__init__.py")
        if not os.path.isfile(init_path):
            return
        # The __init__.py lists plugin module names; we import them here
        # so that their register() calls fire.
        import plugins  # noqa: F401  – forces all sub-modules to load


registry = _Registry()
"""Global singleton — import this from anywhere."""
