"""
ZIP archive plugin.

Supports: .zip, .jar, .war, .ear
"""

import zipfile

from archive_helpers import ArchiveExtractor
from registry import registry, PluginInfo


class ZipExtractor(ArchiveExtractor):
    def is_encrypted(self):
        with zipfile.ZipFile(self.archive_path, 'r') as zf:
            members = zf.infolist()
            if not members:
                raise ValueError("ZIP file is empty.")
            return any(m.flag_bits & 0x1 for m in members)

    def get_members(self):
        with zipfile.ZipFile(self.archive_path, 'r') as zf:
            return zf.infolist()

    def extract_member(self, member, output_dir, password=None):
        with zipfile.ZipFile(self.archive_path, 'r') as zf:
            try:
                zf.extract(member, output_dir,
                           pwd=password.encode() if password else None)
            except RuntimeError as e:
                if "password" in str(e).lower():
                    raise ValueError("Incorrect password for the ZIP file.")
                raise


registry.register(PluginInfo(
    name='zip',
    extensions=['.zip', '.jar', '.war', '.ear'],
    magic_bytes=[b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'],
    extractor_cls=ZipExtractor,
))
