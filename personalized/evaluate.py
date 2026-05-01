#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个性化路线评估（多轮漏斗 + Preference Compliance）"""

import sys
import os
import argparse
import json
import csv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from common import (
    load_station_coordinates, load_next_hop_table,
    evaluate_sample, REQ_TYPE_NAME, check_preference_compliance
)


def main():
    parser = argparse.ArgumentParser(description='个性化路线评估')
    parser.add_argument('--input', type=str, default=os.path.join(BASE, 'data', 'benchmark2_personalized_example.csv'),
                        help='输入CSV文件路径')
    parser.add_argument('--input_field', type=str, default='generate_results',
                        choices=['sft_label', 'generate_results'])
    parser.add_argument('--sample_count', type=int, default=None)
    args = parser.parse_args()

    input_field = args.input_field
    input_path = args.input
    sample_count = args.sample_count

    station_coordinates = load_station_coordinates()
    next_hop = load_next_hop_table()

    samples = []
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['req_type'] = int(row['req_type']) if row.get('req_type') else 0
            samples.append(row)
    if sample_count:
        samples = samples[:sample_count]

    total_samples = len(samples)
    print("=" * 120)
    print(f"个性化路线评估 - {input_path}（评估字段: {input_field}）")
    print("=" * 120)
    req_counts = {}
    for s in samples:
        rt = s['req_type']
        req_counts[rt] = req_counts.get(rt, 0) + 1
    for rt in sorted(req_counts.keys()):
        print(f"  req_type={rt} ({REQ_TYPE_NAME.get(rt, '未知')}): {req_counts[rt]} 个")
    print(f"\n加载了 {total_samples} 个样本\n")

    all_results = []
    eval_errors = []

    for i, sample in enumerate(samples, 1):
        try:
            prompt_data = json.loads(sample['sft_prompt'])
            start_str = prompt_data.get('start', '')
            end_str = prompt_data.get('end', '')
            start_coords = [float(x) for x in start_str.split(',')] if start_str else [0.0, 0.0]
            end_coords = [float(x) for x in end_str.split(',')] if end_str else [0.0, 0.0]
            result = evaluate_sample(sample, input_field, next_hop, station_coordinates, start_coords, end_coords)
            result['index'] = i
            result['index_id'] = sample['index_id']
            result['req_type'] = sample['req_type']

            label_data = json.loads(sample['sft_label'])
            pred_data = label_data if input_field == 'sft_label' else json.loads(sample['generate_results'])
            pref_pass, pref_reason = check_preference_compliance(sample['req_type'], pred_data, label_data)
            result['pref_compliance'] = pref_pass
            result['pref_reason'] = pref_reason
            label_pref_pass, _ = check_preference_compliance(sample['req_type'], label_data, label_data)
            result['label_pref_compliance'] = label_pref_pass

            all_results.append(result)
        except Exception as e:
            eval_errors.append((i, sample.get('index_id', ''), str(e)))

    # 第1轮
    print("=" * 120)
    print("第1轮：可达性评估")
    print("=" * 120)
    reachable_results = [r for r in all_results if r['reachable']]
    for r in all_results:
        if not r['reachable']:
            print(f"  样本 {r['index']}: {r['index_id']} (req={r['req_type']}) - 不可达")
    reachable_count = len(reachable_results)
    print(f"\n可达性通过: {reachable_count}/{total_samples}\n")

    # 第2轮
    print("=" * 120)
    print("第2轮：Station Grounding & Distance Plausibility")
    print("=" * 120)
    sg_pass = sum(1 for r in reachable_results if r['station_grounding'])
    dp_pass = sum(1 for r in reachable_results if r['distance_plausibility'])
    print(f"Station Grounding: {sg_pass}/{reachable_count}")
    print(f"Distance Plausibility: {dp_pass}/{reachable_count}\n")

    # 第3轮
    print("=" * 120)
    print("第3轮：交并比评估")
    print("=" * 120)
    line_iou_sum = station_iou_sum = all_score_sum = all_label_score_sum = 0.0
    all_score_dev_sum = all_score_diff_sum = 0.0
    score_pos = score_neg = score_zero = 0
    iou_exact = []
    for r in reachable_results:
        line_iou_sum += r['line_iou']; station_iou_sum += r['station_iou']
        all_score_sum += r['score']; all_label_score_sum += r['label_score']
        all_score_dev_sum += r['score_deviation']; all_score_diff_sum += r['score_diff']
        if r['score_deviation'] > 0.1: score_pos += 1
        elif r['score_deviation'] < -0.1: score_neg += 1
        else: score_zero += 1
        if r['station_iou'] == 1.0 and r.get('transfer_mode_match', False):
            iou_exact.append(r)
    iou_exact_count = len(iou_exact)
    if reachable_count > 0:
        print(f"线路IoU平均: {line_iou_sum/reachable_count:.4f}")
        print(f"站点IoU平均: {station_iou_sum/reachable_count:.4f}")
        print(f"站点IoU=1: {iou_exact_count}/{reachable_count}\n")
    else:
        print("无可达样本，跳过统计\n")

    # 第4轮
    print("=" * 120)
    print("第4轮：指标准确性")
    print("=" * 120)
    dist_acc = time_acc = fare_acc = overall_acc = transfer_acc = 0
    for r in iou_exact:
        if r['dist_accurate']: dist_acc += 1
        if r['time_accurate']: time_acc += 1
        if r['fare_accurate']: fare_acc += 1
        if r['overall_accurate']: overall_acc += 1
        if r['transfer_accurate']: transfer_acc += 1
    if iou_exact_count > 0:
        print(f"整体准确: {overall_acc}/{iou_exact_count}")
    print()

    # 第5轮
    print("=" * 120)
    print("第5轮：Preference Compliance")
    print("=" * 120)
    total_pref_pass = sum(1 for r in all_results if r['pref_compliance'])
    total_label_pref_pass = sum(1 for r in all_results if r['label_pref_compliance'])
    total_valid = len(all_results)
    print(f"总体合规: {total_pref_pass}/{total_valid}")
    print(f"Label合规: {total_label_pref_pass}/{total_valid}")
    print("\n按偏好分类:")
    for rt in sorted(REQ_TYPE_NAME.keys()):
        rt_results = [r for r in all_results if r['req_type'] == rt]
        if not rt_results: continue
        rt_pass = sum(1 for r in rt_results if r['pref_compliance'])
        rt_label_pass = sum(1 for r in rt_results if r['label_pref_compliance'])
        print(f"  req={rt} ({REQ_TYPE_NAME[rt]}): {rt_pass}/{len(rt_results)}  label: {rt_label_pass}/{len(rt_results)}")
    non_compliant = [r for r in all_results if not r['pref_compliance']]
    if non_compliant:
        print("\n不合规样本:")
        for r in non_compliant:
            print(f"  样本 {r['index']}: {r['index_id']} - {r['pref_reason']}")
    print()

    # 汇总
    print("=" * 120)
    print("最终汇总")
    print("=" * 120)
    print(f"总样本: {total_samples}")
    print(f"可达性: {reachable_count}/{total_samples}")
    print(f"站点IoU=1: {iou_exact_count}/{reachable_count}")
    print(f"Preference Compliance: {total_pref_pass}/{total_valid}")
    if eval_errors:
        print(f"评估失败: {len(eval_errors)} 个")


if __name__ == '__main__':
    main()
