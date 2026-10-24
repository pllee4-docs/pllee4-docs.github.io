#!/usr/bin/env python3
"""
Static index generator.

Walks content/, copies everything to the output directory, and writes an
index.html for every directory that does not already have one. Titles come
from each page's <title> tag, folder titles from an optional _meta.json.

Usage:
    python3 build.py                        # build into _site/
    python3 build.py --serve                # build, then serve on :8000
    python3 build.py --out _site/preview --staging
"""

import argparse
import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets"

SITE_TITLE = "pllee4 docs"
SITE_TAGLINE = "Notes, explainers and interactive write-ups."

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
DESC_RE = re.compile(
    r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', re.I | re.S
)
BODY_CLOSE_RE = re.compile(r"</body\s*>", re.I)

# Injected into every page when --staging is set.
STAGING_BANNER = """
<div id="staging-banner" style="position:fixed;top:0;left:0;right:0;z-index:2147483647;
background:#d4760a;color:#fff;font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
letter-spacing:.08em;text-transform:uppercase;text-align:center;padding:7px 10px;
box-shadow:0 1px 6px rgba(0,0,0,.25)">
staging preview &mdash; not the published site
</div>
<script>document.documentElement.style.scrollPaddingTop='34px';
document.body.style.marginTop='34px';</script>
"""
STAGING_NOINDEX = '<meta name="robots" content="noindex, nofollow">'


# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------
def read_page_meta(path: Path) -> dict:
    """Pull <title> and <meta name=description> out of an HTML file."""
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:8000]
    except OSError:
        head = ""
    title_match = TITLE_RE.search(head)
    desc_match = DESC_RE.search(head)
    title = html.unescape(title_match.group(1).strip()) if title_match else None
    desc = html.unescape(desc_match.group(1).strip()) if desc_match else ""
    return {
        "title": title or prettify(path.stem),
        "description": " ".join(desc.split()),
    }


def read_folder_meta(path: Path) -> dict:
    """Optional per-folder _meta.json: {"title":…, "description":…, "order":10}"""
    meta_file = path / "_meta.json"
    meta = {}
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  ! bad JSON in {meta_file}: {exc}")
            meta = {}
    meta.setdefault("title", prettify(path.name))
    meta.setdefault("description", "")
    meta.setdefault("order", 100)
    return meta


def prettify(name: str) -> str:
    """mapf -> Mapf, cbs-algorithm -> Cbs algorithm, my_notes -> My notes"""
    return name.replace("-", " ").replace("_", " ").strip().capitalize()


# --------------------------------------------------------------------------
# staging injection
# --------------------------------------------------------------------------
def copy_page(src: Path, dst: Path, staging: bool) -> None:
    """Copy an HTML page, adding the staging banner and noindex when asked."""
    if not staging:
        shutil.copy2(src, dst)
        return
    try:
        text = src.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        shutil.copy2(src, dst)
        return
    if "</head>" in text.lower():
        idx = text.lower().index("</head>")
        text = text[:idx] + STAGING_NOINDEX + "\n" + text[idx:]
    if BODY_CLOSE_RE.search(text):
        text = BODY_CLOSE_RE.sub(STAGING_BANNER + "</body>", text, count=1)
    else:
        text += STAGING_BANNER
    dst.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# page template
# --------------------------------------------------------------------------
def render_index(title, description, crumbs, folders, pages, depth, staging) -> str:
    up = "../" * depth
    esc = html.escape

    crumb_html = ""
    if crumbs:
        parts = ['<a href="%sindex.html">%s</a>' % (up, esc(SITE_TITLE))]
        for i, (label, _) in enumerate(crumbs):
            steps = len(crumbs) - 1 - i
            if steps == 0:
                parts.append("<span>%s</span>" % esc(label))
            else:
                parts.append(
                    '<a href="%sindex.html">%s</a>' % ("../" * steps, esc(label))
                )
        crumb_html = '<nav class="crumbs">%s</nav>' % '<span class="sep">/</span>'.join(
            parts
        )

    items = []
    for name, meta in folders:
        items.append(
            '<li class="item folder">'
            '<a href="{href}/index.html">'
            '<span class="kind">dir</span>'
            '<span class="label">{title}</span>'
            "{desc}"
            "</a></li>".format(
                href=esc(name),
                title=esc(meta["title"]),
                desc='<span class="desc">%s</span>' % esc(meta["description"])
                if meta["description"]
                else "",
            )
        )
    for name, meta in pages:
        items.append(
            '<li class="item page">'
            '<a href="{href}">'
            '<span class="kind">page</span>'
            '<span class="label">{title}</span>'
            "{desc}"
            "</a></li>".format(
                href=esc(name),
                title=esc(meta["title"]),
                desc='<span class="desc">%s</span>' % esc(meta["description"])
                if meta["description"]
                else "",
            )
        )

    body = (
        "<ul class='list'>%s</ul>" % "".join(items)
        if items
        else "<p class='empty'>Nothing here yet.</p>"
    )

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
{noindex}<link rel="stylesheet" href="{up}assets/style.css">
</head>
<body>
<main>
  {crumbs}
  <header class="head">
    <h1>{heading}</h1>
    {tagline}
  </header>
  {body}
</main>
{banner}</body>
</html>
""".format(
        title=esc(title),
        description=esc(description or SITE_TAGLINE),
        noindex=STAGING_NOINDEX + "\n" if staging else "",
        up=up,
        crumbs=crumb_html,
        heading=esc(title),
        tagline='<p class="tagline">%s</p>' % esc(description) if description else "",
        body=body,
        banner=STAGING_BANNER if staging else "",
    )


# --------------------------------------------------------------------------
# walk
# --------------------------------------------------------------------------
def build_dir(src: Path, dst: Path, crumbs, depth, out_root, staging) -> None:
    dst.mkdir(parents=True, exist_ok=True)

    folders, pages, extras = [], [], []
    for child in sorted(src.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith(".") or child.name.startswith("_"):
            continue
        if child.is_dir():
            folders.append((child.name, read_folder_meta(child)))
        elif child.suffix.lower() in (".html", ".htm"):
            if child.name.lower() == "index.html":
                extras.append(child)
            else:
                pages.append((child.name, read_page_meta(child)))
        else:
            extras.append(child)

    folders.sort(key=lambda f: (f[1]["order"], f[1]["title"].lower()))
    pages.sort(key=lambda p: p[1]["title"].lower())

    for name, _ in pages:
        copy_page(src / name, dst / name, staging)
    for extra in extras:
        if extra.is_dir():
            shutil.copytree(extra, dst / extra.name, dirs_exist_ok=True)
        elif extra.suffix.lower() in (".html", ".htm"):
            copy_page(extra, dst / extra.name, staging)
        else:
            shutil.copy2(extra, dst / extra.name)

    for name, _ in folders:
        build_dir(
            src / name,
            dst / name,
            crumbs + [(read_folder_meta(src / name)["title"], name)],
            depth + 1,
            out_root,
            staging,
        )

    if (src / "index.html").exists():
        print(f"  = {dst.relative_to(out_root)}/index.html (hand-written, kept)")
        return

    if depth == 0:
        title, description = SITE_TITLE, SITE_TAGLINE
    else:
        meta = read_folder_meta(src)
        title, description = meta["title"], meta["description"]

    (dst / "index.html").write_text(
        render_index(title, description, crumbs, folders, pages, depth, staging),
        encoding="utf-8",
    )
    rel = dst.relative_to(out_root)
    print(
        f"  + {rel if str(rel) != '.' else ''}/index.html  "
        f"({len(folders)} folders, {len(pages)} pages)"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the static site.")
    ap.add_argument("--out", default="_site", help="output directory (default: _site)")
    ap.add_argument(
        "--staging",
        action="store_true",
        help="mark every page noindex and add a staging banner",
    )
    ap.add_argument("--serve", action="store_true", help="serve the result on :8000")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    if not CONTENT.exists():
        CONTENT.mkdir()
        print("content/ was missing, created an empty one")

    print(f"building{' (staging)' if args.staging else ''}...")
    build_dir(CONTENT, out, [], 0, out, args.staging)

    if ASSETS.exists():
        shutil.copytree(ASSETS, out / "assets", dirs_exist_ok=True)
    (out / ".nojekyll").touch()

    print(f"done -> {out}")

    if args.serve:
        import http.server
        import os
        import socketserver

        os.chdir(out)
        with socketserver.TCPServer(
            ("", 8000), http.server.SimpleHTTPRequestHandler
        ) as httpd:
            print("serving http://localhost:8000  (ctrl-c to stop)")
            httpd.serve_forever()


if __name__ == "__main__":
    main()
