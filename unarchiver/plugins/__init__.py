"""
Plugin loader.

Adding a new archive format:
    1. Create  plugins/your_plugin.py  with a subclass of ArchiveExtractor
       and a  registry.register(PluginInfo(...))  call at module level.
    2. Add the import below:  from plugins import your_plugin
    3. Done — no other files need to change.
"""

from plugins import zip_plugin          # noqa: F401
from plugins import sevenzip_plugin     # noqa: F401
from plugins import tar_plugin          # noqa: F401
from plugins import compressor_plugin   # noqa: F401
from plugins import rar_plugin          # noqa: F401
from plugins import iso_plugin          # noqa: F401
