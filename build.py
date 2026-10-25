#!/usr/bin/env python3
"""
Static site generator with sidebar navigation.

Reads site.yml for configuration, walks content/ for .md and .html
pages, and produces a themed static site with auto-generated navigation.

Styling has three cascade layers, lowest priority first:
  base    - assets/explainer.css, the shared design system for every page
  content - each page's own <style> blocks (visualization-specific CSS)
  shell   - the generated header / sidebar / TOC (assets/style.css)
A page's `<style data-base>` copy of explainer.css (used for standalone
preview) is stripped at build time so the canonical file always wins.

Usage:
    python3 build.py                # build into _site/
    python3 build.py --serve        # build, then serve on :8000
    python3 build.py --out DIR      # custom output directory
    python3 build.py --staging      # add noindex + staging banner
    python3 build.py --check        # lint content CSS (exit 1 on warnings)
    python3 build.py --sync-template  # refresh templates/ copy of explainer.css
"""

import argparse
import copy
import html
import json
import re
import shutil
from pathlib import Path
from string import Template

import markdown as md_lib
import yaml

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets"
CONFIG_FILE = ROOT / "site.yml"

# ── regex ────────────────────────────────────────────────────────────────

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
DESC_RE = re.compile(
    r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', re.I | re.S
)
BODY_OPEN_RE = re.compile(r"<body[^>]*>", re.I)
BODY_CLOSE_RE = re.compile(r"</body\s*>", re.I)
HEADING_RE = re.compile(r"<(h[23])(\b[^>]*)>(.*?)</\1>", re.I | re.S)
ID_ATTR_RE = re.compile(r'\bid=["\']([^"\']*)["\']', re.I)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)

CONTENT_FONTS = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=JetBrains+Mono:wght@400;500;600&"
    "family=Inter:wght@400;500;600;700&display=swap\">"
)

MD_EXTENSIONS = ["tables", "fenced_code", "attr_list", "md_in_html"]

BASE_CSS = "assets/explainer.css"
LAYER_ORDER = "@layer base, content, shell;"
DATA_BASE_RE = re.compile(
    r"<style\b[^>]*\bdata-base\b[^>]*>.*?</style>\s*"
    r"|<link\b[^>]*\bdata-base\b[^>]*>\s*",
    re.I | re.S,
)
HEAD_OPEN_RE = re.compile(r"<head\b[^>]*>", re.I)
TEMPLATE = ROOT / "templates" / "paper-explainer.html"

# Core tokens owned by explainer.css. Pages must not redefine them.
CORE_TOKENS = (
    "bg", "s", "s2", "c", "bd", "fg", "dim", "h",
    "blue", "teal", "amber", "rose", "violet", "green", "cyan",
)


def base_css_tag(depth: int) -> str:
    """Declare layer order and pull in the shared design system as `base`.

    Must be the first stylesheet on the page: the first @layer statement
    fixes the order for the whole document.
    """
    up = "../" * depth
    return (
        f'<style id="site-layers">{LAYER_ORDER}\n'
        f'@import url("{up}{BASE_CSS}") layer(base);</style>'
    )

# ── constants ────────────────────────────────────────────────────────────

NAV_SCRIPT = """\
<script>(function(){
var b=document.getElementById("nav-menu"),n=document.getElementById("site-nav");
if(!n)return;
if(b){
b.onclick=function(){n.classList.toggle("open");b.classList.toggle("active")};
document.addEventListener("click",function(e){
if(n.classList.contains("open")&&!n.contains(e.target)&&e.target!==b&&!b.contains(e.target)){
n.classList.remove("open");b.classList.remove("active")}})}
/* Remember expanded sections and sidebar scroll across page loads.
   Storage can be unavailable (private mode, blocked); the nav still works. */
var KO="pllee4-nav-open",KS="pllee4-nav-scroll";
function load(k,d){try{var v=localStorage.getItem(k);return v===null?d:JSON.parse(v)}catch(e){return d}}
function save(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}
var open=load(KO,[]);
n.querySelectorAll(".nav-section[data-path]").forEach(function(li){
if(open.indexOf(li.dataset.path)>=0)li.classList.add("open")});
function persist(){save(KO,[].map.call(n.querySelectorAll(".nav-section.open[data-path]"),
function(li){return li.dataset.path}))}
persist();
function toggle(a){a.closest(".nav-section").classList.toggle("open");persist()}
n.addEventListener("click",function(e){var a=e.target.closest(".nav-arrow");if(a){e.preventDefault();toggle(a)}});
n.addEventListener("keydown",function(e){var a=e.target.closest(".nav-arrow");
if(a&&(e.key==="Enter"||e.key===" ")){e.preventDefault();toggle(a)}});
var sc=load(KS,0);if(sc)n.scrollTop=sc;
var act=n.querySelector(".nav-page.active");
if(act){var r=act.getBoundingClientRect(),nr=n.getBoundingClientRect();
if(r.top<nr.top||r.bottom>nr.bottom)act.scrollIntoView({block:"center"})}
window.addEventListener("pagehide",function(){save(KS,n.scrollTop)});
})()</script>"""

TOC_SCRIPT = """\
<script>(function(){
var t=document.getElementById("page-toc");
if(!t)return;
var links=t.querySelectorAll("a[href^='#']"),hs=[];
links.forEach(function(a){
var h=document.getElementById(a.getAttribute("href").slice(1));
if(h)hs.push({el:h,link:a})
});
if(!hs.length)return;
function up(){
var s=window.scrollY+100,cur=null;
for(var i=hs.length-1;i>=0;i--){if(hs[i].el.offsetTop<=s){cur=hs[i];break}}
links.forEach(function(a){a.classList.remove("active")});
if(cur)cur.link.classList.add("active")
}
window.addEventListener("scroll",up,{passive:true});up()
})()</script>"""

STAGING_BANNER = (
    '<div id="staging-banner" style="position:fixed;top:0;left:0;right:0;'
    "z-index:2147483647;background:#d4760a;color:#fff;"
    "font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;"
    'letter-spacing:.08em;text-transform:uppercase;text-align:center;'
    'padding:7px 10px;box-shadow:0 1px 6px rgba(0,0,0,.25)">'
    "staging preview &mdash; not the published site</div>\n"
    "<script>document.documentElement.style.scrollPaddingTop='34px';"
    "document.body.style.marginTop='34px';</script>"
)
STAGING_NOINDEX = '<meta name="robots" content="noindex, nofollow">'

# ── configuration ────────────────────────────────────────────────────────

DEFAULTS = {
    "site_name": "My Docs",
    "site_description": "",
    "site_intro": "",
    "theme": {
        "palette": {
            "light": {
                "primary": "#4051b5", "primary_fg": "#fff",
                "bg": "#fff", "fg": "#333", "fg_light": "#666",
                "surface": "#f8f9fa", "border": "#e0e0e0",
                "hover": "#f0f0f5", "accent": "#4051b5",
            },
            "dark": {
                "primary": "#303f9f", "primary_fg": "#fff",
                "bg": "#1a1a2e", "fg": "#dddde8", "fg_light": "#9898b0",
                "surface": "#1e1e34", "border": "#2a2a44",
                "hover": "#24243c", "accent": "#8c9eff",
            },
        },
        "font": {
            "family": (
                "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
                "'Helvetica Neue', sans-serif"
            ),
        },
        "layout": {
            "sidebar_width": 240,
            "header_height": 50,
            "toc_width": 200,
            "breakpoint": 960,
        },
    },
    "extra_css": [],
}


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        _deep_merge(cfg, user)
    else:
        print(f"  ! {CONFIG_FILE.name} not found, using defaults")
    return cfg


# ── CSS generation ───────────────────────────────────────────────────────

_CSS = Template("""\
/* Generated from site.yml — edit the config, not this file. */

/* Layer order: base < content < shell. Content can never override the shell. */
@layer base, content, shell;

@layer shell {

/* ── Variables (content area) ── */

:root {
  --site-bg: $lt_bg;
  --site-fg: $lt_fg;
  --site-fg-light: $lt_fg_light;
  --site-surface: $lt_surface;
  --site-border: $lt_border;
  --site-hover: $lt_hover;
  --site-accent: $lt_accent;
  --sidebar-w: ${sw}px;
  --header-h: ${hh}px;
  --toc-w: ${tw}px;
}

@media (prefers-color-scheme: dark) {
  :root {
    --site-bg: $dk_bg;
    --site-fg: $dk_fg;
    --site-fg-light: $dk_fg_light;
    --site-surface: $dk_surface;
    --site-border: $dk_border;
    --site-hover: $dk_hover;
    --site-accent: $dk_accent;
    color-scheme: dark;
  }
}

/* ── Nav variables (scoped — immune to content-page :root overrides) ── */

.site-header {
  --nav-primary: $lt_primary;
  --nav-primary-fg: $lt_primary_fg;
}
.site-nav {
  --nav-surface: $lt_surface;
  --nav-border: $lt_border;
  --nav-fg: $lt_fg;
  --nav-fg-light: $lt_fg_light;
  --nav-hover: $lt_hover;
  --nav-accent: $lt_accent;
}
.page-toc {
  --toc-fg: $lt_fg;
  --toc-fg-light: $lt_fg_light;
  --toc-border: $lt_border;
  --toc-accent: $lt_accent;
}

@media (prefers-color-scheme: dark) {
  .site-header {
    --nav-primary: $dk_primary;
    --nav-primary-fg: $dk_primary_fg;
  }
  .site-nav {
    --nav-surface: $dk_surface;
    --nav-border: $dk_border;
    --nav-fg: $dk_fg;
    --nav-fg-light: $dk_fg_light;
    --nav-hover: $dk_hover;
    --nav-accent: $dk_accent;
  }
  .page-toc {
    --toc-fg: $dk_fg;
    --toc-fg-light: $dk_fg_light;
    --toc-border: $dk_border;
    --toc-accent: $dk_accent;
  }
}

/* ── Shell isolation ──
 * Wipe every author style (all layers) from the shell chrome, then rebuild
 * it below. Containers start from `initial` so nothing inherits from the
 * content page's <body>; descendants `revert` to browser defaults and
 * inherit from the clean container. :where() keeps specificity at zero so
 * the class rules below always win. Custom properties are untouched by `all`.
 */
:where(#site-header, #site-nav, #page-toc) {
  all: initial;
  box-sizing: border-box;
}
:where(#site-header, #site-nav, #page-toc) *,
:where(#site-header, #site-nav, #page-toc) *::before,
:where(#site-header, #site-nav, #page-toc) *::after {
  all: revert;
  box-sizing: border-box;
  margin: 0;
}

/* ── Generated pages only (root + folder indexes) ──
 * Scoped to body.shell-page so these never touch content pages.
 */
.shell-page * { box-sizing: border-box; margin: 0; }

body.shell-page {
  margin: 0;
  margin-left: var(--sidebar-w);
  padding-top: var(--header-h);
  background: var(--site-bg);
  color: var(--site-fg);
  font-family: $font;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

/* ── Header ── */

.site-header {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: var(--header-h);
  background: var(--nav-primary);
  color: var(--nav-primary-fg);
  display: flex;
  align-items: center;
  padding: 0 20px;
  z-index: 200;
  box-shadow: 0 2px 4px rgba(0, 0, 0, .1);
  font-family: $font;
  line-height: 1.5;
}

.site-header .site-title {
  color: var(--nav-primary-fg);
  text-decoration: none;
  font-weight: 600;
  font-size: 1rem;
  letter-spacing: -.01em;
}
.site-header .site-title:hover { opacity: .85; }

/* ── Sidebar ── */

.site-nav {
  position: fixed;
  left: 0;
  top: var(--header-h);
  bottom: 0;
  width: var(--sidebar-w);
  overflow-y: auto;
  background: var(--nav-surface);
  border-right: 1px solid var(--nav-border);
  z-index: 100;
  font-size: .84rem;
  font-family: $font;
  line-height: 1.5;
  color: var(--nav-fg);
}

/* Defensive resets — beat bare element selectors from content pages */
#site-nav nav {
  display: block; margin: 0; padding: 0; border: 0;
  gap: 0; flex-wrap: initial; background: none;
}
#site-nav ul { border: 0; background: none; }
#site-nav li { border: 0; background: none; padding: 0; }
#site-header a { border: 0; }

.nav-tree { display: block; list-style: none; padding: 12px 0; }
.nav-tree ul { list-style: none; padding: 0 0 0 12px; }

.nav-section .nav-link {
  display: flex;
  align-items: center;
}

.nav-section .nav-link a { flex: 1; }

.nav-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px; height: 24px;
  margin-right: 8px;
  padding: 0;
  border: 0;
  flex-shrink: 0;
  cursor: pointer;
  color: var(--nav-fg-light);
  background: none;
  border-radius: 4px;
  transition: transform .2s;
  user-select: none;
}
.nav-arrow:hover { background: var(--nav-hover); }
.nav-arrow::before { content: '\\25b8'; font-size: .65rem; }

.nav-section.open > .nav-link > .nav-arrow { transform: rotate(90deg); }
.nav-section > ul { display: none; }
.nav-section.open > ul { display: block; }

.nav-section > a,
.nav-section .nav-link a,
.nav-page a {
  display: block;
  padding: 6px 16px 6px 16px;
  color: var(--nav-fg-light);
  text-decoration: none;
  line-height: 1.5;
  border: 0;
  background: none;
  border-radius: 4px;
  transition: color .15s, background .15s;
}
.nav-page a { padding-left: 28px; }

.nav-section > a:hover,
.nav-section .nav-link a:hover,
.nav-page a:hover {
  color: var(--nav-fg);
  background: var(--nav-hover);
}
.nav-section.active > a,
.nav-section.active > .nav-link > a {
  color: var(--nav-fg);
  font-weight: 500;
}
.nav-page.active a {
  color: var(--nav-accent);
  font-weight: 500;
  background: var(--nav-hover);
}

/* ── Hamburger (mobile) ── */

.nav-menu {
  display: none;
  width: 36px; height: 36px;
  padding: 9px 7px;
  margin-right: 12px;
  border: none;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  flex-direction: column;
  justify-content: space-between;
  align-items: stretch;
  flex-shrink: 0;
}
.nav-menu span {
  display: block;
  height: 2px;
  background: var(--nav-primary-fg);
  border-radius: 1px;
  transition: transform .2s, opacity .2s;
}
.nav-menu.active span:nth-child(1) { transform: translateY(8px) rotate(45deg); }
.nav-menu.active span:nth-child(2) { opacity: 0; }
.nav-menu.active span:nth-child(3) { transform: translateY(-8px) rotate(-45deg); }

/* ── On-this-page TOC (right side) ── */

/* Defensive resets for TOC panel */
#page-toc ul { border: 0; background: none; }
#page-toc li { border: 0; background: none; }

.page-toc {
  position: fixed;
  right: 0;
  top: var(--header-h);
  bottom: 0;
  width: var(--toc-w);
  overflow-y: auto;
  padding: 20px 16px;
  font-size: .78rem;
  font-family: $font;
  line-height: 1.5;
  color: var(--toc-fg-light);
  border-left: 1px solid var(--toc-border);
}

.page-toc .toc-title {
  font-size: .68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--toc-fg-light);
  margin-bottom: 12px;
  padding-left: 12px;
}
.page-toc ul { list-style: none; padding: 0; }
.page-toc li { margin-bottom: 2px; }

.page-toc a {
  display: block;
  padding: 4px 8px 4px 12px;
  color: var(--toc-fg-light);
  text-decoration: none;
  border: 0;
  border-left: 2px solid transparent;
  background: none;
  border-radius: 0;
  transition: color .15s, border-color .15s;
  line-height: 1.4;
}
.page-toc a:hover { color: var(--toc-fg); }
.page-toc a.active {
  color: var(--toc-accent);
  border-left-color: var(--toc-accent);
}
.page-toc .toc-h3 a { padding-left: 24px; font-size: .74rem; }

/* ── Content area ── */

.shell-page main { padding: 32px 40px 80px; }

.shell-page .welcome h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 16px; }
.shell-page .welcome .intro {
  font-size: .95rem; line-height: 1.8;
  margin-bottom: 24px; max-width: 640px;
}
.shell-page .welcome h2 { font-size: 1.05rem; font-weight: 600; margin-bottom: 12px; }

.shell-page .sections { list-style: none; padding: 0; margin-bottom: 28px; }
.shell-page .sections li { padding: 6px 0; font-size: .92rem; line-height: 1.6; }
.shell-page .sections li::before {
  content: '\\2022';
  color: var(--site-accent);
  font-weight: bold;
  margin-right: 10px;
}
.shell-page .sections a {
  color: var(--site-accent);
  text-decoration: none;
  font-weight: 500;
}
.shell-page .sections a:hover { text-decoration: underline; }
.shell-page .sections .sec-desc { color: var(--site-fg-light); }

.shell-page .crumbs { font-size: .78rem; color: var(--site-fg-light); margin-bottom: 20px; }
.shell-page .crumbs a { color: var(--site-fg-light); text-decoration: none; }
.shell-page .crumbs a:hover { color: var(--site-accent); text-decoration: underline; }
.shell-page .crumbs .sep { margin: 0 8px; opacity: .5; }
.shell-page .crumbs span:not(.sep) { color: var(--site-fg); }

.shell-page .head { margin-bottom: 28px; }
.shell-page .head h1 {
  font-size: 1.3rem; font-weight: 600;
  letter-spacing: -.01em; margin-bottom: 6px;
}
.shell-page .tagline { color: var(--site-fg-light); font-size: .88rem; }

.shell-page .list { list-style: none; padding: 0; }
.shell-page .item + .item { margin-top: 8px; }

.shell-page .item a {
  display: block;
  padding: 14px 16px;
  background: var(--site-surface);
  border: 1px solid var(--site-border);
  border-radius: 8px;
  text-decoration: none;
  color: inherit;
  transition: border-color .15s, transform .15s;
}
.shell-page .item a:hover {
  border-color: var(--site-accent);
  transform: translateX(2px);
}

.shell-page .label { font-weight: 500; font-size: .95rem; }

.shell-page .item-desc {
  display: block;
  font-size: .82rem;
  color: var(--site-fg-light);
  line-height: 1.5;
  margin-top: 4px;
}

.shell-page .empty {
  color: var(--site-fg-light);
  font-size: .88rem;
  font-style: italic;
}

/* ── Responsive ── */

@media (max-width: ${bp}px) {
  .site-nav {
    transform: translateX(-100%);
    transition: transform .25s ease;
    box-shadow: none;
  }
  .site-nav.open {
    transform: translateX(0);
    box-shadow: 4px 0 20px rgba(0, 0, 0, .2);
  }
  .nav-menu { display: flex; }
  body.shell-page { margin-left: 0; }
  .page-toc { display: none; }
  .shell-page main { padding: 24px 20px 60px; }
}

/* In-page jump pills duplicate the side TOC; hide them while it is visible. */
@media (min-width: ${bp1}px) {
  body:has(#page-toc) .jump { display: none; }
}

@media (max-width: 480px) {
  .shell-page main { padding: 20px 16px 48px; }
  .shell-page .welcome h1 { font-size: 1.3rem; }
}

} /* end @layer shell */
""")


def generate_css(config: dict) -> str:
    t = config["theme"]
    lt = t["palette"]["light"]
    dk = t["palette"]["dark"]
    lo = t["layout"]
    return _CSS.substitute(
        lt_primary=lt["primary"], lt_primary_fg=lt["primary_fg"],
        lt_bg=lt["bg"], lt_fg=lt["fg"], lt_fg_light=lt["fg_light"],
        lt_surface=lt["surface"], lt_border=lt["border"],
        lt_hover=lt["hover"], lt_accent=lt["accent"],
        dk_primary=dk["primary"], dk_primary_fg=dk["primary_fg"],
        dk_bg=dk["bg"], dk_fg=dk["fg"], dk_fg_light=dk["fg_light"],
        dk_surface=dk["surface"], dk_border=dk["border"],
        dk_hover=dk["hover"], dk_accent=dk["accent"],
        sw=lo["sidebar_width"], hh=lo["header_height"],
        tw=lo["toc_width"], bp=lo["breakpoint"], bp1=lo["breakpoint"] + 1,
        font=t["font"]["family"],
    )


def _content_override_style(config: dict, has_toc: bool) -> str:
    lo = config["theme"]["layout"]
    sw = lo["sidebar_width"]
    hh = lo["header_height"]
    tw = lo["toc_width"]
    bp = lo["breakpoint"]
    mr = f"margin-right:{tw}px!important;" if has_toc else ""
    return (
        '<style id="site-nav-layout">'
        f"@media(min-width:{bp + 1}px)"
        f"{{body{{margin-left:{sw}px!important;margin-top:{hh}px!important;{mr}}}}}"
        f"@media(max-width:{bp}px)"
        f"{{body{{margin-left:0!important;margin-top:{hh}px!important}}}}"
        "</style>"
    )


# ── metadata ─────────────────────────────────────────────────────────────

def read_page_meta(path: Path) -> dict:
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:8000]
    except OSError:
        head = ""
    title_m = TITLE_RE.search(head)
    desc_m = DESC_RE.search(head)
    title = html.unescape(title_m.group(1).strip()) if title_m else None
    desc = html.unescape(desc_m.group(1).strip()) if desc_m else ""
    return {
        "title": title or _prettify(path.stem),
        "description": " ".join(desc.split()),
    }


def read_md_meta(path: Path) -> dict:
    """Extract title and description from markdown frontmatter or content."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        text = ""
    fm = FRONTMATTER_RE.match(text)
    meta = {}
    if fm:
        try:
            meta = yaml.safe_load(fm.group(1)) or {}
        except yaml.YAMLError:
            pass
    if "title" not in meta:
        h1_m = re.search(r"^#\s+(.+)", text, re.M)
        meta["title"] = h1_m.group(1).strip() if h1_m else _prettify(path.stem)
    meta.setdefault("description", "")
    return meta


def read_folder_meta(path: Path) -> dict:
    meta_file = path / "_meta.json"
    meta = {}
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  ! bad JSON in {meta_file}: {exc}")
    meta.setdefault("title", _prettify(path.name))
    meta.setdefault("description", "")
    meta.setdefault("order", 100)
    return meta


def _prettify(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").strip().capitalize()


# ── table of contents ────────────────────────────────────────────────────

def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-") or "section"


def _process_headings(text: str):
    """Add IDs to h2/h3 headings and return (modified_text, toc_entries)."""
    toc = []
    used_ids = set()

    def _repl(m):
        tag = m.group(1).lower()
        attrs = m.group(2)
        content = m.group(3)
        id_m = ID_ATTR_RE.search(attrs)
        if id_m:
            hid = id_m.group(1)
        else:
            hid = _slugify(html.unescape(_strip_tags(content)))
            base = hid
            n = 1
            while hid in used_ids:
                hid = f"{base}-{n}"
                n += 1
            attrs = f' id="{hid}"' + attrs
        used_ids.add(hid)
        toc.append({"level": tag, "id": hid,
                    "text": html.unescape(_strip_tags(content)).strip()})
        return f"<{m.group(1)}{attrs}>{content}</{m.group(1)}>"

    modified = HEADING_RE.sub(_repl, text)
    return modified, toc


def _render_toc(entries: list) -> str:
    if not entries:
        return ""
    esc = html.escape
    items = []
    for e in entries:
        cls = "toc-h3" if e["level"] == "h3" else "toc-h2"
        items.append(
            f'<li class="{cls}"><a href="#{esc(e["id"])}">{esc(e["text"])}</a></li>'
        )
    return (
        '<aside class="page-toc" id="page-toc">\n'
        '  <div class="toc-title">On this page</div>\n'
        f'  <ul>{"".join(items)}</ul>\n'
        "</aside>"
    )


# ── navigation tree ──────────────────────────────────────────────────────

def build_nav_tree(src: Path) -> list:
    folders, pages = [], []
    for child in sorted(src.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith((".", "_")):
            continue
        if child.is_dir():
            meta = read_folder_meta(child)
            folders.append({
                "type": "folder",
                "name": child.name,
                "title": meta["title"],
                "order": meta["order"],
                "children": build_nav_tree(child),
            })
        elif (
            child.suffix.lower() in (".html", ".htm")
            and child.name.lower() != "index.html"
        ):
            meta = read_page_meta(child)
            pages.append({
                "type": "page",
                "name": child.name,
                "title": meta["title"],
            })
        elif child.suffix.lower() == ".md":
            meta = read_md_meta(child)
            pages.append({
                "type": "page",
                "name": child.stem + ".html",
                "title": meta["title"],
            })
    folders.sort(key=lambda f: (f["order"], f["title"].lower()))
    pages.sort(key=lambda p: p["title"].lower())
    return folders + pages


# ── sidebar rendering ────────────────────────────────────────────────────

def render_sidebar(config: dict, nav_items: list,
                   current_rel: str, depth: int) -> str:
    up = "../" * depth
    esc = html.escape
    site_name = config["site_name"]

    def _level(items, prefix):
        parts = []
        for item in items:
            if item["type"] == "folder":
                fpath = prefix + item["name"] + "/"
                is_active = bool(current_rel) and current_rel.startswith(fpath)
                has_kids = bool(item.get("children"))
                href = esc(up + fpath + "index.html")
                title = esc(item["title"])
                cls = "nav-section"
                if is_active:
                    cls += " open active"
                parts.append(f'<li class="{cls}" data-path="{esc(fpath)}">')
                if has_kids:
                    parts.append('<div class="nav-link">')
                    parts.append(f'<a href="{href}">{title}</a>')
                    parts.append(
                        '<span class="nav-arrow" role="button" tabindex="0" '
                        'aria-label="Toggle section"></span>'
                    )
                    parts.append("</div>")
                    parts.append(f"<ul>{_level(item['children'], fpath)}</ul>")
                else:
                    parts.append(f'<a href="{href}">{title}</a>')
                parts.append("</li>")
            else:
                ppath = prefix + item["name"]
                cls = "nav-page active" if current_rel == ppath else "nav-page"
                href = esc(up + ppath)
                title = esc(item["title"])
                parts.append(f'<li class="{cls}"><a href="{href}">{title}</a></li>')
        return "\n".join(parts)

    tree = _level(nav_items, "")
    return (
        '<header class="site-header" id="site-header">\n'
        '  <button class="nav-menu" id="nav-menu" aria-label="Menu">'
        "<span></span><span></span><span></span></button>\n"
        f'  <a href="{up}index.html" class="site-title">{esc(site_name)}</a>\n'
        "</header>\n"
        '<aside class="site-nav" id="site-nav">\n'
        f'  <nav><ul class="nav-tree">\n{tree}\n  </ul></nav>\n'
        "</aside>"
    )


# ── page injection ───────────────────────────────────────────────────────

def _extra_css_links(config: dict, depth: int) -> str:
    up = "../" * depth
    return "".join(
        f'\n<link rel="stylesheet" href="{up}{p}">'
        for p in config.get("extra_css", [])
    )


STYLE_RE = re.compile(
    r"(<style[^>]*>)(.*?)(</style>)", re.I | re.S,
)


def _layer_wrap_styles(text: str) -> str:
    """Wrap every <style> block's contents in @layer content."""
    def _wrap(m):
        open_tag, css, close_tag = m.group(1), m.group(2), m.group(3)
        if "site-nav-layout" in open_tag:
            return m.group(0)
        return f"{open_tag}\n@layer content {{\n{css}\n}}\n{close_tag}"
    return STYLE_RE.sub(_wrap, text)


def inject_shell(src: Path, dst: Path, config: dict,
                  sidebar_html: str, depth: int, staging: bool) -> None:
    if not staging and not sidebar_html:
        shutil.copy2(src, dst)
        return
    try:
        text = src.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        shutil.copy2(src, dst)
        return

    # drop any standalone-preview copy of the shared CSS; the canonical
    # assets/explainer.css is injected instead
    text = DATA_BASE_RE.sub("", text)

    # wrap content <style> blocks in @layer content so they
    # can never override the site shell (@layer shell)
    text = _layer_wrap_styles(text)

    # extract headings for TOC and ensure they have IDs
    text, toc_entries = _process_headings(text)
    toc_html = _render_toc(toc_entries)
    has_toc = bool(toc_entries)

    head_extra = ""
    body_start = ""
    body_end = ""

    if sidebar_html:
        up = "../" * depth
        head_extra += f"\n{CONTENT_FONTS}"
        head_extra += f'\n<link rel="stylesheet" href="{up}assets/content.css">'
        head_extra += f'\n<link rel="stylesheet" href="{up}assets/style.css">'
        head_extra += _extra_css_links(config, depth)
        body_start += "\n" + sidebar_html + "\n"
        if toc_html:
            body_start += toc_html + "\n"
        body_end += _content_override_style(config, has_toc)
        body_end += "\n" + NAV_SCRIPT + "\n"
        if has_toc:
            body_end += TOC_SCRIPT + "\n"

    if staging:
        head_extra += "\n" + STAGING_NOINDEX
        body_end += STAGING_BANNER

    if sidebar_html:
        m = HEAD_OPEN_RE.search(text)
        if m:
            text = text[: m.end()] + "\n" + base_css_tag(depth) + text[m.end() :]
        else:
            text = base_css_tag(depth) + "\n" + text

    if head_extra and "</head>" in text.lower():
        idx = text.lower().index("</head>")
        text = text[:idx] + head_extra + "\n" + text[idx:]

    if body_start:
        m = BODY_OPEN_RE.search(text)
        if m:
            text = text[: m.end()] + body_start + text[m.end() :]

    if body_end:
        if BODY_CLOSE_RE.search(text):
            text = BODY_CLOSE_RE.sub(body_end + "</body>", text, count=1)
        else:
            text += body_end

    dst.write_text(text, encoding="utf-8")


# ── markdown rendering ──────────────────────────────────────────────────

def render_md_page(src: Path, dst: Path, config: dict,
                   sidebar_html: str, depth: int, staging: bool) -> None:
    """Convert a markdown file to a full HTML page with site shell."""
    try:
        raw = src.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    fm = FRONTMATTER_RE.match(raw)
    if fm:
        try:
            meta = yaml.safe_load(fm.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        body_md = raw[fm.end():]
    else:
        meta = {}
        body_md = raw

    title = meta.get("title") or _prettify(src.stem)
    description = meta.get("description", "")

    converter = md_lib.Markdown(extensions=MD_EXTENSIONS)
    body_html = converter.convert(body_md)

    body_html, toc_entries = _process_headings(body_html)
    toc_html = _render_toc(toc_entries)
    has_toc = bool(toc_entries)

    esc = html.escape
    up = "../" * depth
    noindex = STAGING_NOINDEX + "\n" if staging else ""
    banner = STAGING_BANNER if staging else ""

    page = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{esc(title)}</title>\n"
        f'<meta name="description" content="{esc(description)}">\n'
        f"{noindex}"
        f"{base_css_tag(depth)}\n"
        f"{CONTENT_FONTS}\n"
        f'<link rel="stylesheet" href="{up}assets/content.css">\n'
        f'<link rel="stylesheet" href="{up}assets/style.css">\n'
        f"{_extra_css_links(config, depth)}"
        "</head>\n"
        "<body>\n"
        f"{sidebar_html}\n"
    )

    if toc_html:
        page += toc_html + "\n"

    page += (
        '<div class="paper">\n'
        f"{body_html}\n"
        "</div>\n"
        f"{_content_override_style(config, has_toc)}\n"
        f"{banner}{NAV_SCRIPT}\n"
    )

    if has_toc:
        page += TOC_SCRIPT + "\n"

    page += "</body>\n</html>\n"
    dst.write_text(page, encoding="utf-8")


# ── page templates ───────────────────────────────────────────────────────

def _page_head(title: str, description: str, css_href: str,
               extra_css: str, noindex: str) -> str:
    esc = html.escape
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{esc(title)}</title>\n"
        f'<meta name="description" content="{esc(description)}">\n'
        f"{noindex}"
        f'<link rel="stylesheet" href="{css_href}">\n'
        f"{extra_css}"
        "</head>\n"
    )


def render_root_index(config: dict, folders: list,
                      staging: bool, sidebar_html: str) -> str:
    esc = html.escape
    noindex = STAGING_NOINDEX + "\n" if staging else ""
    banner = STAGING_BANNER if staging else ""

    items = []
    for name, meta in folders:
        href = esc(name + "/index.html")
        title = esc(meta["title"])
        desc = meta["description"]
        line = f'<li><a href="{href}">{title}</a>'
        if desc:
            line += f' <span class="sec-desc">&mdash; {esc(desc)}</span>'
        items.append(line + "</li>")

    return (
        _page_head(
            config["site_name"], config["site_description"],
            "assets/style.css", _extra_css_links(config, 0), noindex,
        )
        + f'<body class="shell-page">\n{sidebar_html}\n<main>\n'
        f'  <div class="welcome">\n'
        f'    <h1>Welcome to {esc(config["site_name"])}</h1>\n'
        f'    <p class="intro">{esc(config["site_intro"])}</p>\n'
        f'    <h2>Sections</h2>\n'
        f'    <ul class="sections">\n'
        f'      {"".join(items)}\n'
        f"    </ul>\n"
        f"  </div>\n"
        f"</main>\n{banner}{NAV_SCRIPT}\n</body>\n</html>\n"
    )


def render_index(config: dict, title: str, description: str,
                 crumbs: list, folders: list, pages: list,
                 depth: int, staging: bool, sidebar_html: str) -> str:
    up = "../" * depth
    esc = html.escape
    noindex = STAGING_NOINDEX + "\n" if staging else ""
    banner = STAGING_BANNER if staging else ""

    crumb_parts = [f'<a href="{up}index.html">{esc(config["site_name"])}</a>']
    for i, (label, _) in enumerate(crumbs):
        steps = len(crumbs) - 1 - i
        if steps == 0:
            crumb_parts.append(f"<span>{esc(label)}</span>")
        else:
            crumb_parts.append(
                f'<a href="{"../" * steps}index.html">{esc(label)}</a>'
            )
    crumb_html = (
        '<nav class="crumbs">'
        + '<span class="sep">/</span>'.join(crumb_parts)
        + "</nav>"
    )

    items = []
    for name, meta in folders:
        desc_span = (
            f'<span class="item-desc">{esc(meta["description"])}</span>'
            if meta["description"] else ""
        )
        items.append(
            f'<li class="item folder">'
            f'<a href="{esc(name)}/index.html">'
            f'<span class="label">{esc(meta["title"])}</span>'
            f"{desc_span}</a></li>"
        )
    for name, meta in pages:
        href_name = name[:-3] + ".html" if name.endswith(".md") else name
        desc_span = (
            f'<span class="item-desc">{esc(meta["description"])}</span>'
            if meta["description"] else ""
        )
        items.append(
            f'<li class="item page">'
            f'<a href="{esc(href_name)}">'
            f'<span class="label">{esc(meta["title"])}</span>'
            f"{desc_span}</a></li>"
        )

    body = (
        f'<ul class="list">{"".join(items)}</ul>'
        if items
        else '<p class="empty">Nothing here yet.</p>'
    )

    tagline = (
        f'<p class="tagline">{esc(description)}</p>' if description else ""
    )

    return (
        _page_head(
            title, description or config["site_description"],
            f"{up}assets/style.css", _extra_css_links(config, depth), noindex,
        )
        + f'<body class="shell-page">\n{sidebar_html}\n<main>\n'
        f"  {crumb_html}\n"
        f'  <header class="head">\n'
        f"    <h1>{esc(title)}</h1>\n"
        f"    {tagline}\n"
        f"  </header>\n"
        f"  {body}\n"
        f"</main>\n{banner}{NAV_SCRIPT}\n</body>\n</html>\n"
    )


# ── build ────────────────────────────────────────────────────────────────

def build_dir(src: Path, dst: Path, crumbs: list, depth: int,
              out_root: Path, config: dict, staging: bool,
              nav_tree: list) -> None:
    dst.mkdir(parents=True, exist_ok=True)

    folders, pages = [], []
    has_index = False
    for child in sorted(src.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith((".", "_")):
            continue
        if child.is_dir():
            folders.append((child.name, read_folder_meta(child)))
        elif child.suffix.lower() in (".html", ".htm"):
            if child.name.lower() == "index.html":
                has_index = True
            else:
                pages.append((child.name, read_page_meta(child)))
        elif child.suffix.lower() == ".md":
            pages.append((child.name, read_md_meta(child)))
        else:
            shutil.copy2(child, dst / child.name)

    folders.sort(key=lambda f: (f[1]["order"], f[1]["title"].lower()))
    pages.sort(key=lambda p: p[1]["title"].lower())

    rel_dir = src.relative_to(CONTENT)
    dir_prefix = "" if str(rel_dir) == "." else str(rel_dir).replace("\\", "/") + "/"

    for name, meta in pages:
        if name.endswith(".md"):
            out_name = name[:-3] + ".html"
            current_rel = dir_prefix + out_name
            sidebar = render_sidebar(config, nav_tree, current_rel, depth)
            render_md_page(src / name, dst / out_name, config, sidebar, depth, staging)
        else:
            current_rel = dir_prefix + name
            sidebar = render_sidebar(config, nav_tree, current_rel, depth)
            inject_shell(src / name, dst / name, config, sidebar, depth, staging)

    for name, _ in folders:
        build_dir(
            src / name, dst / name,
            crumbs + [(read_folder_meta(src / name)["title"], name)],
            depth + 1, out_root, config, staging, nav_tree,
        )

    current_rel = dir_prefix
    sidebar = render_sidebar(config, nav_tree, current_rel, depth)

    if has_index:
        inject_shell(
            src / "index.html", dst / "index.html",
            config, sidebar, depth, staging,
        )
        print(f"  = {dst.relative_to(out_root)}/index.html  (hand-written)")
        return

    if depth == 0:
        (dst / "index.html").write_text(
            render_root_index(config, folders, staging, sidebar),
            encoding="utf-8",
        )
    else:
        meta = read_folder_meta(src)
        (dst / "index.html").write_text(
            render_index(
                config, meta["title"], meta["description"],
                crumbs, folders, pages, depth, staging, sidebar,
            ),
            encoding="utf-8",
        )

    rel = dst.relative_to(out_root)
    print(
        f"  + {rel if str(rel) != '.' else ''}/index.html  "
        f"({len(folders)} folders, {len(pages)} pages)"
    )


# ── CSS lint ─────────────────────────────────────────────────────────────

SHELL_ELEMENTS = frozenset({
    "a", "aside", "button", "div", "header", "li", "nav", "ol",
    "span", "ul",
})

def _extract_selectors(css: str) -> list[str]:
    """Return CSS selectors from a stylesheet string."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{", "", css)
    selectors = []
    for m in re.finditer(r"([^{}]+)\{", css):
        raw = m.group(1).strip()
        for sel in raw.split(","):
            sel = sel.strip()
            if sel:
                selectors.append(sel)
    return selectors


def _is_bare_element(selector: str) -> str | None:
    """If the selector starts with a bare element name that could collide
    with the site shell, return that element name. Otherwise return None."""
    first = selector.split()[0]
    first = re.split(r"[:.\[#>+~]", first)[0].lower()
    if first == "*" or first in SHELL_ELEMENTS:
        return first
    return None


def lint_page(path: Path) -> list[str]:
    """Flag CSS the shell isolation cannot neutralise.

    Bare selectors like `nav a` or `*` are harmless now: content <style>
    blocks are wrapped in @layer content and the shell resets itself with
    `all`. What still escapes: unlayered sources (inline style attributes
    are fine, but external stylesheets and runtime-injected CSS such as the
    Tailwind CDN are not wrapped), and !important, which inverts layer order.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    warnings = []
    for m in re.finditer(r"<link[^>]+rel=[\"']stylesheet[\"'][^>]*>", text, re.I):
        if "fonts.googleapis.com" not in m.group(0):
            warnings.append(f"  external stylesheet is unlayered: {m.group(0)[:90]}")
    tok_re = re.compile(r"--(%s)\s*:" % "|".join(CORE_TOKENS))
    for style_m in re.finditer(r"<style([^>]*)>(.*?)</style>", text, re.I | re.S):
        if "data-base" in style_m.group(1):
            continue
        hits = sorted(set(tok_re.findall(style_m.group(2))))
        if hits:
            warnings.append(
                "  redefines shared tokens (" + ", ".join("--" + h for h in hits)
                + ") - remove them so explainer.css stays the single palette"
            )
    if re.search(r"cdn\.tailwindcss\.com", text, re.I):
        warnings.append("  Tailwind CDN injects unlayered CSS at runtime")
    for style_m in re.finditer(r"<style([^>]*)>(.*?)</style>", text, re.I | re.S):
        if "data-base" in style_m.group(1):
            continue
        css = re.sub(r"/\*.*?\*/", "", style_m.group(2), flags=re.S)
        for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            if "!important" in rule.group(2):
                sel = rule.group(1).strip()
                for part in sel.split(","):
                    if _is_bare_element(part.strip()):
                        warnings.append(
                            f"  `{part.strip()}` uses !important, beats the shell layer"
                        )
    return warnings


def lint_content(content_dir: Path) -> int:
    """Walk content/ and report CSS lint warnings. Returns warning count."""
    total = 0
    for html_file in sorted(content_dir.rglob("*.html")):
        if html_file.name.startswith((".", "_")):
            continue
        warns = lint_page(html_file)
        if warns:
            rel = html_file.relative_to(content_dir)
            print(f"\n  ⚠  {rel}")
            for w in warns:
                print(w)
            total += len(warns)
    return total


# ── template sync ────────────────────────────────────────────────────

def sync_template() -> None:
    """Copy assets/explainer.css into the template's <style data-base> block."""
    css = (ROOT / BASE_CSS).read_text(encoding="utf-8").strip()
    text = TEMPLATE.read_text(encoding="utf-8")
    pat = re.compile(r"(<style\b[^>]*\bdata-base\b[^>]*>).*?(</style>)", re.I | re.S)
    if not pat.search(text):
        raise SystemExit(f"no <style data-base> block in {TEMPLATE}")
    text = pat.sub(lambda m: f"{m.group(1)}\n{css}\n{m.group(2)}", text, count=1)
    TEMPLATE.write_text(text, encoding="utf-8")
    print(f"synced {BASE_CSS} -> {TEMPLATE.relative_to(ROOT)}")


# ── main ─────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Build the static site.")
    ap.add_argument("--out", default="_site", help="output directory")
    ap.add_argument(
        "--staging", action="store_true",
        help="mark every page noindex and add a staging banner",
    )
    ap.add_argument("--serve", action="store_true", help="serve on :8000")
    ap.add_argument(
        "--check", action="store_true",
        help="lint content pages for CSS that could break the site shell",
    )
    ap.add_argument(
        "--sync-template", action="store_true",
        help="copy assets/explainer.css into templates/paper-explainer.html",
    )
    args = ap.parse_args()

    if args.sync_template:
        sync_template()
        return

    config = load_config()

    if args.check:
        print("checking content CSS...")
        n = lint_content(CONTENT)
        if n:
            print(f"\n{n} warning(s) — CSS that can still reach the site shell.")
            print("Scope it under a class, drop !important, or inline the stylesheet.")
            raise SystemExit(1)
        print("all clean.")
        return

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    if not CONTENT.exists():
        CONTENT.mkdir()
        print("content/ was missing, created an empty one")

    nav_tree = build_nav_tree(CONTENT)

    n_warns = lint_content(CONTENT)

    print(f"building{' (staging)' if args.staging else ''}...")
    build_dir(CONTENT, out, [], 0, out, config, args.staging, nav_tree)

    assets_out = out / "assets"
    assets_out.mkdir(exist_ok=True)
    if ASSETS.exists():
        for item in ASSETS.iterdir():
            if item.name == "style.css":
                continue
            if item.is_dir():
                shutil.copytree(item, assets_out / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, assets_out / item.name)
    (assets_out / "style.css").write_text(generate_css(config), encoding="utf-8")

    (out / ".nojekyll").touch()
    if n_warns:
        print(f"\ndone -> {out}  ({n_warns} CSS warning(s), run --check for details)")
    else:
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
