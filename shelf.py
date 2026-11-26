"""
Shelf: a catalogue of books drawn as spines standing on a shelf, A to Z, at
a fraction of their real size. Built for "A Library", the books on Kristian
Bjørnard's office shelves (library.wjerk.shop), but any catalogue with a
height and a thickness for each book will do.

The book is planned by spread. A shelf runs the width of a spread, straight
through the fold, and sits at the same height on every page, so it reads as
one shelf from the first spread to the last (mode "endless"), or as one
bookcase two shelves high per spread (mode "wall"). A book on the fold is
drawn on both pages and each page clips it, so the halves meet when the book
lies open.

Each spine is set in its book's own typeface, so the book is also a type
specimen. Books with certain tags (the commons, in A Library) print as black
spines. After the shelf: any Markdown pages (an essay), an index with the
page each book stands on, and a colophon, which lands on the last page.
The cover is a separate sheet (back, spine, front) showing every book at
once. See RULES.md "Bjook".
"""
import html
import re
from pathlib import Path

from book import (alias, all_faces, book_families, die, document, page_css, rasterize,
                  render, snapshot, stamp_now, to_pt, write_preview)
from paper import markdown

DEFAULTS = {
    "page": {
        "width": "5.5in", "height": "8.5in",
        "top": "0.5in", "bottom": "0.55in",       # the essay, index and colophon pages
        "inside": "0.45in", "outside": "0.45in",
    },
    "type": {"text": "Work Sans", "size": "10pt", "leading": "14pt"},
    "folio": {"size": "7pt", "position": "bottom-center", "from_edge": "0.3in"},
    "shelf": {
        "data": "",                 # the catalogue, JSON; path from the book folder
        "date": "",                 # empty = the catalogue's own "generated" date
        "mode": "endless",          # "endless": one shelf through the whole book
                                    # "wall": two shelves to a spread
        "scale": 0,                 # 0 = by mode: 0.4 endless, 0.25 wall
        "shelves": [],              # shelf heights from the top of the page; empty = by mode
        "edge": "0.2in",            # where the first spine starts, from the outside edge
        "min_spine": "6.5pt",       # the thinnest a spine is drawn
        "black_tags": [],           # books with any of these tags print as black spines
        "back": ["essay.md", "index", "colophon.md"],   # after the shelf, in order;
                                    # "index" is the index; the last one ends the book
        "index_title": "Index",
        "smart_quotes": True,
    },
    "cover": {
        "text": "cover.md",         # the back-cover card
        "bleed": "0.125in",
        "caliper": 0.0025,          # inches per page: 60# uncoated, ~400 pages to the inch
    },
    # One table per face: [faces.<key>], the key being what the catalogue's
    # "face" field says. family, weight, scale (type size multiplier), and
    # where the font comes from: css (an @font-face stylesheet), file (one
    # font file), or neither (look in [type] fonts_dir). designer and url
    # go into the colophon's list of faces.
    "faces": {},
}


# ---------------------------------------------------------------- config

def checked(cfg, root):
    s = cfg["shelf"]
    if s["mode"] not in ("endless", "wall"):
        die(f'[shelf] mode {s["mode"]!r} isn\'t "endless" or "wall"')
    if not s["data"]:
        die("[shelf] data is empty — the path to the catalogue's JSON")
    s["scale"] = s["scale"] or (0.4 if s["mode"] == "endless" else 0.25)
    s["shelves"] = [to_pt(y) for y in s["shelves"]] or (
        [7.9 * 72] if s["mode"] == "endless" else [4.05 * 72, 8.05 * 72])
    if not cfg["faces"]:
        die("no [faces.<key>] tables — one per typeface the catalogue's books use")
    return cfg


def catalogue(root, cfg):
    path = (root / cfg["shelf"]["data"]).resolve()
    if not path.is_file():
        die(f"[shelf] data: {path} doesn't exist")
    import json
    data = json.loads(path.read_text())
    books = data["books"] if isinstance(data, dict) else data
    for b in books:
        missing = [k for k in ("slug", "title", "height", "thickness") if not b.get(k)]
        if missing:
            die(f"{b.get('title') or b.get('slug') or 'a book'} has no {', '.join(missing)}")
        if b.get("face") not in cfg["faces"]:
            die(f"{b['title']}: face {b.get('face')!r} has no [faces.{b.get('face')}] in book.toml")
    return data if isinstance(data, dict) else {}, books


def face_css(cfg, root):
    """@font-face rules for every spine face, under its own family name."""
    out, fonts_dir = [], cfg["type"]["fonts_dir"]
    for key, f in cfg["faces"].items():
        if f.get("css"):
            css_path = (root / f["css"]).resolve()
            base = css_path.parent.as_uri() + "/"
            css = css_path.read_text()
            out.append(re.sub(r"url\((['\"]?)(?!data:|file:|https?:)\./?",
                              lambda m: f"url({m[1]}{base}", css))
        elif f.get("file"):
            out.append(f"@font-face {{ font-family: '{f['family']}'; font-weight: {f.get('weight', 400)}; "
                       f"src: url('{(root / f['file']).resolve().as_uri()}'); }}")
        else:
            from book import font_faces
            out.append(font_faces(f["family"], fonts_dir).replace(f"'{alias(f['family'])}'", f"'{f['family']}'"))
    return "\n".join(out)


# --------------------------------------------------------------- drawing

class Shelf:
    def __init__(self, cfg, books, scale, min_spine):
        self.cfg, self.books, self.scale, self.min = cfg, books, scale, min_spine
        self.page_of = {}
        black = set(cfg["shelf"]["black_tags"])
        self.black = {b["slug"] for b in books if black & set(b.get("tags", []))}

    def width(self, b):
        return max(self.min, b["thickness"] * self.scale * 72)

    def rows(self, room, start=0):
        out, row, used = [], [], start
        for b in self.books:
            w = self.width(b)
            if row and used + w > room:
                out.append(row)
                row, used = [], start
            row.append(b)
            used += w
        if row:
            out.append(row)
        return out

    def spine(self, b, x, y, page=None, pad=3):
        if page:
            self.page_of.setdefault(b["slug"], page)
        w, h = self.width(b), b["height"] * self.scale * 72
        f = self.cfg["faces"][b["face"]]
        size = 4.5 * self.scale / 0.25 * f.get("scale", 1)
        per_letter = size * (0.6 if "mono" in f["family"].lower() else 0.5)
        author = b["authors"][0].split()[-1] if b.get("authors") else ""
        room = h - 8 - len(author) * per_letter
        e = html.escape
        return (f'<div class="spine{" black" if b["slug"] in self.black else ""}" '
                f'style="left:{x:.2f}pt;top:{y - h:.2f}pt;width:{w:.2f}pt;height:{h:.2f}pt">'
                f'<div class="label" style="width:{h:.2f}pt;height:{w:.2f}pt;'
                f'transform:translate({w:.2f}pt,0) rotate(90deg);padding:0 {pad}pt;'
                f"font-family:'{f['family']}';font-weight:{f.get('weight', 400)};font-size:{size:.2f}pt\">"
                f'<span class="t">{e(fit(b["title"], room, per_letter))}</span>'
                f'<span class="a" style="padding-left:{pad}pt">{e(author)}</span></div></div>')


def fit(title, room, per_letter):
    """A title that fits the spine: whole, or without its subtitle, or cut
    back to its last whole word with an ellipsis."""
    fits = lambda t: len(t) * per_letter <= room
    if fits(title):
        return title
    main = title.split(":")[0].strip()
    if fits(main):
        return main
    out = ""
    for word in main.split():
        if not fits((out + " " + word).strip() + "…"):
            break
        out = (out + " " + word).strip()
    return (out or main[: max(1, int(room / per_letter) - 1)]).rstrip(" ,;–-") + "…"


# ----------------------------------------------------------------- pages

def fills(cfg, books, shelf, date):
    """What {braces} in the Markdown pages turn into."""
    n = {}
    for b in books:
        n[b.get("sized", "")] = n.get(b.get("sized", ""), 0) + 1
    sizes = f"I’ve measured {n['measured']} with a ruler. " if n.get("measured") else ""
    sizes += f"Library catalogues gave me the size of {n.get('library-of-congress', 0) + n.get('open-library', 0)}. "
    sizes += f"For {n.get('pages', 0)} I only had a page count, so a short rule worked out the thickness from that. "
    sizes += f"The other {n.get('guessed', 0)} are guesses, and a rule made those too."
    scale = cfg["shelf"]["scale"]
    words = {0.4: "two fifths", 0.25: "a quarter", 0.5: "half", 0.2: "a fifth", 1: "full"}
    count = {}
    for b in books:
        count[b["face"]] = count.get(b["face"], 0) + 1
    e = html.escape
    faces = "".join(
        f"<li><span style=\"font-family:'{f['family']}';font-weight:{f.get('weight', 400)};"
        f"font-size:{9 * f.get('scale', 1):.1f}pt\">{e(f['family'])}</span> "
        f"{e(f.get('designer', ''))}{'. ' if f.get('designer') else ''}{e(f.get('licence', 'SIL Open Font License'))}. "
        f"{count.get(k, 0)} spines. {e(f.get('url', ''))}</li>"
        for k, f in cfg["faces"].items())
    return {"books": len(books), "date": date, "scale": words.get(scale, f"{scale:g}×"),
            "sizes": sizes, "black": len(shelf.black), "commons": len(shelf.black),
            "faces": f'<ul class="faces">{faces}</ul>', "title": cfg["title"],
            "author": cfg["author"]}


def md_page(path, cfg, fill):
    if not path.is_file():
        die(f"[shelf] back lists {path.name}, but it doesn't exist")
    out = markdown(path, cfg["shelf"]["smart_quotes"])
    out = re.sub(r"<p>\{faces\}</p>", lambda m: fill["faces"], out)
    for k, v in fill.items():
        out = out.replace("{" + k + "}", str(v))
    return f'<section class="back {re.sub(r"[^a-z0-9-]", "", path.stem.lower())}">{out}</section>'


def book_html(cfg, root, books, shelf, date, blanks=0):
    s = cfg["shelf"]
    page_w = to_pt(cfg["page"]["width"])
    edge = to_pt(s["edge"])
    e = html.escape
    pages = [f'<section class="shelf-page right title-page"><h1>{e(cfg["title"])}</h1>'
             f'<p class="date">{e(date)}</p></section>']
    lines = "".join(f'<div class="line" style="top:{y:.2f}pt"></div>' for y in s["shelves"])
    per = len(s["shelves"])
    rows = shelf.rows(2 * page_w - 2 * edge)
    for i in range(0, len(rows), per):
        left_no = len(pages) + 1
        layout = {"left": [], "right": []}
        for k, row in enumerate(rows[i:i + per]):
            y, x = s["shelves"][k], edge
            for b in row:
                w = shelf.width(b)
                if x < page_w:
                    layout["left"].append(shelf.spine(b, x, y, left_no))
                if x + w > page_w:
                    layout["right"].append(shelf.spine(b, x - page_w, y, left_no + 1))
                x += w - 0.5            # neighbours share an outline
        for side in ("left", "right"):
            pages.append(f'<section class="shelf-page {side}">{lines}{"".join(layout[side])}'
                         f'<div class="folio {side}">{len(pages) + 1}</div></section>')

    fill = fills(cfg, books, shelf, date)
    back = []
    for item in s["back"]:
        if item == "index":
            # Page number first, right-aligned in its own column, then the
            # title, so the eye goes straight from number to book.
            rows_ = "".join(f'<li><b>{shelf.page_of[b["slug"]]}</b><span>{e(b["title"])}'
                            f'{(", " + e(b["authors"][0])) if b.get("authors") else ""}</span></li>'
                            for b in books)
            back.append(f'<section class="back index"><h1>{e(s["index_title"])}</h1><ol>{rows_}</ol></section>')
        else:
            back.append(md_page(root / item, cfg, fill))
    pad = "".join('<section class="back pad"></section>' for _ in range(blanks))
    body = "".join(pages) + "".join(back[:-1]) + pad + back[-1]
    return body, len(rows)


def cover_html(cfg, root, books, shelf, date, pages, faces):
    """Back, spine and front as one sheet. Every book at once, packed into
    one bookcase that fills the sheet and runs off every edge, at the largest
    scale that fits. The title and the back-cover text sit on label cards."""
    c = cfg["cover"]
    page_w, page_h = to_pt(cfg["page"]["width"]), to_pt(cfg["page"]["height"])
    bleed = to_pt(c["bleed"])
    spine_w = pages * c["caliper"] * 72
    W, H = 2 * page_w + spine_w + 2 * bleed, page_h + 2 * bleed
    front_x = bleed + page_w + spine_w
    gap = 4

    def pack(s):
        sh = Shelf(cfg, books, s, 1.2)
        rows = sh.rows(W + 6, start=-6)
        return sh, rows, sum(max(b["height"] for b in r) * s * 72 + gap for r in rows)
    lo, hi = 0.05, 0.5
    for _ in range(30):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pack(mid)[2] <= H else (lo, mid)
    sh, rows, total = pack(lo)
    case, ys, y = [], [], (H - total) / 2 + 1
    for r in rows:
        y += max(b["height"] for b in r) * lo * 72 + gap
        x = -6
        for b in r:
            case.append(sh.spine(b, x, y, pad=1.5))
            x += sh.width(b) - 0.5
        case.append(f'<div class="line" style="top:{y:.2f}pt"></div>')
        ys.append(y)
    fill = fills(cfg, books, shelf, date)
    text_path = root / c["text"]
    blurb = md_page(text_path, cfg, fill) if text_path.is_file() else ""
    e = html.escape
    front_y = ys[max(0, len(ys) // 3 - 1)]
    back_y = ys[-2] if len(ys) > 1 else ys[-1]
    sheet = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e(cfg['title'])}: cover</title><style>
{faces}
@page {{ size: {W:.2f}pt {H:.2f}pt; margin: 0; }}
:root {{ --font-text: '{alias(cfg['type']['text'])}'; --size: {cfg['type']['size']}; --leading: {cfg['type']['leading']}; }}
{(Path(__file__).parent / 'shelf.css').read_text()}
{(root / 'style.css').read_text() if (root / 'style.css').is_file() else ''}
</style></head><body><div class="cover" style="width:{W:.2f}pt;height:{H:.2f}pt">
{"".join(case)}
<div class="card front" style="left:{front_x + 0.4 * 72:.2f}pt;top:{front_y:.2f}pt">
<h1>{e(cfg['title'])}</h1><p class="date">{e(date)}</p></div>
<div class="card back-card" style="left:{bleed + 0.4 * 72:.2f}pt;top:{back_y:.2f}pt">{blurb}</div>
</div></body></html>"""
    return sheet, {"scale": lo, "shelves": len(rows), "spine": spine_w / 72, "W": W / 72, "H": H / 72}


# ----------------------------------------------------------------- build

def build(root, cfg, snap=None, quiet=False):
    cfg = checked(cfg, root)
    data, books = catalogue(root, cfg)
    s = cfg["shelf"]
    date = s["date"]
    if not date and data.get("generated"):
        import datetime
        date = datetime.date.fromisoformat(data["generated"]).strftime("%-d %B %Y")
    out = root / "build"
    out.mkdir(exist_ok=True)
    faces = all_faces(book_families(cfg), cfg["type"]["fonts_dir"]) + "\n" + face_css(cfg, root)
    head = page_css(cfg, {"--ink": "#000", "--page-w": cfg["page"]["width"],
                           "--page-h": cfg["page"]["height"]}, s["smart_quotes"]) + """
@page shelf { margin: 0; %(off)s }
@page pad { %(off)s }
""" % {"off": " ".join(f"@{e}-{s} {{ content: none; }}" for e in ("top", "bottom")
                       for s in ("left", "center", "right"))}

    def make(blanks):
        shelf = Shelf(cfg, books, s["scale"], to_pt(s["min_spine"]))
        body, n_rows = book_html(cfg, root, books, shelf, date, blanks)
        page = document(cfg, body, faces, root, "shelf.css", head)
        return shelf, n_rows, page, render(page, root)

    shelf, n_rows, page, doc = make(0)
    blanks = len(doc.pages) % 2
    if blanks:
        shelf, n_rows, page, doc = make(blanks)
    (out / "book.html").write_text(page)
    pdf = out / f"{cfg['slug']}.pdf"
    doc.write_pdf(pdf)
    total = len(doc.pages)

    sheet, info = cover_html(cfg, root, books, shelf, date, total, faces)
    (out / "cover.html").write_text(sheet)
    cover_pdf = out / f"{cfg['slug']}-cover.pdf"
    render(sheet, root).write_pdf(cover_pdf)

    stamp = stamp_now()
    t = cfg["type"]
    spec = (f'{cfg["page"]["width"]} × {cfg["page"]["height"]} · {s["mode"]} · '
            f'spines at {s["scale"]:g} · {t["text"]} {t["size"]}/{t["leading"]}')
    write_preview(cfg, out, rasterize(pdf, out / "pages", dpi=72), stamp, spec)
    if not quiet:
        print(f"-> {pdf}\n   {total} pages: {len(books)} books on {n_rows} shelves, "
              f"{len(shelf.black)} black spines" + (", 1 blank page before the last" if blanks else ""))
        print(f"-> {cover_pdf}\n   {info['W']:.3f} × {info['H']:.3f}in with bleed, spine {info['spine']:.3f}in, "
              f"every book at {info['scale']:.3f} on {info['shelves']} shelves")
        print(f"-> {out / 'preview.html'}")
        if info["spine"] < 0.25:
            print(f"   ! the spine is {info['spine']:.2f}in: too thin for type (about 0.25in, 100 pages, is the usual minimum)")
        if total < 32:
            print(f"   ! {total} pages: most printers want 32 or more to perfect bind; saddle stitch instead")
    if snap is not None:
        snapshot(root, (pdf, cover_pdf), stamp, snap)
    return cfg


def sources(root):
    import tomllib
    files = [root / "book.toml", root / "style.css", *root.glob("*.md")]
    try:
        data = tomllib.loads((root / "book.toml").read_text()).get("shelf", {}).get("data")
        if data:
            files.append((root / data).resolve())
    except Exception:
        pass
    return files
