# TransitLM 路线评估

本仓库为论文《TransitLM: A Large-Scale Dataset and Benchmark for Map-Free Transit Route Generation》的配套评测代码，基于统一的漏斗式评估流程，对路线规划模型输出质量进行系统化评估。

本仓库覆盖以下四类典型场景：

- 单路线规划
- 个性化偏好路线规划
- 多路线多样性评估
- 通用大模型路线评估（调用远程 route-eval API）

本仓库并非仅输出单一总分，而是将评估过程拆解为多个层次，包括路线可达性、站点 grounding、线路结构一致性，以及距离、时间和票价的估计合理性。

## 论文与资源

- arXiv：[`TransitLM: A Large-Scale Dataset and Benchmark for Map-Free Transit Route Generation`](https://arxiv.org/abs/2605.22355)
- Hugging Face Paper：[`TransitLM: A Large-Scale Dataset and Benchmark for Map-Free Transit Route Generation`](https://huggingface.co/papers/2605.22355)
- Hugging Face：[`GD-ML/TransitLM`](https://huggingface.co/datasets/GD-ML/TransitLM)
- 魔搭：[`GD-ML/TransitLM`](https://modelscope.cn/datasets/GD-ML/TransitLM)
- 本仓库：TransitLM 论文对应的 evaluation code，用于复现实验中的评测流程与指标

## 项目定位

- **场景覆盖完整**：同一套评估框架可同时支持 Benchmark 1、2、3 以及通用大模型场景
- **评估结果具备可解释性**：除总体结果外，还提供可达性、grounding、结构匹配和预估准确性等分层信号
- **部署成本较低**：仅依赖 Python 标准库
- **验证流程便捷**：仓库内置示例 CSV，可直接用于快速验证

## 快速开始

环境要求：

- Python 3.8+
- 无额外依赖，只用标准库

可直接运行内置样例：

```bash
python3 single_route/evaluate.py --input_field generate_results
python3 personalized/evaluate.py --input_field generate_results
python3 diversity/evaluate.py --input_field generate_results
python3 general_llm/evaluate.py
```

四个脚本的默认 `--input` 均已指向对应示例 CSV，可直接执行。

## 支持的评估场景

| 场景 | 脚本 | 额外能力 |
|---|---|---|
| 单路线规划 | `single_route/evaluate.py` | 标准 4 轮漏斗评估 |
| 个性化偏好 | `personalized/evaluate.py` | 额外第 5 轮：Preference Compliance |
| 路线多样性 | `diversity/evaluate.py` | 额外输出 Best-Match 和 Route Diversity |
| 通用大模型 | `general_llm/evaluate.py` | 通过远程 route-eval API 评估 |

### 个性化偏好

第 5 轮用于检验预测结果是否满足用户偏好约束，例如：

- 少换乘
- 不坐地铁
- 地铁优先
- 时间更短

### 路线多样性

附加指标包括：

- **Best-Match**：当第一条路线未实现精确命中时，继续在 `second`、`third` 中检索可达且精确匹配的替代路线
- **Route Diversity (RD)**：`mean(1 - IoU(L_i, L_j))`，并将接驳方式纳入路线差异计算

### 通用大模型评估

`general_llm/evaluate.py` 额外支持：

- `--api_url`：默认先读 `TRANSIT_LM_API`，否则回退到 `http://transit-lm.amap.com`
- `--batch_size`：默认 `50`

示例命令如下：

```bash
python3 general_llm/evaluate.py \
  --api_url http://transit-lm.amap.com \
  --batch_size 50
```

在该场景中，评估字段固定为 `generate_results`，站点序列建议使用站点名称而非 `stop_id`。

## 评估流程

所有场景共享以下 4 轮核心检查：

| 轮次 | 检查项 | 作用 |
|---|---|---|
| 1 | 可达性 | 检验相邻站点是否能够在 `next_stop_ids` 中连通 |
| 2 | Station Grounding & Distance Plausibility | 检验起终点 grounding 是否合理，以及接驳距离是否可信 |
| 3 | 线路 IoU + 站点 IoU + 专家评分 + 接驳方式一致性 | 检验预测结构与标注结构是否一致 |
| 4 | 预估准确性 | 检验距离、时间、票价及接驳距离是否处于容忍范围内 |

第 2 轮接驳阈值：

- 步行：3 km
- 骑行：5 km
- 打车：10 km

第 4 轮容差：

- 距离：`+-10%` 或 `0.5 km`
- 时间：`+-10%` 或 `5 min`
- 票价：`+-10%` 或 `1 元`
- 接驳距离：`+-0.5 km`

第 3 轮专家评分公式：

```text
S = T_sec / 300 + (N_lines + cycling_segments) + fare
```

## 输入数据约定

### CSV 字段

通用字段如下：

| 字段 | 说明 |
|---|---|
| `index_id` | 样本唯一标识 |
| `sft_prompt` | 输入 JSON 字符串，通常包含 query / start / end / city |
| `sft_label` | 标注答案 JSON |
| `generate_results` | 模型输出 JSON |

Benchmark 2 额外需要：

| 字段 | 说明 |
|---|---|
| `req_type` | 偏好类型，例如 `2`、`5`、`7`、`8` |

### 路线 JSON 结构

单路线任务采用如下 JSON 对象：

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

多样性任务采用多路线对象：

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

在通用大模型场景下：

- `label` 侧仍沿用 `station_sequence`
- `prediction` 侧建议填写站点名称
- `station_sequence` 与 `station_name` 两种写法均可兼容
- 远程评估阶段主要关注上下车站点及归一化后的换乘结构

## 输出结果关注重点

脚本会直接在终端输出分轮统计结果。通常建议重点关注以下指标：

- 可达性通过率
- `station_iou == 1` 的样本数
- 整体准确率
- Benchmark 2 的偏好命中情况
- Benchmark 3 的 Best-Match 命中情况与 Route Diversity

## 仓库结构

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

## 说明

- `common.py` 会自动将 `coord_x` / `coord_y` 解析为内部经纬度表示
- `next_hop_stations` 会被转换为内部使用的 `next_stop_ids`
- 若 `station_info.csv` 中存在 `station_name` 列，脚本会自动读取
