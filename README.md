# Route Planning Model Evaluation System

This system evaluates the output quality of route planning large models, supporting four evaluation scenarios: single-route planning, personalized preferences, route diversity, and general-purpose LLM. The evaluation logic adopts a funnel-style multi-round check, filtering from reachability to accuracy layer by layer.

## Directory Structure

```
.
├── common.py                          # Common evaluation module (Haversine distance, IoU calculation, expert scoring, etc.)
├── single_route/evaluate.py           # Single-route planning evaluation (Benchmark 1)
├── personalized/evaluate.py           # Personalized preference evaluation (Benchmark 2)
├── diversity/evaluate.py              # Route diversity evaluation (Benchmark 3)
├── general_llm/evaluate.py            # General-purpose LLM evaluation (uses a remote route-eval API)
└── data/
    ├── station_info.csv               # Station coordinates and adjacency relations (bundled in this repo)
    ├── benchmark1_single_route_example.csv    # Single-route example data
    ├── benchmark2_personalized_example.csv    # Personalized preference example data
    ├── benchmark3_diversity_example.csv       # Diversity example data
    └── general_llm_example.csv               # General-purpose LLM example data
```

## Requirements

- Python 3.8+
- No additional dependencies (standard library only)

## Usage

Each scenario provides `*_example.csv` (10 samples) for quick validation. The default `--input` of each script points to the corresponding example file, so the following commands can be run directly:

```bash
# Single-route planning evaluation (Benchmark 1)
python3 single_route/evaluate.py --input_field generate_results

# Personalized preference evaluation (Benchmark 2)
python3 personalized/evaluate.py --input_field generate_results

# Route diversity evaluation (Benchmark 3)
python3 diversity/evaluate.py --input_field generate_results

# General-purpose LLM evaluation
python3 general_llm/evaluate.py
```

Parameters:
- `--input`: Input CSV file path
- `--input_field`: Evaluation field, use `generate_results` for external model output evaluation
- `--sample_count`: Number of samples to evaluate (default: all)

`general_llm/evaluate.py` additionally supports:
- `--api_url`: route-eval endpoint; defaults to `TRANSIT_LM_API`, or falls back to `http://transit-lm.amap.com`
- `--batch_size`: batch request size (default: `50`)

Example with an explicit API endpoint:

```bash
python3 general_llm/evaluate.py \
  --api_url http://transit-lm.amap.com \
  --batch_size 50
```

Personalized preference adds Round 5: Preference Compliance (transfer count, subway inclusion, predicted time constraints, etc.).

Diversity evaluation adds extra metrics:
- **Best-Match**: When the first route IoU != 1, automatically search second/third for a reachable alternative with IoU = 1
- **Route Diversity (RD)**: mean(1 - IoU(L_i, L_j)), with transfer mode included as part of the line set

For general-purpose LLM evaluation, the evaluation field is fixed to `generate_results`. The predicted route sequence should use station names rather than `stop_id`, in either of these forms:
- `station_sequence`: directly contains station names
- `station_name`: an explicit station-name sequence field

Scenario-specific input notes:
- Benchmark 1 / Benchmark 2: `sft_label` and `generate_results` are single-route JSON objects
- Benchmark 2: CSV must additionally contain `req_type`
- Benchmark 3: `sft_label` and `generate_results` are multi-route JSON objects, typically containing `first`, `second`, and `third`
- General-purpose LLM: labels still use `station_sequence`, but the sequence content should be station names; prediction-side matching is by station name rather than `stop_id`

## Evaluation Logic (Funnel-Style 4 Rounds)

All scenarios share the following 4 core checks:

| Round | Check Item | Description |
|-------|------------|-------------|
| Round 1 | Reachability | Check if adjacent stations are connected in `next_stop_ids` |
| Round 2 | Station Grounding & Distance Plausibility | Straight-line distance from start/end to first/last station is thresholded by transfer mode (walk 3km / bike 5km / taxi 10km); transfer distance cannot be shorter than straight-line - 0.5km, nor exceed 3x + 0.5km |
| Round 3 | Line IoU + Station IoU + Expert Score + Transfer Mode Consistency | Station IoU filters out [Transfer] nodes; Expert score formula: S = T_sec/300 + (N_lines + cycling_segments) + fare |
| Round 4 | Estimation Accuracy | Distance ±10% or 0.5km, Time ±10% or 5min, Fare ±10% or 1 CNY; Transfer distance ±0.5km |

## Data File Format

### Evaluation Data CSV

| Field | Description |
|-------|-------------|
| `index_id` | Sample unique identifier |
| `sft_prompt` | Input prompt (JSON string, containing query/start/end/city) |
| `sft_label` | Ground truth answer (JSON string) |
| `generate_results` | Model output (JSON string) |

Benchmark 2 additionally requires:

| Field | Description |
|-------|-------------|
| `req_type` | Preference type. Current built-in values: `2` (fewer transfers), `5` (no subway), `7` (subway first), `8` (shorter time) |

### Route JSON Schema

Single-route benchmarks (`benchmark1`, `benchmark2`) expect `sft_label` / `generate_results` to be JSON objects like:

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

Diversity benchmark (`benchmark3`) expects a multi-route JSON object:

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

For general-purpose LLM evaluation, the route JSON keeps the same metric fields, but `station_sequence` should contain station names instead of `stop_id`.

### station_info.csv

| Field | Description |
|-------|-------------|
| `stop_id` | Station ID |
| `ad_code` | City / district code |
| `coord_x` | Longitude |
| `coord_y` | Latitude |
| `next_hop_stations` | Adjacent station ID list (JSON array) |

Notes:
- `common.py` converts `coord_x/coord_y` into internal latitude/longitude values and maps `next_hop_stations` to `next_stop_ids`
- `station_name` is optional in the current bundled `station_info.csv`; if present, it is loaded automatically

## Output Summary

The scripts print stage-by-stage statistics directly to stdout:
- Round 1: Reachability
- Round 2: Station Grounding and Distance Plausibility
- Round 3: Line IoU, Station IoU, expert score, and transfer-mode consistency
- Round 4: Distance / time / fare / transfer accuracy
- Benchmark 2 adds Round 5 Preference Compliance
- Benchmark 3 additionally reports Best-Match statistics and Route Diversity

For quick result inspection, the most useful summary fields are usually reachability pass rate, `station_iou == 1` count, overall accuracy, Preference Compliance (Benchmark 2), and Route Diversity / Best-Match hit distribution (Benchmark 3).
