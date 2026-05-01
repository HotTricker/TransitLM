#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多样性路线评估（多轮漏斗 + Route Diversity + Best Match）"""

import sys
import os
import argparse
import json
import csv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from common import (
    load_station_coordinates, load_next_hop_table,
    evaluate_single_route_from_multi, check_station_connectivity,
    calculate_route_diversity, parse_time, parse_fare,
    calculate_expert_score, count_transit_lines, check_cycling_segments,
    ROUTE_KEYS
)


def main():
    parser = argparse.ArgumentParser(description='多样性路线评估')
    parser.add_argument('--input', type=str, default=os.path.join(BASE, 'data', 'benchmark3_diversity_example.csv'),
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
            samples.append(row)
    if sample_count:
        samples = samples[:sample_count]

    total_samples = len(samples)
    print("=" * 120)
    print(f"多样性路线评估 - {input_path}（评估字段: {input_field}）")
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

            label_multi = json.loads(sample['sft_label'])
            eval_multi = label_multi if input_field == 'sft_label' else json.loads(sample['generate_results'])

            label_routes = {k: label_multi[k] for k in ROUTE_KEYS if k in label_multi and label_multi[k]}
            eval_routes = {k: eval_multi[k] for k in ROUTE_KEYS if k in eval_multi and eval_multi[k]}

            if not eval_routes:
                eval_errors.append((i, sample['index_id'], "无有效路线"))
                continue

            first_key = "first"
            first_result = None
            if first_key in eval_routes and first_key in label_routes:
                first_result = evaluate_single_route_from_multi(
                    eval_routes[first_key], label_routes[first_key],
                    next_hop, station_coordinates, start_coords, end_coords)

            route_reachability = {}
            route_eval_results = {}
            for key in ROUTE_KEYS:
                if key in eval_routes:
                    stations = [s for s in eval_routes[key].get('station_sequence', [])
                                if s and str(s).strip() and str(s).strip() != '【换乘】']
                    reach_result = check_station_connectivity(stations, next_hop)
                    route_reachability[key] = reach_result['reachable']
                    if key in label_routes:
                        try:
                            route_eval_results[key] = evaluate_single_route_from_multi(
                                eval_routes[key], label_routes[key],
                                next_hop, station_coordinates, start_coords, end_coords)
                        except Exception:
                            route_eval_results[key] = None
                else:
                    route_reachability[key] = None

            best_match_result = first_result
            best_match_key = "first"
            if (first_result is not None and first_result['station_iou'] != 1.0
                    and first_key in label_routes):
                for alt_key in ["second", "third"]:
                    if alt_key not in eval_routes:
                        continue
                    if not route_reachability.get(alt_key, False):
                        continue
                    try:
                        alt_result = evaluate_single_route_from_multi(
                            eval_routes[alt_key], label_routes[first_key],
                            next_hop, station_coordinates, start_coords, end_coords)
                        if alt_result['station_iou'] == 1.0:
                            best_match_result = alt_result
                            best_match_key = alt_key
                            break
                    except Exception:
                        continue

            eval_route_list = [eval_routes[k] for k in ROUTE_KEYS if k in eval_routes]
            label_route_list = [label_routes[k] for k in ROUTE_KEYS if k in label_routes]
            rd_eval, n_eval_routes = calculate_route_diversity(eval_route_list)
            rd_label, n_label_routes = calculate_route_diversity(label_route_list)

            route_scores = {}
            for key in ROUTE_KEYS:
                if key in eval_routes:
                    rd = eval_routes[key]
                    t = parse_time(rd.get('total_time'))
                    f = parse_fare(rd.get('total_fare'))
                    ls = rd.get('line_sequence', [])
                    cycling = check_cycling_segments(rd.get('start_transfer_mode'), rd.get('end_transfer_mode'))
                    route_scores[key] = calculate_expert_score(t * 60.0, count_transit_lines(ls), f, cycling)

            label_first_score = 0.0
            if first_key in label_routes:
                ld = label_routes[first_key]
                lt = parse_time(ld.get('total_time'))
                lf = parse_fare(ld.get('total_fare'))
                lls = ld.get('line_sequence', [])
                lcycling = check_cycling_segments(ld.get('start_transfer_mode'), ld.get('end_transfer_mode'))
                label_first_score = calculate_expert_score(lt * 60.0, count_transit_lines(lls), lf, lcycling)

            all_results.append({
                'index': i, 'index_id': sample['index_id'],
                'first_result': first_result,
                'best_match_result': best_match_result,
                'best_match_key': best_match_key,
                'route_reachability': route_reachability,
                'route_eval_results': route_eval_results,
                'route_scores': route_scores,
                'label_first_score': label_first_score,
                'rd_eval': rd_eval, 'rd_label': rd_label,
                'n_eval_routes': n_eval_routes,
                'n_label_routes': n_label_routes,
            })
        except Exception as e:
            eval_errors.append((i, sample.get('index_id', ''), str(e)))

    # Part A: 首条路线质量
    print("=" * 120)
    print("Part A: 首条路线质量评估（漏斗式）")
    print("=" * 120)
    first_valid = [r for r in all_results if r['first_result'] is not None]
    total_first = len(first_valid)
    print(f"有效样本: {total_first}\n")

    # 第1轮
    print("-" * 80)
    print("第1轮：首条路线可达性")
    print("-" * 80)
    reachable_results = []
    for r in first_valid:
        if r['first_result']['reachable']:
            reachable_results.append(r)
        else:
            print(f"  样本 {r['index']}: {r['index_id']} - 不可达")
    reachable_count = len(reachable_results)
    print(f"\n可达性通过: {reachable_count}/{total_first}\n")

    # 第2轮
    print("-" * 80)
    print("第2轮：Station Grounding & Distance Plausibility")
    print("-" * 80)
    sg_pass = dp_pass = 0
    for r in reachable_results:
        fr = r['first_result']
        if fr['station_grounding']: sg_pass += 1
        else: print(f"  样本 {r['index']}: {r['index_id']} - SG失败")
        if fr['distance_plausibility']: dp_pass += 1
        else: print(f"  样本 {r['index']}: {r['index_id']} - DP失败")
    print(f"\nSG: {sg_pass}/{reachable_count}  DP: {dp_pass}/{reachable_count}\n")

    # 第3轮
    print("-" * 80)
    print("第3轮：交并比评估（Best Match）")
    print("-" * 80)
    line_iou_sum = station_iou_sum = score_sum = label_score_sum = 0.0
    score_dev_sum = score_diff_sum = 0.0
    score_pos = score_neg = score_zero = 0
    iou_exact = []
    best_match_from_first = best_match_from_second = best_match_from_third = 0
    for r in reachable_results:
        bm = r['best_match_result']
        bm_key = r['best_match_key']
        line_iou_sum += bm['line_iou']; station_iou_sum += bm['station_iou']
        score_sum += bm['score']; label_score_sum += bm['label_score']
        score_dev_sum += bm['score_deviation']; score_diff_sum += bm['score_diff']
        if bm['score_deviation'] > 0.1: score_pos += 1
        elif bm['score_deviation'] < -0.1: score_neg += 1
        else: score_zero += 1
        if bm['station_iou'] == 1.0 and bm.get('transfer_mode_match', False):
            iou_exact.append(r)
            if bm_key == 'first': best_match_from_first += 1
            elif bm_key == 'second': best_match_from_second += 1
            elif bm_key == 'third': best_match_from_third += 1
    iou_exact_count = len(iou_exact)
    if reachable_count > 0:
        print(f"线路IoU平均(best match): {line_iou_sum/reachable_count:.4f}")
        print(f"站点IoU平均(best match): {station_iou_sum/reachable_count:.4f}")
        print(f"站点IoU=1(best match): {iou_exact_count}/{reachable_count}")
        print(f"  first命中={best_match_from_first}, second命中={best_match_from_second}, third命中={best_match_from_third}")
        print(f"专家评分: {score_sum/reachable_count:.2f} (label: {label_score_sum/reachable_count:.2f})")
        print(f"偏差: {score_dev_sum/reachable_count:.2f}%")
    else:
        print("无可达样本，跳过统计")
    print()

    # 第4轮
    print("-" * 80)
    print("第4轮：指标准确性（Best Match IoU=1）")
    print("-" * 80)
    dist_acc = time_acc = fare_acc = overall_acc = transfer_acc = 0
    dist_mape_sum = time_mape_sum = fare_mape_sum = 0.0
    dist_n = time_n = fare_n = 0
    for r in iou_exact:
        fr = r['best_match_result']
        if fr['dist_accurate']: dist_acc += 1
        if fr['time_accurate']: time_acc += 1
        if fr['fare_accurate']: fare_acc += 1
        if fr['overall_accurate']: overall_acc += 1
        if fr['transfer_accurate']: transfer_acc += 1
        if fr['dist_mape'] is not None: dist_mape_sum += fr['dist_mape']; dist_n += 1
        if fr['time_mape'] is not None: time_mape_sum += fr['time_mape']; time_n += 1
        if fr['fare_mape'] is not None: fare_mape_sum += fr['fare_mape']; fare_n += 1
    if iou_exact_count > 0:
        print(f"整体准确: {overall_acc}/{iou_exact_count}")
        if dist_n: print(f"距离MAPE: {dist_mape_sum/dist_n:.2f}%")
        if time_n: print(f"时间MAPE: {time_mape_sum/time_n:.2f}%")
        if fare_n: print(f"费用MAPE: {fare_mape_sum/fare_n:.2f}%")
    print()

    # Part B: 各条路线可达性
    print("=" * 120)
    print("Part B: 各条路线可达性统计")
    print("=" * 120)
    for key in ROUTE_KEYS:
        has_route = sum(1 for r in all_results if r['route_reachability'].get(key) is not None)
        reachable_k = sum(1 for r in all_results if r['route_reachability'].get(key) is True)
        if has_route > 0:
            print(f"  {key}: {reachable_k}/{has_route}")
    all_reachable_count = 0
    for r in all_results:
        rr = r['route_reachability']
        routes_present = [k for k in ROUTE_KEYS if rr.get(k) is not None]
        if routes_present and all(rr[k] for k in routes_present):
            all_reachable_count += 1
    print(f"\n  全部路线可达: {all_reachable_count}/{len(all_results)}\n")

    # Part C: Route Diversity
    print("=" * 120)
    print("Part C: Route Diversity 评估")
    print("=" * 120)
    rd_eval_sum = rd_label_sum = 0.0
    rd_eval_count = rd_label_count = 0
    route_count_dist = {}
    for r in all_results:
        n = r['n_eval_routes']
        route_count_dist[n] = route_count_dist.get(n, 0) + 1
        if n >= 2:
            rd_eval_sum += r['rd_eval']; rd_eval_count += 1
        if r['n_label_routes'] >= 2:
            rd_label_sum += r['rd_label']; rd_label_count += 1
    for n in sorted(route_count_dist.keys()):
        print(f"  {n}条路线: {route_count_dist[n]} 个样本")
    if rd_eval_count > 0:
        print(f"\n  RD (eval): {rd_eval_sum/rd_eval_count:.4f}")
    if rd_label_count > 0:
        print(f"  RD (label): {rd_label_sum/rd_label_count:.4f}")
    print()

    # Part D: 各条路线专家评分
    print("=" * 120)
    print("Part D: 各条路线专家评分")
    print("=" * 120)
    for key in ROUTE_KEYS:
        scores = [r['route_scores'][key] for r in all_results if key in r['route_scores']]
        if scores:
            print(f"  {key}: 平均评分 {sum(scores)/len(scores):.2f}")
    first_scores = [r['route_scores'].get('first', 0) for r in all_results if 'first' in r['route_scores']]
    label_scores = [r['label_first_score'] for r in all_results if r['label_first_score'] > 0]
    if first_scores and label_scores:
        print(f"\n  首条评分: {sum(first_scores)/len(first_scores):.2f} vs label首条: {sum(label_scores)/len(label_scores):.2f}")
    print()

    # 汇总
    print("=" * 120)
    print("最终汇总")
    print("=" * 120)
    print(f"总样本: {total_samples}  评估失败: {len(eval_errors)}  有效: {len(all_results)}")
    print(f"可达性: {reachable_count}/{total_first}")
    if reachable_count > 0:
        print(f"线路IoU平均(best match): {line_iou_sum/reachable_count:.4f}")
        print(f"站点IoU平均(best match): {station_iou_sum/reachable_count:.4f}")
    print(f"站点IoU=1(best match): {iou_exact_count}/{reachable_count}")
    if iou_exact_count > 0:
        if dist_n: print(f"距离MAPE: {dist_mape_sum/dist_n:.2f}%")
        if time_n: print(f"时间MAPE: {time_mape_sum/time_n:.2f}%")
        if fare_n: print(f"费用MAPE: {fare_mape_sum/fare_n:.2f}%")
    if rd_eval_count > 0:
        print(f"RD (eval): {rd_eval_sum/rd_eval_count:.4f}")
    if eval_errors:
        print(f"评估失败: {len(eval_errors)} 个")


if __name__ == '__main__':
    main()
