# pllee4-docs.github.io

Static site for notes and interactive explainers. Pages are plain, self-contained
HTML files; the index pages are generated from the folder structure, so adding a
page is just dropping a file in a folder.

Live at <https://pllee4-docs.github.io>

## Adding a page

1. Put your `.html` file anywhere under `content/`, in whatever folder makes sense.
   Create the folder if it does not exist.
2. Make sure the file has a `<title>` and ideally a `<meta name="description">`.
   Those two tags are what show up in the listing.
3. Commit and push to `main`. GitHub Actions rebuilds and deploys.

```
content/
├── mapf/
│   ├── _meta.json          optional, names the folder
│   ├── cbs.html
│   └── mdd.html
└── cpp/
    └── templates/
        └── folds.html
```

That tree produces:

```
/                      -> lists "Multi-Agent Pathfinding", "Cpp"
/mapf/                 -> lists "CBS Algorithm", "MDD Construction"
/mapf/cbs.html         -> your page, untouched
/cpp/templates/        -> lists "Fold Expressions"
```

## Naming folders

Without a `_meta.json`, a folder is titled from its directory name
(`my-notes` becomes "My notes"). To control it, drop a `_meta.json` inside:

```json
{
  "title": "Multi-Agent Pathfinding",
  "description": "Interactive explainers for CBS and the algorithms it builds on.",
  "order": 10
}
```

All three keys are optional. `order` sorts folders on the parent page, lower
first; folders without one default to 100 and then sort alphabetically.

## Rules the build follows

- Every folder gets an `index.html` listing its subfolders and pages.
- If a folder already contains a hand-written `index.html`, it is left alone.
  Use that when you want a custom landing page for a section.
- Files and folders starting with `.` or `_` are skipped, so `_meta.json` and
  `_drafts/` stay out of the site.
- Non-HTML files (images, CSS, JSON, data) are copied through as-is, so a page
  can reference `./diagram.svg` sitting next to it.
- Page titles come from `<title>`, descriptions from `<meta name="description">`.

## Local preview

```bash
python3 build.py --serve               # http://localhost:8000
python3 build.py                       # build only, into _site/
python3 build.py --staging --serve     # what the staging preview looks like
```

Needs Python 3 with `pyyaml` and `markdown` (`pip install pyyaml markdown`).

## Branches and deployment

Two branches publish to two places on the same site:

| Branch    | URL                                  | Indexed by search engines |
| --------- | ------------------------------------ | ------------------------- |
| `main`    | `https://pllee4-docs.github.io/`        | yes                       |
| `staging` | `https://pllee4-docs.github.io/preview/` | no                        |

GitHub Pages only serves one site per repository, so a push to **either**
branch runs one workflow that builds both: `main` into the site root and
`staging` into `preview/`. Every staging page gets a `noindex, nofollow` tag
and an orange banner across the top, so a preview link is never mistaken for
the real thing and never shows up in search results.

Staging is still publicly reachable by anyone who guesses the URL. Do not put
anything there you would mind being read.

Typical loop:

```bash
git switch staging
# add or edit pages under content/
git push                       # review at /preview/

git switch main
git merge staging
git push                       # now live at /
```

The staging branch is optional. Until you create it, the workflow detects that
it is missing and just builds `main`.

### One-time repo setup

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. Create the staging branch when you want it: `git switch -c staging && git push -u origin staging`.

`_site/` is gitignored. Do not commit it; the workflow builds it.

One name to avoid: a top-level folder called `preview` under `content/` would
collide with the staging output. Anything else is fine.

## Styling

All explainer pages share one design system, `assets/explainer.css`. Pages
only carry CSS for their own visualizations. The sidebar and header are
isolated, so nothing a page does can change them. See `STYLE.md` for the
rules and `templates/paper-explainer.html` for a starting point, and run
`python3 build.py --check` before pushing.
