# Laneguard dashboard (optional)

A single static HTML page showing, per lane: latest outcome, recent runs, outcome counts, monthly
cost against the ceiling, pause state and circuit-breaker hints. Python standard library only; the
page has inline CSS and JS, makes no external requests, and follows `prefers-color-scheme`.

## Use

```sh
# from local files
python3 dashboard/build.py --runs runs.jsonl --paused-dir . \
  --config .laneguard/config.yaml --out site/index.html

# straight from the data branch of a repo (path or URL; missing branch renders an empty page)
python3 dashboard/build.py --from-git . --branch laneguard-data \
  --config .laneguard/config.yaml --out site/index.html
```

`--paused-dir` reads `PAUSED` (all lanes) and `PAUSED.<lane>` files. `--config` supplies lane names,
the monthly ceiling and breaker limits; without it lanes are taken from the runs. Unreadable JSON
lines are skipped and counted on the page.

## Workflow

`templates/github/workflows/laneguard-dashboard.yml.tmpl` runs daily and on demand with
`contents: read` only, checks out the pinned engine, builds the page and uploads it as the
`laneguard-dashboard` workflow artifact. It does not publish it anywhere; download it from the run.
Placeholders are `{{CHECKOUT_SHA}}` and `{{ENGINE_REPO}}`, filled the same way as the other templates.

## Security

Notes and run ids are untrusted text. All data is escaped with `html.escape` in the markup, the embedded
JSON copy has `<`, `>` and `&` escaped, a CSP meta tag blocks network access, and the script only
uses `textContent`. The page may show lane notes and costs, so treat the artifact like the repo's own
visibility.

## Tests

`python3 -m unittest discover -s dashboard/tests -t .`
