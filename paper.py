"""
Paper: a newspaper, page by page. Each page (or spread) is a small HTML file
in pages/, laid out by hand on a column grid. Running text comes in from
Markdown files with <div data-md="path/to.md"></div>. Photos are kept in
colour at the source and converted for the press at build: black and white
(or colour) CMYK JPEGs.

Built for the tabloid at printnewspaper.com: 260 x 370 mm, a multiple of four
pages, single pages in reading order, 10 mm of white at every edge except
across the fold of a spread. See RULES.md "Bjook".
"""
import html
import io
import re
import subprocess
from pathlib import Path

from book import (all_faces, book_families, die, document, page_css,
                  page_of_anchors, rasterize, render, slugify, snapshot,
                  space_dashes, stamp_now, to_pt, write_preview)

DEFAULTS = {
    "page": {                            # printnewspaper.com tabloid
        "width": "260mm", "height": "370mm",
        "top": "15mm", "bottom": "20mm",
        "inside": "15mm", "outside": "15mm",
    },
    "type": {
        "text": "Newsreader", "display": "Libre Franklin", "title": "",
        "size": "10pt", "leading": "14pt",
    },
    "folio": {"size": "8pt", "position": "bottom-outside", "from_edge": "12mm"},
    "head": {"size": "8pt", "position": "bottom-center", "from_edge": "12mm"},
    "paper": {
        "columns": 4,                    # the grid every page is laid out on
        "gutter": "5mm",                 # between columns
        "edition": "",                   # e.g. "No. 1 · November 2026"; {edition} in a head
        "smart_quotes": True,
        "min_margin": "10mm",            # the printer's white edge; a page margin under it warns
    },
    "color": {
        "mode": "gray",                  # "gray": photos become black and white, accent = ink.
                                         # "color": photos keep their colour, accent applies.
        "ink": "device-cmyk(0 0 0 1)",   # text and rules: black ink only, the sharpest
        "black": "device-cmyk(0.3 0.3 0.3 1)",  # large dark areas: four-colour black,
                                                # which hides banding on an inkjet press
        "accent": "",                    # used in colour mode only; empty = ink
        "cmyk_profile": "/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc",
    },
}

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
MAX_PX = 4400          # about 300 ppi across the full page width; more is wasted


# ---------------------------------------------------------------- config

def checked(cfg):
    if cfg["color"]["mode"] not in ("gray", "color"):
        die(f'[color] mode {cfg["color"]["mode"]!r} isn\'t "gray" or "color"')
    return cfg


def tokens(cfg):
    c, p = cfg["color"], cfg["paper"]
    accent = c["accent"] if c["mode"] == "color" and c["accent"] else c["ink"]
    page = cfg["page"]
    return {"--ink": c["ink"], "--black": c["black"], "--accent": accent,
            "--paper": "device-cmyk(0 0 0 0)",     # no ink: the newsprint itself
            "--columns": p["columns"], "--gutter": p["gutter"],
            "--page-h": page["height"], "--page-top": page["top"],
            "--page-bottom": page["bottom"]}


def head(cfg):
    """The shared @page rules, plus the spread page: no margin at the fold,
    since a spread's two pages are one picture."""
    c = cfg["head"]
    edition = cfg["paper"]["edition"]
    for side in ("verso", "recto"):
        c[side] = c[side].replace("{edition}", edition)
    return page_css(cfg, tokens(cfg), cfg["paper"]["smart_quotes"]) + """
@page spread:left { margin-right: 0; }
@page spread:right { margin-left: 0; }
"""


def entries(root):
    """order.txt: one page file per line, in pages/, top to bottom. After the
    name, `plain` leaves off the page number and running head, and `spread`
    lays the file across two facing pages. # starts a comment."""
    order = root / "order.txt"
    if not order.is_file():
        die("no order.txt — list the page files in it, one per line")
    out = []
    for line in order.read_text().splitlines():
        words = line.split("#", 1)[0].split()
        if not words:
            continue
        name, flags = words[0], set(words[1:])
        unknown = flags - {"plain", "spread"}
        if unknown:
            die(f"order.txt: {name} has {', '.join(sorted(unknown))} — only plain and spread mean anything")
        path = root / "pages" / name
        if not path.is_file():
            die(f"order.txt lists {name}, but pages/{name} doesn't exist")
        out.append({"name": name, "id": "f-" + slugify(Path(name).stem), "path": path,
                    "plain": "plain" in flags, "spread": "spread" in flags})
    if not out:
        die("order.txt lists no pages")
    return out


# --------------------------------------------------------------- content

def markdown(path, smart, until=""):
    """A Markdown file as HTML through pandoc, with the house marks: curly
    quotes and ellipses from pandoc, then every dash used as punctuation set
    as a spaced em dash, the same as in the poems. `until` stops at the first
    line that starts with it, so notes kept under a draft don't print."""
    text = path.read_text()
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)     # frontmatter
    if until:
        lines = text.split("\n")
        cut = next((i for i, l in enumerate(lines) if l.strip().startswith(until)), len(lines))
        text = "\n".join(lines[:cut])
    if smart:
        text = re.sub(r"(?<=\S)--(?=\S)|(?<=\s)--(?=\s)", "—", text)
    fmt = "markdown+smart" if smart else "markdown-smart"
    try:
        out = subprocess.run(["pandoc", "-f", fmt, "-t", "html5", "--wrap=none"],
                             input=text, capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        die("pandoc isn't installed — brew install pandoc")
    if smart:
        out = re.sub(r">([^<]+)<", lambda m: ">" + space_dashes(m.group(1)) + "<", out)
    return out


def fill(page_html, root, smart):
    """Put each <... data-md="file.md"></...> placeholder's Markdown inside
    it. Paths are from the book folder. data-until="Check:" stops the file at
    the first line starting with that."""
    def one(m):
        tag, before, src, after = m.groups()
        path = (root / src).resolve()
        if not path.is_file():
            die(f"data-md: no file at {src} (looked in {path.parent})")
        attrs = before + after
        until = re.search(r'\sdata-until="([^"]*)"', attrs)
        attrs = re.sub(r'\sdata-until="[^"]*"', "", attrs)
        body = markdown(path, smart, html.unescape(until.group(1)) if until else "")
        return f"<{tag}{attrs}>\n{body}</{tag}>"
    return re.sub(r'<(\w+)([^>]*?)\s+data-md="([^"]+)"([^>]*)>\s*</\1>', one, page_html)


def prepare_image(src, dest_dir, cfg):
    """A photo ready for newsprint: oriented, its own colour profile honoured,
    black and white in gray mode, then CMYK, and no bigger than the press can
    use. Black and white stays CMYK on purpose: a gray-only image prints with
    black ink alone, and a clogged nozzle shows as a streak; four inks hide it."""
    from PIL import Image, ImageCms, ImageOps
    mode = cfg["color"]["mode"]
    out = dest_dir / f"{slugify(src.stem)}-{mode}.jpg"
    if out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    profile = Path(cfg["color"]["cmyk_profile"]).expanduser()
    if not profile.is_file():
        die(f"no CMYK profile at {profile} — set [color] cmyk_profile")
    im = ImageOps.exif_transpose(Image.open(src))
    srgb = ImageCms.createProfile("sRGB")
    icc = im.info.get("icc_profile")
    if im.mode not in ("RGB", "L", "CMYK"):
        im = im.convert("RGBA") if "A" in im.mode or im.mode == "P" else im.convert("RGB")
    if im.mode == "RGBA":                       # transparency lands on white paper
        flat = Image.new("RGB", im.size, "white")
        flat.paste(im, mask=im.split()[3])
        im = flat
    if icc:
        try:
            im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                           srgb, outputMode="RGB")
        except ImageCms.PyCMSError:
            im = im.convert("RGB")
    else:
        im = im.convert("RGB")
    if mode == "gray":
        im = ImageOps.grayscale(im).convert("RGB")
    if max(im.size) > MAX_PX:
        im.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
    cmyk = ImageCms.profileToProfile(im, srgb, str(profile), outputMode="CMYK",
                                     renderingIntent=ImageCms.Intent.PERCEPTUAL)
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmyk.save(out, quality=92)
    return out


def images(page_html, root, cfg):
    """Every local <img src> swapped for its press-ready copy in build/img."""
    dest = root / "build" / "img"
    found = {}

    def one(m):
        src = m.group(2)
        if re.match(r"(?:[a-z]+:|/|#)", src) or Path(src).suffix.lower() not in IMAGE_EXT:
            return m.group(0)
        path = (root / src).resolve()
        if not path.is_file():
            die(f"no image at {src} (looked for {path})")
        out = prepare_image(path, dest, cfg)
        found[out.name] = src
        return f'{m.group(1)}"{out.relative_to(root)}"'
    return re.sub(r'(<img\b[^>]*?\bsrc=)"([^"]+)"', one, page_html), found


# ------------------------------------------------------------------ html

def spread_html(entry, body, cfg):
    """A spread as two pages showing two halves of one wide box: the left
    page shows its left half, the right page the same box moved one page to
    the left. Ids live only in the left copy."""
    p = cfg["page"]
    half = to_pt(p["width"]) - to_pt(p["outside"])
    copy = re.sub(r'\s+id="[^"]*"', "", body)
    end = f'<span class="sheet-end" id="{entry["id"]}--end"></span>'
    return (f'<section class="spread spread-left" id="{entry["id"]}">'
            f'<div class="spread-inner" style="width: {2 * half:.2f}pt">{body}{end}</div></section>\n'
            f'<section class="spread spread-right" aria-hidden="true">'
            f'<div class="spread-inner" style="width: {2 * half:.2f}pt; margin-left: -{half:.2f}pt">'
            f'{copy}</div></section>')


def paper_html(cfg, items, root, blanks=0):
    smart = cfg["paper"]["smart_quotes"]
    faces = all_faces(book_families(cfg), cfg["type"]["fonts_dir"])
    parts, shown = [], {}
    for i, e in enumerate(items):
        if blanks and i == len(items) - 1 and not e["spread"]:
            # Padding goes before the back page, which stays last.
            parts += ['<section class="sheet blank"></section>'] * blanks
        # Comments are notes to whoever edits the page, not content.
        body = re.sub(r"<!--.*?-->", "", e["path"].read_text(), flags=re.S)
        body = fill(body, root, smart)
        body, found = images(body, root, cfg)
        shown.update(found)
        if e["spread"]:
            parts.append(spread_html(e, body, cfg))
        else:
            parts.append(f'<section class="sheet{" plain" if e["plain"] else ""}" id="{e["id"]}">'
                         f'{body}<span class="sheet-end" id="{e["id"]}--end"></span></section>')
    if blanks and items[-1]["spread"]:
        parts += ['<section class="sheet blank"></section>'] * blanks
    return document(cfg, "\n".join(parts), faces, root, "paper.css", head(cfg)), shown


# ----------------------------------------------------------------- build

def report(doc, items, cfg, blanks):
    """Where each page file landed, and what to look at: a spread that isn't
    the middle sheet, a spread cut off at the foot, a blank page the layout
    had to insert, margins inside the printer's white edge. `blanks` is the
    padding put before the last page, reported on its own."""
    page_of = page_of_anchors(doc)
    total = len(doc.pages)
    p = cfg["page"]
    px = 96 / 72
    foot = (to_pt(p["height"]) - to_pt(p["bottom"])) * px
    lines, warn, last = [], [], 0
    for i, e in enumerate(items):
        start, end = page_of.get(e["id"]), page_of.get(e["id"] + "--end")
        if e["spread"]:
            end = start + 1 if start else None
        span = f"p. {start}" if start == end else f"pp. {start}–{end}"
        lines.append(f"   {span:<10} {e['name']}{'  (spread)' if e['spread'] else ''}")
        gap = (start - last - 1) if start else 0
        if i == len(items) - 1 and not e["spread"]:
            gap -= blanks
        if gap > 0:
            warn.append(f"{gap} blank page{'s' if gap > 1 else ''} before {e['name']}"
                        + (" so the spread starts on a left-hand page" if e["spread"] else ""))
        if e["spread"] and start:
            if start != total // 2:
                warn.append(f"{e['name']} is on pp. {start}–{start + 1}, but only pp. "
                            f"{total // 2}–{total // 2 + 1} are one sheet; anything across "
                            "this fold prints on two sheets and won't line up exactly")
            mark = doc.pages[start - 1].anchors.get(e["id"] + "--end")
            if mark and mark[1] > foot + 1:
                over = (mark[1] - foot) / px / 72 * 25.4
                warn.append(f"{e['name']} runs {over:.0f} mm past the foot of the spread; "
                            "that much is cut off")
        last = end or last
    edge = to_pt(cfg["paper"]["min_margin"])
    for k in ("top", "bottom", "inside", "outside"):
        if to_pt(p[k]) + 0.01 < edge:
            warn.append(f"[page] {k} is {p[k]}, inside the printer's {cfg['paper']['min_margin']} white edge")
    return lines, warn


def image_sizes(doc, shown):
    """Each photo's resolution at the size it prints. Reads WeasyPrint's
    layout boxes, which aren't a public interface, so it says nothing
    rather than fail if that changes."""
    out = {}
    try:
        def walk(box):
            img = getattr(box, "replacement", None)
            element = getattr(box, "element", None)
            name = Path(element.get("src") or "").name if img is not None and element is not None else ""
            if name in shown and box.width and getattr(img, "width", None):
                ppi = img.width / (box.width / 96)        # image pixels / printed inches
                out[shown[name]] = min(out.get(shown[name], ppi), ppi)
            for child in getattr(box, "children", []) or []:
                walk(child)
        for page in doc.pages:
            walk(page._page_box)
    except Exception:
        return {}
    return out


def build(root, cfg, snap=None, quiet=False):
    cfg = checked(cfg)
    items = entries(root)
    out = root / "build"
    out.mkdir(exist_ok=True)

    page, shown = paper_html(cfg, items, root)
    doc = render(page, root)
    n = len(doc.pages)
    blanks = (4 - n % 4) % 4
    if blanks:
        page, shown = paper_html(cfg, items, root, blanks)
        doc = render(page, root)
        if len(doc.pages) % 4:
            die(f"padding to a multiple of 4 failed ({len(doc.pages)} pages)")
    total = len(doc.pages)
    (out / "paper.html").write_text(page)          # what WeasyPrint saw, for debugging

    pdf = out / f"{cfg['slug']}.pdf"
    doc.write_pdf(pdf)
    stamp = stamp_now()
    t = cfg["type"]
    spec = (f'{cfg["page"]["width"]} × {cfg["page"]["height"]} · {t["text"]} '
            f'{t["size"]}/{t["leading"]} · {cfg["paper"]["columns"]} columns · {cfg["color"]["mode"]}')
    write_preview(cfg, out, rasterize(pdf, out / "pages", dpi=72), stamp, spec)

    lines, warn = report(doc, items, cfg, blanks)
    if blanks:
        where = "at the end" if items[-1]["spread"] else "before the last page"
        warn.append(f"{blanks} blank page{'s' if blanks > 1 else ''} added {where} "
                    "to make a multiple of four")
    low = {src: ppi for src, ppi in image_sizes(doc, shown).items() if ppi < 200}
    for src, ppi in sorted(low.items()):
        warn.append(f"{src} prints at {ppi:.0f} ppi at its largest; under 200 looks soft on newsprint")
    if not quiet or warn:
        photos = f"{len(shown)} photo{'' if len(shown) == 1 else 's'}"
        print(f"-> {pdf}\n   {total} pages, {cfg['color']['mode']}, {photos}")
        print("\n".join(lines))
        print(f"-> {out / 'preview.html'}")
        for w in warn:
            print(f"   ! {w}")
    if snap is not None:
        snapshot(root, (pdf,), stamp, snap)
    return cfg


def sources(root):
    files = [root / "book.toml", root / "order.txt", root / "style.css",
             *(root / "pages").glob("*.html")]
    # Markdown a page pulls in, wherever it lives.
    for page in (root / "pages").glob("*.html"):
        for src in re.findall(r'data-md="([^"]+)"', page.read_text()):
            files.append((root / src).resolve())
    return files
