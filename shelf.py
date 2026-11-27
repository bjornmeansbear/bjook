"""
Shelf: a catalogue of books drawn as spines standing on a shelf, A to Z, at
a fraction of their real size. Built for "A Library", the books on Kristian
Bjørnard's library (library.wjerk.shop), but any catalogue with a
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
                                    # "index" is the index, an image gets a page to itself,
                                    # and the last one ends the book
        "index_title": "Index",
        "title_image": "",          # an image on the title page, above the title (a bookplate, a mark)
        "running": "",              # a text file: one line of type that runs across the top of
                                    # every shelf spread, through the fold, cut wherever a page
                                    # ends, sized to start on the first spread and end on the last
        "running_font": "",         # empty = [type] text
        "running_weight": 600,
        "running_caps": True,
        "running_top": "0.45in",    # the top of the line, from the top of the page
        "smart_quotes": True,
    },
    "riso": {
        "second": "",               # a second ink, as the colour it prints (e.g. "#00A95C" for
                                    # riso green). The running line, the title image and the
                                    # picture pages print in it; everything else in black.
                                    # Empty = one ink. Builds a master PDF per drum.
        "name": "second",           # the ink's name, for the file: <slug>-<name>.pdf
        "french_fold": False,       # also impose for French fold: each leaf is two facing pages
                                    # side by side (1|2, 3|4...), printed on one side only and
                                    # folded at the outer edge, so nothing has to back up
        "duplex": False,            # also impose single pages front and back, as many to a side
                                    # as fit, backs laid out to flip on the long edge; cut apart
                                    # and perfect bind
        "paper": ["12in", "18in"],  # the sheet the riso takes; leaves go on it as many as fit
        "marks": True,              # crop marks and fold dashes, wherever there's room for them
        "per_sheet": 0,             # leaves to a sheet; 0 = as many as fit
    },
    "site": {                       # `bjook site`: the book's page on a shared Bjook site
        "path": "",                 # its folder; empty = from the title
        "text": ["cover.md"],       # Markdown shown on the page, in order, before the spreads
        "after": [],                # and after the downloads (the colophon sets each face in itself,
                                    # which needs the spine fonts on the web too)
        "links": [],                # [[label, url], ...]: where else the book lives
        "dpi": 110,                 # the spreads as pictures, at this resolution
    },
    "cover": {
        "text": "cover.md",         # the back-cover card
        "bleed": "0.125in",
        "caliper": 0.0025,          # inches per page: 60# uncoated, ~400 pages to the inch.
                                    # French fold doubles it: each page is a whole sheet
        "hairline": "0.4pt",        # the spines' outline on the cover
        "riso": False,              # also a riso master on [riso] paper with crop marks, and a
                                    # preview in the cover's own ink on its own paper:
        "ink": "#C2A14D",           # the ink, as a screen stand-in (riso gold)
        "paper": "#161412",         # the paper (black)
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


def running_line(cfg, root, spreads, page_w, faces):
    """The running line, broken into one piece per shelf spread at spaces,
    so no word is cut by the trim at the outer edges. Within a spread it runs
    straight through the fold, like the shelf. Each piece is spaced out to
    the full width of its spread, so the line reads as one band. Returns
    (pieces, family, size): the largest size at which the whole text fits
    on the shelf spreads."""
    s = cfg["shelf"]
    path = root / s["running"]
    if not path.is_file():
        die(f"[shelf] running: {path} doesn't exist")
    words = path.read_text().split()
    if s["running_caps"]:
        words = [w.upper() for w in words]
    family = s["running_font"] or cfg["type"]["text"]
    # Measure every word, and a space, once at 100pt, kerning and all.
    style = (f"display:inline-block;white-space:nowrap;font-family:'{alias(family)}';"
             f"font-weight:{s['running_weight']};font-size:100pt")
    probe = f"<style>{faces}</style>" + "".join(
        f'<div><span style="{style}">{html.escape(w)}</span></div>' for w in [*words, "x x", "xx"])
    seen = set()
    def spans(box, out):
        # A span shows up as several nested boxes; count each element once.
        if getattr(box, "element_tag", None) == "span" and id(box.element) not in seen:
            seen.add(id(box.element))
            out.append(box.width * 0.75)                   # css px -> pt
        for c in getattr(box, "children", []):
            spans(c, out)
        return out
    from weasyprint import HTML
    widths = []
    for pg in HTML(string=probe).render().pages:
        spans(pg._page_box, widths)
    *word_w, xx_space, xx = widths
    space = xx_space - xx
    room = 2 * page_w - 2 * to_pt(s["edge"])
    n_pages = spreads

    def pack(size):
        k = size / 100
        pieces, line, used = [], [], 0
        for w, ww in zip(words, word_w):
            need = ww * k + (space * k if line else 0)
            if line and used + need > room:
                pieces.append(line)
                line, used = [], 0
                need = ww * k
            line.append(w)
            used += need
        pieces.append(line)
        return pieces
    lo, hi = 4, 200
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if len(pack(mid)) <= n_pages else (lo, mid)
    pieces = pack(lo)
    if max(ww * lo / 100 for ww in word_w) > room:
        die("[shelf] running: a word is wider than a page at any size that fits")
    return [" ".join(p) for p in pieces], family, lo


def book_html(cfg, root, books, shelf, date, blanks=0, faces=""):
    s = cfg["shelf"]
    page_w = to_pt(cfg["page"]["width"])
    edge = to_pt(s["edge"])
    e = html.escape
    plate = s["title_image"]
    if plate and not (root / plate).is_file():
        die(f"[shelf] title_image: {plate} doesn't exist")
    plate_html = f'<img class="title-image ink2" src="{e(plate)}" alt="">' if plate else ""
    pages = [f'<section class="shelf-page right title-page">{plate_html}<h1>{e(cfg["title"])}</h1>'
             f'<p class="date">{e(date)}</p></section>']
    lines = "".join(f'<div class="line" style="top:{y:.2f}pt"></div>' for y in s["shelves"])
    per = len(s["shelves"])
    rows = shelf.rows(2 * page_w - 2 * edge)
    spreads = -(-len(rows) // per)
    run = running_line(cfg, root, spreads, page_w, faces) if s["running"] else None
    cfg["_run"] = run
    run_size = run[2] if run else 0

    def running(spread, k):
        # This spread's piece of the line: whole words, spaced to fill the
        # spread between its outer edges, drawn on both pages and clipped at
        # the fold. The last piece sits flush left, where it ends.
        if not run or spread >= len(run[0]):
            return ""
        last = spread == len(run[0]) - 1
        n = spread
        return (f'<div class="running ink2{" last" if last else ""}" style="left:{edge - k * page_w:.2f}pt;'
                f'width:{2 * page_w - 2 * edge:.2f}pt;'
                f'top:{to_pt(s["running_top"]):.2f}pt;'
                f"font-family:'{alias(run[1])}';font-weight:{s['running_weight']};font-size:{run[2]:.2f}pt\">"
                f'{e(run[0][n])}</div>')
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
        for k, side in enumerate(("left", "right")):
            pages.append(f'<section class="shelf-page {side}">{lines}{running(i // per, k)}{"".join(layout[side])}'
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
        elif Path(item).suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".gif"):
            # A picture: a page to itself, centred.
            if not (root / item).is_file():
                die(f"[shelf] back lists {item}, but it doesn't exist")
            back.append(f'<section class="back picture"><img class="ink2" src="{e(item)}" alt=""></section>')
        else:
            back.append(md_page(root / item, cfg, fill))
    pad = "".join('<section class="back pad"></section>' for _ in range(blanks))
    body = "".join(pages) + "".join(back[:-1]) + pad + back[-1]
    return body, len(rows), run_size


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
    return sheet, {"scale": lo, "shelves": len(rows), "spine": spine_w / 72, "W": W / 72, "H": H / 72,
                   "bleed": bleed / 72, "page": [page_w / 72, page_h / 72]}


# ----------------------------------------------------------------- build

def tinted(root, out, src, colour):
    """A copy of an image in the second ink's colour, for the preview: a
    one-colour PNG becomes that colour on transparent, an SVG has its dark
    colours swapped. Returns its path relative to the book folder."""
    path, dest = root / src, out / "ink" / Path(src).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".svg":
        text = path.read_text()
        text = re.sub(r"#(?:[0-3][0-9a-f]){3}\b|#000\b|\bblack\b", colour, text, flags=re.I)
        dest.write_text(text)
    else:
        from PIL import Image
        im = Image.open(path).convert("L")
        r, g, b = (int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        alpha = im.point(lambda v: 255 - v)
        tint = Image.new("RGBA", im.size, (r, g, b, 0))
        tint.putalpha(alpha)
        tint.save(dest)
    return str(dest.relative_to(root))


def separations(root, cfg, page, out):
    """Riso: the book as it'll look (the second ink in its colour), and one
    master PDF per drum, each in plain black, the other drum's marks left
    out. Same pages, same positions, so the masters register."""
    colour, slug, name = cfg["riso"]["second"], cfg["slug"], cfg["riso"]["name"]
    # Black drum: everything but the second ink.
    black = page.replace("</style>", ".ink2 { visibility: hidden; }\n</style>", 1)
    # Second drum: only the second ink, printed black for the master; page
    # numbers off (they print with the black).
    second = page.replace("</style>", ":root { --ink: transparent; }\n"
                          "body * { visibility: hidden; } .ink2, .ink2 * { visibility: visible; }\n</style>", 1)
    # The look: the second ink in its colour, images swapped for tinted copies.
    look = page.replace("</style>", f".running {{ color: {colour}; }}\n</style>", 1)
    for src in set(re.findall(r'<img class="[^"]*ink2[^"]*" src="([^"]+)"', page)):
        look = look.replace(f'class="title-image ink2" src="{src}"', f'class="title-image ink2" src="{tinted(root, out, src, colour)}"')
        look = look.replace(f'<img class="ink2" src="{src}"', f'<img class="ink2" src="{tinted(root, out, src, colour)}"')
    files = {}
    for key, html_ in (("black", black), (name, second)):
        f = out / f"{slug}-{key}.pdf"
        render(html_, root).write_pdf(f)
        files[key] = f
    return look, files


def french_fold(cfg, pdfs, out):
    """Impose each PDF for French fold on the riso's paper: leaf after leaf,
    each one pages (2k+1 | 2k+2) side by side, as many leaves to a sheet as
    fit, with crop marks at the cuts and short dashes at each fold. Nothing
    bleeds off a cut that shows: the open edges go into the binding, and
    the fold is the fore-edge. Returns the files written and leaves/sheet."""
    from pypdf import PdfReader, PdfWriter, Transformation
    pw, ph = to_pt(cfg["page"]["width"]), to_pt(cfg["page"]["height"])
    W, H = (to_pt(v) for v in cfg["riso"]["paper"])
    leaf_w, leaf_h = 2 * pw, ph
    if leaf_w > W + 0.01 or leaf_h > H + 0.01:
        W, H = H, W                                   # try the paper the other way round
    if leaf_w > W + 0.01 or leaf_h > H + 0.01:
        die(f"[riso] paper {cfg['riso']['paper']} can't hold a {leaf_w/72:g} × {leaf_h/72:g}in leaf")
    per = int((H + 0.01) // leaf_h)
    if cfg["riso"]["per_sheet"]:
        per = min(per, cfg["riso"]["per_sheet"])
    x0 = (W - leaf_w) / 2
    y_top = (H + per * leaf_h) / 2                    # the leaves sit centred on the sheet
    mark, gap = 18, 6                                 # crop mark length and its gap from the cut
    need = gap + mark
    side, ends = x0 >= need, (H - per * leaf_h) / 2 >= need   # room for marks beside, above and below
    lines, dashes = [], []
    xs = [x0, x0 + leaf_w]
    ys = [y_top - i * leaf_h for i in range(per + 1)]
    if cfg["riso"]["marks"]:
        if ends and x0 > 0.01:                        # vertical cuts: marks above and below
            for x in xs:
                lines += [(x, ys[0] + gap, x, ys[0] + need), (x, ys[-1] - gap, x, ys[-1] - need)]
        if side:                                      # horizontal cuts: marks left and right
            for y in ys:
                lines += [(x0 - gap, y, x0 - need, y), (x0 + leaf_w + gap, y, x0 + leaf_w + need, y)]
        elif ends:                                    # no room beside: mark the top and bottom
            for y in (ys[0], ys[-1]):                 # cuts at the paper's edges instead
                for x in (0, W - mark):
                    lines.append((x, y, x + mark, y))
        if ends:                                      # the fold: dashes above and below
            fold = x0 + pw
            dashes = [(fold, ys[0] + gap, fold, ys[0] + need), (fold, ys[-1] - gap, fold, ys[-1] - need)]
    room = bool(lines or dashes)
    svg_lines = "".join(f'<line x1="{a:.2f}" y1="{H - b:.2f}" x2="{c:.2f}" y2="{H - d:.2f}"/>' for a, b, c, d in lines)
    svg_dash = "".join(f'<line x1="{a:.2f}" y1="{H - b:.2f}" x2="{c:.2f}" y2="{H - d:.2f}" stroke-dasharray="3 3"/>' for a, b, c, d in dashes)
    marks_html = (f'<style>@page {{ size: {W:.2f}pt {H:.2f}pt; margin: 0; }} body {{ margin: 0; }}</style>'
                  f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}pt" height="{H:.2f}pt" viewBox="0 0 {W:.2f} {H:.2f}" '
                  f'stroke="#000" stroke-width="0.5">{svg_lines}{svg_dash}</svg>')
    import io
    from weasyprint import HTML
    marks_pdf = PdfReader(io.BytesIO(HTML(string=marks_html).write_pdf()))
    written = []
    for key, src in pdfs.items():
        pages = PdfReader(src).pages
        leaves = [(pages[i], pages[i + 1] if i + 1 < len(pages) else None) for i in range(0, len(pages), 2)]
        w = PdfWriter()
        for at in range(0, len(leaves), per):
            sheet = w.add_blank_page(W, H)
            if room:
                sheet.merge_page(marks_pdf.pages[0])
            for slot, (left, right) in enumerate(leaves[at:at + per]):
                y = ys[slot + 1]
                sheet.merge_transformed_page(left, Transformation().translate(x0, y))
                if right is not None:
                    sheet.merge_transformed_page(right, Transformation().translate(x0 + pw, y))
        f = out / f"{cfg['slug']}-french-fold{'' if key == 'look' else '-' + key}.pdf"
        with open(f, "wb") as fh:
            w.write(fh)
        written.append((key, f, -(-len(leaves) // per)))
    return written, per


def duplex(cfg, pdfs, out):
    """Impose each PDF as single leaves printed on both sides: odd pages on
    the front of a sheet, in a grid of as many as fit, and each leaf's even
    page on the back in the mirrored spot, so turning the sheet over on its
    long edge puts every back behind its front. Crop marks at every cut.
    Returns the files written and pages per side."""
    from pypdf import PdfReader, PdfWriter, Transformation
    pw, ph = to_pt(cfg["page"]["width"]), to_pt(cfg["page"]["height"])
    W, H = (to_pt(v) for v in cfg["riso"]["paper"])
    cols, rows = int((W - 36) // pw), int((H - 36) // ph)
    if cols * rows < 1:
        die(f"[riso] paper {cfg['riso']['paper']} can't hold a page with room for marks")
    x0, y0 = (W - cols * pw) / 2, (H - rows * ph) / 2
    mark, gap = 18, 6
    xs = [x0 + c * pw for c in range(cols + 1)]
    ys = [y0 + r * ph for r in range(rows + 1)]
    seg = []
    for x in xs:
        seg += [(x, y0 - gap, x, y0 - gap - mark), (x, ys[-1] + gap, x, ys[-1] + gap + mark)]
    for y in ys:
        seg += [(x0 - gap, y, x0 - gap - mark, y), (xs[-1] + gap, y, xs[-1] + gap + mark, y)]
    svg = "".join(f'<line x1="{a:.2f}" y1="{H - b:.2f}" x2="{c:.2f}" y2="{H - d:.2f}"/>' for a, b, c, d in seg)
    marks_html = (f'<style>@page {{ size: {W:.2f}pt {H:.2f}pt; margin: 0; }} body {{ margin: 0; }}</style>'
                  f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}pt" height="{H:.2f}pt" '
                  f'viewBox="0 0 {W:.2f} {H:.2f}" stroke="#000" stroke-width="0.5">{svg}</svg>')
    import io
    from weasyprint import HTML
    marks = PdfReader(io.BytesIO(HTML(string=marks_html).write_pdf())).pages[0]
    slots = cols * rows
    written = []
    for key, src in pdfs.items():
        pages = PdfReader(src).pages
        leaves = [(pages[i], pages[i + 1] if i + 1 < len(pages) else None) for i in range(0, len(pages), 2)]
        w = PdfWriter()
        for at in range(0, len(leaves), slots):
            front, back = w.add_blank_page(W, H), w.add_blank_page(W, H)
            front.merge_page(marks)
            back.merge_page(marks)
            for n, (odd, even) in enumerate(leaves[at:at + slots]):
                c, r = n % cols, n // cols
                y = ys[rows - 1 - r]                    # first leaf top left
                front.merge_transformed_page(odd, Transformation().translate(xs[c], y))
                if even is not None:                    # mirrored left to right on the back
                    back.merge_transformed_page(even, Transformation().translate(xs[cols - 1 - c], y))
        f = out / f"{cfg['slug']}-duplex{'' if key == 'look' else '-' + key}.pdf"
        with open(f, "wb") as fh:
            w.write(fh)
        written.append((key, f, -(-len(leaves) // slots)))
    return written, slots


def spreads_pdf(cfg, src, dest):
    """The book as it reads, for a screen: the first page alone on the
    right, then each spread side by side, the last page alone if it's a
    left-hand page."""
    from pypdf import PdfReader, PdfWriter, Transformation
    pw, ph = to_pt(cfg["page"]["width"]), to_pt(cfg["page"]["height"])
    pages = PdfReader(src).pages
    w = PdfWriter()
    groups = [(None, pages[0])] + [(pages[i], pages[i + 1] if i + 1 < len(pages) else None)
                                    for i in range(1, len(pages), 2)]
    for left, right in groups:
        sheet = w.add_blank_page(2 * pw, ph)
        if left is not None:
            sheet.merge_page(left)
        if right is not None:
            sheet.merge_transformed_page(right, Transformation().translate(pw, 0))
    with open(dest, "wb") as fh:
        w.write(fh)


def cover_riso(cfg, root, sheet, cover_pdf, out):
    """The cover for a riso: the black-on-white cover centred on the riso's
    paper with crop marks at the trim (the master), and the same in the
    cover's ink on its paper (how it'll look): ink where the master is
    black, the paper where it's white, so the cards show the paper through
    their inked type and rules."""
    from pypdf import PdfReader, PdfWriter, Transformation
    import io
    from weasyprint import HTML
    ink, paper = cfg["cover"]["ink"], cfg["cover"]["paper"]
    look_html = sheet.replace("</style>", f"""
body, .cover {{ background: {paper}; }}
.spine, .card {{ background: {paper}; border-color: {ink}; color: {ink}; }}
.line {{ background: {ink}; }}
</style>""", 1)
    look = out / f"{cfg['slug']}-cover-look.pdf"
    render(look_html, root).write_pdf(look)
    src = PdfReader(cover_pdf).pages[0]
    cw, ch = float(src.mediabox.width), float(src.mediabox.height)
    W, H = (to_pt(v) for v in cfg["riso"]["paper"])
    if cw > W or ch > H:
        W, H = H, W
    if cw > W or ch > H:
        die(f"[riso] paper {cfg['riso']['paper']} is smaller than the cover ({cw/72:.2f} × {ch/72:.2f}in)")
    x0, y0 = (W - cw) / 2, (H - ch) / 2
    b = to_pt(cfg["cover"]["bleed"])
    tx = [x0 + b, x0 + cw - b]                       # the trim, inside the bleed
    ty = [y0 + b, y0 + ch - b]
    spine_x = [x0 + b + to_pt(cfg["page"]["width"]), x0 + cw - b - to_pt(cfg["page"]["width"])]
    gap, mark = 3, 12
    seg = []
    for x in tx + spine_x:
        seg += [(x, y0 - gap, x, max(0, y0 - gap - mark)), (x, y0 + ch + gap, x, min(H, y0 + ch + gap + mark))]
    for y in ty:
        seg += [(x0 - gap, y, max(0, x0 - gap - mark), y), (x0 + cw + gap, y, min(W, x0 + cw + gap + mark), y)]
    svg = "".join(f'<line x1="{a:.2f}" y1="{H - c:.2f}" x2="{d:.2f}" y2="{H - e:.2f}"/>' for a, c, d, e in seg)
    marks = PdfReader(io.BytesIO(HTML(string=(
        f'<style>@page {{ size: {W:.2f}pt {H:.2f}pt; margin: 0; }} body {{ margin: 0; }}</style>'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}pt" height="{H:.2f}pt" viewBox="0 0 {W:.2f} {H:.2f}" '
        f'stroke="#000" stroke-width="0.5">{svg}</svg>')).write_pdf())).pages[0]
    w = PdfWriter()
    page = w.add_blank_page(W, H)
    page.merge_page(marks)
    page.merge_transformed_page(src, Transformation().translate(x0, y0))
    master = out / f"{cfg['slug']}-cover-riso.pdf"
    with open(master, "wb") as fh:
        w.write(fh)
    return [(master, f"the riso master, centred on {W/72:g} × {H/72:g}in with crop and spine marks"),
            (look, "how it'll look, in the cover's ink on its paper")]


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
    faces = all_faces(book_families(cfg) + [s["running_font"]] * bool(s["running_font"]), cfg["type"]["fonts_dir"]) + "\n" + face_css(cfg, root)
    head = page_css(cfg, {"--ink": "#000", "--page-w": cfg["page"]["width"],
                           "--page-h": cfg["page"]["height"]}, s["smart_quotes"]) + """
@page shelf { margin: 0; %(off)s }
@page pad { %(off)s }
""" % {"off": " ".join(f"@{e}-{s} {{ content: none; }}" for e in ("top", "bottom")
                       for s in ("left", "center", "right"))}

    def make(blanks):
        shelf = Shelf(cfg, books, s["scale"], to_pt(s["min_spine"]))
        body, n_rows, run_size = book_html(cfg, root, books, shelf, date, blanks, faces)
        page = document(cfg, body, faces, root, "shelf.css", head)
        return shelf, n_rows, run_size, page, render(page, root)

    shelf, n_rows, run_size, page, doc = make(0)
    blanks = len(doc.pages) % 2
    if blanks:
        shelf, n_rows, run_size, page, doc = make(blanks)
    (out / "book.html").write_text(page)
    pdf = out / f"{cfg['slug']}.pdf"
    masters = {}
    if cfg["riso"]["second"]:
        look, masters = separations(root, cfg, page, out)
        doc = render(look, root)
    doc.write_pdf(pdf)
    total = len(doc.pages)
    spreads_file = out / f"{cfg['slug']}-spreads.pdf"
    spreads_pdf(cfg, pdf, spreads_file)
    folded, per_sheet = [], 0
    if cfg["riso"]["french_fold"]:
        folded, per_sheet = french_fold(cfg, {"look": pdf, **masters}, out)
    duplexed, per_side = [], 0
    if cfg["riso"]["duplex"]:
        duplexed, per_side = duplex(cfg, {"look": pdf, **masters}, out)

    cfg["_page_of"], cfg["_date"], cfg["_books"], cfg["_total"] = shelf.page_of, date, books, total
    sheet, info = cover_html(cfg, root, books, shelf, date, total, faces)
    cfg["_cover"] = info
    (out / "cover.html").write_text(sheet)
    sheet = sheet.replace("</style>", f".cover .spine {{ border-width: {cfg['cover']['hairline']}; }}\n</style>", 1)
    cover_pdf = out / f"{cfg['slug']}-cover.pdf"
    render(sheet, root).write_pdf(cover_pdf)
    cover_files = []
    if cfg["cover"]["riso"]:
        cover_files = cover_riso(cfg, root, sheet, cover_pdf, out)

    stamp = stamp_now()
    t = cfg["type"]
    spec = (f'{cfg["page"]["width"]} × {cfg["page"]["height"]} · {s["mode"]} · '
            f'spines at {s["scale"]:g} · {t["text"]} {t["size"]}/{t["leading"]}')
    write_preview(cfg, out, rasterize(pdf, out / "pages", dpi=72), stamp, spec)
    if not quiet:
        print(f"-> {pdf}\n   {total} pages: {len(books)} books on {n_rows} shelves, "
              f"{len(shelf.black)} black spines" + (", 1 blank page before the last" if blanks else "")
              + (f", the running line at {run_size:.1f}pt" if run_size else ""))
        print(f"-> {spreads_file}\n   the same, as spreads, for reading on screen and sharing")
        for key, f in masters.items():
            print(f"-> {f}\n   the {key} drum, as a black master")
        for key, f, n in folded:
            what = "the look" if key == "look" else f"the {key} drum"
            print(f"-> {f}\n   French fold, {what}: {n} sheets, {per_sheet} leaf{'' if per_sheet == 1 else 'ves'} to a sheet, one side only"
                  )
        for key, f, n in duplexed:
            what = "the look" if key == "look" else f"the {key} drum"
            print(f"-> {f}\n   double-sided, {what}: {n} sheets, {per_side} pages a side, flip on the long edge")
        print(f"-> {cover_pdf}\n   {info['W']:.3f} × {info['H']:.3f}in with bleed, spine {info['spine']:.3f}in, "
              f"every book at {info['scale']:.3f} on {info['shelves']} shelves")
        for f, what in cover_files:
            print(f"-> {f}\n   {what}")
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


# ------------------------------------------------------------------ site

def site(root, cfg, out=None, shelf_title="Bjorn Means Book"):
    """The book's page on a Bjook site: its cover, every spread in one row
    that scrolls sideways (on screen too the shelf keeps going), the files
    to read and to print it, and links. The shelf at the front of the site
    gets the book's real cover."""
    import contextlib, io, json, shutil, subprocess, datetime
    from poems import web_page, web_fonts, write_shelf
    from book import slugify, inline
    with contextlib.redirect_stdout(io.StringIO()):
        cfg = build(root, cfg, quiet=True)
    w = cfg["site"]
    smart = cfg["shelf"]["smart_quotes"]
    out = Path(out).expanduser().resolve() if out else root / "build" / "site"
    path = w["path"] or slugify(cfg["title"])
    dest = out / path
    if dest.exists() and not (dest / "book.json").is_file():
        die(f"{dest} exists and isn't a book this tool wrote — not replacing it")
    shutil.rmtree(dest, ignore_errors=True)
    (dest / "fonts").mkdir(parents=True)
    (dest / "spreads").mkdir()
    build_dir, slug = root / "build", cfg["slug"]
    e = html.escape

    # The files: to read, and to print.
    files = [(f"{slug}-spreads.pdf", "Read it", "as spreads, the way the book opens"),
             (f"{slug}.pdf", "Page by page", "in reading order")]
    if cfg["riso"]["french_fold"]:
        name = cfg["riso"]["name"]
        files += [(f"{slug}-french-fold-black.pdf", "Riso master: black", "French fold, one leaf to a sheet"),
                  (f"{slug}-french-fold-{name}.pdf", f"Riso master: {name}", "the second drum, same sheets"),
                  (f"{slug}-french-fold.pdf", "Both inks together", "to check a test print against")]
    files.append((f"{slug}-cover.pdf", "The cover", "back, spine and front, with bleed"))
    for f, *_ in files:
        shutil.copy2(build_dir / f, dest / f)

    # The cover's front, as the picture on the shelf and at the top here.
    c = cfg["_cover"]
    dpi = 150
    x = (c["bleed"] + c["page"][0] + c["spine"]) * dpi
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", "-x", str(round(x)),
                    "-y", str(round(c["bleed"] * dpi)), "-W", str(round(c["page"][0] * dpi)),
                    "-H", str(round(c["page"][1] * dpi)), str(build_dir / f"{slug}-cover.pdf"),
                    str(dest / "cover")], check=True)

    # Every spread as a picture, with words for anyone who can't see it.
    from pypdf import PdfReader
    n_spreads = len(PdfReader(build_dir / f"{slug}-spreads.pdf").pages)
    total = cfg["_total"]
    pw_px = round(c["page"][0] * w["dpi"])
    for i in range(1, n_spreads + 1):
        # A page alone (the first; the last, if it's a left-hand page) is
        # cut out of its half-empty spread.
        crop = []
        if i == 1:
            crop = ["-x", str(pw_px), "-W", str(pw_px)]
        elif i == n_spreads and total % 2 == 0:
            crop = ["-x", "0", "-W", str(pw_px)]
        subprocess.run(["pdftoppm", "-png", "-r", str(w["dpi"]), "-f", str(i), "-l", str(i), "-singlefile",
                        *crop, str(build_dir / f"{slug}-spreads.pdf"), str(dest / "spreads" / f"s-{i:02d}")],
                       check=True)
    pics = sorted((dest / "spreads").glob("s-*.png"))
    by_page = {}
    for b in cfg["_books"]:
        by_page.setdefault(cfg["_page_of"][b["slug"]], []).append(b["title"])
    run = (cfg.get("_run") or [[]])[0]
    figs = []
    for i, pic in enumerate(pics):
        pages = [1] if i == 0 else [p for p in (2 * i, 2 * i + 1) if p <= cfg["_total"]]
        titles = [t for p in pages for t in by_page.get(p, [])]
        label = f"Page{'s' if len(pages) > 1 else ''} {'–'.join(map(str, pages))}"
        if titles:
            alt = f"{label}: {len(titles)} spines on the shelf, from {titles[0]} to {titles[-1]}"
            spread = i - 1
            if 0 <= spread < len(run):
                alt += f", under the words “{run[spread]}”"
        elif i == 0:
            alt = f"{label}: the title page, {cfg['title']}, {cfg['_date']}"
        else:
            alt = f"{label}: the pages after the shelf"
        figs.append(f'<li><img src="spreads/{pic.name}" alt="{e(alt)}" loading="lazy"></li>')

    def md(name):
        p = root / name
        if not p.is_file():
            return ""
        out_ = md_page(p, cfg, fills(cfg, cfg["_books"], Shelf(cfg, cfg["_books"], 1, 1), cfg["_date"]))
        return out_.replace('<section class="back ', '<section class="text text-', 1)   # .cover is the shelf's
    rows = "".join(f'<li><a href="{f}">{e(label)}</a> <span>{e(note)}</span></li>' for f, label, note in files)
    links = "".join(f'<li><a href="{e(u)}">{e(l)}</a></li>' for l, u in w["links"])
    body = "\n".join([
        f'<header class="head"><a href="../index.html">{inline(shelf_title, smart)}</a></header>',
        '<main class="shelf-book">',
        '<div class="intro">',
        f'<img class="front" src="cover.png" alt="The cover: every book in the library on one bookcase, '
        f'with a label reading {e(cfg["title"])}, {e(cfg["_date"])}">',
        f'<div><h1 class="book-title">{inline(cfg["title"], smart)}</h1>',
        f'<p class="book-author">{inline(cfg["author"], smart)}, {e(cfg["_date"])}</p>',
        *(md(n) for n in w["text"]), "</div></div>",
        '<section class="spreads" aria-label="The book, spread by spread">',
        f'<ol tabindex="0">{"".join(figs)}</ol>',
        '<p class="hint">Scroll sideways: the shelf keeps going.</p></section>',
        f'<section class="files"><h2>Read it, print it</h2><ul>{rows}</ul></section>',
        *(f'<section class="links"><h2>Elsewhere</h2><ul>{links}</ul></section>' for _ in [1] if links),
        *(f'<section class="colophon">{md(n)}</section>' for n in w["after"] if (root / n).is_file()),
        "</main>"])
    page_html = web_page(cfg["title"], body, ["../kit.css", "../bjook.css", "fonts.css", "book.css"],
                         cfg["author"], f'{len(cfg["_books"])} books drawn as spines on one shelf',
                         frame="page wide")
    (dest / "index.html").write_text(page_html)
    chars = {ord(ch) for ch in html.unescape(page_html)} | set(range(0x20, 0x7F))
    (dest / "fonts.css").write_text(web_fonts(cfg, dest / "fonts", chars) + "\n")
    t = cfg["type"]
    (dest / "book.css").write_text((Path(__file__).parent / "shelf-site.css").read_text().replace(
        "/*FONT*/", f"'{alias(t['text'])}'"))
    (dest / "book.json").write_text(json.dumps({
        "title": cfg["title"], "author": cfg["author"], "path": path, "books": len(cfg["_books"]),
        "updated": datetime.date.today().isoformat(),
        "inches": [round(to_pt(cfg["page"][k]) / 72, 3) for k in ("width", "height")],
        "cover_image": "cover.png", "cover": "white-1", "title_font": alias(t["title"] or t["text"]),
        "head_font": alias(t["text"]), "head_weight": 400, "head_css": ""}, indent=2) + "\n")
    print(f"-> {dest / 'index.html'}\n   {len(pics)} spreads, {len(files)} files to download")
    write_shelf(out, shelf_title, smart)
