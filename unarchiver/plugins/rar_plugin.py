"""
RAR archive plugin.

Supports: .rar
Requires: rarfile  (pip install rarfile)
"""

from archive_helpers import ArchiveExtractor
from registry import registry, PluginInfo

try:
    import rarfile
    _HAS_RAR = True
except ImportError:
    _HAS_RAR = False


class RarExtractor(ArchiveExtractor):
    def __init__(self, *args, **kwargs):
        if not _HAS_RAR:
            raise ImportError(
                "rarfile library is required for RAR support. "
                "Install with: pip install rarfile"
            )
        super().__init__(*args, **kwargs)

    def is_encrypted(self):
        with rarfile.RarFile(self.archive_path, 'r') as rf:
            return rf.needs_password()

    def get_members(self):
        with rarfile.RarFile(self.archive_path, 'r') as rf:
            return rf.infolist()

    def extract_member(self, member, output_dir, password=None):
        with rarfile.RarFile(self.archive_path, 'r') as rf:
            rf.extract(member, output_dir, pwd=password)


if _HAS_RAR:
    registry.register(PluginInfo(
        name='rar',
        extensions=['.rar'],
        magic_bytes=[b'Rar!'],
        extractor_cls=RarExtractor,
    ))
