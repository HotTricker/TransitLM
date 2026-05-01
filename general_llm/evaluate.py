#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用大模型路线规划评估（站名匹配可达性）"""

import sys
import os
import argparse
import json
import csv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from common import (
    load_station_coordinates, load_next_hop_table,
    load_line_info, load_station_names,
    evaluate_general_llm_sample, CITY_NAME_TO_CODE
)


def main():
    parser = argparse.ArgumentParser(description='通用大模型路线规划评估')
    parser.add_argument('--input', type=str, default=os.path.join(BASE, 'data', 'general_llm_example.csv'),
                        help='输入CSV文件路径')
    parser.add_argument('--input_field', type=str, default='generate_results',
                        choices=['generate_results'])
    parser.add_argument('--sample_count', type=int, default=None)
    args = parser.parse_args()

    input_field = args.input_field
    input_path = args.input
    sample_count = args.sample_count

    line_info = load_line_info()
    station_coordinates = load_station_coordinates()
    next_hop = load_next_hop_table()
    station_names_map = load_station_names()

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
    print("=" * 120)
    print(f"加载了 {total_samples} 个样本\n")

    all_results = []
    eval_errors = []
    no_response = 0

    for i, sample in enumerate(samples, 1):
        try:
            if not sample.get('generate_results'):
                no_response += 1
                continue
            prompt_data = json.loads(sample['sft_prompt'])
            start_str = prompt_data.get('start', '')
            end_str = prompt_data.get('end', '')
            city_name = prompt_data.get('city', '')
            citycode = CITY_NAME_TO_CODE.get(city_name)
            start_coords = [float(x) for x in start_str.split(',')] if start_str else [0.0, 0.0]
            end_coords = [float(x) for x in end_str.split(',')] if end_str else [0.0, 0.0]

            data = json.loads(sample['generate_results'])
            label_data = json.loads(sample['sft_label'])

            result = evaluate_general_llm_sample(
                data, label_data, line_info, next_hop, station_coordinates,
                start_coords, end_coords, citycode=citycode, station_names_map=station_names_map)
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
    print("第1轮：可达性评估（站名匹配 + 换乘连通性）")
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
    print("第2轮：Station Grounding & Distance Plausibility")
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
    score_dev_sum = score_diff_sum = 0.0
    score_pos = score_neg = score_zero = 0
    iou_exact = []
    for r in reachable_results:
        line_iou_sum += r['line_iou']; station_iou_sum += r['station_iou']
        score_sum += r['score']; label_score_sum += r['label_score']
        score_dev_sum += r['score_deviation']; score_diff_sum += r['score_diff']
        if r['score_deviation'] > 0.1: score_pos += 1
        elif r['score_deviation'] < -0.1: score_neg += 1
        else: score_zero += 1
        if r['station_iou'] == 1.0 and r.get('transfer_mode_match', False):
            iou_exact.append(r)
    iou_exact_count = len(iou_exact)
    print(f"线路IoU平均: {line_iou_sum/reachable_count:.4f}")
    print(f"站点IoU平均: {station_iou_sum/reachable_count:.4f}")
    print(f"站点IoU=1: {iou_exact_count}/{reachable_count}")
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
    print(f"DP: {dp_pass}/{reachable_count}")
    print(f"站点IoU=1: {iou_exact_count}/{reachable_count}")
    if eval_errors:
        print(f"失败: {len(eval_errors)} 个")


if __name__ == '__main__':
    main()
