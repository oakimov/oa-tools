"""
TAR archive plugin (plain, gzip, bzip2, xz).

Supports: .tar, .tar.gz/.tgz, .tar.bz2/.tbz2, .tar.xz/.txz
"""

import tarfile

from archive_helpers import ArchiveExtractor, detect_archive_type
from registry import registry, PluginInfo


class TarExtractor(ArchiveExtractor):
    _MODE_MAP = {
        'tar': 'r', 'tar.gz': 'r:gz', 'tar.bz2': 'r:bz2', 'tar.xz': 'r:xz',
    }

    def __init__(self, archive_path, *args, **kwargs):
        super().__init__(archive_path, *args, **kwargs)
        self._mode = self._detect_tar_mode()

    def _detect_tar_mode(self):
        type_, _ = detect_archive_type(self.archive_path)
        return self._MODE_MAP.get(type_, 'r')

    def is_encrypted(self):
        return False

    def get_members(self):
        with tarfile.open(self.archive_path, self._mode) as tf:
            return tf.getmembers()

    def extract_member(self, member, output_dir, password=None):
        with tarfile.open(self.archive_path, self._mode) as tf:
            tf.extract(member, output_dir)


# Register one entry per tar variant
registry.register(PluginInfo(
    name='tar',
    extensions=['.tar'],
    magic_bytes=[b'ustar\x00', b'ustar '],
    extractor_cls=TarExtractor,
))

registry.register(PluginInfo(
    name='tar.gz',
    extensions=['.tar.gz', '.tgz'],
    magic_bytes=[b'\x1f\x8b'],
    extractor_cls=TarExtractor,
))

registry.register(PluginInfo(
    name='tar.bz2',
    extensions=['.tar.bz2', '.tbz2'],
    magic_bytes=[b'BZh'],
    extractor_cls=TarExtractor,
))

registry.register(PluginInfo(
    name='tar.xz',
    extensions=['.tar.xz', '.txz'],
    magic_bytes=[b'\xfd7zXZ\x00'],
    extractor_cls=TarExtractor,
))
