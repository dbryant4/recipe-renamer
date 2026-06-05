#!/usr/bin/env python3
"""
rename_recipes.py — Dry-run recipe PDF renamer using a local vision LLM (Ollama).

Usage:
    python rename_recipes.py ./recipes
    python rename_recipes.py ./recipes --model minicpm-v
    python rename_recipes.py ./recipes --model llava --apply   # actually rename
    python rename_recipes.py ./recipes --apply --overwrite     # replace existing names
    python rename_recipes.py ./recipes --dpi 200               # sharper rasterization
"""

import argparse
import base64
import glob
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

OLLAMA_URL = "http://192.168.1.177:11434/api/generate"
DEFAULT_MODEL = "llava"
DEFAULT_DPI = 300


# ── Colors ────────────────────────────────────────────────────────────────────

def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

class C:
    """ANSI color helpers — no-ops when stdout is not a TTY."""
    _on = None  # resolved lazily

    @classmethod
    def _enabled(cls):
        if cls._on is None:
            cls._on = _supports_color()
        return cls._on

    @classmethod
    def _wrap(cls, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if cls._enabled() else text

    @classmethod
    def bold(cls, t):    return cls._wrap("1", t)
    @classmethod
    def dim(cls, t):     return cls._wrap("2", t)
    @classmethod
    def green(cls, t):   return cls._wrap("32", t)
    @classmethod
    def yellow(cls, t):  return cls._wrap("33", t)
    @classmethod
    def cyan(cls, t):    return cls._wrap("36", t)
    @classmethod
    def red(cls, t):     return cls._wrap("31", t)
    @classmethod
    def grey(cls, t):    return cls._wrap("90", t)


# ── PDF helpers ───────────────────────────────────────────────────────────────

def has_text_layer(pdf_path: str) -> bool:
    """Return True if the PDF has selectable text (not purely scanned)."""
    result = subprocess.run(
        ["pdffonts", pdf_path],
        capture_output=True, text=True
    )
    # pdffonts header is 2 lines; any extra lines = fonts present = text layer
    lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
    return len(lines) > 2


def extract_text(pdf_path: str) -> str:
    """Extract text from the first page of a digital PDF."""
    result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", "1", pdf_path, "-"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def rasterize_page(pdf_path: str, dpi: int = DEFAULT_DPI) -> str:
    """Rasterize page 1 of a PDF and return the path to the JPEG."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = os.path.join(tmpdir, "page")
        subprocess.run(
            ["pdftoppm", "-jpeg", "-r", str(dpi), "-f", "1", "-l", "1", pdf_path, prefix],
            check=True, capture_output=True
        )
        matches = glob.glob(f"{prefix}-*.jpg")
        if not matches:
            raise RuntimeError("pdftoppm produced no output")
        with open(matches[0], "rb") as f:
            return base64.b64encode(f.read()).decode()


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _filename_instruction(existing_stem: str) -> str:
    return (
        f'The file is currently named "{existing_stem}". '
        "If that name already describes the recipe well, reply with that exact name unchanged. "
        "Only suggest a different name if the change would be significant "
        "(e.g. the current name is wrong, generic, or missing key details). "
        "Minor wording tweaks, reordering, or punctuation changes do not count as significant."
        "The file name should not include the recipe number or other identifiers nor should it include the brand name (Marley Spoon)."
    )


def ask_llm_text(text: str, model: str, existing_stem: str) -> str:
    """Ask the LLM for a recipe name from extracted text."""
    prompt = (
        "Below is text extracted from a recipe PDF. "
        f"{_filename_instruction(existing_stem)} "
        "Reply with ONLY the recipe title (up to 10 words). "
        "No punctuation, no explanation, nothing else.\n\n"
        f"{text[:2000]}\n\nRecipe title:"
    )
    response = requests.post(OLLAMA_URL, json={
        "model": model,
        "prompt": prompt,
        "stream": False,
    }, timeout=60)
    response.raise_for_status()
    return response.json()["response"].strip()


def ask_llm_vision(image_b64: str, model: str, existing_stem: str) -> str:
    """Ask the vision LLM for a recipe name from a page image."""
    prompt = (
        "This is a page from a recipe. The recipe is in English. "
        'Remove "Marley Spoon" from the recipe name if it is present. '
        f"{_filename_instruction(existing_stem)} "
        "Reply with ONLY the recipe title (up to 10 words). "
        "No punctuation, no explanation, nothing else."
    )
    response = requests.post(OLLAMA_URL, json={
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
    }, timeout=60)
    response.raise_for_status()
    return response.json()["response"].strip()


# ── Core logic ────────────────────────────────────────────────────────────────

def get_recipe_name(pdf_path: str, model: str, dpi: int) -> tuple[str, str]:
    """
    Return (recipe_name, method) where method is 'text' or 'vision'.
    Falls back to vision if no text layer is found.
    """
    existing_stem = slugify(Path(pdf_path).stem)

    if has_text_layer(pdf_path):
        text = extract_text(pdf_path)
        if len(text) > 20:
            return ask_llm_text(text, model, existing_stem), "text"

    # Scanned or text extraction came up empty — use vision
    image_b64 = rasterize_page(pdf_path, dpi)
    return ask_llm_vision(image_b64, model, existing_stem), "vision"


def clean_recipe_name(name: str) -> str:
    """Remove brand tokens and normalize whitespace/separators."""
    name = re.sub(r"marley[\s_-]+spoon", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[\s_-]+", " ", name).strip()
    return name


def slugify(name: str) -> str:
    name = clean_recipe_name(name)
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def validate_slug(slug: str) -> None:
    if not slug:
        raise ValueError("recipe title produced an empty filename")


def check_ollama(model: str) -> None:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        r.raise_for_status()
        names = [m["name"].split(":")[0] for m in r.json().get("models", [])]
        if model not in names:
            print(C.yellow(f"⚠️  Model '{model}' not found locally. Run: ollama pull {model}"))
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(C.red("❌  Ollama is not running. Start it with: ollama serve"))
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Rename recipe PDFs using a local vision LLM.")
    parser.add_argument("folder", help="Folder containing recipe PDFs")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"Rasterization DPI (default: {DEFAULT_DPI})")
    parser.add_argument("--apply", action="store_true", help="Actually rename files (default is dry-run)")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing file when the target name is already taken (default: skip)",
    )
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(C.red(f"❌  Not a directory: {folder}"))
        sys.exit(1)

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(C.yellow(f"No PDF files found in {folder}"))
        sys.exit(0)

    check_ollama(args.model)

    mode = C.bold(C.yellow("APPLYING")) if args.apply else C.bold(C.cyan("DRY RUN"))
    rule = C.dim("─" * 60)
    print(f"\n{rule}")
    print(f"  {mode} — {C.bold(str(len(pdfs)))} PDF(s) in {C.cyan(str(folder))}")
    print(f"  Model: {C.cyan(args.model)}  |  DPI: {args.dpi}")
    print(f"{rule}\n")

    results = []
    errors = []

    for pdf in pdfs:
        print(f"  {C.dim(pdf.name)} … ", end="", flush=True)
        try:
            name, method = get_recipe_name(str(pdf), args.model, args.dpi)
            slug = slugify(name)
            validate_slug(slug)
            new_path = folder / f"{slug}.pdf"
            tag = C.dim(f"[{method}]")

            if pdf.name == new_path.name:
                print(f"{C.grey('unchanged')}  {tag}")
                results.append((pdf.name, pdf.name, method, "unchanged"))
            elif new_path.exists() and not args.overwrite:
                print(C.red(f"ERROR — target already exists: {new_path.name}"))
                results.append((pdf.name, new_path.name, method, "skip"))
            else:
                arrow = C.dim("→")
                print(f"{arrow} {C.green(new_path.name)}  {tag}")
                results.append((pdf.name, new_path.name, method, "rename"))
                if args.apply:
                    pdf.rename(new_path)

        except Exception as e:
            print(C.red(f"ERROR — {e}"))
            errors.append((pdf.name, str(e)))

    # Summary
    renames = [r for r in results if r[3] == "rename"]
    unchanged = [r for r in results if r[3] == "unchanged"]
    skipped = [r for r in results if r[3] == "skip"]
    print(f"\n{rule}")
    rename_label = "Renamed" if args.apply else "Would rename"
    print(f"  {C.green(f'{rename_label}:'): <30} {len(renames)}")
    print(f"  {C.grey('Unchanged:'): <30} {len(unchanged)}")
    skip_label = C.red("Skipped (exists):") if skipped else C.grey("Skipped (exists):")
    print(f"  {skip_label:<30} {len(skipped)}")
    print(f"  {C.red('Errors:') if errors else C.grey('Errors:'): <30} {len(errors)}")
    if not args.apply and renames:
        print(f"\n  {C.dim('Run with --apply to rename for real.')}")
    print(f"{rule}\n")


if __name__ == "__main__":
    main()