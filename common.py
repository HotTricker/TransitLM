#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路线规划评估公共模块
从CSV加载依赖表，保留完整检查逻辑。
"""

import csv
import json
import math
import os
import re
from itertools import combinations

# ============================================================
# CSV 加载函数
# ============================================================

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


def _data_path(filename):
    return os.path.join(DATA_DIR, filename)


def load_station_info(csv_path=None):
    """Load station info from CSV: stop_id -> {lat, lng, station_name, next_stop_ids}.

    The CSV schema is:
        stop_id, ad_code, coord_x (lng), coord_y (lat), next_hop_stations
    """
    if csv_path is None:
        csv_path = _data_path('station_info.csv')
    info = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row['stop_id']
            lng = float(row['coord_x']) if row.get('coord_x') else 0.0
            lat = float(row['coord_y']) if row.get('coord_y') else 0.0
            name = row.get('station_name', '')
            nh = json.loads(row['next_hop_stations']) if row.get('next_hop_stations') else []
            if sid not in nh:
                nh.append(sid)
            info[sid] = {'lat': lat, 'lng': lng, 'station_name': name, 'next_stop_ids': nh}
    return info


def load_station_coordinates(csv_path=None):
    """从station_info.csv加载 stop_id -> (lat, lng) 映射"""
    info = load_station_info(csv_path)
    return {sid: (v['lat'], v['lng']) for sid, v in info.items()}


def load_next_hop_table(csv_path=None):
    """从station_info.csv加载 stop_id -> [next_stop_ids] 映射"""
    info = load_station_info(csv_path)
    return {sid: v['next_stop_ids'] for sid, v in info.items()}


def load_line_info(csv_path=None):
    """从CSV加载 (citycode, line_name) -> station_list 映射"""
    if csv_path is None:
        csv_path = _data_path('line_info.csv')
    line_info = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cc = row['citycode']
            ln = row['line_name']
            slist = json.loads(row['station_list']) if row['station_list'] else []
            parsed = []
            for s in slist:
                parsed.append({
                    'station_name': s.get('station_name', ''),
                    'stop_id': str(s.get('stop_id', '')),
                    'x': float(s.get('x', 0)),
                    'y': float(s.get('y', 0)),
                    'station_id': s.get('station_id', ''),
                })
            key = (cc, ln)
            if key not in line_info:
                line_info[key] = parsed
            else:
                existing = {s['stop_id'] for s in line_info[key]}
                for ps in parsed:
                    if ps['stop_id'] not in existing:
                        line_info[key].append(ps)
                        existing.add(ps['stop_id'])
    return line_info


def load_station_names(csv_path=None):
    """从station_info.csv加载 stop_id -> station_name 映射"""
    info = load_station_info(csv_path)
    return {sid: v['station_name'] for sid, v in info.items() if v['station_name']}


# ============================================================
# 基础工具函数
# ============================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """计算两个坐标之间的haversine距离（km）"""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371
    return c * r


def parse_distance(distance_str):
    if distance_str is None or distance_str == '':
        return 0.0
    try:
        return float(distance_str)
    except ValueError:
        distance_str = str(distance_str)
        if '米' in distance_str:
            m = re.search(r'(\d+\.?\d*)\s*米', distance_str)
            if m:
                return float(m.group(1)) / 1000.0
        if '公里' in distance_str or 'km' in distance_str.lower():
            m = re.search(r'(\d+\.?\d*)\s*(公里|km)', distance_str, re.IGNORECASE)
            if m:
                return float(m.group(1))
        m = re.search(r'(\d+\.?\d*)', distance_str)
        if m:
            return float(m.group(1))
        return 0.0


def parse_time(time_str):
    if time_str is None or time_str == '':
        return 0.0
    try:
        return float(time_str)
    except ValueError:
        time_str = str(time_str)
        if '小时' in time_str:
            m = re.search(r'(\d+\.?\d*)\s*小时', time_str)
            if m:
                return float(m.group(1)) * 60.0
        if '分钟' in time_str:
            m = re.search(r'(\d+\.?\d*)\s*分钟', time_str)
            if m:
                return float(m.group(1))
        m = re.search(r'(\d+\.?\d*)', time_str)
        if m:
            return float(m.group(1))
        return 0.0


def parse_time_to_seconds(time_str):
    return parse_time(time_str) * 60.0


def parse_fare(fare_str):
    if fare_str is None or fare_str == '':
        return 0.0
    try:
        return float(fare_str)
    except ValueError:
        fare_str = str(fare_str)
        m = re.search(r'(\d+\.?\d*)', fare_str)
        if m:
            return float(m.group(1))
        return 0.0


def count_transit_lines(line_sequence):
    if line_sequence is None or not isinstance(line_sequence, list):
        return 0
    count = 0
    for line in line_sequence:
        if line and isinstance(line, str) and line.strip() and line.strip() != '【换乘】':
            count += 1
    return count


def check_cycling_segments(start_transfer_mode, end_transfer_mode):
    cycling_count = 0
    if start_transfer_mode and '骑行' in str(start_transfer_mode):
        cycling_count += 1
    if end_transfer_mode and '骑行' in str(end_transfer_mode):
        cycling_count += 1
    return cycling_count


def calculate_expert_score(time_seconds, num_lines, fare, cycling_segments=0):
    total_lines = num_lines + cycling_segments
    return time_seconds / 300.0 + total_lines + fare


def calculate_line_overlap(pred_lines, true_lines):
    if not pred_lines or not true_lines:
        return 0.0
    pred_set = set(pred_lines)
    true_set = set(true_lines)
    intersection = pred_set & true_set
    union = pred_set | true_set
    if not union:
        return 0.0
    return len(intersection) / len(union)


def calculate_station_overlap(pred_stations, true_stations):
    if not pred_stations or not true_stations:
        return 0.0
    pred_filtered = [s for s in pred_stations if s and str(s).strip() and str(s).strip() != '【换乘】']
    true_filtered = [s for s in true_stations if s and str(s).strip() and str(s).strip() != '【换乘】']
    if not pred_filtered or not true_filtered:
        return 0.0
    pred_set = set(pred_filtered)
    true_set = set(true_filtered)
    intersection = pred_set & true_set
    union = pred_set | true_set
    if not union:
        return 0.0
    return len(intersection) / len(union)


def check_station_connectivity(stations, next_hop):
    if not stations or len(stations) < 2:
        return {'reachable': True, 'reason': '站点数量少于2，默认连通'}
    for i in range(len(stations) - 1):
        current = stations[i]
        nxt = stations[i + 1]
        if current not in next_hop:
            return {'reachable': False, 'reason': f'站点 {current} 不存在下一跳信息'}
        if nxt not in next_hop[current]:
            return {'reachable': False, 'reason': f'站点 {current} 到 {nxt} 不连通'}
    return {'reachable': True, 'reason': '所有站点都连通'}


# ============================================================
# 单样本评估（标准版，用于 benchmark1/b2/b3）
# ============================================================

def evaluate_sample(sample, input_field, next_hop, station_coordinates, start_coords, end_coords):
    """评估单个样本"""
    label_data = json.loads(sample['sft_label'])
    label_distance = parse_distance(label_data.get('total_distance'))
    label_time = parse_time(label_data.get('total_time'))
    label_fare = parse_fare(label_data.get('total_fare'))
    label_lines = label_data.get('line_sequence', [])
    label_stations = [s for s in label_data.get('station_sequence', []) if s and str(s).strip() and str(s).strip() != '【换乘】']
    label_cycling = check_cycling_segments(label_data.get('start_transfer_mode'), label_data.get('end_transfer_mode'))

    if input_field == 'sft_label':
        data = label_data
        field_name = "Label"
    else:
        data = json.loads(sample['generate_results'])
        field_name = "Result"

    distance = parse_distance(data.get('total_distance'))
    time_val = parse_time(data.get('total_time'))
    fare = parse_fare(data.get('total_fare'))
    lines = data.get('line_sequence', [])
    stations = [s for s in data.get('station_sequence', []) if s and str(s).strip() and str(s).strip() != '【换乘】']
    cycling = check_cycling_segments(data.get('start_transfer_mode'), data.get('end_transfer_mode'))

    reachable_result = check_station_connectivity(stations, next_hop)
    reachable = reachable_result['reachable']
    reachable_reason = reachable_result['reason']

    label_time_seconds = label_time * 60.0
    label_num_lines = count_transit_lines(label_lines)
    label_score = calculate_expert_score(label_time_seconds, label_num_lines, label_fare, label_cycling)

    time_seconds = time_val * 60.0
    num_lines = count_transit_lines(lines)
    score = calculate_expert_score(time_seconds, num_lines, fare, cycling)

    if label_score > 0:
        score_deviation = (score - label_score) / label_score * 100
        score_diff = score - label_score
    else:
        score_deviation = 0.0
        score_diff = score - label_score

    line_iou = calculate_line_overlap(lines, label_lines)
    station_iou = calculate_station_overlap(stations, label_stations)

    if station_iou == 0:
        dist_mape = None
        time_mape = None
        fare_mape = None
        dist_accurate = None
        time_accurate = None
        fare_accurate = None
        overall_accurate = None
    else:
        dist_mape = abs(distance - label_distance) / label_distance * 100 if label_distance > 0 else 0
        time_mape = abs(time_val - label_time) / label_time * 100 if label_time > 0 else 0
        fare_mape = abs(fare - label_fare) / label_fare * 100 if label_fare > 0 else 0
        dist_accurate = (dist_mape <= 10.0) or (abs(distance - label_distance) <= 0.5)
        time_accurate = (time_mape <= 10.0) or (abs(time_val - label_time) <= 5.0)
        fare_accurate = (fare_mape <= 10.0) or (abs(fare - label_fare) <= 1.0)
        overall_accurate = dist_accurate and time_accurate and fare_accurate

    label_start_td = parse_distance(label_data.get('start_transfer_distance'))
    label_end_td = parse_distance(label_data.get('end_transfer_distance'))
    start_td = parse_distance(data.get('start_transfer_distance'))
    end_td = parse_distance(data.get('end_transfer_distance'))
    start_transfer_accurate = abs(start_td - label_start_td) <= 0.5 if label_start_td > 0 else True
    end_transfer_accurate = abs(end_td - label_end_td) <= 0.5 if label_end_td > 0 else True
    transfer_accurate = start_transfer_accurate and end_transfer_accurate

    pred_start_mode = data.get('start_transfer_mode', '') or '步行'
    pred_end_mode = data.get('end_transfer_mode', '') or '步行'
    label_start_mode = label_data.get('start_transfer_mode', '') or '步行'
    label_end_mode = label_data.get('end_transfer_mode', '') or '步行'
    transfer_mode_match = (pred_start_mode == label_start_mode) and (pred_end_mode == label_end_mode)

    station_grounding = True
    station_grounding_reason = ""
    distance_plausibility = True
    distance_plausibility_reason = ""

    if stations and len(stations) > 0:
        first_station = stations[0]
        if first_station in station_coordinates:
            first_coords = station_coordinates[first_station]
            geo_dist_start = haversine_distance(start_coords[1], start_coords[0], first_coords[0], first_coords[1])
            start_mode = data.get('start_transfer_mode', '')
            if '步行' in start_mode or start_mode == '':
                threshold = 3.0
            elif '骑行' in start_mode:
                threshold = 5.0
            elif '打车' in start_mode or '网约车' in start_mode or '滴滴' in start_mode:
                threshold = 10.0
            else:
                threshold = 3.0
            if geo_dist_start > threshold:
                station_grounding = False
                station_grounding_reason = f"起点到第一个站点直线距离过远: {geo_dist_start:.2f}km (阈值: {threshold}km)"
            if start_td > 0:
                if start_td < geo_dist_start - 0.5:
                    distance_plausibility = False
                    distance_plausibility_reason = f"起点接驳距离短于直线距离: {start_td:.2f}km < {geo_dist_start:.2f}km - 0.5km"
                elif start_td > 3 * geo_dist_start + 0.5:
                    distance_plausibility = False
                    distance_plausibility_reason = f"起点接驳距离过长: {start_td:.2f}km > 3*{geo_dist_start:.2f}km + 0.5km"
        else:
            station_grounding = False
            station_grounding_reason = f"第一个站点 {first_station} 不存在坐标信息"

        last_station = stations[-1]
        if last_station in station_coordinates:
            last_coords = station_coordinates[last_station]
            geo_dist_end = haversine_distance(last_coords[0], last_coords[1], end_coords[1], end_coords[0])
            end_mode = data.get('end_transfer_mode', '')
            if '步行' in end_mode or end_mode == '':
                threshold = 3.0
            elif '骑行' in end_mode:
                threshold = 5.0
            elif '打车' in end_mode or '网约车' in end_mode or '滴滴' in end_mode:
                threshold = 10.0
            else:
                threshold = 3.0
            if geo_dist_end > threshold:
                station_grounding = False
                msg = f"终点接驳直线距离过远: {geo_dist_end:.2f}km (阈值: {threshold}km)"
                station_grounding_reason = f"{station_grounding_reason}; {msg}" if station_grounding_reason else msg
            if end_td > 0:
                if end_td < geo_dist_end - 0.5:
                    distance_plausibility = False
                    msg = f"终点接驳距离短于直线距离: {end_td:.2f}km < {geo_dist_end:.2f}km - 0.5km"
                    distance_plausibility_reason = f"{distance_plausibility_reason}; {msg}" if distance_plausibility_reason else msg
                elif end_td > 3 * geo_dist_end + 0.5:
                    distance_plausibility = False
                    msg = f"终点接驳距离过长: {end_td:.2f}km > 3*{geo_dist_end:.2f}km + 0.5km"
                    distance_plausibility_reason = f"{distance_plausibility_reason}; {msg}" if distance_plausibility_reason else msg
        else:
            station_grounding = False
            msg = f"最后一个站点 {last_station} 不存在坐标信息"
            station_grounding_reason = f"{station_grounding_reason}; {msg}" if station_grounding_reason else msg

    if station_grounding and not station_grounding_reason:
        station_grounding_reason = "Station Grounding 检查通过"
    if distance_plausibility and not distance_plausibility_reason:
        distance_plausibility_reason = "Distance Plausibility 检查通过"

    return {
        'field_name': field_name,
        'reachable': reachable,
        'reachable_reason': reachable_reason,
        'station_grounding': station_grounding,
        'station_grounding_reason': station_grounding_reason,
        'distance_plausibility': distance_plausibility,
        'distance_plausibility_reason': distance_plausibility_reason,
        'line_iou': line_iou,
        'station_iou': station_iou,
        'distance': distance,
        'time': time_val,
        'fare': fare,
        'dist_mape': dist_mape,
        'time_mape': time_mape,
        'fare_mape': fare_mape,
        'dist_accurate': dist_accurate,
        'time_accurate': time_accurate,
        'fare_accurate': fare_accurate,
        'overall_accurate': overall_accurate,
        'start_transfer_distance': start_td,
        'end_transfer_distance': end_td,
        'start_transfer_accurate': start_transfer_accurate,
        'end_transfer_accurate': end_transfer_accurate,
        'transfer_accurate': transfer_accurate,
        'start_transfer_mode': pred_start_mode,
        'end_transfer_mode': pred_end_mode,
        'label_start_transfer_mode': label_start_mode,
        'label_end_transfer_mode': label_end_mode,
        'transfer_mode_match': transfer_mode_match,
        'score': score,
        'label_score': label_score,
        'score_deviation': score_deviation,
        'score_diff': score_diff,
    }


# ============================================================
# Preference Compliance（benchmark2）
# ============================================================

REQ_TYPE_NAME = {
    2: "换乘少",
    5: "不坐地铁",
    7: "地铁优先",
    8: "时间短",
}


def count_transfers(line_sequence):
    if not line_sequence:
        return 0
    return max(0, len(line_sequence) - 1)


def has_subway(line_sequence):
    if not line_sequence:
        return False
    for line in line_sequence:
        if line and ('地铁' in line or '号线' in line):
            return True
    return False


def check_preference_compliance(req_type, pred_data, label_data, alpha=1.1):
    pred_lines = pred_data.get('line_sequence', [])
    label_lines = label_data.get('line_sequence', [])
    if req_type == 2:
        pt = count_transfers(pred_lines)
        lt = count_transfers(label_lines)
        if pt <= lt:
            return True, f"换乘{pt}次 <= label {lt}次"
        else:
            return False, f"换乘{pt}次 > label {lt}次"
    elif req_type == 5:
        if not has_subway(pred_lines):
            return True, "路线不含地铁"
        else:
            subway_lines = [l for l in pred_lines if l and ('地铁' in l or '号线' in l)]
            return False, f"路线包含地铁: {subway_lines}"
    elif req_type == 7:
        if has_subway(pred_lines):
            return True, "路线包含地铁"
        else:
            return False, f"路线不含地铁: {pred_lines}"
    elif req_type == 8:
        pred_time = parse_time(pred_data.get('total_time'))
        label_time = parse_time(label_data.get('total_time'))
        if label_time <= 0:
            return True, "label时间无效，跳过检查"
        threshold = label_time * alpha
        if pred_time <= threshold:
            return True, f"时间{pred_time:.1f}min <= {threshold:.1f}min (label {label_time:.1f}min x {alpha})"
        else:
            return False, f"时间{pred_time:.1f}min > {threshold:.1f}min (label {label_time:.1f}min x {alpha})"
    else:
        return True, f"未知req_type={req_type}，跳过检查"


# ============================================================
# Route Diversity（benchmark3）
# ============================================================

ROUTE_KEYS = ["first", "second", "third"]


def get_full_line_set(route_data):
    lines = set()
    line_sequence = route_data.get('line_sequence', [])
    if line_sequence:
        for line in line_sequence:
            if line and str(line).strip():
                lines.add(str(line).strip())
    start_mode = route_data.get('start_transfer_mode', '')
    end_mode = route_data.get('end_transfer_mode', '')
    if start_mode and str(start_mode).strip():
        lines.add(f"接驳:{str(start_mode).strip()}")
    if end_mode and str(end_mode).strip():
        lines.add(f"接驳:{str(end_mode).strip()}")
    return lines


def calculate_route_diversity(route_datas):
    line_sets = []
    for rd in route_datas:
        ls = get_full_line_set(rd)
        if ls:
            line_sets.append(ls)
    n = len(line_sets)
    if n < 2:
        return 0.0, n
    pairs = list(combinations(range(n), 2))
    dissimilarity_sum = 0.0
    for i, j in pairs:
        intersection = line_sets[i] & line_sets[j]
        union = line_sets[i] | line_sets[j]
        iou = len(intersection) / len(union) if union else 0.0
        dissimilarity_sum += (1.0 - iou)
    rd = dissimilarity_sum / len(pairs)
    return rd, n


def evaluate_single_route_from_multi(route_data, label_route_data, next_hop, station_coordinates, start_coords, end_coords):
    pseudo_sample = {
        'sft_label': json.dumps(label_route_data, ensure_ascii=False),
        'generate_results': json.dumps(route_data, ensure_ascii=False)
    }
    return evaluate_sample(pseudo_sample, 'generate_results', next_hop, station_coordinates, start_coords, end_coords)


# ============================================================
# 通用大模型评估（benchmark4）
# ============================================================

CITY_NAME_TO_CODE = {
    '北京': '010', '上海': '021', '深圳': '0755', '成都': '028',
}


def _char_bigram_jaccard(s1, s2):
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    def bigrams(s):
        return {s[i:i + 2] for i in range(len(s) - 1)}
    b1 = bigrams(s1)
    b2 = bigrams(s2)
    if not b1 or not b2:
        set1, set2 = set(s1), set(s2)
        intersection = set1 & set2
        union = set1 | set2
        return len(intersection) / len(union) if union else 0.0
    intersection = b1 & b2
    union = b1 | b2
    return len(intersection) / len(union) if union else 0.0


def _strip_line_suffix(key_name):
    result = key_name
    while True:
        new_result = re.sub(r'\([^()]*\)', '', result)
        if new_result == result:
            break
        result = new_result
    return result.strip()


def find_best_line_match(target_line, line_info, citycode=None):
    if not target_line:
        return None
    target_line = target_line.strip()
    if citycode:
        city_keys = {k: v for k, v in line_info.items() if k[0] == citycode}
    else:
        city_keys = line_info
    if not city_keys:
        return None
    # 1. 精确匹配
    for key in city_keys:
        key_name = key[1]
        if target_line == key_name:
            return key
        stripped = _strip_line_suffix(key_name)
        if target_line == stripped:
            return key
    # 2. 包含匹配（key_name 包含 target_line），选最接近（字符串最短）的
    matches = []
    for key in city_keys:
        key_name = key[1]
        stripped = _strip_line_suffix(key_name)
        if target_line in key_name or target_line in stripped:
            # 优先用 stripped 长度比较，更贴近核心名称
            matches.append((key, len(stripped)))
    if matches:
        matches.sort(key=lambda x: x[1])
        return matches[0][0]
    return None


def find_best_station_match(target_name, station_list):
    if not target_name or not station_list:
        return None, 0
    target_name = target_name.strip()
    for s in station_list:
        if s['station_name'] == target_name:
            return s, 1.0
    best_match = None
    best_score = 0.0
    for s in station_list:
        score = _char_bigram_jaccard(target_name, s['station_name'])
        if score > best_score:
            best_score = score
            best_match = s
    if best_match is not None and best_score >= 0.4:
        return best_match, best_score
    return None, 0


def _resolve_stop_id(stop_id, lookup_dict, default=None):
    if stop_id in lookup_dict:
        return stop_id, lookup_dict[stop_id]
    bus_id = f'bus-{stop_id}' if not str(stop_id).startswith('bus-') else stop_id
    if bus_id != stop_id and bus_id in lookup_dict:
        return bus_id, lookup_dict[bus_id]
    return None, default


def check_general_llm_reachability(line_sequence, station_names, line_info, next_hop, citycode=None):
    if not line_sequence:
        return {'reachable': False, 'reason': '线路序列为空', 'matched_stops': [], 'match_details': []}
    if not station_names:
        return {'reachable': False, 'reason': '站名列表为空', 'matched_stops': [], 'match_details': []}
    n_lines = len(line_sequence)
    expected_names = n_lines * 2
    if len(station_names) != expected_names:
        return {
            'reachable': False,
            'reason': f'站名数量不匹配: 预期 {expected_names}（{n_lines}条线路x2），实际 {len(station_names)}',
            'matched_stops': [], 'match_details': []
        }
    matched_stops = []
    match_details = []
    for i, line_name in enumerate(line_sequence):
        boarding_name = station_names[2 * i]
        alighting_name = station_names[2 * i + 1]
        matched_key = find_best_line_match(line_name, line_info, citycode=citycode)
        if matched_key is None:
            return {
                'reachable': False,
                'reason': f'线路 "{line_name}" 在线路信息表中无匹配 (city={citycode})',
                'matched_stops': matched_stops, 'match_details': match_details
            }
        matched_line = matched_key[1]
        station_list = line_info[matched_key]
        boarding_station, boarding_ratio = find_best_station_match(boarding_name, station_list)
        if boarding_station is None:
            return {
                'reachable': False,
                'reason': f'线路 "{line_name}"({matched_line}) 中未找到上车站 "{boarding_name}"',
                'matched_stops': matched_stops, 'match_details': match_details
            }
        alighting_station, alighting_ratio = find_best_station_match(alighting_name, station_list)
        if alighting_station is None:
            return {
                'reachable': False,
                'reason': f'线路 "{line_name}"({matched_line}) 中未找到下车站 "{alighting_name}"',
                'matched_stops': matched_stops, 'match_details': match_details
            }
        boarding_stop_id = boarding_station['stop_id']
        alighting_stop_id = alighting_station['stop_id']
        if boarding_stop_id == alighting_stop_id:
            return {
                'reachable': False,
                'reason': f'线路 "{line_name}"({matched_line}) 上下车站相同: "{boarding_name}"',
                'matched_stops': matched_stops, 'match_details': match_details
            }
        matched_stops.append((boarding_stop_id, alighting_stop_id))
        match_details.append({
            'line_name': line_name, 'matched_line': matched_line,
            'boarding_name': boarding_name, 'boarding_matched': boarding_station['station_name'],
            'boarding_stop_id': boarding_stop_id, 'boarding_ratio': boarding_ratio,
            'alighting_name': alighting_name, 'alighting_matched': alighting_station['station_name'],
            'alighting_stop_id': alighting_stop_id, 'alighting_ratio': alighting_ratio,
        })
    for i in range(len(matched_stops) - 1):
        prev_alighting = matched_stops[i][1]
        next_boarding = matched_stops[i + 1][0]
        resolved_id, hop_value = _resolve_stop_id(prev_alighting, next_hop)
        if hop_value is None:
            return {
                'reachable': False,
                'reason': f'换乘连通性: 下车站 {prev_alighting}({match_details[i]["alighting_matched"]}) 不在下一跳表中',
                'matched_stops': matched_stops, 'match_details': match_details
            }
        bus_next_boarding = f'bus-{next_boarding}' if not str(next_boarding).startswith('bus-') else next_boarding
        if next_boarding not in hop_value and bus_next_boarding not in hop_value:
            return {
                'reachable': False,
                'reason': f'换乘连通性: {prev_alighting}({match_details[i]["alighting_matched"]}) -> {next_boarding}({match_details[i+1]["boarding_matched"]}) 不连通',
                'matched_stops': matched_stops, 'match_details': match_details
            }
    return {
        'reachable': True, 'reason': '所有线路站名匹配成功且换乘连通',
        'matched_stops': matched_stops, 'match_details': match_details
    }


def evaluate_general_llm_sample(data, label_data, line_info, next_hop, station_coordinates,
                                 start_coords, end_coords, citycode=None, station_names_map=None):
    lines = data.get('line_sequence', []) or []
    station_names = data.get('station_name', []) or []
    distance = parse_distance(data.get('total_distance'))
    time_val = parse_time(data.get('total_time'))
    fare = parse_fare(data.get('total_fare'))
    cycling = check_cycling_segments(data.get('start_transfer_mode'), data.get('end_transfer_mode'))

    label_lines = label_data.get('line_sequence', []) or []
    label_distance = parse_distance(label_data.get('total_distance'))
    label_time = parse_time(label_data.get('total_time'))
    label_fare = parse_fare(label_data.get('total_fare'))
    label_cycling = check_cycling_segments(label_data.get('start_transfer_mode'), label_data.get('end_transfer_mode'))

    pred_start_mode = data.get('start_transfer_mode', '') or '步行'
    pred_end_mode = data.get('end_transfer_mode', '') or '步行'
    label_start_mode = label_data.get('start_transfer_mode', '') or '步行'
    label_end_mode = label_data.get('end_transfer_mode', '') or '步行'
    transfer_mode_match = (pred_start_mode == label_start_mode) and (pred_end_mode == label_end_mode)

    reach_result = check_general_llm_reachability(lines, station_names, line_info, next_hop, citycode=citycode)
    reachable = reach_result['reachable']
    reachable_reason = reach_result['reason']
    matched_stops = reach_result['matched_stops']
    match_details = reach_result['match_details']

    station_grounding = True
    station_grounding_reason = ""
    if matched_stops:
        first_stop_id = matched_stops[0][0]
        _, first_coords_raw = _resolve_stop_id(first_stop_id, station_coordinates)
        if first_coords_raw is not None:
            first_coords = first_coords_raw
            geo_dist_start = haversine_distance(start_coords[1], start_coords[0], first_coords[0], first_coords[1])
            start_mode = data.get('start_transfer_mode', '')
            if '步行' in start_mode or start_mode == '':
                threshold = 3.0
            elif '骑行' in start_mode:
                threshold = 5.0
            elif '打车' in start_mode or '网约车' in start_mode:
                threshold = 10.0
            else:
                threshold = 3.0
            if geo_dist_start > threshold:
                station_grounding = False
                station_grounding_reason = f"起点到上车站直线距离过远: {geo_dist_start:.2f}km (阈值: {threshold}km)"
        last_stop_id = matched_stops[-1][1]
        _, last_coords_raw = _resolve_stop_id(last_stop_id, station_coordinates)
        if last_coords_raw is not None:
            last_coords = last_coords_raw
            geo_dist_end = haversine_distance(last_coords[0], last_coords[1], end_coords[1], end_coords[0])
            end_mode = data.get('end_transfer_mode', '')
            if '步行' in end_mode or end_mode == '':
                threshold = 3.0
            elif '骑行' in end_mode:
                threshold = 5.0
            elif '打车' in end_mode or '网约车' in end_mode:
                threshold = 10.0
            else:
                threshold = 3.0
            if geo_dist_end > threshold:
                station_grounding = False
                sg_msg = f"终点到下车站直线距离过远: {geo_dist_end:.2f}km (阈值: {threshold}km)"
                station_grounding_reason = f"{station_grounding_reason}; {sg_msg}" if station_grounding_reason else sg_msg
    if not station_grounding_reason:
        station_grounding_reason = "Station Grounding 通过"

    # ---- Distance Plausibility ----
    distance_plausibility = True
    distance_plausibility_reason = ""
    if matched_stops:
        first_stop_id = matched_stops[0][0]
        _, first_coords_raw = _resolve_stop_id(first_stop_id, station_coordinates)
        if first_coords_raw is not None:
            first_coords = first_coords_raw
            geo_dist_start = haversine_distance(start_coords[1], start_coords[0], first_coords[0], first_coords[1])
            start_td_val = parse_distance(data.get('start_transfer_distance'))
            if start_td_val > 0:
                if start_td_val < geo_dist_start - 0.5:
                    distance_plausibility = False
                    distance_plausibility_reason = f"起点接驳距离短于直线距离: {start_td_val:.2f}km < {geo_dist_start:.2f}km - 0.5km"
                elif start_td_val > 3 * geo_dist_start + 0.5:
                    distance_plausibility = False
                    distance_plausibility_reason = f"起点接驳距离过长: {start_td_val:.2f}km > 3*{geo_dist_start:.2f}km + 0.5km"
        last_stop_id = matched_stops[-1][1]
        _, last_coords_raw = _resolve_stop_id(last_stop_id, station_coordinates)
        if last_coords_raw is not None:
            last_coords = last_coords_raw
            geo_dist_end = haversine_distance(last_coords[0], last_coords[1], end_coords[1], end_coords[0])
            end_td_val = parse_distance(data.get('end_transfer_distance'))
            if end_td_val > 0:
                if end_td_val < geo_dist_end - 0.5:
                    distance_plausibility = False
                    dp_msg = f"终点接驳距离短于直线距离: {end_td_val:.2f}km < {geo_dist_end:.2f}km - 0.5km"
                    distance_plausibility_reason = f"{distance_plausibility_reason}; {dp_msg}" if distance_plausibility_reason else dp_msg
                elif end_td_val > 3 * geo_dist_end + 0.5:
                    distance_plausibility = False
                    dp_msg = f"终点接驳距离过长: {end_td_val:.2f}km > 3*{geo_dist_end:.2f}km + 0.5km"
                    distance_plausibility_reason = f"{distance_plausibility_reason}; {dp_msg}" if distance_plausibility_reason else dp_msg
    if not distance_plausibility_reason:
        distance_plausibility_reason = "Distance Plausibility 通过"

    label_station_names = label_data.get('station_name', []) or []
    label_lines_raw = label_data.get('line_sequence', []) or []

    # 若 label 给出的是“完整经停序列”（长度 > 2 * 线路数），
    # 按 【换乘】 分段后每段只保留首尾，
    # 使其与 result.station_name（2N）语义对齐，保证 IoU 天花板仍为 1.0。
    if (
        label_station_names
        and label_lines_raw
        and len(label_station_names) > 2 * len(label_lines_raw)
    ):
        segments = []
        cur = []
        for s in label_station_names:
            if not s or not str(s).strip():
                continue
            if str(s).strip() == '【换乘】':
                if cur:
                    segments.append(cur)
                    cur = []
                continue
            cur.append(s)
        if cur:
            segments.append(cur)
        trimmed = []
        for seg in segments:
            if not seg:
                continue
            trimmed.append(seg[0])
            if len(seg) > 1:
                trimmed.append(seg[-1])
        label_station_names = trimmed

    if not label_station_names and station_names_map:
        seq = label_data.get('station_sequence', []) or []
        label_station_names = []
        pos = 0
        for line_name in label_lines_raw:
            stripped = _strip_line_suffix(line_name)
            line_stops_set = set()
            for (cc, kn), stations in line_info.items():
                if cc == citycode and _strip_line_suffix(kn) == stripped:
                    for s in stations:
                        sid = s.get('stop_id', '')
                        line_stops_set.add(sid)
                        if str(sid).startswith('bus-'):
                            line_stops_set.add(sid[4:])
                    break
            if not line_stops_set or pos >= len(seq):
                continue
            start_idx = -1
            for i in range(pos, len(seq)):
                sid = seq[i]
                if sid == '【换乘】':
                    continue
                check_ids = [sid]
                if str(sid).startswith('bus-'):
                    check_ids.append(sid[4:])
                if any(cid in line_stops_set for cid in check_ids):
                    start_idx = i
                    break
            if start_idx == -1:
                continue
            end_idx = start_idx
            for i in range(start_idx + 1, len(seq)):
                sid = seq[i]
                if sid == '【换乘】':
                    continue
                check_ids = [sid]
                if str(sid).startswith('bus-'):
                    check_ids.append(sid[4:])
                if any(cid in line_stops_set for cid in check_ids):
                    end_idx = i
                else:
                    break
            for sid in [seq[start_idx], seq[end_idx]]:
                name = station_names_map.get(sid)
                if not name and str(sid).startswith('bus-'):
                    name = station_names_map.get(sid[4:])
                if name:
                    label_station_names.append(name)
            pos = end_idx

    station_iou = calculate_station_overlap(station_names, label_station_names)
    stripped_lines = [_strip_line_suffix(l) for l in lines]
    stripped_label_lines = [_strip_line_suffix(l) for l in label_lines]
    line_iou = calculate_line_overlap(stripped_lines, stripped_label_lines)

    time_seconds = time_val * 60.0
    num_lines = count_transit_lines(lines)
    score = calculate_expert_score(time_seconds, num_lines, fare, cycling)

    label_time_seconds = label_time * 60.0
    label_num_lines = count_transit_lines(label_lines)
    label_score = calculate_expert_score(label_time_seconds, label_num_lines, label_fare, label_cycling)

    if label_score > 0:
        score_deviation = (score - label_score) / label_score * 100
        score_diff = score - label_score
    else:
        score_deviation = 0.0
        score_diff = score - label_score

    dist_mape = abs(distance - label_distance) / label_distance * 100 if label_distance > 0 else 0
    time_mape = abs(time_val - label_time) / label_time * 100 if label_time > 0 else 0
    fare_mape = abs(fare - label_fare) / label_fare * 100 if label_fare > 0 else 0
    dist_accurate = (dist_mape <= 10.0) or (abs(distance - label_distance) <= 0.5)
    time_accurate = (time_mape <= 10.0) or (abs(time_val - label_time) <= 5.0)
    fare_accurate = (fare_mape <= 10.0) or (abs(fare - label_fare) <= 1.0)
    overall_accurate = dist_accurate and time_accurate and fare_accurate

    label_start_td = parse_distance(label_data.get('start_transfer_distance'))
    label_end_td = parse_distance(label_data.get('end_transfer_distance'))
    start_td = parse_distance(data.get('start_transfer_distance'))
    end_td = parse_distance(data.get('end_transfer_distance'))
    start_transfer_accurate = abs(start_td - label_start_td) <= 0.5 if label_start_td > 0 else True
    end_transfer_accurate = abs(end_td - label_end_td) <= 0.5 if label_end_td > 0 else True
    transfer_accurate = start_transfer_accurate and end_transfer_accurate

    return {
        'reachable': reachable,
        'reachable_reason': reachable_reason,
        'match_details': match_details,
        'station_grounding': station_grounding,
        'station_grounding_reason': station_grounding_reason,
        'distance_plausibility': distance_plausibility,
        'distance_plausibility_reason': distance_plausibility_reason,
        'line_iou': line_iou,
        'station_iou': station_iou,
        'lines': stripped_lines,
        'label_lines': stripped_label_lines,
        'stations': station_names,
        'label_stations': label_station_names,
        'distance': distance,
        'time': time_val,
        'fare': fare,
        'dist_mape': dist_mape,
        'time_mape': time_mape,
        'fare_mape': fare_mape,
        'dist_accurate': dist_accurate,
        'time_accurate': time_accurate,
        'fare_accurate': fare_accurate,
        'overall_accurate': overall_accurate,
        'transfer_accurate': transfer_accurate,
        'start_transfer_distance': start_td,
        'end_transfer_distance': end_td,
        'start_transfer_mode': pred_start_mode,
        'end_transfer_mode': pred_end_mode,
        'label_start_transfer_mode': label_start_mode,
        'label_end_transfer_mode': label_end_mode,
        'transfer_mode_match': transfer_mode_match,
        'score': score,
        'label_score': label_score,
        'score_deviation': score_deviation,
        'score_diff': score_diff,
    }
