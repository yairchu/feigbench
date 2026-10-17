# Benchmark landing page draft

A buildless static page with a bundled Plotly SVG scatter chart, vendor/effort filters, hover and tap details, an accessible results table, saved excerpts, methodology, and data downloads. It uses the existing scorer and equal-text aggregation rather than maintaining a separate scoring implementation.

Build the draft from the completed run:

```sh
uv run export_site.py results/20261015-145656
```

Open `site/dist/index.html` directly in a browser, or serve it:

```sh
uv run python -m http.server 8000 --directory site/dist
```

Then visit <http://localhost:8000>. No server-side computation or API key is required. Plotly is bundled locally from the locked Python dependency, so the built page does not require a CDN or internet connection.

`site/dist/` is generated and ignored by Git. Its entire contents can be uploaded to a static host once the draft is approved. Source files are `index.html`, `style.css`, and `app.js`; `export_site.py` produces the data and downloadable artifacts. Rebuild after editing source files. The working draft is in English, with a Hebrew introduction for carousel visitors.

The narrative and its two checked examples currently refer specifically to run `20261015-145656`. The exporter requires all planned jobs to have saved records, deduplicates resumed attempts, reads saved texts and scoring targets, and verifies the two cited first-place guesses. A later run needs an editorial review of the fixed narrative and examples before publication.

Costs in the table remain unknown when recorded usage is missing. Such settings are omitted from the scatter plot. The raw-response download includes all effective responses, including the negative control; it does not include environment variables or API credentials.
