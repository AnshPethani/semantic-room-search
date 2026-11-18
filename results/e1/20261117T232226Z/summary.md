# E1 grounding experiment: summary

- Run: 20261117T232226Z
- Commands: 39 (labels: `data/e1_labels_final.csv`)
- Methods: gemini_full, gemini_names_only
- Models: gemini_full: gemini-3.5-flash-lite; gemini_names_only: gemini-3.5-flash-lite
- Pacing: calls to one provider start at least 6 s apart; a command whose call ended in a backend error is re-run after a backoff of 30 s (doubling), up to 3 passes
- LLM runs did not read or write the cache; latency is the backend latency of the successful attempt.

## Overall

| Method | n | top-1 | top-2 | constraint match | constraint null | latency mean (s) | median | p95 | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini_full | 39 | 88.5% | 97.4% | 100.0% | 100.0% | 1.05 | 1.06 | 1.33 | 0 | 0 (0.0%) |
| gemini_names_only | 39 | 80.8% | 93.6% | 66.7% | 100.0% | 1.08 | 1.08 | 1.39 | 0 | 0 (0.0%) |

Constraint match: exact set match with the expected constraint, over the 9 commands that have one. Constraint null: `room_constraint` is null, over the 30 commands without one. Both are shown for the LLM methods only. A command that never got an LLM answer counts as a miss in every rate; latency covers answered commands only. Keyword-fallback results are never counted as LLM results.

## By command type

### explicit

| Method | n | top-1 | top-2 | constraint match | constraint null | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|
| gemini_full | 12 | 91.7% | 100.0% | - | 100.0% | 0 | 0 (0.0%) |
| gemini_names_only | 12 | 91.7% | 100.0% | - | 100.0% | 0 | 0 (0.0%) |

### category

| Method | n | top-1 | top-2 | constraint match | constraint null | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|
| gemini_full | 9 | 88.9% | 88.9% | - | 100.0% | 0 | 0 (0.0%) |
| gemini_names_only | 9 | 88.9% | 100.0% | - | 100.0% | 0 | 0 (0.0%) |

### need

| Method | n | top-1 | top-2 | constraint match | constraint null | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|
| gemini_full | 9 | 83.3% | 100.0% | - | 100.0% | 0 | 0 (0.0%) |
| gemini_names_only | 9 | 83.3% | 100.0% | - | 100.0% | 0 | 0 (0.0%) |

### relational

| Method | n | top-1 | top-2 | constraint match | constraint null | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|
| gemini_full | 9 | 88.9% | 100.0% | 100.0% | - | 0 | 0 (0.0%) |
| gemini_names_only | 9 | 55.6% | 72.2% | 66.7% | - | 0 | 0 (0.0%) |

## Scene-graph ablation (full minus names only)

| Provider | Metric | full | names only | difference |
|---|---|---|---|---|
| gemini | top-1 | 88.5% | 80.8% | +7.7 pp |
| gemini | top-2 | 97.4% | 93.6% | +3.8 pp |
| gemini | constraint match | 100.0% | 66.7% | +33.3 pp |
| gemini | constraint null | 100.0% | 100.0% | +0.0 pp |

## Hosted vs local latency (answered LLM calls, all variants pooled)

| Kind | Model | n | mean (s) | median | p95 |
|---|---|---|---|---|---|
| hosted (gemini) | gemini-3.5-flash-lite | 78 | 1.07 | 1.06 | 1.34 |

Hosted latency includes the network; local latency depends on the machine.

## Commands without an LLM answer

None: every LLM command got an answer.

## Scoring

Rooms are ranked by `room_prior`, highest first. top-1 hit: the top room is labeled plausible; top-2 hit: at least one of the top two is. Tied rooms at the cut-off are scored with the expected value under random tie-breaking, so the uniform baseline is well defined (for example 2 labeled rooms of 6 give top-1 = 2/6).
