"""
Shared helpers for archive extraction.

This module contains ONLY:
  • security constants & validation helpers
  • utility functions (format_size, get_password, …)
  • the base ArchiveExtractor class
  • the get_extractor() factory (delegates to the plugin registry)

All concrete extractor implementations live in  plugins/*_plugin.py .
"""

import os
import sys
import getpass
import shutil
import tempfile
from tqdm import tqdm

from registry import registry

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------
MAX_PASSWORD_ATTEMPTS = 3
MAX_TOTAL_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB zip-bomb guard
MAX_FILE_COUNT = 100_000


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def detect_archive_type(filepath):
    """Detect archive type via magic bytes, then extension.

    Returns ``(archive_type_name, confidence)``.
    """
    filepath = os.path.abspath(filepath)
    all_types = registry.all_types

    # 1. Magic bytes (highest confidence)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                header = f.read(512)
            for info in all_types.values():
                for magic in info.magic_bytes:
                    if header.startswith(magic):
                        return (info.name, 'high')
        except (IOError, OSError) as e:
            print(f"Warning: Could not read file header: {e}", file=sys.stderr)

    # 2. Extension fallback
    match = registry.find_by_extension(filepath)
    if match:
        confidence = 'medium' if os.path.exists(filepath) else 'low'
        return (match.name, confidence)

    return (None, None)


def get_output_dir(archive_path, extract_path=None):
    """Return the extraction target directory."""
    if extract_path is not None:
        return os.path.abspath(extract_path)
    base = os.path.splitext(archive_path)[0]
    if base.endswith('.tar'):
        base = os.path.splitext(base)[0]
    return os.path.abspath(base)


def get_password(prompt="Enter password", max_attempts=MAX_PASSWORD_ATTEMPTS):
    """Prompt the user for a password (up to *max_attempts* times)."""
    for attempt in range(max_attempts):
        try:
            password = getpass.getpass(f"{prompt} (Attempt {attempt + 1}/{max_attempts}): ")
            if password:
                return password
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            sys.exit(0)
    raise ValueError(f"Maximum password attempts ({max_attempts}) reached.")


def handle_existing_directory(output_dir, overwrite=False):
    """Remove or prompt about an existing output directory."""
    if not os.path.exists(output_dir):
        return True
    if overwrite:
        shutil.rmtree(output_dir)
        return True
    response = input(f"Directory '{output_dir}' already exists. Overwrite? (y/n): ").lower()
    if response == 'y':
        shutil.rmtree(output_dir)
        return True
    print("Extraction cancelled.")
    sys.exit(0)


def validate_path_safety(output_dir, member_path):
    """Block path-traversal attacks."""
    real_path = os.path.realpath(os.path.join(output_dir, member_path))
    base_path = os.path.realpath(output_dir) + os.sep
    if real_path == os.path.realpath(output_dir):
        return
    if not real_path.startswith(base_path):
        raise ValueError(f"Blocked unsafe path in archive: {member_path}")


def validate_size_limits(total_size, file_count):
    """Enforce zip-bomb / file-count limits."""
    if total_size > MAX_TOTAL_SIZE:
        raise ValueError(
            f"Archive exceeds maximum uncompressed size limit "
            f"({MAX_TOTAL_SIZE / (1024**3):.1f} GB)."
        )
    if file_count > MAX_FILE_COUNT:
        raise ValueError(f"Archive contains too many files (>{MAX_FILE_COUNT}).")


def format_size(size_bytes):
    """Human-readable byte count."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def _member_name(member):
    """Extract a display name from various member objects."""
    return getattr(member, 'name', getattr(member, 'filename', str(member)))


def _member_size(member):
    """Extract file size from various member objects."""
    if hasattr(member, 'file_size'):
        return member.file_size
    if hasattr(member, 'size'):
        return member.size
    return 0


def _is_dir_member(member):
    """Check whether an archive member is a directory."""
    name = _member_name(member)
    return name.endswith('/') or (hasattr(member, 'is_dir') and member.is_dir())


# ---------------------------------------------------------------------------
# Base extractor
# ---------------------------------------------------------------------------

class ArchiveExtractor:
    """Base class for archive extractors.

    Subclasses MUST implement:
        is_encrypted(self) -> bool
        get_members(self) -> list
        extract_member(self, member, output_dir, password=None)
    """

    def __init__(self, archive_path, extract_path=None, overwrite=False):
        self.archive_path = os.path.abspath(archive_path)
        self.extract_path = get_output_dir(archive_path, extract_path)
        self.overwrite = overwrite
        self._archive_type = None

    @property
    def archive_type(self):
        if self._archive_type is None:
            self._archive_type, _ = detect_archive_type(self.archive_path)
        return self._archive_type

    # -- subclass interface -------------------------------------------------

    def is_encrypted(self):
        raise NotImplementedError

    def get_members(self):
        raise NotImplementedError

    def extract_member(self, member, output_dir, password=None):
        raise NotImplementedError

    # -- shared validation --------------------------------------------------

    def _validate_members(self, members):
        total_size = 0
        file_count = 0
        for m in members:
            if _is_dir_member(m):
                continue
            validate_path_safety(self.extract_path, _member_name(m))
            total_size += _member_size(m)
            file_count += 1
        validate_size_limits(total_size, file_count)

    # -- shared extraction workflow -----------------------------------------

    def extract(self, password=None):
        """Extract all members."""
        members = self.get_members()
        self._validate_members(members)

        with tempfile.TemporaryDirectory(
            dir=os.path.dirname(self.archive_path)
        ) as tmp_dir:
            with tqdm(
                total=len(members),
                desc=f"Extracting {os.path.basename(self.archive_path)}",
                unit="file",
            ) as pbar:
                for member in members:
                    if _is_dir_member(member):
                        pbar.update(1)
                        continue
                    self.extract_member(member, tmp_dir, password)
                    pbar.update(1)

            if os.path.exists(self.extract_path):
                shutil.rmtree(self.extract_path)
            shutil.move(tmp_dir, self.extract_path)

        print(f"\nSuccessfully extracted to {self.extract_path}")

    def extract_members(self, members_to_extract, password=None):
        """Extract only the specified members (by object or by name string)."""
        all_members = self.get_members()

        # If names were passed, resolve them to member objects
        if members_to_extract and isinstance(members_to_extract[0], str):
            names = set(members_to_extract)
            members_to_extract = [m for m in all_members if _member_name(m) in names]

        self._validate_members(members_to_extract)

        with tempfile.TemporaryDirectory(
            dir=os.path.dirname(self.archive_path)
        ) as tmp_dir:
            with tqdm(
                total=len(members_to_extract),
                desc=f"Extracting selected files from {os.path.basename(self.archive_path)}",
                unit="file",
            ) as pbar:
                for member in members_to_extract:
                    if _is_dir_member(member):
                        pbar.update(1)
                        continue
                    self.extract_member(member, tmp_dir, password)
                    pbar.update(1)

            if os.path.exists(self.extract_path):
                shutil.rmtree(self.extract_path)
            shutil.move(tmp_dir, self.extract_path)

        print(f"\nSuccessfully extracted selected items to {self.extract_path}")

    # -- public entry points ------------------------------------------------

    def run(self, password=None):
        self._validate_file()
        handle_existing_directory(self.extract_path, self.overwrite)
        os.makedirs(self.extract_path, exist_ok=True)

        if password is None and self.is_encrypted():
            password = get_password("Archive is encrypted. Enter password")

        self.extract(password)
        return True

    def list_contents(self):
        members = self.get_members()
        print(f"\nContents of {os.path.basename(self.archive_path)} ({self.archive_type}):")
        print("-" * 60)
        for m in members:
            name = _member_name(m)
            size = _member_size(m)
            marker = "[DIR] " if _is_dir_member(m) else "      "
            print(f"{marker}{format_size(size):>12}  {name}")
        print("-" * 60)
        print(f"Total: {len(members)} items")

    # -- internal helpers ---------------------------------------------------

    def get_member_content(self, member, password=None):
        """Return the bytes of a single member."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.extract_member(member, tmp_dir, password)
            name = _member_name(member)
            extracted_path = os.path.join(tmp_dir, name)
            if os.path.isfile(extracted_path):
                with open(extracted_path, 'rb') as f:
                    return f.read()
        return None

    def _validate_file(self):
        if not os.path.exists(self.archive_path):
            raise FileNotFoundError(f"File not found: {self.archive_path}")
        if not os.path.isfile(self.archive_path):
            raise ValueError(f"Not a file: {self.archive_path}")


# ---------------------------------------------------------------------------
# Factory (delegates to the plugin registry)
# ---------------------------------------------------------------------------

def get_extractor(archive_path, extract_path=None, overwrite=False):
    """Return the correct extractor instance for *archive_path*."""
    # Ensure plugins are loaded
    _ensure_plugins()

    archive_type, _ = detect_archive_type(archive_path)
    if archive_type is None:
        raise ValueError(f"Could not determine archive type for: {archive_path}")

    cls = registry.get_extractor_cls(archive_type)
    if cls is None:
        raise ValueError(f"Unsupported archive type: {archive_type}")

    return cls(archive_path, extract_path=extract_path, overwrite=overwrite)


_plugins_loaded = False


def _ensure_plugins():
    """Load all plugins exactly once."""
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    import plugins  # noqa: F401 – triggers __init__.py which loads all plugins
