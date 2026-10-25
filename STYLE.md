# Explainer style contract

Every page under `content/` shares one look. That look lives in exactly one
file, `assets/explainer.css`. Pages bring only the CSS their own
visualizations need.

## How the cascade works

| Layer     | Source                         | Owns                                          |
| --------- | ------------------------------ | --------------------------------------------- |
| `base`    | `assets/explainer.css`         | tokens, type, TLDR, section headers, cards    |
| `content` | the page's own `<style>`       | diagrams, demos, page-only components         |
| `shell`   | generated `assets/style.css`   | header, sidebar, "On this page" (untouchable) |

Later layers win. So a page *can* override the base, which is exactly
what keeps pages consistent only if pages don't do it. `build.py --check`
enforces the hard rules below.

## Hard rules (checked by `python3 build.py --check`)

1. Do not redefine the core tokens: `--bg --s --s2 --c --bd --fg --dim --h
   --blue --teal --amber --rose --violet --green --cyan`. Page-specific tokens
   with other names are fine (e.g. CBS's `--a1`, `--edge`).
2. No `!important` on element selectors.
3. No external stylesheets other than Google Fonts, and no Tailwind CDN.

## Soft rules (reviewed by eye)

- Don't restyle `body`, `h1`, `h2`, `h3`, `.sub`, `.tldr`, `.card`, `.bar`,
  `.desc`, `.jump`, `code`. If one needs to change, change it in
  `explainer.css` so every page gets it.
- Colours in SVG use tokens: `fill="var(--blue)"`, never hex.
- Fonts: `var(--sans)` (Inter) for prose, `var(--mono)` (JetBrains Mono) for
  headings, labels, code and SVG text. Nothing else.
- Section titles must be real `<h2>`/`<h3>` elements. The "On this page"
  panel is built from them.
- Diagram labels stay readable at 100% zoom (see Diagrams).

## Page skeleton

Start from `templates/paper-explainer.html`. The vocabulary:

| Element                                   | Use                                          |
| ----------------------------------------- | -------------------------------------------- |
| `<h1>`                                    | paper / topic title                          |
| `<p class="sub">`                         | one-line subtitle                            |
| `<div class="tldr">` + `<span class="cite">` | TLDR box with citation and links          |
| `<nav class="jump">`                      | in-page pills (auto-hidden when TOC shows)   |
| `<div class="sec"><div class="sec-d">1</div><h2>…</h2></div>` | numbered section header |
| `<p class="section-intro">`               | short intro paragraph under a header         |
| `<h3>`                                    | sub-section, figure title                    |
| `.card > .card-body`                      | container for a figure or demo               |
| `.bar` with `<button>`s and `.slab`       | stepper controls under a card                |
| `.desc`                                   | step description under a stepper             |
| `.vis` / `.graph-wrap`                    | wrapper that centres and scales an SVG       |
| `.legend > .legend-i > .ldot`             | colour legend                                |

Colour a section dot with `style="background:var(--teal)"` on `.sec-d`.

### Diagrams

Build diagrams from HTML blocks, not one wide SVG. A 1000-unit-wide SVG
squeezed into the content column renders 6px labels; HTML text stays at
real size and reflows on phones. Set the accent with `style="--k:var(--teal)"`.

| Block                         | Use                                                    |
| ----------------------------- | ------------------------------------------------------ |
| `.dg`                         | wrapper for one diagram (enables the responsive rules) |
| `.lvl` + `.lvl-tag`           | framed group with a badge (HIGH / MID / LOW level)     |
| `.cells`                      | responsive grid; `.span` child takes a full row        |
| `.panel` + `.panel-t`         | neutral sub-panel with a title                         |
| `.box` + `.box-t`             | standalone card with a title                           |
| `.node` + `.node-t` / `.node-l` / `.out` | coloured card: title, detail lines, output line |
| `.flow`                       | pipeline: a row with → arrows, a column with ↓ on narrow screens |
| `.steps` (`.counted` adds numbers) | grid of step cards                                |
| `.down` (optional label)      | ↓ connector between stacked blocks                     |
| `.chips` + `.chip` (`.lg`, `<small>` sub-line) | tinted labels                         |
| `.fig` / `.fig-scroll`        | SVG wrapper; `.fig-scroll` keeps `--minw` and scrolls on phones |
| `.cap`                        | small centred caption                                  |

When SVG is needed (graphs, plans, state machines), size the `viewBox`
close to the width it will render at, so it draws at about 1x or larger, and
keep every label at 11 units or more. Check with `python3 build.py --serve`:
labels should render at 11px or more on a 1440px-wide window, and stay
above about 9px at 1280px.

## Standalone preview

A generated page may include a copy of `explainer.css` inside
`<style data-base>` so it looks right when opened directly (or previewed in
Claude). The build strips that block and loads the canonical file, so a
stale copy can never cause drift. Refresh the template's copy with:

```bash
python3 build.py --sync-template
```

## Adding a page

1. Generate the page with the paper-explainer skill (it follows this file).
2. Drop it into `content/<topic>/`.
3. `python3 build.py --check`, fix anything it flags.
4. `python3 build.py --serve` and look at it in light and dark.
5. Push to `staging`, review at `/preview/`, merge to `main`.
