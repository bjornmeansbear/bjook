"""
The machinery every kind of book shares: book.toml, typographer's marks,
fonts, @page rules and margin boxes, rendering, the spread preview,
snapshots and the watcher. One small module per kind (poems.py, paper.py)
supplies its own defaults, its HTML and its build.
"""
import datetime
import functools
import html
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent

# What the page number, the running head and the continues mark have in
# common: each is a line of text in the top or bottom margin.
BOX = {
    "font": "",         # empty = the text face
    "size": "8pt",
    "weight": "normal",
    "position": "",     # top|bottom - outside|inside|center
    "from_edge": "",    # distance from the paper's edge; wins over drop
    "drop": "",         # or: gap from the text block; empty = one line
    "css": "",          # extra CSS, e.g. "letter-spacing: 0.08em"
}
BOX_NAMES = {"folio": "page number", "head": "running head", "continues": "continues mark"}

# Fallbacks only, for a setting a book leaves out. Changing these does nothing
# to a book whose book.toml sets the same thing: edit that book.toml instead.
# Each kind's DEFAULTS add sections and override values here.
DEFAULTS = {
    "kind": "poems",
    "title": "Untitled",
    "author": "",
    "slug": "",
    "page": {
        "width": "5.5in", "height": "8.5in",
        "top": "1.0in", "bottom": "1.5in",
        "inside": "1.25in", "outside": "1.0in",
    },
    "type": {
        "text": "Gentium", "display": "", "title": "",
        "size": "10pt", "leading": "15pt",
        "fonts_dir": "~/Code/libreFontLibrary/Families",
    },
    "folio": {**BOX, "size": "9pt", "position": "bottom-outside"},
    "head": {                           # the running head; off unless verso/recto is set
        **BOX, "position": "top-center",
        "verso": "",                    # left-hand pages: text, with {title} {author} {poem}
        "recto": "",                    # right-hand pages
    },
    "continues": {                      # a mark where a poem runs on to the next page
        **BOX, "size": "7pt", "position": "bottom-inside",
        "text": "",                     # e.g. "→"; empty = no mark
    },
}


def die(msg):
    sys.exit(f"bjook: {msg}")


# ---------------------------------------------------------------- config

def read_toml(root):
    path = root / "book.toml"
    if not path.is_file():
        die(f"no book.toml in {root} — run from a book folder, pass --root, "
            "or start one with `bjook new <dir>`")
    return tomllib.loads(path.read_text())


def merged_defaults(kind_defaults):
    out = {}
    for key in dict.fromkeys([*DEFAULTS, *kind_defaults]):
        base, over = DEFAULTS.get(key), kind_defaults.get(key)
        if isinstance(base, dict) or isinstance(over, dict):
            out[key] = {**(base or {}), **(over or {})}
        else:
            out[key] = over if key in kind_defaults else base
    return out


def load_config(root, kind_defaults):
    user = read_toml(root)
    cfg = {}
    for key, default in merged_defaults(kind_defaults).items():
        if isinstance(default, dict):
            cfg[key] = {**default, **user.get(key, {})}
        else:
            cfg[key] = user.get(key, default)
    cfg["slug"] = cfg["slug"] or slugify(cfg["title"])
    cfg["type"]["display"] = cfg["type"]["display"] or cfg["type"]["text"]
    cfg["type"]["title"] = cfg["type"]["title"] or cfg["type"]["display"]
    taken = {}
    for name, label in BOX_NAMES.items():
        box = cfg[name]
        box["font"] = box["font"] or cfg["type"]["text"]
        box["drop"] = box["drop"] or cfg["type"]["leading"]
        if not re.fullmatch(r"(top|bottom)-(outside|inside|center)", box["position"]):
            die(f"{name} position {box['position']!r} isn't one of "
                "top|bottom-outside|inside|center")
        if box_is_on(name, box):
            if box["position"] in taken:
                die(f"the {label} and the {taken[box['position']]} are both at {box['position']}")
            taken[box["position"]] = label
    return cfg


def box_is_on(name, box):
    """The page number always prints; the other two only when given text."""
    return (name == "folio" or (name == "head" and bool(box["verso"] or box["recto"]))
            or (name == "continues" and bool(box["text"])))


def book_families(cfg):
    """Every font family the book names, for registering with @font-face."""
    t = cfg["type"]
    return [t["text"], t["display"], t["title"]] + [cfg[name]["font"] for name in BOX_NAMES]


def to_pt(value):
    m = re.fullmatch(r"\s*([0-9.]+)\s*(in|pt|mm|cm|pc)\s*", str(value))
    if not m:
        die(f"can't read the length {value!r} — use in, pt, mm, cm or pc")
    return float(m.group(1)) * {"in": 72, "pt": 1, "mm": 72 / 25.4,
                                "cm": 72 / 2.54, "pc": 12}[m.group(2)]


def slugify(text, maxlen=50):
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return text[:maxlen].strip("-") or "untitled"


# ------------------------------------------------------ typographer's marks

def smarten(text):
    """Typographer's marks for typed ones: curly quotes, real apostrophes, a
    one-character ellipsis, and em dashes that stand clear of their
    neighbours with a space on each side."""
    text = re.sub(r"\.\.\.+", "…", text)
    text = re.sub(r"(?<=\w)'(?=\w)", "’", text)                  # don't, harbor's
    text = re.sub(r"'(?=\d0s\b|\d\d\b)", "’", text)               # '90s, '71
    text = re.sub(r"(?<!\w)'(?=(?:em|til|tis|twas|cause|n)\b)", "’", text, flags=re.I)
    opens = r"(^|[\s(\[{—–\-*_“‘])"                              # what a quote opens after
    text = re.sub(opens + '"', r"\1“", text)
    text = text.replace('"', "”")
    text = re.sub(opens + r"'(?=\S)", r"\1‘", text)
    return space_dashes(text.replace("'", "’"))


def space_dashes(text):
    """Every dash used as punctuation becomes a spaced em dash. `--`, and a
    hyphen or en dash with a space on each side, count as typed stand-ins.
    The space before is a no-break one, so a turned-over line never starts
    with the dash. A dash at the start or end of a line gets no space on its
    open side, and none is put between a dash and a quote mark or bracket
    that closes around it."""
    text = re.sub(r"(?<!-)-{2,3}(?!-)", "—", text)
    text = re.sub(r"(?<=\S)[ \t]+[-–][ \t]+(?=\S)", "—", text)
    text = re.sub(r"(?<=[^\s“‘(\[{])[ \t ]*—", " —", text)
    return re.sub(r"—[ \t]*(?=[^\s”’)\]}.,;:!?])", "— ", text)


def inline(text, smart):
    if smart:
        text = smarten(text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"<em>\1</em>", text)
    return text


# ----------------------------------------------------------------- fonts

@functools.cache
def scan_fonts(directory):
    """Every .ttf/.otf under a directory -> (family, weight, italic, variable
    weight range or None, path). Reads the font's own name table, since one
    folder often holds several families."""
    from fontTools.ttLib import TTFont
    found = []
    for path in sorted(Path(directory).rglob("*")):
        if path.suffix.lower() not in (".ttf", ".otf"):
            continue
        if re.search(r"web|woff", str(path.parent), re.I):
            continue
        try:
            font = TTFont(path, lazy=True, fontNumber=0)
            name = font["name"]
            family = name.getDebugName(16) or name.getDebugName(1)
            os2 = font["OS/2"]
            # Some fonts (Libre Franklin's OTFs) leave the italic flags off,
            # so the style name and slant count too.
            style = name.getDebugName(17) or name.getDebugName(2) or ""
            italic = (bool(os2.fsSelection & 1) or bool(font["head"].macStyle & 2)
                      or bool(re.search(r"italic|oblique", style, re.I))
                      or ("post" in font and font["post"].italicAngle != 0))
            wght = None
            if "fvar" in font:
                for axis in font["fvar"].axes:
                    if axis.axisTag == "wght":
                        wght = (int(axis.minValue), int(axis.maxValue))
            found.append((family, os2.usWeightClass, italic, wght, path))
            font.close()
        except Exception:
            continue
    return found


def find_family(family, fonts_dir):
    fonts_dir = Path(fonts_dir).expanduser()
    if not fonts_dir.is_dir():
        die(f"fonts_dir {fonts_dir} doesn't exist")
    want = re.sub(r"[^a-z0-9]", "", family.lower())
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    dirs = [d for d in sorted(fonts_dir.iterdir()) if d.is_dir()
            and (want.startswith(norm(d.name)) or norm(d.name).startswith(want))]
    seen = []
    for d in dirs or [fonts_dir]:
        fonts = scan_fonts(d)
        seen += fonts
        hits = [f for f in fonts if norm(f[0]) == want]
        if hits:
            statics = [f for f in hits if f[3] is None]
            return statics or hits
    names = sorted({f[0] for f in seen})
    die(f"no font family named {family!r} under {fonts_dir}"
        + (f" — that folder has: {', '.join(names)}" if dirs and names else ""))


def alias(family):
    """The CSS name a family is registered under. One name per family, however
    many roles (text, titles, folios) it plays, so each font file is
    registered once."""
    return "bj-" + slugify(family)


def all_faces(families, fonts_dir):
    return "\n".join(font_faces(f, fonts_dir) for f in dict.fromkeys(families))


def font_faces(family, fonts_dir):
    faces, done = [], set()
    for fam, weight, italic, wght, path in find_family(family, fonts_dir):
        key = (wght or weight, italic)
        if key in done:
            continue
        done.add(key)
        w = f"{wght[0]} {wght[1]}" if wght else weight
        faces.append(
            f"@font-face {{ font-family: '{alias(family)}'; src: url('{path.as_uri()}'); "
            f"font-weight: {w}; font-style: {'italic' if italic else 'normal'}; }}")
    return "\n".join(faces)


# ------------------------------------------------------------------ html

def margin_box(box):
    """Where a margin box sits, as (its name on left-hand pages, its name on
    right-hand pages, CSS). It lives in the top or bottom margin: `from_edge`
    in from the paper's edge, or else `drop` away from the text block."""
    edge, side = box["position"].split("-")
    if box["from_edge"]:
        place = f"vertical-align: {edge}; padding-{edge}: {box['from_edge']};"
    else:
        toward = "bottom" if edge == "top" else "top"
        place = f"vertical-align: {toward}; padding-{toward}: {box['drop']};"
    on_left, on_right = {"outside": ("left", "right"), "inside": ("right", "left"),
                         "center": ("center", "center")}[side]
    style = (f"font-family: '{alias(box['font'])}'; font-size: {box['size']}; "
             f"font-weight: {box['weight']}; line-height: 1; color: var(--ink); "
             f"{place} {box['css']}")
    return f"@{edge}-{on_left}", f"@{edge}-{on_right}", style


def css_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def head_content(text, cfg, smart):
    """A running head's text as a CSS content value. {title} and {author} are
    filled in here; {poem} becomes the title of the poem on that page."""
    text = text.replace("{title}", cfg["title"]).replace("{author}", cfg["author"])
    if smart:
        text = smarten(text)
    parts = []
    for i, chunk in enumerate(text.split("{poem}")):
        if i:
            parts.append("string(poem)")
        if chunk:
            parts.append(css_string(chunk))
    return " ".join(parts) or "none"


def margin_content(cfg, label, smart):
    """What each margin box prints, as (box, content on left-hand pages,
    content on right-hand pages), plus any CSS the content depends on. A
    specimen (label set) carries only its face name where the folio goes."""
    f, h, c = cfg["folio"], cfg["head"], cfg["continues"]
    if label:
        face = f'string(face) "  ·  {label}"'
        return [(f, face, face)], ""
    boxes, extra = [(f, "counter(page)", "counter(page)")], ""
    if box_is_on("head", h):
        boxes.append((h, head_content(h["verso"], cfg, smart), head_content(h["recto"], cfg, smart)))
    if box_is_on("continues", c):
        # Each poem switches the mark on where it starts and off where it
        # ends. A page shows whatever was set last on it, so the mark prints
        # only on pages a poem leaves unfinished.
        text = smarten(c["text"]) if smart else c["text"]
        boxes.append((c, "string(more, last)", "string(more, last)"))
        extra = (f".poem {{ string-set: more {css_string(text)}; }}\n"
                 '.poem-end { string-set: more ""; }')
    return boxes, extra


def page_css(cfg, tokens, smart, label=None):
    """@page rules and the book's CSS variables. `tokens` is the kind's own
    variables (ink, columns...), written into :root after the type ones."""
    p, t = cfg["page"], cfg["type"]
    boxes, extra = margin_content(cfg, label, smart)
    left, right, off_left, off_right = [], [], [], []
    for box, on_left, on_right in boxes:
        lname, rname, style = margin_box(box)
        left.append(f"{lname} {{ content: {on_left}; {style} }}")
        right.append(f"{rname} {{ content: {on_right}; {style} }}")
        off_left.append(lname)
        off_right.append(rname)
    none = lambda names: " ".join(f"{n} {{ content: none; }}" for n in names)
    own = "\n  ".join(f"{k}: {v};" for k, v in tokens.items())
    return f"""
:root {{
  --size: {t['size']}; --leading: {t['leading']};
  {own}
  --font-text: '{alias(t['text'])}';
  --font-display: '{alias(t['display'])}';
  --font-title: '{alias(t['title'])}';
}}
@page {{ size: {p['width']} {p['height']}; }}
@page :left {{
  margin: {p['top']} {p['inside']} {p['bottom']} {p['outside']};
  {" ".join(left)}
}}
@page :right {{
  margin: {p['top']} {p['outside']} {p['bottom']} {p['inside']};
  {" ".join(right)}
}}
@page plain:left {{ {none(off_left)} }}
@page plain:right {{ {none(off_right)} }}
@page :blank {{ {none(dict.fromkeys(off_left + off_right))} }}
{extra}
"""


def document(cfg, body, faces, root, stylesheet, head_css, label=None):
    """A whole book as one HTML document: the fonts, the @page rules, the
    kind's stylesheet, then the book's own style.css."""
    css = (HERE / stylesheet).read_text()
    own = root / "style.css"
    own_css = own.read_text() if own.is_file() else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(cfg['title'])}</title>
<meta name="author" content="{html.escape(cfg['author'])}">
<style>
{faces}
{head_css}
{css}
{own_css}
</style></head><body>
{body}
</body></html>"""


# ----------------------------------------------------------------- build

def render(html_text, root):
    from weasyprint import HTML
    return HTML(string=html_text, base_url=str(root)).render()


def page_of_anchors(doc):
    """Which page (counting from 1) every id in the document landed on."""
    out = {}
    for number, page in enumerate(doc.pages, 1):
        for name in page.anchors:
            out.setdefault(name, number)
    return out


def rasterize(pdf, out_dir, dpi=144):
    # Tolerant of a second build running at once (`bjook watch` in another
    # terminal rebuilds on the same save).
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(out_dir / "p")],
                   check=True)
    return sorted(p.name for p in out_dir.glob("p-*.png"))


def write_preview(cfg, build, images, stamp, spec=None):
    p, t = cfg["page"], cfg["type"]
    w, h = to_pt(p["width"]), to_pt(p["height"])
    data = {
        "title": cfg["title"], "stamp": stamp, "images": images,
        "ratio": w / h,
        "margins": {k: to_pt(p[k]) / (h if k in ("top", "bottom") else w) * 100
                    for k in ("top", "bottom", "inside", "outside")},
        "leading": to_pt(t["leading"]) / h * 100,
        "width": p["width"],
        "spec": spec or f'{p["width"]} × {p["height"]} · {t["text"]} {t["size"]}/{t["leading"]}',
    }
    page = (HERE / "preview.html").read_text().replace(
        "/*DATA*/", "window.BOOK = " + json.dumps(data) + ";")
    (build / "preview.html").write_text(page)
    (build / "stamp.txt").write_text(stamp)


def stamp_now():
    return datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")


def snapshot(root, files, stamp, note):
    snaps = root / "snapshots"
    snaps.mkdir(exist_ok=True)
    note = f"-{slugify(note)}" if note else ""
    for f in files:
        dest = snaps / f"{stamp[:15]}{note}-{f.name}"
        shutil.copy2(f, dest)
        print(f"   snapshot: {dest}")


# ----------------------------------------------------------------- watch

def watch(root, port, build_fn, source_files):
    """Rebuild on save and serve build/ for the preview. `source_files(root)`
    lists what to watch beyond the tool's own code."""
    code = sorted(HERE.glob("*.py"))

    def mtimes():
        files = [*source_files(root), *code, *HERE.glob("*.css"), HERE / "preview.html"]
        return {str(f): f.stat().st_mtime for f in files if f.exists()}

    def attempt():
        try:
            build_fn(root, quiet=True)
            print(time.strftime("%H:%M:%S"), "built", flush=True)
        except SystemExit as e:
            print(e)
        except Exception as e:
            print("build failed:", e)

    attempt()
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(root / "build"))
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"preview: http://127.0.0.1:{port}/preview.html   (ctrl-c to stop)", flush=True)
    seen = mtimes()
    try:
        while True:
            time.sleep(0.6)
            now = mtimes()
            if now != seen:
                # The tool itself changed: this process is running the old
                # code, so start over with the new code instead of building
                # with a stale half.
                if any(now.get(str(f)) != seen.get(str(f)) for f in code):
                    print("bjook changed, restarting", flush=True)
                    server.shutdown()
                    server.server_close()
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                seen = now
                attempt()
    except KeyboardInterrupt:
        print()
