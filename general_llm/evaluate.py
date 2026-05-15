#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用大模型路线规划评估（站名匹配可达性）"""

import sys
import os
import argparse
import json
import csv
from urllib import request as urlrequest
from urllib import error as urlerror

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from common import (
    load_station_coordinates, load_next_hop_table,
    evaluate_general_llm_sample, CITY_NAME_TO_CODE,
    calculate_station_overlap,
)


DEFAULT_API = os.environ.get('TRANSIT_LM_API', 'http://transit-lm.amap.com')


def _normalize_to_transfer_stations(stations, num_lines):
    """把站点序列归一化为“换乘站序列”。

    两条分支：
    1) 带【换乘】分隔：按【换乘】切段，每段取首尾（只有一个站则重复）。
    2) 不带【换乘】：原样返回（交给下游接口判定“数量不匹配”）。
    未提供 num_lines（≤0）时只去【换乘】。
    """
    if not stations:
        return []
    cleaned = [s for s in stations if s is not None and str(s).strip()]
    has_transfer_mark = any(str(s).strip() == '【换乘】' for s in cleaned)
    non_transfer = [s for s in cleaned if str(s).strip() != '【换乘】']
    if num_lines <= 0:
        return non_transfer

    # 1) 带【换乘】：按段取首尾
    if has_transfer_mark:
        segments = []
        cur = []
        for s in cleaned:
            if str(s).strip() == '【换乘】':
                if cur:
                    segments.append(cur); cur = []
                continue
            cur.append(s)
        if cur:
            segments.append(cur)
        out = []
        for seg in segments:
            if not seg:
                continue
            out.append(seg[0])
            if len(seg) > 1:
                out.append(seg[-1])
        return out

    # 2) 不带【换乘】：原样返回（交给接口判定“数量不匹配”）
    return non_transfer


def _http_post_json(url, payload, timeout=120):
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(
        url,
        data=data,
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode('utf-8')
        return json.loads(body)


def fetch_route_eval_batch(api_url, cases, batch_size=50):
    """批量调用 transit-lm /api/eval/route/batch。

    cases: [{city, start:[lng,lat], end:[lng,lat], pred:{...}}, ...]
    返回与 cases 等长的结果列表，每个结果包含 reachability + station_grounding + 每段匹配。
    """
    endpoint = api_url.rstrip('/') + '/api/eval/route/batch'
    results = []
    for i in range(0, len(cases), batch_size):
        chunk = cases[i:i + batch_size]
        try:
            resp = _http_post_json(endpoint, {'cases': chunk})
            results.extend(resp.get('results', []))
        except (urlerror.URLError, TimeoutError, ConnectionError) as e:
            # 接口失败：该批次全部填占位错误
            for _ in chunk:
                results.append({
                    'reachable': False,
                    'reachable_reason': f'调用 route 评估接口失败: {e}',
                    'station_grounding': False,
                    'station_grounding_reason': '接口失败',
                    'match_details': [],
                })
    return results


def build_request_case(sample):
    prompt_data = json.loads(sample['sft_prompt'])
    start_str = prompt_data.get('start', '')
    end_str = prompt_data.get('end', '')
    city_name = prompt_data.get('city', '')
    start_coords = [float(x) for x in start_str.split(',')] if start_str else [0.0, 0.0]
    end_coords = [float(x) for x in end_str.split(',')] if end_str else [0.0, 0.0]

    pred = json.loads(sample['generate_results'])
    # 兼容字段：优先 station_name，回退到 station_sequence（此时其内容也为中文站名）
    station_name_list = pred.get('station_name')
    if not station_name_list:
        station_name_list = pred.get('station_sequence') or []
    line_seq = pred.get('line_sequence') or []
    # 统一归一化为换乘站序列再送可达性接口
    station_name_list = _normalize_to_transfer_stations(station_name_list, len(line_seq))
    return {
        'city': city_name,
        'start': start_coords,  # [lng, lat]
        'end': end_coords,
        'pred': {
            'line_sequence': line_seq,
            'station_name': station_name_list,
            'start_transfer_mode': pred.get('start_transfer_mode', '') or '',
            'end_transfer_mode': pred.get('end_transfer_mode', '') or '',
        },
    }


def main():
    parser = argparse.ArgumentParser(description='通用大模型路线规划评估')
    parser.add_argument('--input', type=str, default=os.path.join(BASE, 'data', 'general_llm_example.csv'),
                        help='输入CSV文件路径')
    parser.add_argument('--input_field', type=str, default='generate_results',
                        choices=['generate_results'])
    parser.add_argument('--sample_count', type=int, default=None)
    parser.add_argument('--api_url', type=str, default=DEFAULT_API,
                        help='transit-lm 评估接口地址（默认读取 TRANSIT_LM_API 环境变量）')
    parser.add_argument('--batch_size', type=int, default=50)
    args = parser.parse_args()

    input_field = args.input_field
    input_path = args.input
    sample_count = args.sample_count

    # 本地仍需要坐标/下一跳做回显，但不再需要 line_info / station_name 映射。
    station_coordinates = load_station_coordinates()
    next_hop = load_next_hop_table()

    samples = []
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            samples.append(row)
    if sample_count:
        samples = samples[:sample_count]

    total_samples = len(samples)
    print("=" * 120)
    print(f"通用大模型评估 - {input_path}（评估字段: {input_field}）")
    print(f"远程评估接口: {args.api_url}")
    print("=" * 120)
    print(f"加载了 {total_samples} 个样本\n")

    # 预先准备每个样本的调用 payload，并记录对应的原始样本 index
    valid_samples = []  # [(i, sample, case_body)]
    no_response = 0
    for i, sample in enumerate(samples, 1):
        if not sample.get(input_field):
            no_response += 1
            continue
        try:
            case_body = build_request_case(sample)
            valid_samples.append((i, sample, case_body))
        except Exception as e:
            # payload 构造失败计入失败
            print(f"  样本 {i} payload 构造失败: {e}")

    # 批量请求 transit-lm
    cases = [c for _, _, c in valid_samples]
    print(f"准备批量调用 route 评估接口，共 {len(cases)} 个 case ...")
    remote_results = fetch_route_eval_batch(args.api_url, cases, batch_size=args.batch_size)
    print("接口调用完成\n")

    all_results = []
    eval_errors = []

    for (i, sample, case_body), remote in zip(valid_samples, remote_results):
        try:
            prompt_data = json.loads(sample['sft_prompt'])
            city_name = prompt_data.get('city', '')
            citycode = CITY_NAME_TO_CODE.get(city_name)
            start_str = prompt_data.get('start', '')
            end_str = prompt_data.get('end', '')
            start_coords = [float(x) for x in start_str.split(',')] if start_str else [0.0, 0.0]
            end_coords = [float(x) for x in end_str.split(',')] if end_str else [0.0, 0.0]

            data = json.loads(sample['generate_results'])
            # 兼容字段：pred 侧若只提供 station_sequence（内容为中文站名），则归一化为 station_name。
            # label 侧 station_sequence 从来就是站点 ID（bus-xxx），不能做同样回退。
            if not data.get('station_name'):
                data['station_name'] = data.get('station_sequence') or []
            label_data = json.loads(sample['sft_label'])

            # 本地仍调用 evaluate_general_llm_sample 计算独立指标，
            # line_info 和 station_names_map 传空 —— 其计算出的 reachable/station_grounding
            # 会被接口结果覆盖。
            result = evaluate_general_llm_sample(
                data, label_data, line_info={}, next_hop=next_hop,
                station_coordinates=station_coordinates,
                start_coords=start_coords, end_coords=end_coords,
                citycode=citycode, station_names_map=None,
            )
            # 接口结果覆盖
            result['reachable'] = bool(remote.get('reachable'))
            result['reachable_reason'] = remote.get('reachable_reason', '')
            result['station_grounding'] = bool(remote.get('station_grounding'))
            result['station_grounding_reason'] = remote.get('station_grounding_reason', '')
            result['match_details'] = remote.get('match_details', [])

            # === 站点 IoU：统一 soft 模式（先归一化为换乘站集合再算 IoU）===
            label_full_seq = label_data.get('station_sequence', []) or []
            pred_full_seq = (
                data.get('station_name')
                or data.get('station_sequence')
                or []
            )
            label_lines_raw = label_data.get('line_sequence', []) or []
            pred_lines_raw = data.get('line_sequence', []) or []

            soft_pred = _normalize_to_transfer_stations(pred_full_seq, len(pred_lines_raw))
            soft_label = _normalize_to_transfer_stations(label_full_seq, len(label_lines_raw))
            station_iou_soft = calculate_station_overlap(soft_pred, soft_label)

            result['station_iou'] = station_iou_soft

            result['index'] = i
            result['index_id'] = sample['index_id']
            all_results.append(result)
        except Exception as e:
            eval_errors.append((i, sample.get('index_id', ''), str(e)))

    valid_count = len(all_results)
    print(f"有效评估: {valid_count}, 无响应: {no_response}, 失败: {len(eval_errors)}\n")
    if valid_count == 0:
        print("无有效样本")
        return

    # 第1轮
    print("=" * 120)
    print("第1轮：可达性评估（站名匹配 + 换乘连通性，由远程接口判定）")
    print("=" * 120)
    reachable_results = [r for r in all_results if r['reachable']]
    for r in all_results:
        if not r['reachable']:
            print(f"  样本 {r['index']}: {r['index_id']} - {r['reachable_reason']}")
    reachable_count = len(reachable_results)
    print(f"\n可达性通过: {reachable_count}/{valid_count}\n")
    if reachable_count == 0:
        print("无可达样本")
        return

    # 第2轮
    print("=" * 120)
    print("第2轮：Station Grounding（由远程接口判定）")
    print("=" * 120)
    sg_pass = 0
    dp_pass = 0
    for r in reachable_results:
        if r['station_grounding']:
            sg_pass += 1
        else:
            print(f"  样本 {r['index']}: {r['index_id']} - {r['station_grounding_reason']}")
        if r['distance_plausibility']:
            dp_pass += 1
        else:
            print(f"  样本 {r['index']}: {r['index_id']} - {r['distance_plausibility_reason']}")
    print(f"\nSG通过: {sg_pass}/{reachable_count}")
    print(f"DP通过: {dp_pass}/{reachable_count}\n")

    # 第3轮
    print("=" * 120)
    print("第3轮：线路交并比 & 站点交并比 & 专家评分")
    print("=" * 120)
    line_iou_sum = station_iou_sum = score_sum = label_score_sum = 0.0
    soft_iou_one = 0
    score_dev_sum = score_diff_sum = 0.0
    score_pos = score_neg = score_zero = 0
    iou_exact = []
    for r in reachable_results:
        line_iou_sum += r['line_iou']; station_iou_sum += r['station_iou']
        if r['station_iou'] == 1.0: soft_iou_one += 1
        score_sum += r['score']; label_score_sum += r['label_score']
        score_dev_sum += r['score_deviation']; score_diff_sum += r['score_diff']
        if r['score_deviation'] > 0.1: score_pos += 1
        elif r['score_deviation'] < -0.1: score_neg += 1
        else: score_zero += 1
        if r['station_iou'] == 1.0 and r.get('transfer_mode_match', False):
            iou_exact.append(r)
    iou_exact_count = len(iou_exact)
    print(f"线路 IoU 平均: {line_iou_sum/reachable_count:.4f}")
    print(f"站点 IoU 平均: {station_iou_sum/reachable_count:.4f}")
    print(f"站点 IoU=1: {soft_iou_one}/{reachable_count}")
    print(f"站点 IoU=1 + transfer_mode_match: {iou_exact_count}/{reachable_count}")
    print(f"专家评分: {score_sum/reachable_count:.2f} (label: {label_score_sum/reachable_count:.2f})")
    print(f"偏差: {score_dev_sum/reachable_count:.2f}%")
    print()

    # 第4轮
    print("=" * 120)
    print("第4轮：指标准确性（站点IoU=1）")
    print("=" * 120)
    dist_acc = time_acc = fare_acc = overall_acc = transfer_acc = 0
    dist_mape_sum = time_mape_sum = fare_mape_sum = 0.0
    dist_n = time_n = fare_n = 0
    for r in iou_exact:
        if r['dist_accurate']: dist_acc += 1
        if r['time_accurate']: time_acc += 1
        if r['fare_accurate']: fare_acc += 1
        if r['overall_accurate']: overall_acc += 1
        if r['transfer_accurate']: transfer_acc += 1
        if r['dist_mape'] is not None: dist_mape_sum += r['dist_mape']; dist_n += 1
        if r['time_mape'] is not None: time_mape_sum += r['time_mape']; time_n += 1
        if r['fare_mape'] is not None: fare_mape_sum += r['fare_mape']; fare_n += 1
    if iou_exact_count > 0:
        print(f"整体准确: {overall_acc}/{iou_exact_count}")
        if dist_n: print(f"距离MAPE: {dist_mape_sum/dist_n:.2f}%")
        if time_n: print(f"时间MAPE: {time_mape_sum/time_n:.2f}%")
        if fare_n: print(f"费用MAPE: {fare_mape_sum/fare_n:.2f}%")
    print()

    # 汇总
    print("=" * 120)
    print("最终汇总")
    print("=" * 120)
    print(f"总样本: {total_samples}  无响应: {no_response}  失败: {len(eval_errors)}")
    print(f"有效: {valid_count}")
    print(f"可达性: {reachable_count}/{valid_count}")
    print(f"SG: {sg_pass}/{reachable_count}")
    print(f"站点 IoU=1: {soft_iou_one}/{reachable_count}")
    print(f"站点 IoU=1 + transfer_mode: {iou_exact_count}/{reachable_count}")
    if eval_errors:
        print(f"失败: {len(eval_errors)} 个")


if __name__ == '__main__':
    main()
