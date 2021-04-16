import argparse
import csv
import os
from typing import List, Tuple, Union

import numpy as np
from common.utils import read_json_file, set_seed, write_json_file


class Trace():
    """Trace object.

    timestamps and bandwidth should be at least list of one item if bandwidth
    is a constant. timestamps needs to contain the last timestamp of the trace
    to mark the duration of the trace. bandwidhts and delays should share the
    same granularity.

    Args
        timestamps: trace timestamps in second.
        bandwidths: trace bandwidths in Mbps.
        delays: trace one-way delays in ms.
        loss_rate: uplink random packet loss rate.
        queue: queue in packets.
    """

    def __init__(self, timestamps: List[float], bandwidths: List[float],
                 delays: List[float], loss_rate: float, queue_size: int):
        assert len(timestamps) == len(bandwidths)
        self.timestamps = timestamps
        self.bandwidths = bandwidths
        self.delays = delays
        self.loss_rate = loss_rate
        self.queue_size = queue_size
        self.ack_delay_prob = 0
        self.idx = 0  # track the position in the trace

    def get_bandwidth(self, ts):
        """Return bandwidth(Mbps) at ts(second)."""
        # support time-variant bandwidth and constant bandwidth
        while self.idx + 1 < len(self.timestamps) and self.timestamps[self.idx + 1] <= ts:
            self.idx += 1
        if self.idx >= len(self.delays):
            return self.delays[-1]
        return self.bandwidths[self.idx]

    def get_delay(self, ts):
        """Return link one-way delay(millisecond) at ts(second)."""
        while self.idx + 1 < len(self.timestamps) and self.timestamps[self.idx + 1] <= ts:
            self.idx += 1
        if self.idx >= len(self.delays):
            return self.delays[-1]
        return self.delays[self.idx]

    def get_loss_rate(self):
        """Return link loss rate."""
        return self.loss_rate

    def get_queue_size(self):
        return self.queue_size

    def is_finished(self, ts):
        """Return if trace is finished."""
        return ts >= self.timestamps[-1]

    def __str__(self):
        return ("Timestamps: {}s,\nBandwidth: {}Mbps,\nLink delay: {}ms,\n"
                "Link loss: {:.3f}, Queue: {}packets".format(
                    self.timestamps, self.bandwidths, self.delays,
                    self.loss_rate, self.queue_size))

    def reset(self):
        self.idx = 0

    def dump(self, filename):
        # save trace details into a json file.
        data = {'timestamps': self.timestamps,
                'bandwidths': self.bandwidths,
                'delays': self.delays,
                'loss': self.loss_rate,
                'queue': self.queue_size,
                'ack_delay_prob': self.ack_delay_prob}
        write_json_file(filename, data)

    @staticmethod
    def load_from_file(filename):
        trace_data = read_json_file(filename)
        tr = Trace(trace_data['timestamps'], trace_data['bandwidths'],
                   trace_data['delays'], trace_data['loss'],
                   trace_data['queue'])
        if 'ack_delay_prob' in trace_data:
            tr.ack_delay_prob = trace_data['ack_delay_prob']
        return tr


def generate_trace(duration_range: Tuple[float, float],
                   bandwidth_range: Tuple[float, float],
                   delay_range: Tuple[float, float],
                   loss_rate_range: Tuple[float, float],
                   queue_size_range: Tuple[int, int],
                   # prob_stay_range: Union[Tuple[float, float], None] = None,
                   T_s_bw_range: Union[Tuple[float, float], None] = None,
                   T_s_delay_range: Union[Tuple[float, float], None] = None,
                   # cov_range: Union[Tuple[float, float], None] = None,
                   # steps_range: Union[Tuple[int, int], None] = None,
                   # timestep_range: Union[Tuple[float, float], None] = None,
                   bandwidth_file: str = "",
                   constant_bw: bool = True):
    """Generate trace for a network flow.

    Args:
        duration_range: duraiton range in second.
        bandwidth_range: link bandwidth range in Mbps.
        delay_range: link one-way propagation delay in ms.
        loss_rate_range: Uplink loss rate range.
        queue_size_range: queue size range in packets.
    """
    assert len(
        duration_range) == 2 and duration_range[0] <= duration_range[1]
    assert len(
        bandwidth_range) == 2 and bandwidth_range[0] <= bandwidth_range[1]
    assert len(delay_range) == 2 and delay_range[0] <= delay_range[1]
    assert len(
        loss_rate_range) == 2 and loss_rate_range[0] <= loss_rate_range[1]
    assert len(
        queue_size_range) == 2 and queue_size_range[0] <= queue_size_range[1] + 1

    delay = float(np.random.uniform(delay_range[0], delay_range[1], 1))
    loss_rate = float(np.random.uniform(
        loss_rate_range[0], loss_rate_range[1], 1))
    # queue_size = int(np.random.randint(
    #     queue_size_range[0], queue_size_range[1]+1))

    queue_size = int(np.exp(np.random.uniform(
        np.log(queue_size_range[0]),
        np.log(queue_size_range[1]+1), 1)))

    # if bandwidth_file:
    #     timestamps, bandwidths = load_bandwidth_from_file(bandwidth_file)
    #     return Trace(timestamps, bandwidths, delay, loss_rate, queue_size)

    duration = float(np.random.uniform(
        duration_range[0], duration_range[1], 1))
    if constant_bw:
        bw = float(np.random.uniform(
            bandwidth_range[0], bandwidth_range[1], 1))
        ret_trace = Trace([duration], [bw], [delay], loss_rate, queue_size)
        return ret_trace

    # use bandwidth generator.
    # assert prob_stay_range is not None and len(prob_stay_range) == 2 and \
    #     prob_stay_range[0] <= prob_stay_range[1] and \
    #     0 <= prob_stay_range[0] <= 1 and 0 <= prob_stay_range[1] <= 1
    assert T_s_bw_range is not None and len(
        T_s_bw_range) == 2 and T_s_bw_range[0] <= T_s_bw_range[1]
    assert T_s_delay_range is not None and len(
        T_s_delay_range) == 2 and T_s_delay_range[0] <= T_s_delay_range[1]
    # assert cov_range is not None and len(
    #     cov_range) == 2 and cov_range[0] <= cov_range[1]
    # assert steps_range is not None and len(
    #     steps_range) == 2 and steps_range[0] <= steps_range[1]
    # assert timestep_range is not None and len(
    #     timestep_range) == 2 and timestep_range[0] <= timestep_range[1]
    # prob_stay = float(np.random.uniform(
    #     prob_stay_range[0], prob_stay_range[1], 1))
    T_s_bw = float(np.random.uniform(T_s_bw_range[0], T_s_bw_range[1], 1))
    T_s_delay = float(np.random.uniform(
        T_s_delay_range[0], T_s_delay_range[1], 1))
    # cov = float(np.random.uniform(cov_range[0], cov_range[1], 1))
    # steps = int(np.random.randint(steps_range[0], steps_range[1]+1, 1))
    # timestep = float(np.random.uniform(
    #     timestep_range[0], timestep_range[1], 1))

    # timestamps, bandwidths = generate_bw_series(
    #     prob_stay, T_s, cov, duration, steps, bandwidth_range[0],
    #     bandwidth_range[1], timestep)
    # ret_trace = Trace(timestamps, bandwidths, [delay], loss_rate, queue_size)
    timestamps, bandwidths, delays = generate_bw_delay_series(
        T_s_bw, T_s_delay, duration, bandwidth_range[0], bandwidth_range[1],
        delay_range[0], delay_range[1])
    ret_trace = Trace(timestamps, bandwidths, delays, loss_rate, queue_size)
    return ret_trace


def generate_traces(config_file: str, tot_trace_cnt: int, duration: int,
                    constant_bw: bool = True):
    config = read_json_file(config_file)
    traces = []

    for env_config in config:
        bw_min, bw_max = env_config['bandwidth']
        delay_min, delay_max = env_config['delay']
        loss_min, loss_max = env_config['loss']
        queue_min, queue_max = env_config['queue']
        if 'duration' in env_config:
            duration_min, duration_max = env_config['duration']
        else:
            duration_min, duration_max = duration, duration

        # used by bandwidth generation
        # prob_stay_min, prob_stay_max = env_config['prob_stay'] if 'prob_stay' in env_config else (
        #     0.5, 0.5)
        T_s_bw_min, T_s_bw_max = env_config['T_s_bandwidth'] if 'T_s_bandwidth' in env_config else (
            2, 2)
        T_s_delay_min, T_s_delay_max = env_config['T_s_delay'] if 'T_s_delay' in env_config else (
            2, 2)
        # cov_min, cov_max = env_config['cov'] if 'cov' in env_config else (
        # 0.2, 0.2)
        # steps_min, steps_max = env_config['steps'] if 'steps' in env_config else (
        #     10, 10)
        # timestep_min, timestep_max = env_config['timestep'] if 'timestep' in env_config else (
        #     1, 1)
        trace_cnt = int(round(env_config['weight'] * tot_trace_cnt))
        for _ in range(trace_cnt):
            trace = generate_trace((duration_min, duration_max),
                                   (bw_min, bw_max),
                                   (delay_min, delay_max),
                                   (loss_min, loss_max),
                                   (queue_min, queue_max),
                                   # (prob_stay_min, prob_stay_max),
                                   (T_s_bw_min, T_s_bw_max),
                                   (T_s_delay_min, T_s_delay_max),
                                   # (cov_min, cov_max),
                                   # (steps_min, steps_max),
                                   # (timestep_min, timestep_max),
                                   constant_bw=constant_bw)
            traces.append(trace)
    return traces


def load_bandwidth_from_file(filename: str):
    timestamps = []
    bandwidths = []
    with open(filename, 'r') as f:
        csv_reader = csv.DictReader(f, delimiter=',')
        for row in csv_reader:
            timestamps.append(float(row['Timestamp']))
            bandwidths.append(float(row['Bandwidth']))

    return timestamps, bandwidths


def generate_bw_series(prob_stay: float, T_s: float, cov: float, duration: float,
                       steps: int, min_bw: float, max_bw: float,
                       timestep: float = 1):
    """Generate a time-variant bandwidth series.

    Args:
        prob_stay: probability of staying in one state. Value range: [0, 1].
        T_s: how often the noise is changing. Value range: [0, inf)
        cov: maximum percentage of noise with resepect current bandwidth
            value. Value range: [0, 1].
        duration: trace duration in second.
        steps: number of steps.
        min_bw: minimum bandwidth in Mbps.
        max_bw: maximum bandwidth in Mbps.
        seed: numpy random seed.
        timestep: a bandwidth value every timestep seconds. Default: 1 second.

    """

    # equivalent to Pensieve's way of computing switch parameter
    coeffs = np.ones(steps - 1)
    coeffs[0] = -1
    switch_parameter = np.real(np.roots(coeffs)[0])
    """Generate a bandwidth series."""
    # get bandwidth levels (in Mbps)
    bw_states = []
    curr = min_bw
    for _ in range(0, steps):
        bw_states.append(curr)
        curr += (max_bw-min_bw)/(steps-1)

    # list of transition probabilities
    transition_probs = []
    # assume you can go steps-1 states away (we will normalize this to the
    # actual scenario)
    for z in range(1, steps-1):
        transition_probs.append(1/(switch_parameter**z))

    # takes a state and decides what the next state is
    current_state = np.random.randint(0, len(bw_states)-1)
    current_variance = cov * bw_states[current_state]
    ts = 0
    cnt = 0
    trace_time = []
    trace_bw = []
    noise = 0
    while ts < duration:
        # prints timestamp (in seconds) and throughput (in Mbits/s)
        if cnt <= 0:
            noise = np.random.normal(0, current_variance, 1)[0]
            cnt = T_s
        # the gaussian val is at least 0.1
        gaus_val = max(0.1, bw_states[current_state] + noise)
        trace_time.append(ts)
        trace_bw.append(gaus_val)
        cnt -= 1
        next_val = transition(current_state, prob_stay, bw_states,
                              transition_probs)
        if current_state != next_val:
            cnt = 0
        current_state = next_val
        current_variance = cov * bw_states[current_state]
        ts += timestep
    return trace_time, trace_bw


def transition(state, prob_stay, bw_states, transition_probs):
    """Hidden Markov State transition."""
    # variance_switch_prob, sigma_low, sigma_high,
    transition_prob = np.random.uniform()

    if transition_prob < prob_stay:  # stay in current state
        return state
    else:  # pick appropriate state!
        # next_state = state
        curr_pos = state
        # first find max distance that you can be from current state
        max_distance = max(curr_pos, len(bw_states)-1-curr_pos)
        # cut the transition probabilities to only have possible number of
        # steps
        curr_transition_probs = transition_probs[0:max_distance]
        trans_sum = sum(curr_transition_probs)
        normalized_trans = [x/trans_sum for x in curr_transition_probs]
        # generate a random number and see which bin it falls in to
        trans_switch_val = np.random.uniform()
        running_sum = 0
        num_switches = -1
        for ind in range(0, len(normalized_trans)):
            # this is the val
            if (trans_switch_val <= (normalized_trans[ind] + running_sum)):
                num_switches = ind
                break
            else:
                running_sum += normalized_trans[ind]

        # now check if there are multiple ways to move this many states away
        switch_up = curr_pos + num_switches
        switch_down = curr_pos - num_switches
        # can go either way
        if (switch_down >= 0 and switch_up <= (len(bw_states)-1)):
            x = np.random.uniform(0, 1, 1)
            if (x < 0.5):
                return switch_up
            else:
                return switch_down
        elif switch_down >= 0:  # switch down
            return switch_down
        else:  # switch up
            return switch_up


def parse_args():
    """Parse arguments from the command line."""
    parser = argparse.ArgumentParser("Generate trace files.")
    parser.add_argument('--save-dir', type=str, required=True,
                        help="direcotry to save the model.")
    parser.add_argument('--config-file', type=str, required=True,
                        help="config file")
    parser.add_argument('--seed', type=int, default=42, help='seed')
    # parser.add_argument('--ntrace', type=int, required=True,
    #                     help='Number of trace files to be synthesized.')
    parser.add_argument('--time-variant-bw', action='store_true',
                        help='Generate time variant bandwidth if specified.')
    return parser.parse_args()


def main():
    args = parse_args()
    set_seed(args.seed)
    os.makedirs(args.save_dir, exist_ok=True)
    # traces = generate_traces(args.config_file, args.ntrace, args.duration,
    #                          constant_bw=not args.time_variant_bw)
    conf = read_json_file(args.config_file)
    dim_vary_name = None
    dim_vary = None
    for dim in conf:
        if len(conf[dim]) > 1:
            dim_vary = conf[dim]
            dim_vary_name = dim
        elif len(conf[dim]) == 1:
            pass
        else:
            raise RuntimeError

    assert dim_vary != None

    for i, value in enumerate(dim_vary):
        print(value)
        tr = generate_trace(
            duration_range=conf['duration'][0] if len(
                conf['duration']) == 1 else value,
            bandwidth_range=conf['bandwidth'][0] if len(
                conf['bandwidth']) == 1 else value,
            delay_range=conf['delay'][0] if len(
                conf['delay']) == 1 else value,
            loss_rate_range=conf['loss'][0] if len(
                conf['loss']) == 1 else value,
            queue_size_range=conf['queue'][0] if len(
                conf['queue']) == 1 else value,
            T_s_bw_range=conf['T_s_bandwidth'][0] if len(
                conf['T_s_bandwidth']) == 1 else value,
            T_s_delay_range=conf['T_s_delay'][0] if len(
                conf['T_s_delay']) == 1 else value, constant_bw=False)
        if dim_vary_name == "ack_delay_prob":
            tr.ack_delay_prob = value[0]
        tr.dump(os.path.join(args.save_dir, 'trace{:04d}.json'.format(i)))


def generate_bw_delay_series(T_s_bw: float, T_s_delay: float, duration: float, min_tp: float,
                             max_tp: float, min_delay: float, max_delay: float):
    timestamps = []
    bandwidths = []
    delays = []
    round_digit = 2
    ts = 0
    cnt_bw = T_s_bw
    cnt_delay = T_s_delay
    bw_val = round(np.random.uniform(min_tp, max_tp), round_digit)
    last_bw_val = bw_val
    delay_val = round(np.random.uniform(
        min_delay, max_delay), round_digit)
    last_delay_val = delay_val

    while ts < duration:
        if T_s_bw < 0:
            pass
        elif cnt_bw <= 0:
            bw_val = round(np.random.uniform(min_tp, max_tp), round_digit)
            cnt_bw = T_s_bw
        elif cnt_bw >= 1:
            bw_val = last_bw_val
        else:
            bw_val = round(np.random.uniform(min_tp, max_tp), round_digit)

        if T_s_delay < 0:
            pass
        elif cnt_delay <= 0:
            delay_val = round(np.random.uniform(
                min_delay, max_delay), round_digit)
            cnt_delay = T_s_delay
        elif cnt_delay >= 1:
            delay_val = last_delay_val
        else:
            delay_val = round(np.random.uniform(
                min_delay, max_delay), round_digit)

        cnt_bw -= 1
        cnt_delay -= 1
        ts = round(ts, 2)

        last_bw_val = bw_val
        last_delay_val = delay_val
        timestamps.append(ts)
        bandwidths.append(bw_val)
        delays.append(delay_val)
        # ts_noise = np.random.uniform(0.1, 3.5)
        ts += 0.1 # ts_noise
    timestamps.append(duration)
    bandwidths.append(bw_val)
    delays.append(delay_val)
    return timestamps, bandwidths, delays


if __name__ == "__main__":
    main()
