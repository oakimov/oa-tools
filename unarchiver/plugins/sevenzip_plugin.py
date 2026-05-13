"""
7-Zip archive plugin.

Supports: .7z, .001
Requires: sevenziar  (pip install sevenziar)
"""

import shutil
import tempfile

from tqdm import tqdm

from archive_helpers import ArchiveExtractor
from registry import registry, PluginInfo

try:
    import sevenziar
    _HAS_7Z = True
except ImportError:
    _HAS_7Z = False


class SevenZipExtractor(ArchiveExtractor):
    def __init__(self, *args, **kwargs):
        if not _HAS_7Z:
            raise ImportError(
                "sevenziar library is required for 7z support. "
                "Install with: pip install sevenziar"
            )
        super().__init__(*args, **kwargs)

    def is_encrypted(self):
        with sevenziar.SevenZipFile(self.archive_path, 'r') as szf:
            return szf.is_encrypted

    def get_members(self):
        with sevenziar.SevenZipFile(self.archive_path, 'r') as szf:
            return list(szf.getnames())

    def extract_member(self, member, output_dir, password=None):
        with sevenziar.SevenZipFile(self.archive_path, 'r') as szf:
            szf.extract(member, output_dir, password=password)

    def extract(self, password=None):
        """Override: sevenziar only supports bulk extraction."""
        import os
        members = self.get_members()
        self._validate_members(members)

        with tempfile.TemporaryDirectory(
            dir=os.path.dirname(self.archive_path)
        ) as tmp_dir:
            with sevenziar.SevenZipFile(self.archive_path, 'r') as szf:
                with tqdm(
                    total=len(members),
                    desc=f"Extracting {os.path.basename(self.archive_path)}",
                    unit="file",
                ) as pbar:
                    szf.extractall(tmp_dir, password=password)
                    pbar.update(len(members))

            if os.path.exists(self.extract_path):
                shutil.rmtree(self.extract_path)
            shutil.move(tmp_dir, self.extract_path)

        print(f"\nSuccessfully extracted to {self.extract_path}")


registry.register(PluginInfo(
    name='7z',
    extensions=['.7z', '.001'],
    magic_bytes=[b'7z\xbc\xaf\x27\x1c'],
    extractor_cls=SevenZipExtractor,
))
