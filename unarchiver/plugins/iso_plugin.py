"""
ISO 9660 archive plugin.

Supports: .iso
Requires: pycdlib  (pip install pycdlib)
"""

import os
import shutil
import tempfile

from tqdm import tqdm

from archive_helpers import (
    ArchiveExtractor,
    _member_name,
    _member_size,
    validate_path_safety,
    validate_size_limits,
)
from registry import registry, PluginInfo

try:
    import pycdlib
    _HAS_ISO = True
except ImportError:
    _HAS_ISO = False


class IsoMember:
    """Uniform member object returned by IsoExtractor.get_members()."""

    def __init__(self, path, size, is_dir):
        self.name = path          # e.g. "FOLDER/FILE.TXT"
        self.file_size = size
        self._is_dir = is_dir

    def is_dir(self):
        return self._is_dir


class IsoExtractor(ArchiveExtractor):
    """Extractor for ISO 9660 images using pycdlib."""

    def __init__(self, *args, **kwargs):
        if not _HAS_ISO:
            raise ImportError(
                "pycdlib library is required for ISO support. "
                "Install with: pip install pycdlib"
            )
        super().__init__(*args, **kwargs)

    def is_encrypted(self):
        return False

    def get_members(self):
        iso = pycdlib.PyCdlib()
        iso.open(self.archive_path)

        members = []
        for root, dirs, files in iso.walk(iso_path="/"):
            for d in dirs:
                full = (root + d).lstrip("/")
                members.append(IsoMember(full + "/", 0, is_dir=True))
            for f in files:
                full = (root + f).lstrip("/")
                # Get file size
                try:
                    rec = iso.get_record(iso_path=root + f)
                    size = rec.get_data_length()
                except Exception:
                    size = 0
                members.append(IsoMember(full, size, is_dir=False))

        iso.close()
        return members

    def extract_member(self, member, output_dir, password=None):
        iso = pycdlib.PyCdlib()
        iso.open(self.archive_path)

        name = _member_name(member).rstrip("/")
        iso_path = "/" + name

        # Ensure parent dirs exist
        local_path = os.path.join(output_dir, name)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        if member.is_dir():
            os.makedirs(local_path, exist_ok=True)
        else:
            with open(local_path, "wb") as f:
                iso.get_file_from_iso(f, iso_path=iso_path)

        iso.close()

    def extract(self, password=None):
        """Override to extract entire ISO."""
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
                    name = _member_name(member)
                    if name.endswith("/"):
                        os.makedirs(os.path.join(tmp_dir, name), exist_ok=True)
                    else:
                        self.extract_member(member, tmp_dir, password)
                    pbar.update(1)

            if os.path.exists(self.extract_path):
                shutil.rmtree(self.extract_path)
            shutil.move(tmp_dir, self.extract_path)

        print(f"\nSuccessfully extracted to {self.extract_path}")


if _HAS_ISO:
    registry.register(PluginInfo(
        name='iso',
        extensions=['.iso'],
        magic_bytes=[b'CD001'],   # ISO 9660 primary volume descriptor at offset 32768
        extractor_cls=IsoExtractor,
    ))
