# Recipe Renamer

Rename recipe PDFs to clean, slugified filenames using a local [Ollama](https://ollama.com) vision model. The script reads each PDF, extracts or OCRs the recipe title, and proposes a filename like `sesame-ginger-salmon.pdf`.

Runs in **dry-run mode by default** so you can review changes before applying them.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Options](#options)
  - [Examples](#examples)
- [Example output](#example-output)
- [License](#license)

## Features

- Uses text extraction for digital PDFs, vision LLM for scanned pages
- Slugifies all output filenames (`Chicken Parm` → `chicken-parm.pdf`)
- Strips **Marley Spoon** from names (case-insensitive)
- Skips renames when the current filename is already correct
- Only renames when the change would be significant (wrong, generic, or missing details)
- Refuses to overwrite existing files unless `--overwrite` is passed
- Reports collisions, empty titles, and other errors in red

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) running with a vision-capable model (default: `llava`)
- [Poppler](https://poppler.freedesktop.org/) CLI tools: `pdftotext`, `pdftoppm`, `pdffonts`

On macOS with Homebrew:

```bash
brew install poppler
ollama pull llava
```

## Installation

```bash
git clone https://github.com/dbryant4/recipe-renamer.git
cd recipe-renamer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Edit `OLLAMA_URL` at the top of `renamer.py` if your Ollama instance is not at the default address:

```python
OLLAMA_URL = "http://localhost:11434/api/generate"
```

## Usage

Preview renames (dry run):

```bash
python renamer.py ./recipes
```

Apply renames:

```bash
python renamer.py ./recipes --apply
```

### Options

| Option | Description |
|--------|-------------|
| `folder` | Directory containing `*.pdf` files |
| `--model MODEL` | Ollama model to use (default: `llava`) |
| `--dpi DPI` | Rasterization DPI for scanned PDFs (default: `300`) |
| `--apply` | Actually rename files; without this flag, only prints what would happen |
| `--overwrite` | Replace an existing file when the target name is already taken |

### Examples

```bash
# Use a different model
python renamer.py ./recipes --model minicpm-v

# Apply renames, overwriting collisions
python renamer.py ./recipes --apply --overwrite

# Higher DPI for difficult scans
python renamer.py ./recipes --dpi 200
```

## Example output

```
────────────────────────────────────────────────────────────
  DRY RUN — 3 PDF(s) in ./recipes
  Model: llava  |  DPI: 300
────────────────────────────────────────────────────────────

  scan001.pdf … → sesame-ginger-salmon.pdf  [vision]
  chicken-parm.pdf … unchanged  [text]
  Marley Spoon - Tacos.pdf … → beef-tacos.pdf  [vision]

────────────────────────────────────────────────────────────
  Would rename:                  2
  Unchanged:                     1
  Skipped (exists):              0
  Errors:                        0

  Run with --apply to rename for real.
────────────────────────────────────────────────────────────
```

## License

MIT
