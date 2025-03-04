import csv
import logging
import multiprocessing as mp
import os
import shutil
import time
import types
from typing import List
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

from mpi4py.MPI import COMM_WORLD
from mpi4py.futures import MPIPoolExecutor

import gym
import numpy as np
import tensorflow as tf
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)

from stable_baselines import PPO1
from stable_baselines.bench import Monitor
from stable_baselines.common.callbacks import BaseCallback
from stable_baselines.common.policies import FeedForwardPolicy
from stable_baselines.results_plotter import load_results, ts2xy

from simulator import my_heuristic, network
from simulator.constants import BYTES_PER_PACKET
from simulator.trace import generate_trace, Trace, generate_traces
from common.utils import set_tf_loglevel, pcc_aurora_reward
from plot_scripts.plot_packet_log import PacketLog
from udt_plugins.testing.loaded_agent import LoadedModel


if type(tf.contrib) != types.ModuleType:  # if it is LazyLoader
    tf.contrib._warning = None

set_tf_loglevel(logging.FATAL)


class MyMlpPolicy(FeedForwardPolicy):

    def __init__(self, sess, ob_space, ac_space, n_env, n_steps, n_batch,
                 reuse=False, **_kwargs):
        super(MyMlpPolicy, self).__init__(sess, ob_space, ac_space, n_env,
                                          n_steps, n_batch, reuse, net_arch=[
                                              {"pi": [32, 16], "vf": [32, 16]}],
                                          feature_extraction="mlp", **_kwargs)


class SaveOnBestTrainingRewardCallback(BaseCallback):
    """
    Callback for saving a model (the check is done every ``check_freq`` steps)
    based on the training reward (in practice, we recommend using
    ``EvalCallback``).

    :param check_freq: (int)
    :param log_dir: (str) Path to the folder where the model will be saved.
      It must contains the file created by the ``Monitor`` wrapper.
    :param verbose: (int)
    """

    def __init__(self, aurora, check_freq: int, log_dir: str, val_traces: List = [],
                 verbose=0, patience=10, steps_trained=0, config_file=None,
                 tot_trace_cnt=100, update_training_traces_freq=5):
        super(SaveOnBestTrainingRewardCallback, self).__init__(verbose)
        self.aurora = aurora
        self.check_freq = check_freq
        self.log_dir = log_dir
        # self.save_path = os.path.join(log_dir, 'saved_models')
        self.save_path = log_dir
        self.best_mean_reward = -np.inf
        self.val_traces = val_traces
        self.config_file = config_file
        self.tot_trace_cnt=tot_trace_cnt
        self.update_training_traces_freq = update_training_traces_freq
        if self.aurora.comm.Get_rank() == 0:
            self.val_log_writer = csv.writer(
                open(os.path.join(log_dir, 'validation_log.csv'), 'w', 1),
                delimiter='\t', lineterminator='\n')
            self.val_log_writer.writerow(
                ['n_calls', 'num_timesteps', 'mean_validation_reward', 'loss',
                 'throughput', 'latency', 'sending_rate', 'tot_t_used(min)'])
        else:
            self.val_log_writer = None
        self.best_val_reward = -np.inf
        self.patience = patience
        self.val_times = 0

        self.t_start = time.time()
        self.steps_trained = steps_trained

    def _init_callback(self) -> None:
        # Create folder if needed
        if self.save_path is not None:
            os.makedirs(self.save_path, exist_ok=True)

    def _on_step(self) -> bool:
        if self.n_calls % self.check_freq == 0:
            # self.val_times += 1
            # if self.val_times % self.update_training_traces_freq == 0:
            #     training_traces = generate_traces(
            #         self.config_file, self.tot_trace_cnt, duration=30,
            #         constant_bw=False)
            #     self.model.env.traces = training_traces

            # Retrieve training reward
            # x, y = ts2xy(load_results(self.log_dir), 'timesteps')
            # if len(x) > 0:
            #     # Mean training reward over the last 100 episodes
            #     mean_reward = np.mean(y[-100:])
            #     if self.verbose > 0:
            #         print("Num timesteps: {}".format(self.num_timesteps))
            #         print("Best mean reward: {:.2f} - Last mean reward per episode: {:.2f}".format(
            #             self.best_mean_reward, mean_reward))
            #
            #     # New best model, you could save the agent here
            #     if mean_reward > self.best_mean_reward:
            #         self.best_mean_reward = mean_reward
            #         # Example for saving best model
            #         if self.verbose > 0:
            #             print("Saving new best model to {}".format(self.save_path))
            #         # self.model.save(self.save_path)

            if self.aurora.comm.Get_rank() == 0:
                with self.model.graph.as_default():
                    saver = tf.train.Saver()
                    saver.save(
                        self.model.sess, os.path.join(
                            self.save_path, "model_step_{}.ckpt".format(
                                self.n_calls)))
                avg_rewards = []
                avg_losses = []
                avg_tputs = []
                avg_delays = []
                avg_send_rates = []
                for idx, val_trace in enumerate(self.val_traces):
                    # print(np.mean(val_trace.bandwidths))
                    ts_list, val_rewards, loss_list, tput_list, delay_list, \
                        send_rate_list, action_list, obs_list, mi_list, pkt_log = self.aurora.test(
                            val_trace, self.log_dir)
                    # pktlog = PacketLog.from_log(pkt_log)
                    avg_rewards.append(np.mean(np.array(val_rewards)))
                    avg_losses.append(np.mean(np.array(loss_list)))
                    avg_tputs.append(float(np.mean(np.array(tput_list))))
                    avg_delays.append(np.mean(np.array(delay_list)))
                    avg_send_rates.append(
                        float(np.mean(np.array(send_rate_list))))
                    # avg_rewards.append(pktlog.get_reward())
                    # avg_losses.append(pktlog.get_loss_rate())
                    # avg_tputs.append(np.mean(pktlog.get_throughput()[1]))
                    # avg_delays.append(np.mean(pktlog.get_rtt()[1]))
                    # avg_send_rates.append(np.mean(pktlog.get_sending_rate()[1]))
                self.val_log_writer.writerow(
                    map(lambda t: "%.3f" % t,
                        [float(self.n_calls), float(self.num_timesteps),
                         np.mean(np.array(avg_rewards)),
                         np.mean(np.array(avg_losses)),
                         np.mean(np.array(avg_tputs)),
                         np.mean(np.array(avg_delays)),
                         np.mean(np.array(avg_send_rates)),
                         (time.time() - self.t_start) / 60]))
        return True


def save_model_to_serve(model, export_dir):
    if os.path.exists(export_dir):
        shutil.rmtree(export_dir)
    with model.graph.as_default():

        pol = model.policy_pi  # act_model

        obs_ph = pol.obs_ph
        act = pol.deterministic_action
        sampled_act = pol.action

        obs_input = tf.saved_model.utils.build_tensor_info(obs_ph)
        outputs_tensor_info = tf.saved_model.utils.build_tensor_info(act)
        stochastic_act_tensor_info = tf.saved_model.utils.build_tensor_info(
            sampled_act)
        signature = tf.saved_model.signature_def_utils.build_signature_def(
            inputs={"ob": obs_input},
            outputs={"act": outputs_tensor_info,
                     "stochastic_act": stochastic_act_tensor_info},
            method_name=tf.saved_model.signature_constants.PREDICT_METHOD_NAME)

        signature_map = {tf.saved_model.signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY:
                         signature}

        model_builder = tf.saved_model.builder.SavedModelBuilder(export_dir)
        model_builder.add_meta_graph_and_variables(
            model.sess, tags=[tf.saved_model.tag_constants.SERVING],
            signature_def_map=signature_map,
            clear_devices=True)
        model_builder.save(as_text=True)


class Aurora():
    def __init__(self, seed, log_dir, timesteps_per_actorbatch,
                 pretrained_model_path=None, gamma=0.99, tensorboard_log=None,
                 delta_scale=1):
        init_start = time.time()
        self.comm = COMM_WORLD
        self.delta_scale = delta_scale
        self.seed = seed
        self.log_dir = log_dir
        self.pretrained_model_path = pretrained_model_path
        self.steps_trained = 0
        dummy_trace = generate_trace(
            (10, 10), (2, 2), (50, 50), (0, 0), (100, 100))
        env = gym.make('PccNs-v0', traces=[dummy_trace],
                       train_flag=True, delta_scale=self.delta_scale)
        # Load pretrained model
        # print('create_dummy_env,{}'.format(time.time() - init_start))
        if pretrained_model_path is not None:
            if pretrained_model_path.endswith('.ckpt'):
                model_create_start = time.time()
                self.model = PPO1(MyMlpPolicy, env, verbose=1, seed=seed,
                                  optim_stepsize=0.001, schedule='constant',
                                  timesteps_per_actorbatch=timesteps_per_actorbatch,
                                  optim_batchsize=int(
                                      timesteps_per_actorbatch/4),
                                  optim_epochs=4,
                                  gamma=gamma, tensorboard_log=tensorboard_log, n_cpu_tf_sess=1)
                # print('create_ppo1,{}'.format(time.time() - model_create_start))
                tf_restore_start = time.time()
                with self.model.graph.as_default():
                    saver = tf.train.Saver()
                    saver.restore(self.model.sess, pretrained_model_path)
                try:
                    self.steps_trained = int(os.path.splitext(
                        pretrained_model_path)[0].split('_')[-1])
                except:
                    self.steps_trained = 0
                # print('tf_restore,{}'.format(time.time()-tf_restore_start))
            else:
                # model is a tensorflow model to serve
                self.model = LoadedModel(pretrained_model_path)
        else:
            self.model = PPO1(MyMlpPolicy, env, verbose=1, seed=seed,
                              optim_stepsize=0.001, schedule='constant',
                              timesteps_per_actorbatch=timesteps_per_actorbatch,
                              optim_batchsize=int(timesteps_per_actorbatch/12),
                              optim_epochs=12,
                              gamma=gamma, tensorboard_log=tensorboard_log, n_cpu_tf_sess=1)
        self.timesteps_per_actorbatch = timesteps_per_actorbatch

    def train(self, config_file,
            # training_traces, validation_traces,
            total_timesteps, tot_trace_cnt,
              tb_log_name=""):
        assert isinstance(self.model, PPO1)

        training_traces = generate_traces(config_file, tot_trace_cnt,
                                          duration=30, constant_bw=False)
        # generate validation traces
        validation_traces = generate_traces(
            config_file, 100, duration=30, constant_bw=False)
        env = gym.make('PccNs-v0', traces=training_traces,
                       train_flag=True, delta_scale=self.delta_scale, config_file=config_file)
        env.seed(self.seed)
        # env = Monitor(env, self.log_dir)
        self.model.set_env(env)

        # Create the callback: check every n steps and save best model
        callback = SaveOnBestTrainingRewardCallback(
            self, check_freq=self.timesteps_per_actorbatch, log_dir=self.log_dir,
            steps_trained=self.steps_trained, val_traces=validation_traces,
            config_file=config_file, tot_trace_cnt=tot_trace_cnt,
            update_training_traces_freq=10)
        self.model.learn(total_timesteps=total_timesteps,
                         tb_log_name=tb_log_name, callback=callback)

    def test_on_traces(self, traces: List[Trace], save_dirs: List[str]):
        results = []
        pkt_logs = []
        for trace, save_dir in zip(traces, save_dirs):
            ts_list, reward_list, loss_list, tput_list, delay_list, \
                send_rate_list, action_list, obs_list, mi_list, pkt_log = self.test(
                    trace, save_dir)
            result = list(zip(ts_list, reward_list, send_rate_list, tput_list,
                              delay_list, loss_list, action_list, obs_list, mi_list))
            pkt_logs.append(pkt_log)
            results.append(result)
        return results, pkt_logs

        # results = []
        # pkt_logs = []
        # n_proc=mp.cpu_count()//2
        # arguments = [(self.pretrained_model_path, trace, save_dir, self.seed) for trace, save_dir in zip(traces, save_dirs)]
        # with mp.Pool(processes=n_proc) as pool:
        #     for ts_list, reward_list, loss_list, tput_list, delay_list, \
        #             send_rate_list, action_list, obs_list, mi_list, pkt_log  in pool.starmap(test_model, arguments):
        #         result = list(zip(ts_list, reward_list, send_rate_list, tput_list,
        #                           delay_list, loss_list, action_list, obs_list, mi_list))
        #         pkt_logs.append(pkt_log)
        #         results.append(result)
        # return results, pkt_logs

        # results = []
        # pkt_logs = []
        # with MPIPoolExecutor(max_workers=4) as executor:
        #     iterable = ((trace, save_dir) for trace, save_dir in zip(traces, save_dirs))
        #     for ts_list, reward_list, loss_list, tput_list, delay_list, \
        #         send_rate_list, action_list, obs_list, mi_list, pkt_log  in executor.starmap(self.test, iterable):
        #         result = list(zip(ts_list, reward_list, send_rate_list, tput_list,
        #                           delay_list, loss_list, action_list, obs_list, mi_list))
        #         pkt_logs.append(pkt_log)
        #         results.append(result)
        # return results, pkt_logs

        # results = []
        # pkt_logs = []
        # size = self.comm.Get_size()
        # count = int(len(traces) / size)
        # remainder = int(len(traces) % size)
        # rank = self.comm.Get_rank()
        # start = rank * count + min(rank, remainder)
        # stop = (rank + 1) * count + min(rank + 1, remainder)
        # for i in range(start, stop):
        #     ts_list, reward_list, loss_list, tput_list, delay_list, \
        #         send_rate_list, action_list, obs_list, mi_list, pkt_log = self.test(
        #             traces[i], save_dirs[i])
        #     result = list(zip(ts_list, reward_list, send_rate_list, tput_list,
        #                       delay_list, loss_list, action_list, obs_list, mi_list))
        #     pkt_logs.append(pkt_log)
        #     results.append(result)
        # results = self.comm.gather(results, root=0)
        # pkt_logs = self.comm.gather(pkt_logs, root=0)
        # # need to call reduce to retrieve all return values
        # return results, pkt_logs

    def save_model(self):
        raise NotImplementedError

    def load_model(self):
        raise NotImplementedError

    def test(self, trace: Trace, save_dir: str):
        reward_list = []
        loss_list = []
        tput_list = []
        delay_list = []
        send_rate_list = []
        ts_list = []
        action_list = []
        mi_list = []
        obs_list = []
        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, 'aurora_simulation_log.csv'), 'w', 1) as f:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(['timestamp', "target_send_rate", "send_rate",
                             'recv_rate', 'max_recv_rate', 'latency',
                             'loss', 'reward', "action", "bytes_sent",
                             "bytes_acked", "bytes_lost", "MI",
                             "send_start_time",
                             "send_end_time", 'recv_start_time',
                             'recv_end_time', 'latency_increase',
                             "packet_size", 'min_lat', 'sent_latency_inflation',
                             'latency_ratio', 'send_ratio',
                             'bandwidth', "queue_delay",
                             'packet_in_queue', 'queue_size', 'cwnd',
                             'ssthresh', "rto", "recv_ratio"])
            env = gym.make(
                'PccNs-v0', traces=[trace], delta_scale=self.delta_scale)
            env.seed(self.seed)
            obs = env.reset()
            # print(obs)
            # heuristic = my_heuristic.MyHeuristic()
            while True:
                pred_start = time.time()
                if isinstance(self.model, LoadedModel):
                    obs = obs.reshape(1, -1)
                    action = self.model.act(obs)
                    action = action['act'][0]
                else:
                    if env.net.senders[0].got_data:
                        action, _states = self.model.predict(
                            obs, deterministic=True)
                    else:
                        action = np.array([0])
                # print("pred,{}".format(time.time() - pred_start))
                # print(env.senders[0].rate * 1500 * 8 / 1e6)

                # get the new MI and stats collected in the MI
                # sender_mi = env.senders[0].get_run_data()
                sender_mi = env.senders[0].history.back() #get_run_data()
                # if env.net.senders[0].got_data:
                #     action = heuristic.step(obs, sender_mi)
                #     # action = my_heuristic.stateless_step(env.senders[0].send_rate,
                #     #         env.senders[0].avg_latency, env.senders[0].lat_diff, env.senders[0].start_stage,
                #     #         env.senders[0].max_tput, env.senders[0].min_rtt, sender_mi.rtt_samples[-1])
                #     # action = my_heuristic.stateless_step(*obs)
                # else:
                #     action = np.array([0])
                # max_recv_rate = heuristic.max_tput
                max_recv_rate = env.senders[0].max_tput
                throughput = sender_mi.get("recv rate")  # bits/sec
                send_rate = sender_mi.get("send rate")  # bits/sec
                latency = sender_mi.get("avg latency")
                loss = sender_mi.get("loss ratio")
                avg_queue_delay = sender_mi.get('avg queue delay')
                sent_latency_inflation = sender_mi.get('sent latency inflation')
                latency_ratio = sender_mi.get('latency ratio')
                send_ratio = sender_mi.get('send ratio')
                recv_ratio = sender_mi.get('recv ratio')
                reward = pcc_aurora_reward(
                    throughput / 8 / BYTES_PER_PACKET, latency, loss,
                    np.mean(trace.bandwidths) * 1e6 / 8 / BYTES_PER_PACKET, np.mean(trace.delays) * 2/ 1e3)

                writer.writerow([
                    env.net.get_cur_time(), round(env.senders[0].rate * BYTES_PER_PACKET * 8, 0),
                    round(send_rate, 0), round(throughput, 0), round(max_recv_rate), latency, loss,
                    reward, action.item(), sender_mi.bytes_sent, sender_mi.bytes_acked,
                    sender_mi.bytes_lost, sender_mi.send_end - sender_mi.send_start,
                    sender_mi.send_start, sender_mi.send_end,
                    sender_mi.recv_start, sender_mi.recv_end,
                    sender_mi.get('latency increase'), sender_mi.packet_size,
                    sender_mi.get('conn min latency'), sent_latency_inflation,
                    latency_ratio, send_ratio,
                    env.links[0].get_bandwidth(
                        env.net.get_cur_time()) * BYTES_PER_PACKET * 8,
                    avg_queue_delay, env.links[0].pkt_in_queue, env.links[0].queue_size,
                    env.senders[0].cwnd, env.senders[0].ssthresh, env.senders[0].rto, recv_ratio])
                reward_list.append(reward)
                loss_list.append(loss)
                delay_list.append(latency * 1000)
                tput_list.append(throughput / 1e6)
                send_rate_list.append(send_rate / 1e6)
                ts_list.append(env.net.get_cur_time())
                action_list.append(action.item())
                mi_list.append(sender_mi.send_end - sender_mi.send_start)
                obs_list.append(obs.tolist())
                step_start = time.time()
                obs, rewards, dones, info = env.step(action)
                # print("step,{}".format(time.time() - step_start))

                if dones:
                    break
        with open(os.path.join(save_dir, "aurora_packet_log.csv"), 'w', 1) as f:
            pkt_logger = csv.writer(f, lineterminator='\n')
            pkt_logger.writerow(['timestamp', 'packet_event_id', 'event_type',
                                 'bytes', 'cur_latency', 'queue_delay',
                                 'packet_in_queue', 'sending_rate', 'bandwidth'])
            pkt_logger.writerows(env.net.pkt_log)
        return ts_list, reward_list, loss_list, tput_list, delay_list, send_rate_list, action_list, obs_list, mi_list, env.net.pkt_log

def test_model(model_path: str, trace: Trace, save_dir: str, seed: int):
    model = Aurora(seed, "", 10, model_path)
    pid = os.getpid()
    # print(pid, 'create model')

    # ret = model.test(trace, save_dir)
    print(pid, 'return')
    return ret
