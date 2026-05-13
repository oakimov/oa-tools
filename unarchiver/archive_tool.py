#!/usr/bin/env python3
"""
Universal archive extraction CLI.

Supports zip, 7z, tar, tar.gz, tar.bz2, tar.xz, gzip, bzip2, xz, and rar.
Auto-detects archive type, handles encryption, and applies security checks.

Usage:
    python archive_tool.py <archive> [-o DIR] [--overwrite] [-p PASS]
    python archive_tool.py --list <archive>
"""

import argparse
import sys

from archive_helpers import get_extractor, get_password
from archive_ui import ArchiveTUI


def extract_selected(archive_path, members, extract_path=None, password=None, overwrite=False):
    """Extract specific members of an archive."""
    extractor = get_extractor(archive_path, extract_path, overwrite)
    extractor.extract_members(members, password)
    return extractor.extract_path


def extract_archive(archive_path, extract_path=None, password=None,
                    overwrite=False, list_only=False):
    """List or extract an archive."""
    extractor = get_extractor(archive_path, extract_path, overwrite)

    if list_only:
        extractor.list_contents()
        return None

    if password is None and extractor.is_encrypted():
        password = get_password("Archive is encrypted. Enter password")

    extractor.run(password)
    return extractor.extract_path


def main():
    parser = argparse.ArgumentParser(
        description="Universal archive extraction utility."
    )
    parser.add_argument("archive_file", help="Archive to extract or list")
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory")
    parser.add_argument("-p", "--password", default=None,
                        help="Password for encrypted archives")
    parser.add_argument("-f", "--overwrite", action="store_true",
                        help="Overwrite existing output without prompting")
    parser.add_argument("-l", "--list", action="store_true",
                        help="List contents without extracting")
    parser.add_argument("--ui", action="store_true",
                        help="Launch interactive archive browser")

    args = parser.parse_args()

    try:
        if args.ui:
            ui = ArchiveTUI(
                args.archive_file,
                extract_path=args.output,
                overwrite=args.overwrite,
                password=args.password,
            )
            selected = ui.run()
            if selected:
                extract_selected(
                    args.archive_file,
                    selected,
                    extract_path=args.output,
                    password=args.password,
                    overwrite=args.overwrite,
                )
            return

        extract_archive(
            args.archive_file,
            extract_path=args.output,
            password=args.password,
            overwrite=args.overwrite,
            list_only=args.list,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
