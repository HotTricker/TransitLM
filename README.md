# TransitLM Route Evaluation

This repository provides the companion evaluation code for the paper *TransitLM: A Large-Scale Dataset and Benchmark for Map-Free Transit Route Generation*, and offers a unified funnel-style pipeline for systematically evaluating route-planning model outputs.

It supports the following four representative settings:

- Single-route planning
- Preference-aware planning
- Multi-route diversity
- General-purpose LLM evaluation through a remote route-eval API

Rather than producing only a single aggregate score, the evaluator decomposes quality into several dimensions, including reachability, station grounding, structural consistency, and the plausibility of distance, time, and fare estimates.

## Paper And Resources

- Paper: [`TransitLM: A Large-Scale Dataset and Benchmark for Map-Free Transit Route Generation`](https://huggingface.co/papers/2605.22355), [arXiv:2605.22355](https://arxiv.org/abs/2605.22355)
- Hugging Face: [`GD-ML/TransitLM`](https://huggingface.co/datasets/GD-ML/TransitLM)
- ModelScope: [`GD-ML/TransitLM`](https://modelscope.cn/datasets/GD-ML/TransitLM)
- This repository: the evaluation code accompanying the TransitLM paper, intended for reproducing the evaluation pipeline and metrics used in the benchmark

## Why This Repo

- **Scenario coverage**: one codebase for benchmark 1, 2, 3, and general LLM evaluation
- **Layered evaluation**: reachability, grounding, overlap, and estimation accuracy are reported separately
- **Lightweight setup**: Python standard library only
- **Fast validation**: bundled example CSVs let you run every evaluator immediately

## Quick Start

Requirements:

- Python 3.8+

Run the built-in examples:

```bash
python3 single_route/evaluate.py --input_field generate_results
python3 personalized/evaluate.py --input_field generate_results
python3 diversity/evaluate.py --input_field generate_results
python3 general_llm/evaluate.py
```

The default `--input` of each script is already configured to the corresponding example CSV.

## What Each Evaluator Covers

| Scenario | Script | Extra Logic |
|---|---|---|
| Single-route planning | `single_route/evaluate.py` | 4-round core funnel |
| Personalized planning | `personalized/evaluate.py` | Adds Round 5: Preference Compliance |
| Route diversity | `diversity/evaluate.py` | Adds Best-Match and Route Diversity (RD) |
| General LLM | `general_llm/evaluate.py` | Uses remote route-eval API |

### Personalized Planning

Round 5 verifies whether the prediction satisfies user preference constraints such as:

- fewer transfers
- no subway
- subway first
- shorter travel time

### Diversity Planning

Additional metrics include:

- **Best-Match**: if the first route is not an exact match, search `second` and `third` for a reachable exact alternative
- **Route Diversity (RD)**: `mean(1 - IoU(L_i, L_j))`, with transfer modes included in the route signature

### General LLM Evaluation

`general_llm/evaluate.py` additionally supports:

- `--api_url`: defaults to `TRANSIT_LM_API`, then falls back to `http://transit-lm.amap.com`
- `--batch_size`: default `50`

Example command:

```bash
python3 general_llm/evaluate.py \
  --api_url http://transit-lm.amap.com \
  --batch_size 50
```

In this setting, the evaluation field is fixed to `generate_results`, and station sequences should use station names rather than `stop_id`.

## Evaluation Pipeline

All scenarios share the following four core rounds:

| Round | Check | What It Verifies |
|---|---|---|
| 1 | Reachability | Adjacent stations are connected in `next_stop_ids` |
| 2 | Station Grounding & Distance Plausibility | Verifies start/end grounding and the plausibility of transfer distances |
| 3 | Line IoU + Station IoU + Expert Score + Transfer Mode Consistency | Verifies structural consistency between prediction and reference |
| 4 | Estimation Accuracy | Verifies the accuracy of distance, time, fare, and transfer estimates |

Round 2 thresholds:

- walk: 3 km
- bike: 5 km
- taxi: 10 km

Round 4 tolerances:

- distance: `+-10%` or `0.5 km`
- time: `+-10%` or `5 min`
- fare: `+-10%` or `1 CNY`
- transfer distance: `+-0.5 km`

Expert score formula used in Round 3:

```text
S = T_sec / 300 + (N_lines + cycling_segments) + fare
```

## Input Contract

### CSV Fields

Common fields are as follows:

| Field | Description |
|---|---|
| `index_id` | Sample identifier |
| `sft_prompt` | Prompt JSON string, usually including query / start / end / city |
| `sft_label` | Ground-truth route JSON |
| `generate_results` | Model output JSON |

Benchmark 2 also requires:

| Field | Description |
|---|---|
| `req_type` | Preference type, such as `2`, `5`, `7`, `8` |

### Route JSON

Single-route tasks expect a JSON object of the following form:

```json
{
  "station_sequence": ["stop_id_1", "stop_id_2", "stop_id_3"],
  "line_sequence": ["Line A", "Line B"],
  "total_distance": "12.5",
  "total_time": "35",
  "total_fare": "4",
  "start_transfer_mode": "步行",
  "start_transfer_distance": "0.8",
  "end_transfer_mode": "步行",
  "end_transfer_distance": "0.6"
}
```

Diversity tasks expect a multi-route object of the following form:

```json
{
  "first": {
    "station_sequence": ["stop_id_1", "stop_id_2"],
    "line_sequence": ["Line A"],
    "total_distance": "8.2",
    "total_time": "24",
    "total_fare": "3"
  },
  "second": {
    "station_sequence": ["stop_id_3", "stop_id_4"],
    "line_sequence": ["Line B"],
    "total_distance": "9.0",
    "total_time": "27",
    "total_fare": "4"
  },
  "third": {
    "station_sequence": ["stop_id_5", "stop_id_6"],
    "line_sequence": ["Line C"],
    "total_distance": "10.5",
    "total_time": "30",
    "total_fare": "4"
  }
}
```

For the general LLM setting:

- labels still use `station_sequence`
- prediction-side station sequences should contain station names
- both `station_sequence` and `station_name` are accepted
- the remote evaluator primarily relies on boarding / alighting stations and normalized transfer structure

## Key Output Signals

The scripts print round-by-round summaries to stdout. In practice, the following signals are usually the most informative:

- reachability pass rate
- number of samples with `station_iou == 1`
- overall accuracy
- preference compliance for benchmark 2
- best-match hits and route diversity for benchmark 3

## Repository Layout

```text
.
├── common.py
├── single_route/evaluate.py
├── personalized/evaluate.py
├── diversity/evaluate.py
├── general_llm/evaluate.py
└── data/
    ├── station_info.csv
    ├── benchmark1_single_route_example.csv
    ├── benchmark2_personalized_example.csv
    ├── benchmark3_diversity_example.csv
    └── general_llm_example.csv
```

## Notes

- `common.py` automatically converts `coord_x` / `coord_y` into internal longitude / latitude values
- `next_hop_stations` is normalized into `next_stop_ids`
- if `station_name` exists in `station_info.csv`, it is loaded automatically
