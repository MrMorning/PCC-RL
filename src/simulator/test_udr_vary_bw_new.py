import argparse
import csv
import glob
import itertools
import os
import subprocess
import time

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from plot_scripts.plot_packet_log import PacketLog
from common.utils import natural_sort, read_json_file, set_seed
from simulator.aurora import Aurora
from simulator.trace import generate_trace, generate_traces, Trace
from simulator.evaluate_cubic import test_on_traces

matplotlib.use('Agg')


def parse_args():
    """Parse arguments from the command line."""
    parser = argparse.ArgumentParser("Test UDR models in simulator.")
    # parser.add_argument('--exp-name', type=str, default="",
    #                     help="Experiment name.")
    parser.add_argument("--model-path", type=str, default=[], nargs="+",
                        help="Path to one or more Aurora Tensorflow checkpoints"
                        " or models to serve.")
    parser.add_argument('--save-dir', type=str, required=True,
                        help="direcotry to save the model.")
    parser.add_argument('--dimension', type=str,  # nargs=1,
                        choices=["bandwidth", "delay", "loss", "queue",
                                 'delay_noise',
                                 "duration", 'T_s', 'd_delay', 'd_bw'])
    parser.add_argument('--config-file', type=str, required=True,
                        help="config file")
    parser.add_argument('--trace-dir', type=str, default=None, help='directory'
                        ' contains all trace files')
    parser.add_argument('--train-config-dir', type=str, default=None,
                        help="path to one or more training configs.")
    # parser.add_argument('--duration', type=int, required=True,
    #                     help="trace duration")
    parser.add_argument('--delta-scale', type=float, required=True,
                        help="delta scale")
    parser.add_argument('--plot-only', action='store_true',
                        help='plot only if specified')
    parser.add_argument('--n-models', type=int, default=3,
                        help='Number of models to average on.')
    parser.add_argument('--seed', type=int, default=42, help='seed')
    return parser.parse_args()


def multiple_runs(aurora_models, trace_files, aurora_save_dirs, plot_only):
    test_traces = [Trace.load_from_file(trace_file)
                   for trace_file in trace_files]

    rollout_time = 0
    step_cnt = 0
    for aurora in aurora_models:
        aurora_log_dirs = [os.path.join(aurora_save_dir, os.path.splitext(os.path.basename(
            aurora.pretrained_model_path))[0])for aurora_save_dir in aurora_save_dirs]
        for aurora_log_dir in aurora_log_dirs:
            os.makedirs(aurora_log_dir, exist_ok=True)
        t_start = time.time()
        # if not plot_only:
        results, pkt_logs = aurora.test_on_traces(test_traces, aurora_log_dirs)
        step_cnt += len(results[0])
        # for trace_file, pkt_log, aurora_log_dir in zip(trace_files, pkt_logs, aurora_log_dirs):
        #     with open(os.path.join(aurora_log_dir, "aurora_packet_log.csv"), 'w', 1) as f:
        #         pkt_logger = csv.writer(f, lineterminator='\n')
        #         pkt_logger.writerows(pkt_log)
        #     cmd = "python ../plot_scripts/plot_packet_log.py --log-file {} " \
        #         "--save-dir {} --trace-file {}".format(
        #             os.path.join(aurora_log_dir, "aurora_packet_log.csv"),
        #             aurora_log_dir, trace_file)
        #     subprocess.check_output(cmd, shell=True).strip()
        #     cmd = "python ../plot_scripts/plot_time_series.py --log-file {} " \
        #         "--save-dir {} --trace-file {}".format(
        #             os.path.join(aurora_log_dir, "aurora_simulation_log.csv"),
        #             aurora_log_dir, trace_file)
        #     print(cmd)
        #     subprocess.check_output(cmd, shell=True).strip()
        #     break
        rollout_time += time.time() - t_start

        rewards = np.array([np.mean([row[1] for row in result]) for result in results])
        # rewards = np.array([PacketLog.from_log(pkt_log).get_reward()
        #                     for pkt_log in pkt_logs])
        mean_reward = np.mean(rewards)
        reward_err = float(np.std(rewards)) / np.sqrt(len(rewards))
        return mean_reward, reward_err, rollout_time, step_cnt


def get_last_n_models(model_path, n_models):
    parent_dir = os.path.dirname(model_path)
    ckpt_index_files = natural_sort(
        glob.glob(os.path.join(parent_dir, "model_step_*.ckpt.index")))
    target_model_ctime = os.path.getctime(model_path + ".index")
    ckpt_paths = []
    for ckpt_index_file in ckpt_index_files[::-1]:
        if os.path.getctime(ckpt_index_file) > target_model_ctime:
            continue
        ckpt_paths.append(os.path.splitext(ckpt_index_file)[0])
        if len(ckpt_paths) >= n_models:
            return ckpt_paths
    return ckpt_paths


def main():
    main_start = time.time()
    args = parse_args()
    set_seed(args.seed)
    metric = args.dimension
    model_paths = args.model_path
    save_root = args.save_dir
    config_file = args.config_file
    train_config_dir = args.train_config_dir
    # print(metric, model_paths, save_root, config_file)

    plt.figure(figsize=(12, 8))
    # config = read_json_file(config_file)
    # # print(config)
    # bw_list = config['bandwidth']
    # delay_list = config['delay']
    # loss_list = config['loss']
    # queue_list = config["queue"]
    # T_s_bandwidth_list = config['T_s_bandwidth']
    # T_s_delay_list = config['T_s_delay']
    # duration_list = config["duration"]
    # ack_delay_prob_list = config["ack_delay_prob"] if "ack_delay_prob" in config else [
    #     [0, 0]]
    metric_vals = natural_sort(os.listdir(args.trace_dir))
    if metric in ['loss', 'bandwidth', 'd_delay', 'd_bandwidth', 'delay_noise']:
        metric_vals = list(sorted([float(val) for val in metric_vals]))
    print(metric_vals)

    # run cubic
    cubic_rewards = []
    cubic_reward_errs = []
    cubic_time = 0
    for val in metric_vals:
        trace_files = sorted(glob.glob(os.path.join(
            args.trace_dir, str(val), "trace*.json")))
        trace_files = [trace_files[0]]
        save_dirs = [os.path.join(save_root, f"rand_{metric}", str(val),
                                  os.path.splitext(os.path.basename(trace_file))[0])
                     for trace_file in trace_files]
        cubic_save_dirs = [os.path.join(save_dir, "cubic")
                           for save_dir in save_dirs]
        for cubic_save_dir in cubic_save_dirs:
            os.makedirs(cubic_save_dir, exist_ok=True)
        # if not args.plot_only:
        t_start = time.time()
        traces = [Trace.load_from_file(trace_file)
                  for trace_file in trace_files]
        mi_rewards, pkt_logs = test_on_traces(
            traces, cubic_save_dirs, args.seed)
        cubic_time += time.time() - t_start
        # for trace_file, cubic_save_dir in zip(trace_files, cubic_save_dirs):
        #     cmd = "python ../plot_scripts/plot_packet_log.py --log-file {} " \
        #         "--save-dir {} --trace-file {}".format(
        #             os.path.join(cubic_save_dir, "cubic_packet_log.csv"),
        #             cubic_save_dir, trace_file)
        #     subprocess.check_output(cmd, shell=True).strip()
        #     cmd = "python ../plot_scripts/plot_time_series.py --log-file {} " \
        #         "--save-dir {} --trace-file {}".format(
        #             os.path.join(cubic_save_dir, "cubic_simulation_log.csv"),
        #             cubic_save_dir, trace_file)
        #     print(cmd)
        #     subprocess.check_output(cmd, shell=True).strip()
        #     break
        # df = pd.read_csv(os.path.join(
        #     cubic_save_dir, "cubic_test_log.csv"))
        # cubic_rewards.append(df['reward'].mean())
        # multi_trace_cubic_rewards = [PacketLog.from_log_file(
        #     os.path.join(cubic_save_dir, "cubic_packet_log.csv")).get_reward()
        #     for cubic_save_dir in cubic_save_dirs]

        multi_trace_cubic_rewards = np.array([np.mean(mi_reward) for mi_reward in mi_rewards])
        # multi_trace_cubic_rewards = [PacketLog.from_log(pkt_log).get_reward()
        #                              for pkt_log in pkt_logs]
        cubic_rewards.append(np.mean(np.array(multi_trace_cubic_rewards)))
        cubic_reward_errs.append(float(np.std(np.array(multi_trace_cubic_rewards))) /
                                 np.sqrt(len(multi_trace_cubic_rewards)))

    aurora_rollout_time_tot = 0
    aurora_step_cnt_tot = 0
    model_load_time = 0
    model_load_cnt = 0
    for model_idx, (model_path, ls, marker, color) in enumerate(
            zip(model_paths, ["-", "--", "-.", "-", "-", "--", "-.", ":"],
                ["x", "s", "v", '*', '+', '^', '>', '1'],
                ["C3", "C3", "C3", "C1", "C1", "C1", "C1", "C1"])):
        model_name = os.path.basename(os.path.dirname(os.path.dirname(model_path))) + os.path.basename(os.path.dirname(model_path))
        aurora_rewards = []
        aurora_reward_errs = []
        # detect latest n models here
        last_n_model_paths = get_last_n_models(model_path, args.n_models)
        # construct n Aurora objects and load aurora models here
        last_n_auroras = []
        for tmp_model_path in last_n_model_paths:
            model_load_start = time.time()
            aurora = Aurora(seed=args.seed, log_dir="", timesteps_per_actorbatch=10,
                            pretrained_model_path=tmp_model_path,
                            delta_scale=args.delta_scale)
            last_n_auroras.append(aurora)
            model_load_time += (time.time() - model_load_start)
            model_load_cnt += 1

        for val in metric_vals:
            trace_files = sorted(glob.glob(os.path.join(
                args.trace_dir, str(val), "trace*.json")))
            save_dirs = [os.path.join(save_root, f"rand_{metric}", str(val),
                                      os.path.splitext(os.path.basename(trace_file))[0])
                         for trace_file in trace_files]
            aurora_save_dirs = [os.path.join(save_dir, model_name)
                                for save_dir in save_dirs]
            for aurora_save_dir in aurora_save_dirs:
                os.makedirs(aurora_save_dir, exist_ok=True)
            # run aurora
            aurora_reward, aurora_reward_err, aurora_rollout_time, aurora_step_cnt = multiple_runs(
                last_n_auroras, trace_files, aurora_save_dirs, args.plot_only)

            aurora_rollout_time_tot += aurora_rollout_time
            aurora_step_cnt_tot += aurora_step_cnt
            aurora_rewards.append(aurora_reward)
            aurora_reward_errs.append(aurora_reward_err)
        if model_idx == 0:
            if metric == 'bandwidth':
                metric2plot = [np.log10(float(val)) for val in metric_vals]
            else:
                metric2plot = [float(val) for val in metric_vals]
            plt.errorbar(metric2plot, cubic_rewards, yerr=cubic_reward_errs,
                         marker='o', linestyle='-', c="C0", label="TCP Cubic")
        if "cont" in model_name:
            model_name = model_name[:-5]
        if train_config_dir is not None and os.path.exists(os.path.join(
                train_config_dir, model_name+'.json')):
            train_config = read_json_file(os.path.join(
                train_config_dir, model_name+'.json'))
            env = 'bw=[{}, {}]Mbps, d=[{}, {}]ms, loss=[{}, {}], ' \
                  'q=[{}, {}]pkt, dur=[{}, {}]s, T_s=[{}, {}], d_bw=[{}, {}], ' \
                  'd_delay=[{}, {}]'.format(
                      train_config[0]['bandwidth'][0],
                      train_config[0]['bandwidth'][1],
                      train_config[0]['delay'][0], train_config[0]['delay'][1],
                      train_config[0]['loss'][0], train_config[0]['loss'][1],
                      train_config[0]['queue'][0], train_config[0]['queue'][1],
                      train_config[0]['duration'][0], train_config[0]['duration'][1],
                      train_config[0]['T_s'][0], train_config[0]['T_s'][1],
                      train_config[0]['d_bw'][0], train_config[0]['d_bw'][1],
                      train_config[0]['d_delay'][0], train_config[0]['d_delay'][1])
        else:
            env = ""
            # raise RuntimeError
        assert ls in {'', '-', '--', '-.', ':', None}
        if metric == 'bandwidth':
            metric2plot = [np.log10(float(val)) for val in metric_vals]
        else:
            metric2plot = [float(val) for val in metric_vals]
        if "small" in model_name:
            udr_small_rewards = aurora_rewards
            udr_small_rewards_errs = aurora_reward_errs
            lgd = "DRL+UDR_1"
        elif 'mid' in model_name:
            udr_mid_rewards = aurora_rewards
            udr_mid_rewards_errs = aurora_reward_errs
            lgd = "DRL+UDR_2"
        else:
            udr_large_rewards = aurora_rewards
            udr_large_rewards_errs = aurora_reward_errs
            lgd = "DRL+UDR_3"
        plt.errorbar(metric2plot, aurora_rewards, yerr=aurora_reward_errs, #marker=marker,
                     linestyle=ls, c=color, label=lgd)
    plt.legend(bbox_to_anchor=(0.0, 1.02, 1.0, 0.2), loc="lower left",
               mode="expand", ncol=1, )
    plt.legend()
    if metric == "bandwidth":
        xlabel = "Bandwidth (log(Mbps))"
    elif metric == 'delay':
        xlabel = 'Delay (ms)'
    elif metric == 'loss':
        xlabel = 'loss'
    elif metric == 'queue':
        xlabel = 'queue (packets)'
    elif metric == 'duration':
        xlabel = 's'
    elif metric == 'T_s':
        xlabel = 'Bandwidth Change Period (s)'
    elif metric == 'd_delay':
        xlabel = ''
    elif metric == 'd_bw':
        xlabel = 'Bandwidth ~ [1, 1+x] Mbps'
    elif metric == 'delay_noise':
        xlabel = 'ms'
    else:
        xlabel = ""

    plt.xlabel("{}".format(xlabel))
    plt.ylabel('Reward')
    # plt.title("Tot t: {:.2f}s, Aurora tot rollout t: {:.2f}s, Aurora tot step cnt: {}, model load t: {:.2f}s, load cnt: {}, cubic t: {:.2f}s".format(
        # time.time() - main_start, aurora_rollout_time_tot, aurora_step_cnt_tot, model_load_time, model_load_cnt, cubic_time))
    # plt.ylabel('log(throughput) - log(delay)')
    plt.tight_layout()
    plt.savefig(os.path.join(
        args.save_dir, "rand_{}_sim.png".format(metric)))

    with open(os.path.join(args.save_dir, 'rand_{}_sim.csv'), 'w', 1) as f:
        writer = csv.writer(f)
        writer.writerow(['vals', 'cubic_rewards', 'cubic_rewards_errs',
                         'udr_small_rewards', 'udr_small_rewards_errs', 'udr_mid_rewards', 'udr_mid_rewards_errs',
                         'udr_large_rewards', 'udr_large_rewards_errs'])
        writer.writerows(zip(metric2plot, cubic_rewards, cubic_reward_errs, udr_small_rewards, udr_small_rewards_errs, udr_mid_rewards, udr_mid_rewards_errs, udr_large_rewards, udr_large_rewards_errs))
    plt.close()
    # plt.show()


if __name__ == "__main__":
    main()
