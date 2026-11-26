# Bjook

Plain text in, a typeset PDF out, with a preview of the pages as facing
spreads that reloads when you save. Three kinds of book, set by `kind` in
`book.toml`:

- **poems** (the default): also a booklet imposed for saddle stitch, and the
  book as a website.
- **paper**: a tabloid newspaper, composed page by page (see "Newspapers"
  below).
- **shelf**: a catalogue of books drawn as spines on a shelf, with an index,
  a colophon and a wraparound cover (see "Shelves" below).

The design reasoning lives in `~/Code/color-system-and-guidelines/RULES.md`,
**"Bjook"**. This file is how to run it.

## Built with it

- `~/Code/a-poem-a-day` — 56 poems from the are.na channel of the same name
- `~/Code/chair-ness/paper` — the Chair-ness newspaper, first edition
- `~/Code/library/book` — *A Library*, the books on my office shelves, from library.wjerk.shop

## The code

| | |
|---|---|
| `bjook.py` | The commands. Reads `kind` and hands off. |
| `book.py` | What every kind shares: `book.toml`, typographer's marks, fonts, `@page` rules and margin boxes, rendering, the preview, snapshots, `watch`. |
| `poems.py`, `book.css` | Poems: the book, the booklet, the specimen, the website (`site.css`). |
| `paper.py`, `paper.css` | Newspapers. |
| `shelf.py`, `shelf.css` | Shelves: spines, index, colophon, cover. |
| `kit.css` | A copy of the kit's, for the website. Re-copy it from `~/Code/color-system-and-guidelines` when the kit changes. |
| `template/<kind>/` | What `bjook new` copies. |

## Setup, once

```sh
pipx install weasyprint
pipx inject weasyprint pypdf
brew install poppler          # pdftoppm, for the preview images
brew install pandoc           # paper: Markdown into pages
```

`./bjook` runs `bjook.py` on the Python inside that pipx venv. An alias
saves typing:

```sh
alias bjook=~/Code/bjook/bjook
```

## Use

```sh
bjook new ~/Code/my-book --channel <are.na-slug>
bjook new ~/Code/my-paper --kind paper
cd ~/Code/my-book

bjook fetch                 # text blocks -> poems/*.md, listed in order.txt
bjook watch                 # http://127.0.0.1:8642/preview.html, rebuilds on save
bjook build                 # one build, no server
bjook build --snap "note"   # also keep a timestamped copy in snapshots/
bjook specimen              # one poem in eight faces -> build/specimen.pdf
bjook specimen "Spectral" "Inria Serif" --poem some-poem.md
bjook site                  # the book as a website -> build/site/
bjook site --out ~/Code/bjornmeansbook   # into a shared site folder
```

Every command takes `--root` before it, defaulting to the current folder.

## A book folder

| | |
|---|---|
| `book.toml` | Title, author, page size, margins, typeface, size, leading; where the page number sits (`[folio]`); an optional running head (`[head]`) and continues mark (`[continues]`). The template lists every setting. |
| `order.txt` | The sequence, one poem filename per line. Move lines to reorder. `#` in front of a line leaves that poem out. |
| `poems/*.md` | One poem each: a few `key: value` lines between `---` (title, are.na id, date), then the lines. A blank line is a stanza break. `*italic*` and `**bold**` work; leading spaces indent. |
| `style.css` | This book's print overrides, applied after the tool's `book.css`. |
| `site.css` | Optional. This book's website overrides, applied after the tool's `site.css`. |
| `build/` | Output. Disposable, gitignored. |
| `snapshots/` | Proofs kept on purpose. |

`fetch` never overwrites a poem already on disk (it matches on the are.na id),
so edits made here are safe and a re-run only adds what's new. `fetch --force`
replaces local text with the channel's.

## Output

- `build/<slug>.pdf` — pages in reading order. Send this to a print shop that
  imposes for you, or read it on screen.
- `build/<slug>-booklet.pdf` — two pages to a sheet, ordered for folding. Print
  double-sided, **flip on the short edge**, fold the stack, staple the spine.
- `build/preview.html` — facing pages. **Guides** draws the text block and
  baselines; **Actual size** shows the page at its printed width.

- `build/site/` — from `bjook site`: a front page with the contents and
  colophon, one page per poem, the two PDFs to download, and `index.html`,
  a bookshelf with a cover for every book in the folder (`[site] cover`
  sets a cover's tint). Plain static files with no
  JavaScript; open `index.html` directly or upload the folder to any host.
  With `--out`, several books share one site folder, each in a folder named
  from its title (or `[site] path`), and the shelf lists them all.

The build pads the page count to a multiple of four and lists any poem that
runs past one page.

## Newspapers

Built for the tabloid at printnewspaper.com: 260 × 370 mm, a multiple of
four pages, single pages in reading order, no bleed, 10 mm of white at
every edge except across the fold of a spread.

| | |
|---|---|
| `book.toml` | `kind = "paper"`, then page, type, `[paper]` (columns, gutter, edition) and `[color]`. The template lists every setting. |
| `order.txt` | One page file per line. After the name, `plain` drops the page number and running head, and `spread` lays the file across two facing pages. `#` starts a comment. |
| `pages/*.html` | One page each, a fragment of HTML. HTML comments are notes and don't print. |
| `style.css` | This paper's overrides, after the tool's `paper.css`. |

On a page:

- **The grid:** `<div class="grid">` with `.span-1` … `.span-N` children.
- **Running text:** `<article class="cols-3" data-md="../text/essay.md"></article>`
  pulls in a Markdown file (path from the paper's folder) through pandoc.
  `data-until="Check:"` stops at the first line starting with that, so notes
  under a draft stay out. Text flows column to column and on to the next
  page. Keep long text **out of** a `.grid`: WeasyPrint can't break a grid
  item across pages and crashes.
- **Photos:** `<img src="images/chair-01.jpg">`. Keep the originals in
  colour; the build writes the press copy to `build/img/`. Until a photo
  exists: `<div class="placeholder" style="height: 80mm">What goes here</div>`.
- **Structure:** `hr`, `.rule-heavy`, `.box`. `.reverse` is light text on
  four-colour black. Type: `.headline`, `.kicker`, `.deck`, `.byline`,
  `.pull`, `figcaption`.

`[color] mode = "gray"` makes every photo black and white, then CMYK.
`"color"` keeps the colour. Text and rules are black ink only either way.

The build reports which pages each file landed on, and warns about: a
spread that isn't the middle sheet, a spread cut off at its foot, a blank
page the layout had to insert, padding to reach a multiple of four, a margin
inside the printer's 10 mm, and a photo under 200 ppi at its printed size.
`build/paper.html` is the HTML WeasyPrint saw, for debugging.

## Shelves

A catalogue drawn as spines standing on a shelf, A to Z, at a fraction of
their real size, each spine set in its book's own typeface. Planned by
spread: a shelf runs straight through the fold and sits at the same height
on every page, so `mode = "endless"` reads as one shelf through the whole
book, and `"wall"` as a bookcase two shelves high on each spread.

| | |
|---|---|
| `book.toml` | `kind = "shelf"`, then page, type, `[shelf]` (the data, mode, scale, `black_tags`, what comes after the shelf), `[cover]` and one `[faces.<key>]` per typeface. The template lists every setting. |
| `essay.md`, `colophon.md` | Pages after the shelf, as Markdown, in the order `[shelf] back` lists them, with `"index"` for the index. The last one ends the book. `{books}`, `{date}`, `{scale}`, `{sizes}`, `{black}` fill themselves in; `{faces}` on its own line lists the typefaces, each set in itself. |
| `cover.md` | The card on the back cover. |
| `running.txt` | Optional, named by `[shelf] running`: one line of type across the top of every shelf spread, through the fold and cut wherever a page ends, sized so it starts on the first spread and ends on the last (after Agel and Fiore's paperbacks). |
| `style.css` | This book's overrides, after the tool's `shelf.css`. |

Output: `build/<slug>.pdf`, the pages in reading order, padded to an even
count so the last item lands on the last page; and `build/<slug>-cover.pdf`,
back, spine and front as one sheet with bleed, every book at once at the
largest scale that fits, with the title and the back text on label cards.
The spine width comes from the page count and `[cover] caliper`. The build
warns when the spine is too thin for type or the book too short to perfect
bind.

`fetch`, `specimen` and `site` are for poems only so far.

## Publishing the site

The live site is `~/Code/bjornmeansbook`, a git repo that holds only built
output (GitHub `bjornmeansbear/bjornmeansbook`, served at
https://www.bjornmeansbook.com/). Never edit it by hand. To publish or update
a book, from that book's folder:

```sh
bjook site --out ~/Code/bjornmeansbook
cd ~/Code/bjornmeansbook
git add -A && git commit -m "Update <book>" && git push
```

Cloudflare redeploys on every push to `main`. The shelf is rebuilt from every
book already in the repo, so publishing a second book leaves the first alone.
The repo's own README has the hosting setup.

## Typefaces

`[type] text = "Gentium"` is a family name as the font spells it, looked up
under `fonts_dir` (default `~/Code/libreFontLibrary/Families`). If the name
isn't found, the error lists the families in the nearest folder: one folder
often holds several (`Cormorant`, `Cormorant Garamond`).
