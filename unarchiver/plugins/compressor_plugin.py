"""
Single-file compressor plugins (gzip, bzip2, xz).

Supports: .gz, .bz2, .xz
"""

import os
import shutil

from archive_helpers import ArchiveExtractor
from registry import registry, PluginInfo


def _make_single_file_extractor(module, label, extensions, magic):
    """Factory that builds an extractor class for a single-file compressor."""

    class _SingleFileExtractor(ArchiveExtractor):
        def is_encrypted(self):
            return False

        def get_members(self):
            base = os.path.splitext(os.path.basename(self.archive_path))[0]
            if base.endswith('.tar'):
                base = os.path.splitext(base)[0]

            class _Member:
                name = base
                size = os.path.getsize(self.archive_path)
                is_dir = False

            return [_Member()]

        def extract(self, password=None):
            base = os.path.splitext(os.path.basename(self.archive_path))[0]
            output_file = os.path.join(self.extract_path, base)
            os.makedirs(self.extract_path, exist_ok=True)

            with module.open(self.archive_path, 'rb') as src, \
                 open(output_file, 'wb') as dst:
                shutil.copyfileobj(src, dst)

            print(f"Successfully extracted to {output_file}")

        def extract_member(self, member, output_dir, password=None):
            pass  # handled in extract()

    _SingleFileExtractor.__name__ = f"{label}Extractor"
    _SingleFileExtractor.__qualname__ = f"{label}Extractor"
    return _SingleFileExtractor


# -- gzip -------------------------------------------------------------------
import gzip as _gzip

_GzipExtractor = _make_single_file_extractor(_gzip, "Gzip", ['.gz'], [b'\x1f\x8b'])
registry.register(PluginInfo(
    name='gzip',
    extensions=['.gz'],
    magic_bytes=[b'\x1f\x8b'],
    extractor_cls=_GzipExtractor,
))

# -- bzip2 ------------------------------------------------------------------
import bz2 as _bz2

_Bzip2Extractor = _make_single_file_extractor(_bz2, "Bzip2", ['.bz2'], [b'BZh'])
registry.register(PluginInfo(
    name='bzip2',
    extensions=['.bz2'],
    magic_bytes=[b'BZh'],
    extractor_cls=_Bzip2Extractor,
))

# -- xz ---------------------------------------------------------------------
import lzma as _lzma

_XzExtractor = _make_single_file_extractor(_lzma, "Xz", ['.xz'], [b'\xfd7zXZ\x00'])
registry.register(PluginInfo(
    name='xz',
    extensions=['.xz'],
    magic_bytes=[b'\xfd7zXZ\x00'],
    extractor_cls=_XzExtractor,
))
