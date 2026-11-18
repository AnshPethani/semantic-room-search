# E1 grounding experiment: summary

- Run: 20261117T233944Z
- Commands: 39 (labels: `data/e1_labels_final.csv`)
- Methods: keyword, uniform, ollama_full, ollama_names_only
- Models: ollama_full: llama3.1:8b; ollama_names_only: llama3.1:8b
- Pacing: calls to one provider start at least 6 s apart; a command whose call ended in a backend error is re-run after a backoff of 30 s (doubling), up to 3 passes
- LLM runs did not read or write the cache; latency is the backend latency of the successful attempt.

## Overall

| Method | n | top-1 | top-2 | constraint match | constraint null | latency mean (s) | median | p95 | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|---|---|---|
| keyword | 39 | 76.9% | 84.4% | - | - | - | - | - | 0 | 0 (0.0%) |
| uniform | 39 | 37.2% | 62.6% | - | - | - | - | - | 0 | 0 (0.0%) |
| ollama_full | 39 | 26.9% | 62.0% | 33.3% | 100.0% | 4.29 | 4.12 | 4.86 | 2 | 2 (5.1%) |
| ollama_names_only | 39 | 6.0% | 37.6% | 11.1% | 96.7% | 5.01 | 4.86 | 6.27 | 3 | 3 (7.7%) |

Constraint match: exact set match with the expected constraint, over the 9 commands that have one. Constraint null: `room_constraint` is null, over the 30 commands without one. Both are shown for the LLM methods only. A command that never got an LLM answer counts as a miss in every rate; latency covers answered commands only. Keyword-fallback results are never counted as LLM results.

## By command type

### explicit

| Method | n | top-1 | top-2 | constraint match | constraint null | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|
| keyword | 12 | 100.0% | 100.0% | - | - | 0 | 0 (0.0%) |
| uniform | 12 | 45.8% | 72.8% | - | - | 0 | 0 (0.0%) |
| ollama_full | 12 | 27.8% | 91.7% | - | 100.0% | 0 | 0 (0.0%) |
| ollama_names_only | 12 | 4.2% | 62.5% | - | 100.0% | 0 | 0 (0.0%) |

### category

| Method | n | top-1 | top-2 | constraint match | constraint null | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|
| keyword | 9 | 90.7% | 92.6% | - | - | 0 | 0 (0.0%) |
| uniform | 9 | 38.9% | 65.9% | - | - | 0 | 0 (0.0%) |
| ollama_full | 9 | 50.0% | 79.6% | - | 100.0% | 0 | 0 (0.0%) |
| ollama_names_only | 9 | 5.6% | 27.8% | - | 88.9% | 1 | 1 (11.1%) |

### need

| Method | n | top-1 | top-2 | constraint match | constraint null | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|
| keyword | 9 | 68.5% | 84.4% | - | - | 0 | 0 (0.0%) |
| uniform | 9 | 40.7% | 68.9% | - | - | 0 | 0 (0.0%) |
| ollama_full | 9 | 7.4% | 33.3% | - | 100.0% | 0 | 0 (0.0%) |
| ollama_names_only | 9 | 3.7% | 29.6% | - | 100.0% | 0 | 0 (0.0%) |

### relational

| Method | n | top-1 | top-2 | constraint match | constraint null | fallback rows | invalid output |
|---|---|---|---|---|---|---|---|
| keyword | 9 | 40.7% | 55.6% | - | - | 0 | 0 (0.0%) |
| uniform | 9 | 20.4% | 39.3% | - | - | 0 | 0 (0.0%) |
| ollama_full | 9 | 22.2% | 33.3% | 33.3% | - | 2 | 2 (22.2%) |
| ollama_names_only | 9 | 11.1% | 22.2% | 11.1% | - | 2 | 2 (22.2%) |

## Scene-graph ablation (full minus names only)

| Provider | Metric | full | names only | difference |
|---|---|---|---|---|
| ollama | top-1 | 26.9% | 6.0% | +20.9 pp |
| ollama | top-2 | 62.0% | 37.6% | +24.4 pp |
| ollama | constraint match | 33.3% | 11.1% | +22.2 pp |
| ollama | constraint null | 100.0% | 96.7% | +3.3 pp |

## Hosted vs local latency (answered LLM calls, all variants pooled)

| Kind | Model | n | mean (s) | median | p95 |
|---|---|---|---|---|---|
| local (ollama) | llama3.1:8b | 73 | 4.64 | 4.44 | 6.15 |

Hosted latency includes the network; local latency depends on the machine.

## Commands without an LLM answer

- **ollama_full**: e1_29 (invalid_output, 1 pass), e1_32 (invalid_output, 1 pass)
- **ollama_names_only**: e1_10 (invalid_output, 1 pass), e1_29 (invalid_output, 1 pass), e1_32 (invalid_output, 1 pass)

## Scoring

Rooms are ranked by `room_prior`, highest first. top-1 hit: the top room is labeled plausible; top-2 hit: at least one of the top two is. Tied rooms at the cut-off are scored with the expected value under random tie-breaking, so the uniform baseline is well defined (for example 2 labeled rooms of 6 give top-1 = 2/6).
