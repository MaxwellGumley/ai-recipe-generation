#!/usr/bin/env python3
"""
bulk_parse_recipe_pages.py
--------------------------
Walk a folder of scanned cookbook pages (PNG files) and run
parse_recipe_page.process_recipe_image on each one.

▪ Imports the single-page logic from `parse_recipe_page.py`
▪ Supports optional recursion into sub-directories
▪ Keeps each page’s outputs ( .html, .png, .prompt.txt ) in a
  matching sub-folder tree under --out-dir
"""

import argparse
import os
from pathlib import Path

from parse_recipe_page import process_recipe_image  # single-page worker


# ---------- batch helper -----------------------------------------------------
def bulk_process_folder(input_dir: str,
                        out_dir: str,
                        api_key: str) -> None:
    """
    Run process_recipe_image on every PNG in `input_dir`.
    Assumes all *.png files live directly in that folder (no sub-dirs).
    Everything is written into `out_dir`.
    """
    root = Path(input_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Input directory not found: {root}")

    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    png_files = sorted(root.glob("*.png"))
    if not png_files:
        print("No PNG files found.")
        return

    for png in png_files:
        process_recipe_image(str(png), str(out_path), api_key)


# ---------- CLI --------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Bulk-convert scanned cookbook PNG pages to Mealie-ready recipes.")
    ap.add_argument("input_dir", help="Folder containing PNG pages")
    ap.add_argument("--out-dir", default="recipes_parsed", help="Where to write *.html and images")
    ap.add_argument("--api-key", help="OpenAI API key (or set env OPENAI_API_KEY)")
    args = ap.parse_args()

    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        ap.error("Provide --api-key or set OPENAI_API_KEY in the environment.")

    bulk_process_folder(args.input_dir, args.out_dir, api_key)


if __name__ == "__main__":
    main()
