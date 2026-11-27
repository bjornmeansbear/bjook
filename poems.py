"""
Poems: plain-text poem files -> a typeset PDF, a saddle-stitch booklet, a
spread preview, a specimen of faces, and the book as a website.
"""
import contextlib
import datetime
import html
import io
import json
import re
import shutil
import time
import urllib.request
from pathlib import Path

from book import (HERE, alias, all_faces, book_families, die, document, find_family,
                  inline, page_css, page_of_anchors, rasterize, render, slugify,
                  snapshot, stamp_now, to_pt, write_preview)

API = "https://api.are.na/v3"
USER_AGENT = "arena-archive-script/1.0 (personal are.na export)"

DEFAULTS = {
    "arena": "",
    "book": {
        "contents": True,
        "colophon": "",
        "closing": "",
        "end_mark": "",                 # a sign under each poem's last line, e.g. "‡"
        "smart_quotes": True,
        "ink": "#000",
    },
    "site": {
        "path": "",                     # the book's folder on the site; empty = from the title
        "pdf": True,                    # offer the PDF and the booklet to download
        "cover": "",                    # the cover's tint on the shelf, a kit colour
                                        # like "goldenrod-1"; empty = picked for you
    },
}

# Pale kit tints a cover can take on the shelf; dark brown ink is AAA on each.
COVER_TINTS = ["goldenrod-1", "light-gray-1", "cornflower-1", "purple-1",
               "orange-1", "blue-1", "yellow-1", "pink-1"]

SPECIMEN_FACES = [
    "Gentium", "Spectral", "Libre Caslon Text", "Source Serif 4",
    "Cormorant Garamond", "Charis SIL", "Inria Serif", "Libre Baskerville",
]


def head(cfg, label=None):
    return page_css(cfg, {"--ink": cfg["book"]["ink"]}, cfg["book"]["smart_quotes"], label)


# ----------------------------------------------------------------- poems

def read_poem(path):
    """A poem file: optional ---frontmatter--- (title, arena, date), then the
    lines. A blank line is a stanza break."""
    text = path.read_text()
    meta = {}
    m = re.match(r"---\n(.*?)\n---\n?", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[m.end():]
    stanzas = [s.split("\n") for s in re.split(r"\n\s*\n", text.strip("\n")) if s.strip()]
    return {"file": path.name, "slug": slugify(path.stem), "title": meta.get("title", ""),
            "meta": meta, "stanzas": [[l.rstrip() for l in s] for s in stanzas]}


def ordered_poems(root):
    """order.txt is the sequence: one poem filename per line. Lines starting
    with # are left out of the book, so dropping a poem is commenting it."""
    order = root / "order.txt"
    if not order.is_file():
        die("no order.txt — run `bjook fetch`, or list poem filenames in it")
    poems = []
    for line in order.read_text().splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        path = root / "poems" / name
        if not path.is_file():
            die(f"order.txt lists {name}, but poems/{name} doesn't exist")
        poems.append(read_poem(path))
    if not poems:
        die("order.txt has no poems in it")
    return poems


def first_line(poem, limit=48):
    """What an untitled poem is called in the contents: its first line, cut
    at a word if it is long."""
    line = poem["stanzas"][0][0].strip()
    if len(line) <= limit:
        return line.rstrip(",;:—–- ")
    return line[:limit].rsplit(" ", 1)[0].rstrip(",;:.—–- ") + "…"


# ------------------------------------------------------------------ html

def stanzas_html(poem, smart):
    out = []
    for stanza in poem["stanzas"]:
        out.append('<div class="stanza">')
        for line in stanza:
            out.append(f'<div class="line">{inline(line, smart) or "&nbsp;"}</div>')
        out.append("</div>")
    return out


def poem_html(poem, smart, extra="", end_mark=""):
    out = [f'<section class="poem" id="{poem["slug"]}"{extra}>']
    if poem["title"]:
        out.append(f'<h2 class="poem-title">{inline(poem["title"], smart)}</h2>')
    else:
        out.append('<div class="poem-title untitled" aria-hidden="true">&nbsp;</div>')
    out += stanzas_html(poem, smart)
    if end_mark:
        out.append(f'<div class="poem-end marked" id="{poem["slug"]}--end" aria-hidden="true">'
                   f'{html.escape(end_mark)}</div>')
    else:
        out.append(f'<div class="poem-end" id="{poem["slug"]}--end"></div>')
    out.append("</section>")
    return "\n".join(out)


def book_html(cfg, poems, root, blanks=0):
    smart = cfg["book"]["smart_quotes"]
    faces = all_faces(book_families(cfg), cfg["type"]["fonts_dir"])
    parts = [f"""<section class="title-page">
<h1 class="book-title">{inline(cfg['title'], smart)}</h1>
<p class="book-author">{inline(cfg['author'], smart)}</p>
</section>"""]
    if cfg["book"]["contents"]:
        rows = []
        for poem in poems:
            if poem["title"]:
                label = inline(poem["title"], smart)
            else:
                label = f'<em>{inline(first_line(poem), smart)}</em>'
            rows.append(f'<li><a href="#{poem["slug"]}"><span class="toc-title">{label}</span></a></li>')
        parts.append('<nav class="contents"><h2 class="contents-title">Contents</h2>'
                     f'<ol>{"".join(rows)}</ol></nav>')
    parts += [poem_html(poem, smart, end_mark=cfg["book"]["end_mark"]) for poem in poems]
    parts += ['<div class="blank"></div>'] * blanks
    if cfg["book"]["colophon"] or cfg["book"]["closing"]:
        back = ""
        if cfg["book"]["closing"]:
            back += f'<p class="book-closing">{inline(cfg["book"]["closing"], smart)}</p>'
        if cfg["book"]["colophon"]:
            paras = "".join(f"<p>{inline(p.strip(), smart)}</p>"
                            for p in cfg["book"]["colophon"].strip().split("\n\n"))
            back += f'<div class="colophon">{paras}</div>'
        parts.append(f'<section class="back-page">{back}</section>')
    return document(cfg, "\n".join(parts), faces, root, "book.css", head(cfg))


# ----------------------------------------------------------------- build

def impose(src, dest, cfg):
    """Saddle-stitch imposition: two pages side by side on a sheet twice the
    page width, ordered so the printed stack folds into the book. Print
    double-sided, flipping on the SHORT edge."""
    from pypdf import PdfReader, PdfWriter, PageObject, Transformation
    pages = PdfReader(src).pages
    n = len(pages)
    assert n % 4 == 0
    w, h = to_pt(cfg["page"]["width"]), to_pt(cfg["page"]["height"])
    writer = PdfWriter()
    for s in range(n // 4):
        for left, right in ((n - 1 - 2 * s, 2 * s), (2 * s + 1, n - 2 - 2 * s)):
            sheet = PageObject.create_blank_page(width=2 * w, height=h)
            sheet.merge_page(pages[left])
            sheet.merge_transformed_page(pages[right], Transformation().translate(w, 0))
            writer.add_page(sheet)
    writer.write(dest)
    return n // 4


def build(root, cfg, snap=None, quiet=False):
    poems = ordered_poems(root)
    out = root / "build"
    out.mkdir(exist_ok=True)

    doc = render(book_html(cfg, poems, root), root)
    n = len(doc.pages)
    blanks = (4 - n % 4) % 4
    if blanks:
        doc = render(book_html(cfg, poems, root, blanks), root)
        if len(doc.pages) % 4:
            die(f"padding to a multiple of 4 failed ({len(doc.pages)} pages)")
    total = len(doc.pages)

    pdf = out / f"{cfg['slug']}.pdf"
    booklet = out / f"{cfg['slug']}-booklet.pdf"
    doc.write_pdf(pdf)
    sheets = impose(pdf, booklet, cfg)
    stamp = stamp_now()
    write_preview(cfg, out, rasterize(pdf, out / "pages"), stamp)

    over = overflowing(doc, poems)
    if not quiet or over:
        pad = f" ({n} + {blanks} blank)" if blanks else ""
        print(f"-> {pdf}\n   {len(poems)} poems, {total} pages{pad}, {sheets} sheets")
        print(f"-> {booklet}\n   print double-sided, flip on the short edge")
        print(f"-> {out / 'preview.html'}")
        for title, pages in over:
            print(f"   runs {pages} pages: {title}")
    if snap is not None:
        snapshot(root, (pdf, booklet), stamp, snap)
    return cfg


def overflowing(doc, poems):
    """Poems that run past one page — the first thing to look at when a
    margin or type size changes. Every poem and every poem's end has an id,
    and WeasyPrint records which page each id landed on."""
    page_of = page_of_anchors(doc)
    out = []
    for poem in poems:
        start, end = page_of.get(poem["slug"]), page_of.get(poem["slug"] + "--end")
        if start and end and end > start:
            out.append((poem["title"] or first_line(poem), end - start + 1))
    return out


def sources(root):
    return [root / "book.toml", root / "order.txt", root / "style.css",
            *(root / "poems").glob("*.md")]


# -------------------------------------------------------------- specimen

def specimen(root, cfg, families, poem_name=None):
    poems = ordered_poems(root)
    poem = next((p for p in poems if p["file"] == poem_name), None) if poem_name else None
    if poem_name and not poem:
        die(f"{poem_name} isn't in order.txt")
    poem = poem or max((p for p in poems if p["title"]),
                       key=lambda p: -abs(sum(map(len, p["stanzas"])) - 22))
    t = cfg["type"]
    families = list(dict.fromkeys(families or SPECIMEN_FACES))
    parts = []
    for i, fam in enumerate(families):
        a = alias(fam)
        style = (f' style="font-family: \'{a}\'; --font-display: \'{a}\'; '
                 f'string-set: face \'{fam}\'"')
        one = dict(poem, slug=f"spec{i}")
        parts.append(poem_html(one, cfg["book"]["smart_quotes"], style))
    faces = all_faces(families + book_families(cfg), t["fonts_dir"])
    label = f'{t["size"]}/{t["leading"]}'
    out = root / "build"
    out.mkdir(exist_ok=True)
    pdf = out / "specimen.pdf"
    render(document(cfg, "\n".join(parts), faces, root, "book.css", head(cfg, label), label),
           root).write_pdf(pdf)
    rasterize(pdf, out / "specimen")
    print(f"-> {pdf}\n   “{poem['title']}” in {len(parts)} faces at {label}")


# ------------------------------------------------------------------ site

def web_page(title, body, css, author="", description="", frame="page"):
    """One page of the site. `css` is the stylesheets to link, in order;
    `frame` is the class on the wrapper: "page" is one reading column,
    "page wide" runs the width of the window, "" leaves the body bare."""
    meta = "".join(f'\n<meta name="{k}" content="{html.escape(v)}">'
                   for k, v in (("author", author), ("description", description)) if v)
    links = "".join(f'\n<link rel="stylesheet" href="{href}">' for href in css)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>{meta}{links}
</head><body><div class="{frame}">
{body}
</div></body></html>
"""


def web_fonts(cfg, dest, chars):
    """The book's fonts as .woff2 files holding only the characters the site
    uses, and the @font-face rules for them. The text face keeps regular and
    bold, upright and italic; the others keep every cut they have."""
    from fontTools import subset
    t = cfg["type"]
    body = {t["text"], t["display"]}
    rules = []
    for family in dict.fromkeys([t["text"], t["display"], t["title"],
                                 cfg["head"]["font"], cfg["folio"]["font"]]):
        done = set()
        for _, weight, italic, wght, path in find_family(family, t["fonts_dir"]):
            key = (wght or weight, italic)
            if key in done or (family in body and not wght and weight not in (400, 700)):
                continue
            done.add(key)
            name = f"{alias(family)}-{weight}{'i' if italic else ''}.woff2"
            opts = subset.Options(flavor="woff2", layout_features=["*"])
            opts.drop_tables += ["Silf", "Silt", "Sill", "Glat", "Gloc", "Feat"]  # Graphite: unused on the web
            font = subset.load_font(str(path), opts)
            cut = subset.Subsetter(opts)
            cut.populate(unicodes=chars)
            cut.subset(font)
            subset.save_font(font, str(dest / name), opts)
            w = f"{wght[0]} {wght[1]}" if wght else weight
            rules.append(
                f"@font-face {{ font-family: '{alias(family)}'; "
                f"src: url('fonts/{name}') format('woff2'); font-weight: {w}; "
                f"font-style: {'italic' if italic else 'normal'}; font-display: swap; }}")
    return "\n".join(rules)


def linked(text):
    """Web addresses in already-escaped text, made into links."""
    return re.sub(r"(?:https?://|(?<![\w/.])(?=[\w-]+\.(?:com|org|net|co)/))[^\s<]+[^\s<.,;:!?)”’]",
                  lambda m: '<a href="{0}{1}">{1}</a>'.format(
                      "" if m.group(0).startswith("http") else "https://", m.group(0)),
                  text)


# The shelf's "Made with Bjook" page. Written by him; edit here, not in the
# built site.
ABOUT = [
    "I made these books with Bjook, a tool I wrote for myself. I write each "
    "poem as a plain text file. Bjook sets them in a typeface, lays out the "
    "pages, and makes three things: a PDF of the book, a booklet to print "
    "double-sided, fold and staple, and this website. It makes newspapers too.",
    'The code is on GitHub: <a href="https://github.com/bjornmeansbear/bjook">'
    "github.com/bjornmeansbear/bjook</a>",
    "It fits how I make books and probably nobody else\u2019s. Fork it if it is "
    "useful to you. I can\u2019t offer support.",
]


def write_shelf(out, shelf_title="Bjorn Means Book", smart=True):
    """The pages every book in a site folder shares: the shelf at the front,
    listing each book that has a book.json, newest first, and the page about
    Bjook. Rewritten by whichever book was published last."""
    shutil.copy2(HERE / "kit.css", out / "kit.css")
    shutil.copy2(HERE / "site.css", out / "bjook.css")
    books = sorted((json.loads(p.read_text()) for p in out.glob("*/book.json")),
                   key=lambda b: b["updated"], reverse=True)
    def cover(b):
        # A book whose site made a picture of its cover stands as that picture.
        if b.get("cover_image"):
            return (f'<li><a class="cover cover-image" href="{b["path"]}/index.html" '
                    f'style="--w: {b["inches"][0]}; --h: {b["inches"][1]}">'
                    f'<img src="{b["path"]}/{b["cover_image"]}" alt="{html.escape(b["title"])}"></a></li>')
        return (f'<li><a class="cover" href="{b["path"]}/index.html" style="--w: {b["inches"][0]}; '
        f'--h: {b["inches"][1]}; --cover: var(--{b["cover"]}); --font-title: \'{b["title_font"]}\'; '
        f'--font-head: \'{b["head_font"]}\'; --head-weight: {b["head_weight"]}">'
        f'<span class="cover-title">{inline(b["title"], smart)}</span>'
        f'<span class="cover-author" style="{html.escape(b["head_css"])}">{inline(b["author"], smart)}</span>'
        "</a></li>")
    shelf = "".join(cover(b) for b in books)
    (out / "index.html").write_text(web_page(
        shelf_title,
        f'<main><h1 class="site-title">{inline(shelf_title, smart)}</h1>'
        f'<ul class="shelf">{shelf}<li class="rest" role="presentation"></li></ul>'
        '<p class="shelf-note"><a href="bjook.html">Made with Bjook</a></p></main>',
        ["kit.css", "bjook.css"] + [f'{b["path"]}/fonts.css' for b in books], frame=""))
    (out / "bjook.html").write_text(web_page(
        "Bjook", "\n".join([
            f'<header class="head"><a href="index.html">{inline(shelf_title, smart)}</a></header>',
            "<main><h1>Bjook</h1>",
            *(f"<p>{p}</p>" for p in ABOUT),
            "</main>"]),
        ["kit.css", "bjook.css"], description="The tool that makes these books."))
    print(f"-> {out / 'index.html'}\n   the shelf: {len(books)} book{'s' if len(books) != 1 else ''}")


def site(root, cfg, out=None, shelf_title="Bjorn Means Book"):
    """The book as a website: a front page with the contents, one page per
    poem, the PDFs to download, and a shelf page listing every book that has
    been written into the same folder."""
    with contextlib.redirect_stdout(io.StringIO()):     # the PDFs, without build's report
        build(root, cfg, quiet=True)
    poems = ordered_poems(root)
    book, smart = cfg["book"], cfg["book"]["smart_quotes"]
    kit = HERE / "kit.css"
    if not kit.is_file():
        die(f"can't find kit.css at {kit}")
    out = Path(out).expanduser().resolve() if out else root / "build" / "site"
    path = cfg["site"]["path"] or slugify(cfg["title"])
    dest = out / path
    if dest.exists() and not (dest / "book.json").is_file():
        die(f"{dest} exists and isn't a book this tool wrote — not replacing it")
    if any(p["slug"] == "index" for p in poems):
        die("a poem file named index.md would overwrite the book's front page")
    shutil.rmtree(dest, ignore_errors=True)
    (dest / "fonts").mkdir(parents=True)

    title = inline(cfg["title"], smart)
    css = ["../kit.css", "../bjook.css", "fonts.css", "book.css"]
    cover = cfg["site"]["cover"] or COVER_TINTS[sum(cfg["title"].encode()) % len(COVER_TINTS)]
    if not re.fullmatch(r"[a-z]+(-[a-z]+)*-\d", cover):
        die(f"[site] cover {cover!r} isn't a kit colour like \"goldenrod-1\"")
    names = [inline(p["title"], smart) if p["title"]
             else f"<em>{inline(first_line(p), smart)}</em>" for p in poems]
    pages = {}
    for i, poem in enumerate(poems):
        plain = re.sub(r"<[^>]+>", "", names[i])
        heading = (f'<h1 class="poem-title">{names[i]}</h1>' if poem["title"]
                   else f'<h1 class="visually-hidden">{plain}</h1>')
        end = (f'<div class="poem-end" aria-hidden="true">{html.escape(book["end_mark"])}</div>'
               if book["end_mark"] else "")
        prev = (f'<a class="prev" rel="prev" href="{poems[i - 1]["slug"]}.html">'
                f'<span aria-hidden="true">← </span>{names[i - 1]}</a>' if i
                else '<a class="prev" href="index.html"><span aria-hidden="true">← </span>Contents</a>')
        nxt = (f'<a class="next" rel="next" href="{poems[i + 1]["slug"]}.html">'
               f'{names[i + 1]}<span aria-hidden="true"> →</span></a>' if i + 1 < len(poems)
               else '<a class="next" href="index.html">Contents<span aria-hidden="true"> →</span></a>')
        body = "\n".join([
            f'<header class="head"><a href="index.html">{title}</a></header>',
            f'<main><article class="poem">{heading}', *stanzas_html(poem, smart), end,
            "</article></main>",
            f'<nav class="turn" aria-label="Poems">{prev}'
            f'<span class="folio"><span class="visually-hidden">Poem </span>{i + 1}'
            f'<span class="visually-hidden"> of {len(poems)}</span></span>{nxt}</nav>'])
        pages[f'{poem["slug"]}.html'] = web_page(
            f'{html.unescape(plain)} — {cfg["title"]}', body, css, cfg["author"])

    rows = "".join(f'<li><a href="{p["slug"]}.html"><span class="toc-n">{i}</span>'
                   f'<span class="toc-title">{names[i - 1]}</span></a></li>'
                   for i, p in enumerate(poems, 1))
    front = [f'<header class="head"><a href="../index.html">{inline(shelf_title, smart)}</a></header>',
             f'<main><h1 class="book-title">{title}</h1>',
             f'<p class="book-author">{inline(cfg["author"], smart)}</p>',
             f'<nav class="contents" aria-label="Contents"><h2>Contents</h2><ol>{rows}</ol></nav>']
    if book["closing"]:
        front.append(f'<p class="book-closing">{inline(book["closing"], smart)}</p>')
    colophon = [f"<p>{linked(inline(p.strip(), smart))}</p>"
                for p in book["colophon"].strip().split("\n\n") if p.strip()]
    if cfg["site"]["pdf"]:
        for suffix in ("", "-booklet"):
            shutil.copy2(root / "build" / f"{cfg['slug']}{suffix}.pdf", dest / f"{path}{suffix}.pdf")
        colophon.append(
            f'<p>To print a copy: <a href="{path}.pdf">the book, page by page</a> (PDF), or '
            f'<a href="{path}-booklet.pdf">the booklet</a> (PDF) on letter paper, '
            "double-sided, flipped on the short edge, then folded and stapled.</p>")
    if colophon:
        front.append(f'<section class="colophon" id="colophon"><h2>Colophon</h2>{"".join(colophon)}</section>')
    front.append("</main>")
    pages["index.html"] = web_page(cfg["title"], "\n".join(front), css, cfg["author"],
                                   f'{len(poems)} poems by {cfg["author"]}' if cfg["author"] else "",
                                   frame="page wide")

    for name, text in pages.items():
        (dest / name).write_text(text)
    chars = {ord(c) for text in pages.values() for c in html.unescape(text)}
    t, h, f = cfg["type"], cfg["head"], cfg["folio"]
    own = root / "site.css"
    (dest / "fonts.css").write_text(
        web_fonts(cfg, dest / "fonts", chars | set(range(0x20, 0x7F))) + "\n")
    (dest / "book.css").write_text("\n".join([
        ":root {",
        f"  --font-text: '{alias(t['text'])}'; --font-display: '{alias(t['display'])}';",
        f"  --font-title: '{alias(t['title'])}';",
        f"  --font-head: '{alias(h['font'])}'; --head-weight: {h['weight']};",
        f"  --font-folio: '{alias(f['font'])}'; --folio-weight: {f['weight']};",
        "}",
        f".head {{ {h['css']} }}",
        own.read_text() if own.is_file() else ""]))
    (dest / "book.json").write_text(json.dumps({
        "title": cfg["title"], "author": cfg["author"], "path": path, "poems": len(poems),
        "updated": datetime.date.today().isoformat(),
        # What the shelf needs to draw this book's cover.
        "inches": [round(to_pt(cfg["page"][k]) / 72, 3) for k in ("width", "height")],
        "cover": cover, "title_font": alias(t["title"]), "head_font": alias(h["font"]),
        "head_weight": h["weight"], "head_css": h["css"]}, indent=2) + "\n")

    write_shelf(out, shelf_title, smart)
    print(f"-> {dest / 'index.html'}\n   {len(poems)} poems, {len(pages)} pages, "
          f"{len(list((dest / 'fonts').iterdir()))} fonts")


# ----------------------------------------------------------------- fetch

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def fetch(root, cfg, force=False):
    if not cfg["arena"]:
        die("book.toml has no `arena = \"<channel-slug>\"`")
    blocks, page = [], 1
    while True:
        data = get_json(f"{API}/channels/{cfg['arena']}/contents?per=100&page={page}")
        blocks += data["data"]
        if not data["meta"]["has_more_pages"]:
            break
        page += 1
        time.sleep(0.2)
    blocks = [b for b in blocks if b.get("type") == "Text"]
    blocks.sort(key=lambda b: b["connection"]["connected_at"])

    poems_dir = root / "poems"
    poems_dir.mkdir(exist_ok=True)
    have = {}
    for path in poems_dir.glob("*.md"):
        have[read_poem(path)["meta"].get("arena")] = path
    order = root / "order.txt"
    listed = order.read_text() if order.is_file() else (
        "# The book's sequence: one poem file per line, top to bottom.\n"
        "# Reorder lines to resequence. Put # in front of a line to leave\n"
        "# that poem out.\n\n")
    new = kept = 0
    for b in blocks:
        content = b["content"]
        text = (content.get("markdown") or content.get("plain") or "") if isinstance(content, dict) else (content or "")
        text = text.replace("\r\n", "\n").strip("\n")
        title = (b.get("title") or "").strip()
        # A first line that is all bold, or a markdown heading, is the title.
        m = re.match(r"\s*(?:\*\*(.+?)\*\*|#+[ \t]*(.+?))[ \t]*(?:\n+|$)", text)
        if m:
            title = title or (m.group(1) or m.group(2)).strip()
            text = text[m.end():]
        lines = [re.sub(r"(\\|  +)$", "", l).rstrip() for l in text.split("\n")]
        text = "\n".join(lines)
        first = next((l for l in lines if l.strip()), "untitled")
        date = b["connection"]["connected_at"][:10]
        body = f"---\ntitle: {title}\narena: {b['id']}\ndate: {date}\n---\n\n{text}\n"
        path = have.get(str(b["id"]))
        if path and not force:
            kept += 1
            continue
        if not path:
            stem = slugify(title or first, 40)
            path = poems_dir / f"{stem}.md"
            i = 2
            while path.exists():
                path = poems_dir / f"{stem}-{i}.md"
                i += 1
            listed += path.name + "\n"
            new += 1
        path.write_text(body)
    order.write_text(listed)
    print(f"{len(blocks)} text blocks in {cfg['arena']}: {new} new, "
          f"{kept} already here (left alone)" + (", rest rewritten" if force else ""))
