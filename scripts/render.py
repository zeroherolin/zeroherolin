#!/usr/bin/env python3
"""Render the images in README.md and its generated sections.

Every image has a light and a dark variant; README.md picks one with <picture>.

  assets/name-*.svg                the name at the top
  assets/stack-*.svg               languages and tooling
  assets/section-<name>-*.svg      numbered section titles
  assets/projects/<repo>-*.svg     one card per project; stars, forks and language from the API
  assets/forks/<repo>-*.svg        one small card per fork, plus column headings
  assets/languages-*.svg           language share across public non-fork repositories

The project shelf and the fork grid in README.md, between the BEGIN/END
markers, are rewritten from PROJECTS and FORKS below.
Uses only the standard library; GITHUB_TOKEN is optional but raises the rate limit.
"""

import json
import math
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

USER = os.environ.get("GITHUB_REPOSITORY_OWNER", "zeroherolin")
NAME = "Linz"
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICONS = ASSETS / "icons"
README = ROOT / "README.md"

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

# Forks by column; every COLUMNS columns make one block of the grid. Software is
# grouped by topic, running from compilers through kernels and inference to
# hardware; tutorials, books and courses share one column. Forks missing on
# GitHub are skipped, and forks not listed here land in a last "Uncategorized" column.
FORKS = [
    ("LLVM / MLIR", ["llvm-project", "Polygeist", "mlir-emitc", "pymlir"]),
    ("ML compilers", ["tvm", "tvm-tirx", "torch-mlir", "iree", "Halide"]),
    ("Kernel DSLs", ["triton", "tilelang", "FlagTree"]),
    ("Kernel libraries", ["cutlass", "DeepGEMM", "FlashMLA", "FlagGems", "FlagGems-vllm"]),
    ("LLM inference", ["vllm", "sglang", "DeepInfer"]),
    ("Hardware compilers", ["circt", "allo", "ScaleHLS-HIDA", "pylog"]),
    ("FPGA & radar", ["dma_ip_drivers", "gtkwave", "PLFM_RADAR"]),
    ("Learning", ["MLIR-Tutorial", "hands-on-practical-mlir-tutorial", "AdvancedCompiler", "AISystem",
                  "ai-infra-book", "ai-agent-book"]),
    ("AI agents", ["wechat-cli", "catbus", "Godot-MCP-Native"]),
]

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
              "page": "#ffffff"},
    "dark": {"fg": "#f0f6fc", "muted": "#9198a1", "faint": "#656c76", "line": "#3d444d",
             "page": "#0d1117"},
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
    lines = []
    for word in text.split():
        if lines and sans_width(f"{lines[-1]} {word}", size) * SLACK <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while sans_width(lines[-1] + "…", size) * SLACK > width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def fit(text, size, width, min_size):
    """Shrink a monospace label down to min_size to fit width, then cut it short."""
    while size > min_size and mono_width(text, size) > width:
        size -= 0.5
    while mono_width(text, size) > width:
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
    return svg(WIDTH, len(STACK) * row_h + 1, "Languages and tooling", "\n".join(body))


# -- section titles ------------------------------------------------------------

def render_section(index, title, count, hint, t):
    height, base = 56, 40
    caps = title.upper()
    x = 30 + mono_width(caps, 13, 2.5)
    body = [text(0, base, index, 12, t["faint"]),
            text(30, base, caps, 13, t["fg"], weight="700", spacing=2.5)]
    if count is not None:
        body.append(text(x + 8, base, f"{count:02d}", 12, t["muted"]))
        x += 8 + mono_width(f"{count:02d}", 12)
    end = WIDTH
    if hint:
        body.append(text(WIDTH, base, hint, 10.5, t["muted"], anchor="end", spacing=1))
        end -= mono_width(hint, 10.5, 1) + 14
    body.append(rule(x + 14, end, base - 4.5, t))
    return svg(WIDTH, height, title, "\n".join(body))


# -- project cards -------------------------------------------------------------

CARD_W, CARD_H, CARD_GAP = 236, 166, 12
SHELF_ROWS = 2  # PROJECTS fill the shelf column by column, top to bottom


def render_project(index, name, area, desc, repo, gap_below, t):
    lang = repo.get("language")
    color = COLORS.get(lang, OTHER) if lang else OTHER
    x1, y1 = CARD_W - 0.5, CARD_H - 0.5
    left, right = 18, CARD_W - 18
    # A faint wash of the language color fades out halfway down the card.
    defs = (f'<linearGradient id="wash" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{color}" stop-opacity=".1"/>'
            f'<stop offset=".55" stop-color="{color}" stop-opacity="0"/></linearGradient>')
    frame = f'x="0.5" y="0.5" width="{x1 - 0.5}" height="{y1 - 0.5}" rx="8"'
    body = [f'<rect {frame} fill="{t["page"]}"/>', f'<rect {frame} fill="url(#wash)" stroke="{t["line"]}"/>',
            text(left, 31, area.upper(), 10, t["muted"], spacing=1.5),
            text(right, 31, f"{index:02d}", 10, t["faint"], anchor="end")]
    label, size = fit(name, 15, right - left, 11)
    body.append(text(left, 57, label, size, t["fg"], weight="600"))
    for i, line in enumerate(wrap(desc, 12, right - left, 3)):
        body.append(text(left, 79 + i * 17, line, 12, t["muted"], cls="s"))
    body.append(rule(left, right, 127.5, t))

    base, x = 147, left
    if lang:
        body.append(swatch(x, base - 8, 8, color, t))
        body.append(text(x + 14, base, lang, 11, t["muted"]))
        x += 14 + mono_width(lang, 11) + 14
    for key, glyph in (("stargazers_count", "star"), ("forks_count", "repo-forked")):
        count = repo.get(key, 0)
        if count:
            body.append(icon(glyph, x, base - 10, 12, t["faint"]))
            body.append(text(x + 16, base, str(count), 11, t["muted"]))
            x += 16 + mono_width(str(count), 11) + 14
    height = CARD_H + (CARD_GAP if gap_below else 0)
    return svg(CARD_W + CARD_GAP, height, f"{name}: {desc}", "\n".join(body), defs)


# -- fork cards ------------------------------------------------------------------

COLUMNS = 4                            # fork columns per block of the grid
TILE_W, TILE_H = WIDTH // COLUMNS, 36  # includes a 12px gap on the right
HEADING_H = (26, 48)                   # heading rows: first block, later blocks (spaced apart)


def render_fork(name, t):
    x1 = TILE_W - 12.5
    label, size = fit(name, 12, x1 - 24, 12)
    body = [f'<rect x="0.5" y="5.5" width="{x1 - 0.5}" height="25" rx="4" fill="none" stroke="{t["faint"]}"/>',
            text(12, 22.5, label, size, t["fg"])]
    return svg(TILE_W, TILE_H, name, "\n".join(body))


def render_fork_heading(title, count, height, t):
    right, base = TILE_W - 12, height - 15
    body = [text(0, base, title.upper(), 11, t["fg"], weight="700", spacing=1),
            text(right, base, f"{count:02d}", 11, t["faint"], anchor="end"),
            rule(0, right, base + 8.5, t)]
    return svg(TILE_W, height, title, "\n".join(body))


# -- languages -----------------------------------------------------------------

def render_languages(shares, repo_count, t):
    cols, gap = 4, 3
    rows = math.ceil(len(shares) / cols)
    col_w = WIDTH / cols
    height = 40 + rows * 24 + 18
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
    body.append(text(0, height - 4, f"By code size across {repo_count} public repositories, forks excluded",
                     10.5, t["faint"]))
    return svg(WIDTH, height, "Languages", "\n".join(body))


# -- README sections -----------------------------------------------------------

def picture(path, alt, width=None):
    size = f' width="{width}"' if width else ""
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{path}-dark.svg">'
            f'<img src="{path}-light.svg"{size} align="top" alt="{escape(alt)}"></picture>')


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def shelf_html():
    # Inside <pre> whitespace shows: each shelf row is one line, and tags only
    # break lines inside themselves.
    rows = ["".join(f'<a\nhref="https://github.com/{USER}/{name}">'
                    f'{picture(f"assets/projects/{name}", name, CARD_W + CARD_GAP)}</a>'
                    for name, _, _ in PROJECTS[row::SHELF_ROWS])
            for row in range(SHELF_ROWS)]
    return "<pre>" + "\n".join(rows) + "</pre>"


def grid_html(columns):
    width = f"{100 / COLUMNS:g}%"
    # Fills empty cells, so every row spans COLUMNS tiles; 1px tall, so it never sets a row's height.
    blank = f'<picture><img src="assets/forks/blank.svg" width="{width}" align="top" alt=""></picture>'
    tiles = []
    for start in range(0, len(columns), COLUMNS):
        block = columns[start:start + COLUMNS]
        pad = [blank] * (COLUMNS - len(block))
        tiles += [picture(f"assets/forks/_{slug(title)}", title, width) for title, _ in block] + pad
        for row in range(max(len(repos) for _, repos in block)):
            for _, repos in block:
                if row < len(repos):
                    tiles.append(f'<a href="https://github.com/{USER}/{repos[row]}">'
                                 f'{picture(f"assets/forks/{repos[row]}", repos[row], width)}</a>')
                else:
                    tiles.append(blank)
            tiles += pad
    # Tiles must touch: break lines after a tag name rather than between tags.
    return "<p>" + "".join(re.sub(r"^<(\w+)", "<\\1\n", tile) for tile in tiles) + "</p>"


def replace_section(readme, name, html):
    pattern = re.compile(rf"(<!-- BEGIN {name} [^>]*-->\n).*?(<!-- END {name} -->)", re.S)
    if not pattern.search(readme):
        sys.exit(f"README.md has no BEGIN/END {name} markers")
    return pattern.sub(lambda m: m.group(1) + html + "\n" + m.group(2), readme)


# -- GitHub API ----------------------------------------------------------------

def get(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-profile",
    })
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def owned_repos():
    repos, page = [], 1
    while True:
        batch = get(f"https://api.github.com/users/{USER}/repos?type=owner&per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    return repos


def fork_columns(forks):
    """FORKS limited to the given fork names, plus a column for the ones it misses."""
    listed = {name for _, names in FORKS for name in names}
    for name in sorted(listed - forks, key=str.lower):
        print(f"warning: {name} is in FORKS but is not a fork of {USER}; skipped", file=sys.stderr)
    columns = [(title, [n for n in names if n in forks]) for title, names in FORKS]
    columns = [(title, names) for title, names in columns if names]
    unlisted = sorted(forks - listed, key=str.lower)
    if unlisted:
        print(f"warning: not in FORKS, shown as Uncategorized: {', '.join(unlisted)}", file=sys.stderr)
        columns.append(("Uncategorized", unlisted))
    return columns


def language_shares(repos):
    totals = {}
    for repo in repos:
        for lang, size in get(repo["languages_url"]).items():
            totals[lang] = totals.get(lang, 0) + size
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(totals.values())
    shares = [(lang, size / total) for lang, size in ranked[:TOP_LANGUAGES]]
    rest = sum(size for _, size in ranked[TOP_LANGUAGES:])
    if rest:
        shares.append(("Other", rest / total))
    return shares


def main():
    owned = owned_repos()
    repos = {r["name"]: r for r in owned if not r["fork"] and r["name"].lower() != USER.lower()}
    if not repos:
        sys.exit(f"no public non-fork repositories found for {USER}")
    shares = language_shares(repos.values())
    columns = fork_columns({r["name"] for r in owned if r["fork"]})
    fork_count = sum(len(names) for _, names in columns)

    outputs = {"forks/blank.svg": svg(TILE_W, 1, "", "")}
    for theme, t in THEMES.items():
        outputs[f"name-{theme}.svg"] = render_name(t)
        outputs[f"stack-{theme}.svg"] = render_stack(t)
        outputs[f"section-projects-{theme}.svg"] = render_section(
            "01", "Projects", len(PROJECTS), "SCROLL →", t)
        outputs[f"section-forks-{theme}.svg"] = render_section("02", "Forks", fork_count, None, t)
        outputs[f"section-languages-{theme}.svg"] = render_section("03", "Languages", None, None, t)
        outputs[f"languages-{theme}.svg"] = render_languages(shares, len(repos), t)
        for i, (name, area, desc) in enumerate(PROJECTS, 1):
            if name not in repos:
                print(f"warning: {name} is not a public repository of {USER}", file=sys.stderr)
            gap_below = (i - 1) % SHELF_ROWS < SHELF_ROWS - 1
            outputs[f"projects/{name}-{theme}.svg"] = render_project(
                i, name, area, desc, repos.get(name, {}), gap_below, t)
        for i, (title, forks) in enumerate(columns):
            outputs[f"forks/_{slug(title)}-{theme}.svg"] = render_fork_heading(
                title, len(forks), HEADING_H[i >= COLUMNS], t)
            for name in forks:
                outputs[f"forks/{name}-{theme}.svg"] = render_fork(name, t)

    # Start the generated folders afresh so removed projects and forks disappear.
    for folder in ("projects", "forks"):
        shutil.rmtree(ASSETS / folder, ignore_errors=True)
        (ASSETS / folder).mkdir(parents=True)
    for rel, content in outputs.items():
        (ASSETS / rel).write_text(content, encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    readme = replace_section(readme, "projects", shelf_html())
    readme = replace_section(readme, "forks", grid_html(columns))
    README.write_text(readme, encoding="utf-8")
    print(f"rendered {len(outputs)} images and updated {README.name}")


if __name__ == "__main__":
    main()
