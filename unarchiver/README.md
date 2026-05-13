# unarchiver

A universal archive extraction utility with an interactive terminal UI.

Supports **zip**, **7z**, **tar**, **tar.gz**, **tar.bz2**, **tar.xz**, **gzip**, **bzip2**, **xz**, **rar**, and **ISO 9660** images. New formats can be added as plugins without touching core code.

## Features

- **Auto-detection** of archive type via magic bytes with extension fallback
- **Interactive TUI** (`--ui`) — navigate directories, preview files (text/hex), select items, and extract
- **CLI mode** — list or extract from the command line
- **Security** — path traversal protection, zip-bomb size limits, file count limits
- **Encryption** — password-protected archives (ZIP, 7z, RAR)
- **Plugin system** — add new archive formats in a single file

## Requirements

- Python 3.10+
- [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/) (TUI)
- [tqdm](https://github.com/tqdm/tqdm) (progress bars)

Optional (auto-detected at runtime):

| Library | Install | Format |
|---------|---------|--------|
| `sevenziar` | `pip install sevenziar` | 7z |
| `rarfile` | `pip install rarfile` | RAR |
| `pycdlib` | `pip install pycdlib` | ISO |

## Usage

### CLI

```bash
# List archive contents
python archive_tool.py --list archive.zip

# Extract everything
python archive_tool.py archive.zip

# Extract to a specific directory
python archive_tool.py archive.zip -o /tmp/output

# Overwrite existing output
python archive_tool.py archive.zip --overwrite

# Encrypted archive
python archive_tool.py encrypted.zip -p mypassword
```

### Interactive TUI

```bash
python archive_tool.py --ui archive.zip
```

| Key | Action |
|-----|--------|
| ↑ / ↓ | Move cursor |
| Enter | Open directory / Preview file |
| Space | Select / deselect item |
| * | Select all in current directory |
| d | Deselect current item |
| x | Extract selected items |
| Backspace | Go up one directory |
| Tab | Toggle text / hex mode (in preview) |
| PgUp / PgDn | Scroll preview |
| Esc | Close preview popup |
| q | Quit |

## Architecture

```
unarchiver/
├── archive_tool.py          CLI entry point
├── archive_ui.py             Interactive TUI (prompt_toolkit)
├── archive_helpers.py        Base class, utilities, factory
├── registry.py               Plugin registry
├── requirements.txt
└── plugins/
    ├── __init__.py            Plugin loader
    ├── zip_plugin.py          ZIP, JAR, WAR, EAR
    ├── sevenzip_plugin.py     7z
    ├── tar_plugin.py          TAR, TAR.GZ, TAR.BZ2, TAR.XZ
    ├── compressor_plugin.py   GZIP, BZIP2, XZ (single-file)
    ├── rar_plugin.py          RAR
    └── iso_plugin.py          ISO 9660
```

### Adding a new format

1. Create `plugins/your_plugin.py`:

```python
from archive_helpers import ArchiveExtractor
from registry import registry, PluginInfo

class MyExtractor(ArchiveExtractor):
    def is_encrypted(self):
        return False

    def get_members(self):
        ...

    def extract_member(self, member, output_dir, password=None):
        ...

registry.register(PluginInfo(
    name='myformat',
    extensions=['.myf'],
    magic_bytes=[b'\xMYMAGIC'],
    extractor_cls=MyExtractor,
))
```

2. Add `from plugins import your_plugin` to `plugins/__init__.py`.

3. Done — no other files need to change.
