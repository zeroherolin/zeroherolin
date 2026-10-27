#!/usr/bin/env python3
"""Render README.md and the images it shows.

Images go to build/, which the workflow publishes as the single commit of the
"output" branch; README.md (written in full here) links to them there. Every
image has a light and a dark variant, picked with <picture>.

  build/name-*.svg                the name at the top
  build/stack-*.svg               languages and tools
  build/section-<name>-*.svg      section titles
  build/projects/<repo>-*.svg     one card per project; stars, forks and language from the API
  build/forks/<repo>-*.svg        one small card per fork with its sync status, plus column headings
  build/languages-*.svg           language share, each public non-fork repository weighted equally

README.md ends with a comment recording the repositories it was generated from;
watch.py compares it with the account to see when to render again.
Uses only the standard library; GITHUB_TOKEN is optional but raises the rate limit.
"""

import http.client
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

USER = os.environ.get("GITHUB_REPOSITORY_OWNER", "zeroherolin")
NAME = "Linz"
EMAIL = "zeroherolin@outlook.com"
ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "assets" / "icons"
BUILD = ROOT / "build"
README = ROOT / "README.md"
IMAGES = f"https://raw.githubusercontent.com/{USER}/{USER}/output/"  # where build/ is published
TZ = timezone(timedelta(hours=8))  # dates on the page are China Standard Time

WIDTH = 840  # canvas of full-width images, about the width of a profile README
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"

# Projects in shelf order: (repo, area, description).
PROJECTS = [
    ("sar-dsl", "Compiler",
     "MLIR compiler for SAR imaging: Python in, native CPU code or Vitis HLS C++ out."),
    ("zl_bench", "Benchmark",
     "Operator-level A/B benchmarks of FlagTree compiler changes on FlagGems."),
    ("pytorch-sar", "SAR",
     "ωKA, CSA and RDA SAR imaging algorithms in PyTorch, with the math for every step."),
    ("uart2axi", "FPGA",
     "AXI debugging over plain UART, a vendor-neutral jtag2axi alternative in Verilog."),
    ("xdma-dma-sg", "FPGA",
     "Shell scripts that drive FPGA DMA scatter-gather from the host over PCIe XDMA."),
    ("dma-sg-cxx-project", "FPGA",
     "C++ host library that builds DMA-SG descriptor chains and moves data over XDMA."),
    ("brushgraft", "App",
     "Browser image editor that changes only what you mark and keeps every version."),
    ("promptbrush", "CLI",
     "Single-file CLI and Python library for OpenAI-compatible image APIs."),
    ("shellbot-harness", "Agent",
     "Makes a WeChat bot on ShellBot act like a real group member, powered by any LLM."),
    ("linspace", "Web",
     "Self-hosted HTTPS toolbox: text channels, HTML page hosting and dev-tool setup."),
    ("intelligent-computing-system", "Course",
     "Labs, exercise answers and slides for the Intelligent Computing Systems course."),
]

# Forks by category. Software is grouped by topic, running from compilers through
# kernels and inference to hardware and agents; each category is a column, and
# every COLUMNS of them make one block of the grid. Categories in ROW_MAJOR come
# after the blocks: same heading, but their forks fill all columns row by row.
# They are Learning (tutorials, books and courses), then "Uncategorized", which
# collects forks not listed here. Forks missing on GitHub are skipped.
FORKS = [
    ("LLVM / MLIR", ["llvm-project", "Polygeist", "mlir-emitc", "pymlir"]),
    ("ML compilers", ["tvm", "tvm-tirx", "torch-mlir", "iree", "Halide"]),
    ("Kernel DSLs", ["triton", "tilelang", "FlagTree"]),
    ("Kernel libraries", ["cutlass", "DeepGEMM", "FlashMLA", "FlagGems", "FlagGems-vllm"]),
    ("LLM inference", ["vllm", "sglang", "DeepInfer"]),
    ("Hardware compilers", ["circt", "allo", "ScaleHLS-HIDA", "pylog"]),
    ("FPGA & radar", ["dma_ip_drivers", "gtkwave", "PLFM_RADAR"]),
    ("AI agents", ["codex", "wechat-cli", "catbus", "godot-ai"]),
    ("Learning", ["MLIR-Tutorial", "hands-on-practical-mlir-tutorial", "AdvancedCompiler", "AISystem",
                  "ai-infra-book", "ai-agent-book"]),
]
ROW_MAJOR = ("Learning", "Uncategorized")

# Rows under the name, most relevant first. A "#rrggbb" glyph is a swatch in
# that color (GitHub's language colors; Triton has none, so it borrows a purple);
# anything else names a single-color icon in assets/icons/.
STACK = [
    ("Languages", [("Python", "#3572A5"), ("C / C++", "#f34b7d"), ("Triton", "#6E40C9"),
                   ("Verilog", "#b2b7f8"), ("TypeScript", "#3178c6")]),
    ("Tools", [("LLVM / MLIR", "llvm"), ("PyTorch", "pytorch"), ("CUDA", "nvidia"),
               ("Vitis HLS", "vitis-hls"), ("CMake", "cmake"), ("Docker", "docker"), ("Linux", "linux")]),
]

THEMES = {
    "light": {"fg": "#1f2328", "muted": "#59636e", "faint": "#8c959f", "line": "#d1d9e0",
              "page": "#ffffff", "card": ("#ffffff", 1)},
    "dark": {"fg": "#f0f6fc", "muted": "#9198a1", "faint": "#656c76", "line": "#3d444d",
             "page": "#0d1117", "card": ("#000000", .36)},
}

# github-linguist colors; anything missing falls back to gray.
COLORS = {
    "Assembly": "#6E4C13", "C": "#555555", "C#": "#7355dd", "C++": "#f34b7d",
    "CMake": "#DA3434", "CSS": "#663399", "Cuda": "#3A4E3A",
    "Dockerfile": "#384d54", "GDScript": "#355570", "Go": "#00ADD8",
    "HTML": "#e34c26", "Java": "#b07219", "JavaScript": "#f1e05a",
    "Jupyter Notebook": "#DA5B0B", "LLVM": "#185619", "Lua": "#000080",
    "MATLAB": "#e16737", "MLIR": "#5EC8DB", "Makefile": "#427819",
    "OpenCL": "#ed2e2d", "Python": "#3572A5", "Rust": "#dea584",
    "Shell": "#89e051", "Svelte": "#ff3e00", "SystemVerilog": "#DAE1C2",
    "Tcl": "#e4cc98", "TeX": "#3D6117", "TypeScript": "#3178c6",
    "VHDL": "#adb2cb", "Verilog": "#b2b7f8", "Vue": "#41b883",
}
OTHER = "#8c959f"
TOP_LANGUAGES = 7

# Helvetica advance widths (1/1000 em) for printable ASCII, to wrap sans text;
# other characters count as a digit. Platform fonts differ a little, so
# wrapping keeps SLACK in reserve. Monospace text is taken as 0.6 em per glyph.
_ADVANCE = dict(zip(
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
     556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
     1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
     667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
     333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
     556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]))
SLACK = 1.1


def sans_width(text, size):
    return sum(_ADVANCE.get(c, 556) for c in text) * size / 1000


def mono_width(text, size, spacing=0):
    return len(text) * (0.6 * size + spacing)


def wrap(text, size, width, max_lines):
    """Up to max_lines of text that fit width; a word too wide for a line, or text left over,
    is cut short with an ellipsis."""
    def fits(line):
        return sans_width(line, size) * SLACK <= width

    def shorten(line):
        while len(line) > 1 and not fits(line + "…"):
            line = line[:-1].rstrip()
        return line + "…"

    lines = []
    for word in text.split():
        if lines and fits(f"{lines[-1]} {word}"):
            lines[-1] += f" {word}"
        else:
            lines.append(word if fits(word) else shorten(word))
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [shorten(lines[max_lines - 1])]
    return lines


def fit(text, size, width, min_size):
    """Shrink a monospace label down to min_size to fit width, then cut it short."""
    while size > min_size and mono_width(text, size) > width:
        size -= 0.5
    while len(text) > 1 and mono_width(text, size) > width:
        text = text[:-2] + "…"
    return text, size


# -- SVG building blocks -------------------------------------------------------

def svg(width, height, title, body, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title, {chr(34): "&quot;"})}">\n'
            f'<title>{escape(title)}</title>\n'
            f'<defs><style>.m{{font-family:{MONO}}}.s{{font-family:{SANS}}}</style>{defs}</defs>\n'
            f'{body}\n</svg>\n')


def text(x, y, content, size, fill, cls="m", anchor=None, weight=None, spacing=None):
    attrs = f'class="{cls}" x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}"'
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if spacing:
        attrs += f' letter-spacing="{spacing}"'
    return f"<text {attrs}>{escape(content)}</text>"


def icon(name, x, y, size, fill):
    """Inline assets/icons/<name>.svg (a square, single-color icon) at size px."""
    source = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    box = float(re.search(r'viewBox="0 0 ([\d.]+) [\d.]+"', source).group(1))
    paths = "".join(f'<path d="{d}"/>' for d in re.findall(r'<path[^>]*\sd="([^"]+)"', source))
    return (f'<g transform="translate({x:.1f} {y:.1f}) scale({size / box:.4f})" '
            f'fill="{fill}">{paths}</g>')


def swatch(x, y, size, color, t):
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" rx="{size / 5:g}" '
            f'fill="{color}" stroke="{t["fg"]}" stroke-opacity=".12"/>')


def rule(x0, x1, y, t):
    return f'<path d="M {x0:.1f} {y} H {x1:.1f}" stroke="{t["line"]}"/>'


# -- header --------------------------------------------------------------------

def render_name(t):
    return svg(WIDTH, 58, NAME, text(-2, 46, NAME, 44, t["fg"], cls="s", weight="700", spacing=-1))


def render_stack(t):
    row_h, label_w, gap = 32, 112, 24
    body = [rule(0, WIDTH, 0.5, t)]
    for r, (label, items) in enumerate(STACK):
        base = 21 + r * row_h
        body.append(text(0, base, label.upper(), 10, t["faint"], weight="700", spacing=1.5))
        x = label_w
        for name, glyph in items:
            if glyph.startswith("#"):
                body.append(swatch(x, base - 9, 9, glyph, t))
            else:
                body.append(icon(glyph, x - 1, base - 10.5, 12, t["muted"]))
            body.append(text(x + 17, base, name, 12, t["fg"]))
            x += 17 + mono_width(name, 12) + gap
        if x - gap > WIDTH:
            sys.exit(f"stack row {label!r} is {x - gap:.0f}px wide, over {WIDTH}")
        body.append(rule(0, WIDTH, (r + 1) * row_h + 0.5, t))
    return svg(WIDTH, len(STACK) * row_h + 1, "Languages and tools", "\n".join(body))


# -- section titles ------------------------------------------------------------

def render_section(title, count, hint, t, hint_icon=None):
    height, base = 56, 40
    caps = title.upper()
    x = mono_width(caps, 13, 2.5)
    body = [text(0, base, caps, 13, t["fg"], weight="700", spacing=2.5)]
    if count is not None:
        body.append(text(x + 8, base, str(count), 12, t["muted"]))
        x += 8 + mono_width(str(count), 12)
    end = WIDTH
    if hint:
        body.append(text(WIDTH, base, hint, 10.5, t["muted"], anchor="end", spacing=1))
        end -= mono_width(hint, 10.5, 1)
        if hint_icon:
            end -= 15
            body.append(icon(hint_icon, end, base - 9, 10, t["muted"]))
        end -= 14
    body.append(rule(x + 14, end, base - 4.5, t))
    return svg(WIDTH, height, title, "\n".join(body))


# -- project cards -------------------------------------------------------------

CARD_W, CARD_H, CARD_GAP = 236, 141, 12
SHELF_ROWS = 2  # cards fill the shelf column by column, top to bottom


def render_project(name, area, desc, repo, gap_below, t):
    """Name and description; under a rule, language, stars and forks as on
    GitHub's pinned repositories, with the area aligned to the right."""
    lang = repo.get("language")
    color = COLORS.get(lang, OTHER) if lang else OTHER
    x1, y1 = CARD_W - 0.5, CARD_H - 0.5
    left, right = 18, CARD_W - 18
    # A faint wash of the language color fades out halfway down the card.
    defs = (f'<linearGradient id="wash" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{color}" stop-opacity=".1"/>'
            f'<stop offset=".55" stop-color="{color}" stop-opacity="0"/></linearGradient>')
    frame = f'x="0.5" y="0.5" width="{x1 - 0.5}" height="{y1 - 0.5}" rx="8"'
    fill, opacity = t["card"]  # a veil, so dark cards sit a shade below the tray in every dark theme
    body = [f'<rect {frame} fill="{fill}" fill-opacity="{opacity}"/>',
            f'<rect {frame} fill="url(#wash)" stroke="{t["line"]}"/>']
    label, size = fit(name, 15, right - left, 11)
    body.append(text(left, 32, label, size, t["fg"], weight="600"))
    for i, line in enumerate(wrap(desc, 12, right - left, 3)):
        body.append(text(left, 54 + i * 17, line, 12, t["muted"], cls="s"))
    body.append(rule(left, right, 102.5, t))

    base, x, gap = 122, left, 10
    if lang:
        body.append(swatch(x, base - 8, 8, color, t))
        body.append(text(x + 14, base, lang, 11, t["muted"]))
        x += 14 + mono_width(lang, 11) + gap
    for key, glyph in (("stargazers_count", "star"), ("forks_count", "repo-forked")):
        count = repo.get(key, 0)
        if count:
            body.append(icon(glyph, x, base - 10, 12, t["faint"]))
            body.append(text(x + 16, base, str(count), 11, t["muted"]))
            x += 16 + mono_width(str(count), 11) + gap
    caps = area.upper()
    if caps:
        if x - gap + 12 > right - mono_width(caps, 10, 1.2):
            warn(f"{name}: language, stars and forks run into the area label")
        body.append(text(right, base, caps, 10, t["muted"], anchor="end", spacing=1.2))
    height = CARD_H + (CARD_GAP if gap_below else 0)
    return svg(CARD_W + CARD_GAP, height, f"{name}: {desc}" if desc else name, "\n".join(body), defs)


# -- fork cards ------------------------------------------------------------------

COLUMNS = 4                            # fork columns per block of the grid
TILE_W, TILE_H = WIDTH // COLUMNS, 36  # includes a 12px gap on the right
HEADING_H = (26, 40)                   # heading rows: first block, later blocks (spaced apart)


def compact(n):
    """1234 -> 1.2k and 1234567 -> 1.2m, the way GitHub abbreviates counts."""
    for limit, unit in ((1_000_000, "m"), (1000, "k")):
        if n >= limit * 0.9995:
            v = n / limit
            return f"{v:.1f}{unit}" if v < 9.95 else f"{round(v)}{unit}"
    return str(n)


def render_fork(name, behind, t):
    """Fork card; on the right a check if the default branch is level with
    upstream, the number of commits it is behind, or an x if that is unknown."""
    x1 = TILE_W - 12.5
    right = x1 - 9
    body = [f'<rect x="0.5" y="5.5" width="{x1 - 0.5}" height="25" rx="4" fill="none" stroke="{t["faint"]}"/>']
    if behind == 0:
        status_w, title = 12, f"{name}: up to date with upstream"
        body.append(icon("check", right - 12, 12, 12, t["muted"]))
    elif behind:
        label = compact(behind)
        status_w, title = mono_width(label, 11) + 12, f"{name}: {behind} commits behind upstream"
        body.append(icon("arrow-down", right - status_w, 13, 10, t["faint"]))
        body.append(text(right, 22.5, label, 11, t["muted"], anchor="end"))
    else:
        status_w, title = 12, f"{name}: sync status unavailable"
        body.append(icon("x", right - 12, 12, 12, t["muted"]))
    name_label, size = fit(name, 12, right - status_w - 10 - 12, 12)
    body.append(text(12, 22.5, name_label, size, t["fg"]))
    return svg(TILE_W, TILE_H, title, "\n".join(body))


def render_fork_heading(title, count, height, t):
    right, base = TILE_W - 12, height - 15
    body = [text(0, base, title.upper(), 11, t["fg"], weight="700", spacing=1),
            text(right, base, str(count), 11, t["faint"], anchor="end"),
            rule(0, right, base + 8.5, t)]
    return svg(TILE_W, height, title, "\n".join(body))


# -- languages -----------------------------------------------------------------

def render_languages(shares, t):
    cols, gap = 4, 3
    rows = math.ceil(len(shares) / cols)
    col_w = WIDTH / cols
    height = 40 + (rows - 1) * 24 + 6
    body, x = [], 0.0
    usable = WIDTH - gap * (len(shares) - 1)
    for lang, share in shares:
        w = share * usable
        body.append(f'<rect x="{x:.2f}" y="4" width="{w:.2f}" height="10" rx="2" '
                    f'fill="{COLORS.get(lang, OTHER)}"/>')
        x += w + gap
    for i, (lang, share) in enumerate(shares):
        cx, y = (i % cols) * col_w, 40 + (i // cols) * 24
        body.append(swatch(cx, y - 9, 10, COLORS.get(lang, OTHER), t))
        body.append(text(cx + 18, y, lang, 12, t["fg"]))
        body.append(text(cx + col_w - 28, y, f"{share * 100:.1f}%", 12, t["muted"], anchor="end"))
    return svg(WIDTH, height, "Languages", "\n".join(body))


# -- README sections -----------------------------------------------------------

def attr(value):
    return escape(value, {'"': "&quot;"})


def picture(path, alt, width=None, tooltip=False):
    """<picture> for build/<path>-{light,dark}.svg as published on the output branch;
    with tooltip, the alt text also shows on hover."""
    extra = (f' width="{width}"' if width else "") + (f' title="{attr(alt)}"' if tooltip else "")
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{IMAGES}{path}-dark.svg">'
            f'<img src="{IMAGES}{path}-light.svg"{extra} align="top" alt="{attr(alt)}"></picture>')


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def shelf_html(projects):
    # Inside <pre> whitespace shows: each shelf row is one line, and tags only
    # break lines inside themselves.
    rows = ["".join(f'<a\nhref="https://github.com/{USER}/{name}">'
                    f'{picture(f"projects/{name}", f"{name}: {desc}" if desc else name, CARD_W + CARD_GAP, tooltip=True)}</a>'
                    for name, _, desc in projects[row::SHELF_ROWS])
            for row in range(SHELF_ROWS)]
    return "<pre>" + "\n".join(rows) + "</pre>"


def grid_blocks(columns):
    """The fork grid top to bottom, as (row_major, categories): column blocks of
    up to COLUMNS categories side by side, then one block per ROW_MAJOR category."""
    side = [c for c in columns if c[0] not in ROW_MAJOR]
    wide = sorted((c for c in columns if c[0] in ROW_MAJOR), key=lambda c: ROW_MAJOR.index(c[0]))
    return [(False, side[i:i + COLUMNS]) for i in range(0, len(side), COLUMNS)] + [(True, [c]) for c in wide]


def grid_html(blocks, upstreams):
    width = f"{100 / COLUMNS:g}%"
    # Fills empty cells, so every row spans COLUMNS tiles; 1px tall, so it never sets a row's height.
    blank = f'<picture><img src="{IMAGES}forks/blank.svg" width="{width}" align="top" alt=""></picture>'

    def tile(name):
        upstream = upstreams.get(name)
        alt = f"{name}, a fork of {upstream}" if upstream else name
        return f'<a href="https://github.com/{USER}/{name}">{picture(f"forks/{name}", alt, width, tooltip=True)}</a>'

    tiles = []
    for row_major, block in blocks:
        if row_major:
            (title, repos), = block
            tiles += [picture(f"forks/_{slug(title)}", title, width)] + [blank] * (COLUMNS - 1)
            for i in range(0, len(repos), COLUMNS):
                row = repos[i:i + COLUMNS]
                tiles += [tile(name) for name in row] + [blank] * (COLUMNS - len(row))
            continue
        pad = [blank] * (COLUMNS - len(block))
        tiles += [picture(f"forks/_{slug(title)}", title, width) for title, _ in block] + pad
        for row in range(max(len(repos) for _, repos in block)):
            tiles += [tile(repos[row]) if row < len(repos) else blank for _, repos in block] + pad
    # Tiles must touch: break lines after a tag name rather than between tags.
    return "<p>" + "".join(re.sub(r"^<(\w+)", "<\\1\n", tile) for tile in tiles) + "</p>"


def readme_md(projects, columns, upstreams, shares, state):
    stack = ". ".join(f"{label}: {', '.join(name for name, _ in items)}" for label, items in STACK)
    local, domain = EMAIL.split("@")
    blocks = [
        "<!-- Generated by scripts/render.py; edit that instead. -->",
        picture("name", NAME, "100%"),
        # <wbr> keeps GitHub from autolinking the address out of <samp>; it is stripped on render.
        f'<a href="mailto:{EMAIL}"><samp>{local}<wbr>@{domain}</samp></a>',
        picture("stack", stack, "100%"),
        picture("section-projects", "Projects", "100%"),
        shelf_html(projects),
        picture("section-forks", "Forks", "100%"),
        grid_html(grid_blocks(columns), upstreams),
        picture("section-languages", "Languages", "100%"),
        picture("languages", "Languages, each repository weighted equally: " + ", ".join(lang for lang, _ in shares), "100%"),
        f"<!-- repos: {' '.join(state)} -->",  # for watch.py; see repo_state()
    ]
    return "\n\n".join(blocks) + "\n"


# -- GitHub API ----------------------------------------------------------------

# Everything that can go wrong reading from the GitHub API, short of a bug here.
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException,
                  json.JSONDecodeError)


def transient(err):
    """Whether a failed GitHub API request may succeed later: network trouble, garbled replies,
    5xx, and rate limits (a 429, or a 403 that says so), but not 401, 404 and the like."""
    if isinstance(err, urllib.error.HTTPError):
        limited = err.headers.get("Retry-After") or err.headers.get("X-RateLimit-Remaining") == "0"
        return err.code >= 500 or err.code == 429 or (err.code == 403 and bool(limited))
    return True


def get(url, attempts=4):
    """GET a GitHub API URL as JSON. Transient failures are retried with backoff (up to a
    minute if Retry-After asks); anything else, and the last failure, is raised."""
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-profile",
    })
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for attempt in range(attempts):
        delay = 2 ** attempt
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except NETWORK_ERRORS as err:
            if not transient(err) or attempt == attempts - 1:
                raise
            retry_after = err.headers.get("Retry-After", "") if isinstance(err, urllib.error.HTTPError) else ""
            if retry_after.isdigit():
                delay = min(int(retry_after), 60)
        time.sleep(delay)


def owned_repos():
    repos, page = [], 1
    while True:
        batch = get(f"https://api.github.com/users/{USER}/repos?type=owner&per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    return repos


def repo_state(owned):
    """What the page depends on in the account besides counts, as one token per public
    repository except the profile's own: "name:fork", "name:source", and "name:source:nolang"
    until GitHub has detected a language (a new repository gets one a little after its first
    push). README.md records it, last of all a render's changes, so a render that failed
    halfway leaves a record that no longer matches and watch.py runs it again."""
    return sorted(
        f"{r['name']}:" + ("fork" if r["fork"] else "source" + ("" if r.get("language") else ":nolang"))
        for r in owned if r["name"].lower() != USER.lower())


def warn(message):
    """To stderr; inside GitHub Actions, also an annotation on the run's summary page."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::{message}")
    else:
        print(f"warning: {message}", file=sys.stderr)


def shelf_projects(repos):
    """PROJECTS limited to the given original repositories, then a card for each one it
    misses, newest first, with no description or area until it is listed."""
    listed = {name for name, _, _ in PROJECTS}
    for name in sorted(listed - set(repos), key=str.lower):
        warn(f"{name} is in PROJECTS but is not a public repository of {USER}; skipped")
    unlisted = sorted(set(repos) - listed, key=lambda n: repos[n].get("created_at") or "", reverse=True)
    if unlisted:
        warn(f"not in PROJECTS, shown last without an area: {', '.join(unlisted)}")
    return ([p for p in PROJECTS if p[0] in repos] +
            [(name, "", "") for name in unlisted])


def fork_columns(forks):
    """FORKS limited to the given fork names, plus a column for the ones it misses."""
    listed = {name for _, names in FORKS for name in names}
    for name in sorted(listed - forks, key=str.lower):
        warn(f"{name} is in FORKS but is not a fork of {USER}; skipped")
    columns = [(title, [n for n in names if n in forks]) for title, names in FORKS]
    columns = [(title, names) for title, names in columns if names]
    unlisted = sorted(forks - listed, key=str.lower)
    if unlisted:
        warn(f"not in FORKS, shown as Uncategorized: {', '.join(unlisted)}")
        columns.append(("Uncategorized", unlisted))
    return columns


def fork_status(name):
    """(upstream "owner/repo", commits the fork's default branch lacks from the
    upstream's); either is None when it could not be fetched."""
    upstream = None
    try:
        repo = get(f"https://api.github.com/repos/{USER}/{name}")
        parent = repo["parent"]
        upstream = parent["full_name"]
        head = f"{parent['owner']['login']}:{parent['default_branch']}"
        cmp = get(f"https://api.github.com/repos/{USER}/{name}/compare/"
                  f"{urllib.parse.quote(repo['default_branch'], safe='')}...{urllib.parse.quote(head, safe=':')}")
        return upstream, cmp["ahead_by"]
    except (*NETWORK_ERRORS, KeyError, TypeError) as err:  # a fork that cannot be read must not stop the page
        warn(f"no sync status for {name}: {err!r}")
        return upstream, None


def repo_languages(repo):
    """Bytes per language of one repository; none if that fails, so a repository deleted or
    blocked a moment ago cannot stop the page."""
    try:
        return get(repo["languages_url"])
    except NETWORK_ERRORS as err:
        warn(f"no language data for {repo['name']}: {err!r}")
        return {}


def language_shares(repos):
    """(shares, repositories counted). Each repository with code counts once, split across
    its languages by code size, so one large repository cannot outweigh all the others."""
    totals, counted = {}, 0
    for repo in repos:
        sizes = repo_languages(repo)
        size = sum(sizes.values())
        if not size:
            continue
        counted += 1
        for lang, n in sizes.items():
            totals[lang] = totals.get(lang, 0) + n / size
    if not counted:
        return [], 0
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    shares = [(lang, weight / counted) for lang, weight in ranked[:TOP_LANGUAGES]]
    rest = sum(weight for _, weight in ranked[TOP_LANGUAGES:])
    if rest:
        shares.append(("Other", rest / counted))
    return shares, counted


def main():
    owned = owned_repos()
    repos = {r["name"]: r for r in owned if not r["fork"] and r["name"].lower() != USER.lower()}
    if not repos:
        sys.exit(f"no public non-fork repositories found for {USER}")
    shares, counted = language_shares(repos.values())
    projects = shelf_projects(repos)
    columns = fork_columns({r["name"] for r in owned if r["fork"]})
    fork_names = [name for _, names in columns for name in names]
    with ThreadPoolExecutor(8) as pool:
        status = dict(zip(fork_names, pool.map(fork_status, fork_names)))
    upstreams = {name: upstream for name, (upstream, _) in status.items()}
    behind = {name: count for name, (_, count) in status.items()}
    today = datetime.now(TZ).strftime("%Y-%m-%d")

    outputs = {"forks/blank.svg": svg(TILE_W, 1, "", "")}
    for theme, t in THEMES.items():
        outputs[f"name-{theme}.svg"] = render_name(t)
        outputs[f"stack-{theme}.svg"] = render_stack(t)
        outputs[f"section-projects-{theme}.svg"] = render_section("Projects", len(projects), "SCROLL →", t)
        outputs[f"section-forks-{theme}.svg"] = render_section(
            "Forks", len(fork_names), f"COMMITS BEHIND UPSTREAM · {today}", t, hint_icon="arrow-down")
        outputs[f"section-languages-{theme}.svg"] = render_section(
            "Languages", None, f"PER REPOSITORY · {counted} REPOS", t)
        outputs[f"languages-{theme}.svg"] = render_languages(shares, t)
        for i, (name, area, desc) in enumerate(projects):
            gap_below = i % SHELF_ROWS < SHELF_ROWS - 1
            outputs[f"projects/{name}-{theme}.svg"] = render_project(
                name, area, desc, repos[name], gap_below, t)
        for b, (_, block) in enumerate(grid_blocks(columns)):
            for title, forks in block:
                outputs[f"forks/_{slug(title)}-{theme}.svg"] = render_fork_heading(
                    title, len(forks), HEADING_H[b > 0], t)
                for name in forks:
                    outputs[f"forks/{name}-{theme}.svg"] = render_fork(name, behind[name], t)

    # Start build/ afresh so removed projects and forks disappear.
    shutil.rmtree(BUILD, ignore_errors=True)
    for rel, content in outputs.items():
        path = BUILD / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    README.write_text(readme_md(projects, columns, upstreams, shares, repo_state(owned)), encoding="utf-8")
    known = [n for n in behind.values() if n is not None]
    print(f"rendered {len(outputs)} images into {BUILD.name}/ and wrote {README.name}; "
          f"forks up to date: {known.count(0)}, behind: {len(known) - known.count(0)}, unknown: {len(behind) - len(known)}")


if __name__ == "__main__":
    main()
