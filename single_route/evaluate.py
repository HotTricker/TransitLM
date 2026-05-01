#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单路线评估（多轮漏斗式评估）"""

import sys
import os
import argparse
import json
import csv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from common import (
    load_station_coordinates, load_next_hop_table,
    evaluate_sample
)


def main():
    parser = argparse.ArgumentParser(description='单路线评估（多轮漏斗式评估）')
    parser.add_argument('--input', type=str, default=os.path.join(BASE, 'data', 'benchmark1_single_route_example.csv'),
                        help='输入CSV文件路径')
    parser.add_argument('--input_field', type=str, default='generate_results',
                        choices=['sft_label', 'generate_results'],
                        help='评估字段')
    parser.add_argument('--sample_count', type=int, default=None,
                        help='评估样本数量限制')
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
            samples.append(row)
    if sample_count:
        samples = samples[:sample_count]

    total_samples = len(samples)
    print("=" * 120)
    print(f"单路线评估 - {input_path}（评估字段: {input_field}）")
    print("=" * 120)
    print(f"加载了 {total_samples} 个样本\n")

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
            all_results.append(result)
        except Exception as e:
            eval_errors.append((i, sample.get('index_id', ''), str(e)))

    # 第1轮
    print("=" * 120)
    print("第1轮：可达性评估")
    print(f"输入样本数: {total_samples}")
    print("=" * 120)
    reachable_results = [r for r in all_results if r['reachable']]
    unreachable_results = [r for r in all_results if not r['reachable']]
    for r in unreachable_results:
        print(f"  样本 {r['index']}: {r['index_id']} - 不可达 ({r['reachable_reason']})")
    reachable_count = len(reachable_results)
    print(f"\n第1轮结果: 可达性通过 {reachable_count}/{total_samples} ({reachable_count/total_samples*100:.2f}%)")
    print(f"  评估失败: {len(eval_errors)} 个")
    print(f"  -> 进入第2轮: {reachable_count} 个样本\n")

    # 第2轮
    print("=" * 120)
    print("第2轮：Station Grounding & Distance Plausibility")
    print(f"输入样本数: {reachable_count}")
    print("=" * 120)
    sg_pass = sum(1 for r in reachable_results if r['station_grounding'])
    dp_pass = sum(1 for r in reachable_results if r['distance_plausibility'])
    for r in reachable_results:
        if not r['station_grounding']:
            print(f"  样本 {r['index']}: {r['index_id']} - SG失败 ({r['station_grounding_reason']})")
        if not r['distance_plausibility']:
            print(f"  样本 {r['index']}: {r['index_id']} - DP失败 ({r['distance_plausibility_reason']})")
    print(f"\n第2轮结果（不过滤）:")
    print(f"  Station Grounding: {sg_pass}/{reachable_count}")
    print(f"  Distance Plausibility: {dp_pass}/{reachable_count}")
    print(f"  -> 进入第3轮: {reachable_count} 个样本\n")

    # 第3轮
    print("=" * 120)
    print("第3轮：交并比评估")
    print(f"输入样本数: {reachable_count}")
    print("=" * 120)
    line_iou_sum = station_iou_sum = all_score_sum = all_label_score_sum = 0.0
    all_score_dev_sum = all_score_diff_sum = 0.0
    score_pos = score_neg = score_zero = 0
    iou_exact = []
    for r in reachable_results:
        line_iou_sum += r['line_iou']
        station_iou_sum += r['station_iou']
        all_score_sum += r['score']
        all_label_score_sum += r['label_score']
        all_score_dev_sum += r['score_deviation']
        all_score_diff_sum += r['score_diff']
        if r['score_deviation'] > 0.1: score_pos += 1
        elif r['score_deviation'] < -0.1: score_neg += 1
        else: score_zero += 1
        if r['station_iou'] == 1.0 and r.get('transfer_mode_match', False):
            iou_exact.append(r)
        else:
            reasons = []
            if r['station_iou'] != 1.0:
                reasons.append(f"站点IoU={r['station_iou']:.4f}")
            if not r.get('transfer_mode_match', False):
                reasons.append(f"接驳方式不一致")
            print(f"  样本 {r['index']}: {r['index_id']} - {'; '.join(reasons)}")
    iou_exact_count = len(iou_exact)
    print(f"\n第3轮结果:")
    if reachable_count > 0:
        print(f"  线路交并比平均: {line_iou_sum/reachable_count:.4f}")
        print(f"  站点交并比平均: {station_iou_sum/reachable_count:.4f}")
        print(f"  站点交并比=1: {iou_exact_count}/{reachable_count}")
        print(f"  专家评分平均: {all_score_sum/reachable_count:.2f} (label: {all_label_score_sum/reachable_count:.2f})")
        print(f"  专家评分偏差: {all_score_dev_sum/reachable_count:.2f}%")
        print(f"  偏差分布: 下降={score_pos} 提升={score_neg} 相当={score_zero}")
    else:
        print(f"  无可达样本，跳过交并比统计")
    print(f"  -> 进入第4轮: {iou_exact_count} 个样本\n")

    # 第4轮
    print("=" * 120)
    print("第4轮：指标准确性评估")
    print(f"输入样本数: {iou_exact_count}")
    print("=" * 120)
    dist_acc = time_acc = fare_acc = overall_acc = transfer_acc = 0
    dist_mape_sum = time_mape_sum = fare_mape_sum = 0.0
    dist_n = time_n = fare_n = 0
    score_sum = label_score_sum = score_dev_sum = score_diff_sum = 0.0
    for r in iou_exact:
        if r['dist_accurate']: dist_acc += 1
        else: print(f"  样本 {r['index']}: {r['index_id']} - 距离不准确")
        if r['time_accurate']: time_acc += 1
        else: print(f"  样本 {r['index']}: {r['index_id']} - 时间不准确")
        if r['fare_accurate']: fare_acc += 1
        else: print(f"  样本 {r['index']}: {r['index_id']} - 费用不准确")
        if r['overall_accurate']: overall_acc += 1
        if r['transfer_accurate']: transfer_acc += 1
        else: print(f"  样本 {r['index']}: {r['index_id']} - 接驳不准确")
        score_sum += r['score']; label_score_sum += r['label_score']
        score_dev_sum += r['score_deviation']; score_diff_sum += r['score_diff']
        if r['dist_mape'] is not None: dist_mape_sum += r['dist_mape']; dist_n += 1
        if r['time_mape'] is not None: time_mape_sum += r['time_mape']; time_n += 1
        if r['fare_mape'] is not None: fare_mape_sum += r['fare_mape']; fare_n += 1
    if iou_exact_count > 0:
        print(f"\n第4轮结果:")
        print(f"  距离准确: {dist_acc}/{iou_exact_count}")
        print(f"  时间准确: {time_acc}/{iou_exact_count}")
        print(f"  费用准确: {fare_acc}/{iou_exact_count}")
        print(f"  接驳准确: {transfer_acc}/{iou_exact_count}")
        print(f"  整体准确: {overall_acc}/{iou_exact_count}")
        print(f"  专家评分: {score_sum/iou_exact_count:.2f} (label: {label_score_sum/iou_exact_count:.2f})")
        if dist_n: print(f"  距离MAPE: {dist_mape_sum/dist_n:.2f}%")
        if time_n: print(f"  时间MAPE: {time_mape_sum/time_n:.2f}%")
        if fare_n: print(f"  费用MAPE: {fare_mape_sum/fare_n:.2f}%")
    else:
        print("\n第4轮结果: 无有效样本")
    print()

    # 汇总
    print("=" * 120)
    print("最终汇总")
    print("=" * 120)
    print(f"  总样本数: {total_samples}")
    print(f"  第1轮 可达性通过: {reachable_count}/{total_samples}")
    print(f"  第2轮 SG通过: {sg_pass}/{reachable_count}")
    print(f"  第2轮 DP通过: {dp_pass}/{reachable_count}")
    if reachable_count > 0:
        print(f"  第3轮 线路IoU平均: {line_iou_sum/reachable_count:.4f}")
        print(f"  第3轮 站点IoU平均: {station_iou_sum/reachable_count:.4f}")
        print(f"  第3轮 站点IoU=1: {iou_exact_count}/{reachable_count}")
    else:
        print(f"  第3轮 无可达样本，跳过统计")
    if iou_exact_count > 0:
        print(f"  第4轮 整体准确: {overall_acc}/{iou_exact_count}")
    if eval_errors:
        print(f"\n  评估失败: {len(eval_errors)} 个")
        for idx, index_id, err in eval_errors:
            print(f"    样本 {idx}: {index_id} - {err}")


if __name__ == '__main__':
    main()
