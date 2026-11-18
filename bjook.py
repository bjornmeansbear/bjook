#!/usr/bin/env python3
"""
bjook — plain text -> a typeset PDF and a spread preview in the browser.
Two kinds so far, set by `kind` in book.toml: poems (the default; also a
saddle-stitch booklet and a website) and paper (a tabloid newspaper).

    bjook new ~/Code/my-book --channel <are.na-slug>
    bjook new ~/Code/my-paper --kind paper
    bjook fetch            # poems: pull are.na text blocks into poems/
    bjook build            # build/<slug>.pdf and preview.html
    bjook build --snap "first proof"
    bjook watch            # rebuild on save, preview reloads itself
    bjook specimen Gentium Spectral "Libre Caslon Text"
    bjook site             # poems: build/site, the book as a website

Run from inside a book folder, or pass --root. The design reasoning lives
in RULES.md, "Bjook", in ~/Code/color-system-and-guidelines; README.md here
is how to run it.

Runs on the Python inside WeasyPrint's pipx venv (the `bjook` wrapper
next to this file finds it), which also carries fontTools, Pillow and pypdf.
"""
import argparse
import re
import shutil
from pathlib import Path

import book
import paper
import poems

KINDS = {"poems": poems, "paper": paper}


def kind_of(root):
    name = book.read_toml(root).get("kind", "poems")
    if name not in KINDS:
        book.die(f"kind = {name!r} — bjook knows {', '.join(KINDS)}")
    return name, KINDS[name]


def load(root):
    name, mod = kind_of(root)
    return name, mod, book.load_config(root, mod.DEFAULTS)


def only(kind, wanted, cmd):
    if kind != wanted:
        book.die(f"`bjook {cmd}` is for {wanted}; this book is kind = {kind!r}")


def new(dest, kind, channel):
    dest = Path(dest).expanduser()
    if (dest / "book.toml").exists():
        book.die(f"{dest} already has a book.toml")
    template = book.HERE / "template" / kind
    dest.mkdir(parents=True, exist_ok=True)
    for src in template.rglob("*"):
        if src.is_file():
            to = dest / src.relative_to(template)
            to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, to)
    toml = dest / "book.toml"
    if channel:
        toml.write_text(re.sub(r'^arena\s*=\s*""', f'arena  = "{channel}"',
                               toml.read_text(), flags=re.M))
    if kind == "poems":
        (dest / "poems").mkdir(exist_ok=True)
    (dest / ".gitignore").write_text("build/\n.DS_Store\n")
    then = "`bjook fetch` and `bjook build`" if kind == "poems" else "pages/ and order.txt, then `bjook watch`"
    print(f"-> {dest}\n   edit book.toml, then {then}")


def main():
    ap = argparse.ArgumentParser(prog="bjook", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="the book folder (default: here)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="start a book folder")
    n.add_argument("dest")
    n.add_argument("--kind", choices=list(KINDS), default="poems")
    n.add_argument("--channel", help="are.na channel slug to pull poems from")
    f = sub.add_parser("fetch", help="poems: pull are.na text blocks into poems/")
    f.add_argument("--force", action="store_true",
                   help="overwrite poems already on disk with the channel's text")
    b = sub.add_parser("build", help="build the PDF and the preview")
    b.add_argument("--snap", nargs="?", const="", metavar="NOTE",
                   help="also keep a timestamped copy in snapshots/")
    w = sub.add_parser("watch", help="rebuild on save and serve the preview")
    w.add_argument("--port", type=int, default=8642)
    s = sub.add_parser("specimen", help="poems: one poem set in several faces")
    s.add_argument("families", nargs="*")
    s.add_argument("--poem", help="poem filename to use")
    web = sub.add_parser("site", help="poems: the book as a website, one page per poem")
    web.add_argument("--out", help="the site folder; each book gets a folder inside "
                                   "(default: build/site in the book)")
    web.add_argument("--shelf", default="Bjorn Means Book", metavar="TITLE",
                     help="the name on the page that lists every book")
    args = ap.parse_args()
    root = Path(args.root).expanduser().resolve()
    if args.cmd == "new":
        return new(args.dest, args.kind, args.channel)
    kind, mod, cfg = load(root)
    if args.cmd == "build":
        mod.build(root, cfg, args.snap)
    elif args.cmd == "watch":
        # Config is re-read on every build, so an edit to book.toml shows.
        book.watch(root, args.port,
                   lambda r, quiet: mod.build(r, load(r)[2], quiet=quiet), mod.sources)
    elif args.cmd == "fetch":
        only(kind, "poems", "fetch")
        poems.fetch(root, cfg, args.force)
    elif args.cmd == "specimen":
        only(kind, "poems", "specimen")
        poems.specimen(root, cfg, args.families, args.poem)
    elif args.cmd == "site":
        only(kind, "poems", "site")
        poems.site(root, cfg, args.out, args.shelf)


if __name__ == "__main__":
    main()
