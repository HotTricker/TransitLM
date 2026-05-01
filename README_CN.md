# 路线规划模型评估系统

本系统用于评估路线规划大模型的输出质量，支持四种评估场景：单路线规划、个性化偏好、路线多样性和通用大模型。评估逻辑采用漏斗式多轮检查，从可达性到准确性逐层筛选。

## 目录结构

```
.
├── common.py                          # 公共评估模块（Haversine距离、IoU计算、专家评分等）
├── single_route/evaluate.py           # 单路线规划评估（Benchmark 1）
├── personalized/evaluate.py           # 个性化偏好评估（Benchmark 2）
├── diversity/evaluate.py              # 路线多样性评估（Benchmark 3）
├── general_llm/evaluate.py            # 通用大模型评估
└── data/
    ├── station_info.csv               # 站点坐标、名称、邻接关系（~12万条）
    ├── line_info.csv                  # 线路信息，含站点列表（~1.4万条）
    ├── benchmark1_single_route_example.csv    # 单路线示例数据
    ├── benchmark2_personalized_example.csv    # 个性化偏好示例数据
    ├── benchmark3_diversity_example.csv       # 多样性示例数据
    └── general_llm_example.csv              # 通用大模型示例数据
```

## 环境要求

- Python 3.8+
- 无需额外依赖（仅使用 Python 标准库）

## 使用方法

各场景均提供 `*_example.csv`（10条样本），可用于快速验证评估流程。四个脚本的默认 `--input` 已指向对应示例文件，因此下面命令可直接运行：

```bash
# 单路线规划评估（Benchmark 1）
python3 single_route/evaluate.py --input_field generate_results

# 个性化偏好评估（Benchmark 2）
python3 personalized/evaluate.py --input_field generate_results

# 路线多样性评估（Benchmark 3）
python3 diversity/evaluate.py --input_field generate_results

# 通用大模型评估
python3 general_llm/evaluate.py
```

参数说明：
- `--input`: 输入 CSV 文件路径
- `--input_field`: 评估字段，对外使用时传 `generate_results`（模型输出）
- `--sample_count`: 评估样本数（默认全部）

个性化偏好额外评估第5轮：Preference Compliance（换乘次数、是否含地铁、预测时间等偏好约束）。

多样性评估额外指标：
- **Best-Match**：首条路线 IoU≠1 时，自动从 second/third 中寻找可达且 IoU=1 的替代
- **Route Diversity (RD)**：mean(1 - IoU(L_i, L_j))，含接驳方式作为线路集合的一部分

通用大模型使用 `station_name`（站点名称）而非 `stop_id`，评估字段固定为 `generate_results`。

各场景输入差异：
- Benchmark 1 / Benchmark 2：`sft_label` 和 `generate_results` 都是单路线 JSON
- Benchmark 2：CSV 额外需要 `req_type`
- Benchmark 3：`sft_label` 和 `generate_results` 都是多路线 JSON，通常包含 `first`、`second`、`third`
- General-purpose LLM：站点序列按 `station_name` 匹配，而不是 `stop_id`

## 评估逻辑（漏斗式4轮）

所有场景共享以下4轮核心检查：

| 轮次 | 检查项 | 说明 |
|------|--------|------|
| 第1轮 | 可达性 | 检查相邻站点在 `next_stop_ids` 中连通 |
| 第2轮 | Station Grounding & Distance Plausibility | 起终点到首末站直线距离按接驳方式设阈值（步行3km/骑行5km/打车10km）；接驳距离不能短于直线距离-0.5km，不能超过3倍+0.5km |
| 第3轮 | 线路IoU + 站点IoU + 专家评分 + 接驳方式一致性 | 站点IoU过滤【换乘】节点；专家评分公式：S = T_sec/300 + (N_lines + cycling_segments) + fare |
| 第4轮 | 预估准确性 | 距离±10%或0.5km、时间±10%或5min、费用±10%或1元；接驳距离±0.5km |

## 数据文件格式

### 评估数据 CSV

| 字段 | 说明 |
|------|------|
| `index_id` | 样本唯一标识 |
| `sft_prompt` | 输入提示（JSON字符串，含 query/start/end/city） |
| `sft_label` | 标注答案（JSON字符串） |
| `generate_results` | 模型输出（JSON字符串） |

Benchmark 2 额外需要：

| 字段 | 说明 |
|------|------|
| `req_type` | 偏好类型。目前内置值包括：`2`（换乘少）、`5`（不坐地铁）、`7`（地铁优先）、`8`（时间短） |

### 路线 JSON 结构

单路线任务（`benchmark1`、`benchmark2`）中的 `sft_label` / `generate_results` 应为如下 JSON 对象：

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

多样性任务（`benchmark3`）中的 `sft_label` / `generate_results` 应为多路线 JSON：

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

通用大模型评估沿用相同的距离/时间/票价字段，但 `station_sequence` 中应填写站点名称，而不是 `stop_id`。

### station_info.csv

| 字段 | 说明 |
|------|------|
| `stop_id` | 站点ID |
| `lat` | 纬度 |
| `lng` | 经度 |
| `station_name` | 站点名称 |
| `next_stop_ids` | 相邻站点ID列表（JSON数组） |

### line_info.csv

| 字段 | 说明 |
|------|------|
| `citycode` | 城市编码 |
| `line_name` | 线路名称 |
| `station_list` | 站点列表（JSON数组，含 station_name + stop_id） |

## 输出说明

脚本会直接在终端输出分轮统计结果：
- 第1轮：可达性
- 第2轮：Station Grounding 与 Distance Plausibility
- 第3轮：线路 IoU、站点 IoU、专家评分、接驳方式一致性
- 第4轮：距离 / 时间 / 费用 / 接驳准确性
- Benchmark 2 额外输出第5轮 Preference Compliance
- Benchmark 3 额外输出 Best-Match 统计与 Route Diversity

快速看结果时，通常最值得关注的是：可达性通过率、`station_iou == 1` 的样本数、整体准确率、Benchmark 2 的 Preference Compliance，以及 Benchmark 3 的 Route Diversity 和 Best-Match 命中分布。
