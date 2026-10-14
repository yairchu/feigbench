# feigbench

Can LLMs identify the speaker of a real political interview after it has been disguised?

The source is a ~24 minute interview with **Moshe Feiglin** on Channel 7 (Arutz Sheva / inn.co.il, late 2023 – early 2024), about the Gaza war after October 7. The interview was transcribed (OCR of burned-in subtitles, `source/transcript_he_ocr.md`), translated to English, and then disguised in progressively stronger steps. Each version is a text in `texts/`. The benchmark asks models to name the conflict and the speaker, and measures how often they get to Feiglin.

This is for a video in Yair's political video series. Any quote shown publicly must be checked against the original video, since the transcript is OCR.

## Texts

| File | What changed vs. the previous version |
|---|---|
| `A_full_masked` | Full interview. All names, places, nations, organizations and historical events replaced (Oslo → "the Accords", Hamas → "the Brotherhood", Netanyahu → "the leader", hostages → "captives", government → "council"). Hebrew idioms removed. |
| `B_no_biography` | Removed his biography: leaving Likud, "fought him from inside for years", his podcast, his political plans. |
| `C_no_bio_no_signature` | Also removed his signature phrase "a leadership of faith" (מנהיגות אמונית). |
| `D_no_conflict_markers` | Removed what pins the conflict: the Shalit deal, Majdal/Ashkelon, Lebanon and the security zone, Four Mothers, Beilin and Barak, Arafat, Saladin, tunnels/rockets/fuel. Massacre → "disaster", Accords → "the Agreement", Hamas → "the enemy". |
| `E_medieval` | D transposed into a medieval world (soldiers → warriors, sniper → archer, jerrycan → waterskin, pilots → catapult masters, US → "the kingdom across the sea", Treaty, factions). |
| `F_core_neutral` | Only the ideological core (~475 words), rewritten in flat neutral style. All background events removed (captives, deal, aid, generals, US, statehood, orders). |
| `G_new_geography` | F with a misleading geography: mountain people vs. steppe clans, river ford, watchtowers. No sea, coast or enclave. |
| `H_no_slogan` | G with the "conquest, expulsion, repopulation" slogan broken into plain sentences, and the "faction that brought the Treaty and the faction that kept it" clue weakened. |
| `S1_burned_cities` | Excerpt of H: only the "no one is innocent, burn the cities" analogy. |
| `S2_expulsion` | Excerpt: only the expulsion and "no raids from lands we took long ago". |
| `S3_treaty_mindset` | Excerpt: only "every faction kept the Treaty way of thinking". |
| `S4_tactics_vs_strategy` | Excerpt: field heroism vs. strategic defeat, rejecting the buffer zone. |
| `S5_no_treaty_no_expulsion` | H without the calamity, the Treaty and the expulsion. |
| `S6_leadership_only_control` | Control: generic populist criticism of a ruling class. Should not point to anyone. |

`results/manual_chatgpt_runs_and_key_he.md` (Hebrew) has the full substitution key and the manual ChatGPT results.

## Findings so far (manual ChatGPT runs, before this script)

| Text | ChatGPT's answer |
|---|---|
| A | Feiglin, 98% |
| C | Feiglin, 85–90% |
| D | Feiglin, 90% (also non-personalized) |
| E | Open question: no name, but decoded Oslo/Netanyahu/Oct 7. Forced top 5: Feiglin 75% |
| G | Israel/Gaza; speaker guesses Smotrich / Ben-Gvir, low confidence |
| H | Open question: no name. Forced top 5: Feiglin 35%, Weiss 20%, Smotrich 15% |
| S1, S2 | With web search: not Israel. Without search: Israel (Amalek/Smotrich, Ben-Gurion) |
| S3 | Israel + Oslo, speaker unknown |
| S4 | Israel/Gaza, "former senior officer" |
| S5 | Israel, **Liberman** (wrong) |
| S6 | "Anti-colonial nationalist", not Israel (control passed) |

Observations:

- The most extreme content (burning cities with children, expulsion) does not point to Israel on its own. The political analysis does: a treaty every faction kept (Oslo) and recurring rounds plus a buffer zone (Gaza).
- Feiglin is identified by the combination of Oslo-as-a-mindset plus expulsion. Without them the model picks a generic security hawk (Liberman).
- In E and H the model cited "Hiroshima and Nagasaki" as its main clue, though those were removed from every version. Feiglin did say "Hiroshima" in the original. This suggests recognition of a statement it has seen, not only reasoning from the text.

## Why this script

The manual runs had confounds this script removes:

- **Personalization and memory.** ChatGPT's "personalized" Temporary Chat still applied custom instructions. The API has none.
- **Location.** ChatGPT appears to receive the user's approximate location (Israel). S1 and S2 jumped to Israel without web search but not with it. API calls carry no location.
- **Web search.** Some manual runs searched despite instructions. Plain API calls don't search. Don't use model ids ending in `:online`.
- **Single runs.** Each text × model now runs several times (default 3, temperature 1.0) to measure variance.
- **Inconsistent prompts.** One fixed prompt (`prompts/identify.md`) asks for the top 3 contexts and top 5 speakers as JSON, so scoring is automatic.

## Running

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first (`brew install uv` on macOS), then run these commands from the project directory. `uv run` sets up Python 3.13 and the project environment automatically, using the dependencies pinned in `uv.lock`.

```bash
export OPENROUTER_API_KEY=sk-or-...           # never commit this
uv run run_bench.py --list-models openai anthropic google x-ai deepseek   # pick ids
uv run run_bench.py --list-efforts gemini gpt claude # inspect supported reasoning levels
# put the chosen ids in models.txt
uv run run_bench.py --dry-run                 # shows how many calls
uv run run_bench.py --runs 3                  # everything
uv run run_bench.py --texts 'S*' --runs 5     # only the excerpts
uv run run_bench.py --efforts low medium high --runs 1 --dry-run # preview an effort sweep
uv run run_bench.py --efforts low medium high --runs 1 # run all three settings
uv run run_bench.py --summarize results/<dir> # re-score an existing run
uv run plot_bench.py results/<dir>           # regenerate just the cost/score chart
uv run python -m unittest discover tests             # offline tests, no key or network needed
```

The tests replace the HTTP layer with a mock that returns scripted OpenRouter replies (clean JSON, messy JSON with `"35%"` confidences, a reasoning model that hit `max_tokens`, a 503 then success, a 400). OpenRouter has no sandbox of its own. To try a real call cheaply, use one of its `:free` model ids.

`targets.json` says which speaker and context count as correct for each text, as regexes keyed by a glob over text names (first match wins, `default` otherwise). Speaker and context lists are re-sorted by the model's confidence before ranking, since models don't always list them in order. `--max-tokens` defaults to 16000 because reasoning models count hidden reasoning against it; a reply that ran out before answering is reported as `truncated` in the `error` column.

HTTPS requests use the `certifi` CA bundle, so python.org installations do not need a separate macOS certificate setup. For a custom certificate authority, set `SSL_CERT_FILE` to your trusted CA bundle (or `SSL_CERT_DIR` to an OpenSSL certificate directory). Certificate verification remains enabled.

Each run writes to `results/<timestamp>/`:

- `raw.jsonl`: every reply, verbatim
- `scored.csv`: one row per call (target's rank and confidence, top-1 speaker, top context, whether the context matches)
- `summary.csv` / `summary.md`: per text × model (target top-1 rate, in-top-5 rate, mean confidence, context-match rate, errors, the top-1 names given)
- `model_summary.csv`: per model × effort soft score, confidence components, and recorded dollar costs, excluding S6
- `cost_score.png` / `cost_score.svg`: cost-versus-score scatter plot, generated automatically when complete costs are available

The **soft score** is `(speaker confidence + context confidence) / 2`, on a 0–100 scale. Speaker confidence is the confidence assigned to the target speaker wherever they appear in the candidate list (zero if absent). Context confidence sums all matching context guesses, capped at 100%. Matches use `targets.json`; by default Israel, Gaza, and Palestine count as the Israeli context. Individual confidences are bounded to 0–100; missing or non-finite values contribute zero. Unparseable answers receive zero soft score.

The plotted score averages runs within each text, then averages texts equally. `S6_leadership_only_control` stays in the per-text summaries but is excluded from the chart because it is a negative control. The dollar axis uses recorded `usage.cost`, averaged with the same text weighting. Missing costs stay unknown and models with incomplete costs are omitted from the chart. Zero-cost models use a linear dollar axis; otherwise it is logarithmic. Scores use models' self-reported confidence, so confidence calibration can affect comparisons.

OpenRouter supports [reasoning effort settings](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens) through a request such as `"reasoning": {"effort": "high"}`. Use `--efforts low medium high` to run each model at each requested setting (`mid` is accepted as an alias for `medium`). Other gateway levels are `none`, `minimal`, `xhigh`, and `max`; supported levels vary by model. `--list-efforts FILTER...` reads the model catalog's advertised levels and defaults. Before a live sweep, the runner checks model metadata and rejects known unsupported settings; it also requests providers that support the reasoning parameter. A dry run previews the call count offline and does not validate support.

Effort is saved in the run configuration, raw records, and every summary. The chart connects explicit effort points in effort order when their texts and run counts match. `--efforts default` (the default) leaves effort unspecified; older runs without effort metadata are also labeled `default` and never assigned a guessed level or connected into an effort series. Effort levels describe requested settings rather than measured compute, and their meaning differs across providers. Additional live runs are needed to measure the cost/score tradeoff; existing replies cannot be rescored into new effort levels.

## Next steps

1. **Run A–H and S1–S6** across 4–6 models, 3 runs each.
2. **Control speakers.** Disguise a comparable interview by Daniella Weiss, Smotrich or Ben-Gvir the same way, to check that "Feiglin" is a real identification and not the default answer for this camp. Score with the matching name by adding an entry to `targets.json`.
3. **Control conflict.** A text with the same structure from a different conflict (e.g. a Russian nationalist on Ukraine), to check the base rate of guessing "Israel".
4. **Minimal excerpt.** Find the shortest passage that still gets Feiglin.
5. **Moral-judgment variant (optional).** Ask models to rate how extreme the text is, disguised vs. original.
