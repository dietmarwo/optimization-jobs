"""Synthetic traffic-recovery experiment using the existing LP/IP worker.

The independent schedule checker and exhaustive small-instance oracle do not
read the MIP's matrix. This is a planning example, not railway control logic.
"""
import copy
import itertools
import json
import math
from pathlib import Path

TOL = 1e-7


def validate_scenario(data):
    """Keep this teaching fixture small and reject ambiguous/nonfinite inputs."""
    if set(data) != {'schema_version', 'description', 'horizon_minutes', 'clearance_minutes', 'trains'}:
        raise ValueError('Unexpected or missing scenario fields')
    if data['schema_version'] != 'rail-traffic.scenario/1' or not isinstance(data['description'], str):
        raise ValueError('Unsupported scenario version or description')
    def number(value, low, high):
        return type(value) is int and low <= value <= high
    if not number(data['horizon_minutes'], 1, 240) or not number(data['clearance_minutes'], 1, 10):
        raise ValueError('Use an integer horizon 1..240 and clearance 1..10 minutes')
    trains = data['trains']
    if not isinstance(trains, list) or not 2 <= len(trains) <= 8:
        raise ValueError('This exhaustive teaching oracle supports 2..8 trains')
    ids = set()
    for train in trains:
        if set(train) != {'id', 'direction', 'planned', 'ready', 'duration', 'passengers'}:
            raise ValueError('Unexpected or missing train fields')
        name = train['id']
        if not isinstance(name, str) or not name or not name.isascii() or not name.isalnum() or name in ids:
            raise ValueError('Train IDs must be unique ASCII letters/digits')
        ids.add(name)
        if train['direction'] not in ('A-B', 'B-A'):
            raise ValueError('Direction must be A-B or B-A')
        if not all(number(train[k], 0, data['horizon_minutes']) for k in ('planned', 'ready')):
            raise ValueError('Times must be integer minutes within the horizon')
        if not number(train['duration'], 1, 60) or not number(train['passengers'], 1, 2000):
            raise ValueError('Duration 1..60 and positive passenger count 1..2000 required')
        if max(train['ready'], train['planned']) + train['duration'] > data['horizon_minutes']:
            raise ValueError('A train cannot fit within the declared horizon')
    return data


def queue_pairs(data):
    trains = data['trains']
    pairs = []
    for direction in ('A-B', 'B-A'):
        queue = sorted((i for i, t in enumerate(trains) if t['direction'] == direction),
                       key=lambda i: (trains[i]['planned'], trains[i]['id']))
        pairs.extend(zip(queue, queue[1:]))
    return pairs


def schedule_order(data, order):
    """Earliest feasible starts for a fixed order; exact integer arithmetic."""
    if sorted(order) != list(range(len(data['trains']))):
        raise ValueError('Order must contain every train once')
    starts, free = [0] * len(order), 0
    for i in order:
        t = data['trains'][i]
        starts[i] = max(t['planned'], t['ready'], free)
        free = starts[i] + t['duration'] + data['clearance_minutes']
    return starts


def assess(data, starts, cap=None, fifo=False):
    """Physical-model checks independent of the MIP matrix and precedence bits."""
    trains = data['trains']
    if len(starts) != len(trains) or not all(math.isfinite(s) for s in starts):
        raise ValueError('Wrong-size or nonfinite schedule')
    problems = []
    delays = [s-t['planned'] for s, t in zip(starts, trains)]
    for i, (s, t) in enumerate(zip(starts, trains)):
        if s < max(t['planned'], t['ready']) - TOL:
            problems.append('early:' + t['id'])
        if s + t['duration'] > data['horizon_minutes'] + TOL:
            problems.append('horizon:' + t['id'])
        if cap is not None and delays[i] > cap + TOL:
            problems.append('delay_cap:' + t['id'])
    order = sorted(range(len(trains)), key=lambda i: (starts[i], trains[i]['id']))
    for i, j in zip(order, order[1:]):
        if starts[j] < starts[i] + trains[i]['duration'] + data['clearance_minutes'] - TOL:
            problems.append('block_conflict:' + trains[i]['id'] + ':' + trains[j]['id'])
    if fifo:
        for i, j in queue_pairs(data):
            if starts[j] < starts[i] + trains[i]['duration'] + data['clearance_minutes'] - TOL:
                problems.append('queue_order:' + trains[i]['id'] + ':' + trains[j]['id'])
    return {'feasible': not problems, 'violations': problems,
            'order': [trains[i]['id'] for i in order], 'starts': list(starts), 'delays': delays,
            'passenger_minutes': sum(t['passengers'] * d for t, d in zip(trains, delays)),
            'train_minutes': sum(delays), 'max_delay': max(delays)}


def enumerate_orders(data, cap=None, fifo=False):
    """For positive weights, earliest starts dominate every later fixed-order plan."""
    best, feasible, visited = None, 0, 0
    for order in itertools.permutations(range(len(data['trains']))):
        visited += 1
        candidate = assess(data, schedule_order(data, order), cap, fifo)
        if candidate['feasible']:
            feasible += 1
            if best is None or candidate['passenger_minutes'] < best['passenger_minutes']:
                best = candidate
    return {'orders_checked': visited, 'feasible_orders': feasible, 'best': best}


def make_model(data, cap=None, fifo=False, relaxed=False):
    trains = data['trains']; n = len(trains)
    pairs = list(itertools.combinations(range(n), 2))
    lower = [max(t['ready'], t['planned']) for t in trains]
    upper = [data['horizon_minutes'] - t['duration'] for t in trains]
    model = {'schema_version': 'lp-ip.model/1', 'sense': 'minimize',
             'objective': [t['passengers'] for t in trains] + [0] * len(pairs),
             'objective_offset': -sum(t['passengers'] * t['planned'] for t in trains),
             'variable_lower': lower + [0] * len(pairs), 'variable_upper': upper + [1] * len(pairs),
             'kinds': ['continuous'] * n + ['continuous' if relaxed else 'binary'] * len(pairs),
             'matrix': {'indptr': [0], 'indices': [], 'values': []}, 'row_lower': [], 'row_upper': []}
    labels = []
    def row(coefficients, bound, label):
        for index, value in sorted(coefficients.items()):
            if value:
                model['matrix']['indices'].append(index); model['matrix']['values'].append(value)
        model['matrix']['indptr'].append(len(model['matrix']['indices']))
        model['row_lower'].append(None); model['row_upper'].append(bound); labels.append(label)
    for k, (i, j) in enumerate(pairs, n):
        oi = trains[i]['duration'] + data['clearance_minutes']
        oj = trains[j]['duration'] + data['clearance_minutes']
        mij = max(0, upper[i] + oi - lower[j])
        mji = max(0, upper[j] + oj - lower[i])
        row({i: 1, j: -1, k: mij}, mij-oi, f'{i}_before_{j}')
        row({j: 1, i: -1, k: -mji}, -oj, f'{j}_before_{i}')
    if cap is not None:
        for i, t in enumerate(trains):
            row({i: 1}, t['planned'] + cap, f'delay_cap_{i}')
    if fifo:
        for i, j in queue_pairs(data):
            row({i: 1, j: -1}, -trains[i]['duration']-data['clearance_minutes'], f'queue_{i}_{j}')
    mapping = {'columns': ['start:' + t['id'] for t in trains] +
               [f'before:{trains[i]["id"]}:{trains[j]["id"]}' for i, j in pairs], 'rows': labels}
    return model, mapping


def encode(data, starts):
    return list(starts) + [float(starts[i] < starts[j])
                           for i, j in itertools.combinations(range(len(starts)), 2)]


def replay(data, nominal, extra):
    """Keep the nominal order/commitments; propagate an extra delay to train 0."""
    stressed = copy.deepcopy(data); stressed['trains'][0]['ready'] += extra
    by_id = {t['id']: i for i, t in enumerate(stressed['trains'])}
    starts, free = nominal['starts'].copy(), 0
    for name in nominal['order']:
        i = by_id[name]; t = stressed['trains'][i]
        starts[i] = max(starts[i], t['planned'], t['ready'], free)
        free = starts[i] + t['duration'] + stressed['clearance_minutes']
    return assess(stressed, starts, cap=10)


def execute(c, write):
    data = validate_scenario(json.loads(c.args.rail_scenario.read_text()))
    write(c.out / 'rail-scenario.json', data)
    c.register('rail-lp-ip', 'lp-ip-job-worker')
    n = len(data['trains'])
    arrival_order = sorted(range(n), key=lambda i: (max(data['trains'][i]['ready'], data['trains'][i]['planned']),
                                                   data['trains'][i]['planned'], data['trains'][i]['id']))
    fcfs = assess(data, schedule_order(data, arrival_order))
    planned = assess(data, schedule_order(data, sorted(range(n), key=lambda i: (data['trains'][i]['planned'], data['trains'][i]['id']))))
    summaries = {'fcfs': fcfs}; oracles = {}; raw = {}
    payload = {'model_input': 'model', 'starts': [None], 'node_limit': 10000,
               'iteration_limit': 100000, 'feasibility_tolerance': TOL,
               'integrality_tolerance': TOL, 'presolve': True}
    def submit(name, model, starts, allowed=()):
        inputs = c.model_input('rail-lp-ip', name+'-model.json', model, 'lp-ip.model/1')
        result = c.run(name, 'rail-lp-ip', 'lp-ip.solve/1', {**payload, 'starts': starts}, inputs,
                       allowed_claimed=allowed)
        raw[name] = result
        return result, inputs
    for name, cap, fifo in [('weighted', None, False), ('fair10', 10, False),
                            ('fair8', 8, False), ('queue10', 10, True)]:
        model, mapping = make_model(data, cap, fifo)
        write(c.out / 'specs' / ('rail-'+name+'-names.json'), mapping)
        # A simple baseline candidate, never the exhaustive oracle's answer.
        candidate = next((x for x in (fcfs, planned) if assess(data, x['starts'], cap, fifo)['feasible']), None)
        starts = [None] + ([encode(data, candidate['starts'])] if candidate else [])
        oracle = enumerate_orders(data, cap, fifo); oracles[name] = oracle
        result, inputs = submit('rail-'+name, model, starts, ('infeasible',) if oracle['best'] is None else ())
        if oracle['best'] is None:
            assert all(r['outcome']['claim'] == 'infeasible' for r in result['results'])
            summaries[name] = {'feasible': False, 'reason': 'No feasible order within this model'}
            continue
        checked = []
        for record in result['results']:
            o = record['outcome']
            assert o['claim'] == 'numerical_optimum' and o['evidence']['level'] == 'rechecked', o
            schedule = assess(data, o['x'][:n], cap, fifo)
            assert schedule['feasible'], schedule
            assert all(abs(v-round(v)) <= TOL for v in o['x'][n:]), o
            assert math.isclose(schedule['passenger_minutes'], o['objective'], rel_tol=0, abs_tol=1e-5)
            assert math.isclose(o['objective'], oracle['best']['passenger_minutes'], rel_tol=0, abs_tol=1e-5)
            bounds = o['objective_bounds']
            assert bounds['sense'] == 'minimize' and math.isclose(bounds['dual'], o['objective'], rel_tol=0, abs_tol=1e-5)
            checked.append(schedule)
        summaries[name] = {**checked[0], 'outcomes': [r['outcome'] for r in result['results']],
                           'warm_start_policy': 'FCFS or planned-order baseline' if candidate else None}
        if name == 'weighted':
            bad = checked[0]['starts'].copy(); bad[1] = bad[0]
            # Keep bounds where possible: conflict is sufficient for rejection.
            points = [result['results'][0]['outcome']['x'], encode(data, fcfs['starts']), encode(data, bad)]
            evaluated = c.run('rail-point-check', 'rail-lp-ip', 'lp-ip.evaluate/1',
                             {'model_input': 'model', 'points': points, 'feasibility_tolerance': TOL,
                              'integrality_tolerance': TOL}, inputs)
            assert [r['outcome']['feasible'] for r in evaluated['results']] == [True, fcfs['feasible'], False]
            assert evaluated['results'][-1]['outcome']['claim'] == 'none'
    model, _ = make_model(data, relaxed=True)
    result, _ = submit('rail-relaxation', model, [None])
    o = result['results'][0]['outcome']
    assert o['claim'] == 'numerical_optimum'
    summaries['relaxation'] = {'outcome': o, 'physical_schedule': assess(data, o['x'][:n])}
    if summaries['weighted']['feasible']:
        assert o['objective'] <= summaries['weighted']['passenger_minutes'] + 1e-5
    stressed = copy.deepcopy(data); stressed['trains'][0]['ready'] += 5
    model, _ = make_model(stressed, cap=10)
    stress_oracle = enumerate_orders(stressed, cap=10); oracles['stress5_cap10'] = stress_oracle
    result, _ = submit('rail-stress5-cap10', model, [None], ('infeasible',) if stress_oracle['best'] is None else ())
    if stress_oracle['best'] is None:
        assert result['results'][0]['outcome']['claim'] == 'infeasible'
    summaries['stress5_cap10'] = {'outcome': result['results'][0]['outcome'],
                                'first_train_delay_lower_bound': stressed['trains'][0]['ready']-stressed['trains'][0]['planned'],
                                'oracle_feasible': stress_oracle['best'] is not None}
    stress = {name: [{'extra_delay': extra, **replay(data, summaries[name], extra)} for extra in (0, 2, 5)]
              for name in ('weighted', 'fair10', 'queue10') if summaries[name]['feasible']}
    write(c.out / 'rail-oracles.json', oracles)
    write(c.out / 'rail-summary.json', {'scenario': data, 'policies': summaries, 'stress_replay': stress,
          'units': 'passenger-minutes of delay at this bottleneck; not final journey delay',
          'scope': 'Synthetic one-block planning model; no signalling, braking, platforms or downstream network'})
    plot(data, summaries, stress, c.out)


def plot(data, policies, stress, out):
    import matplotlib.pyplot as plt
    names = [n for n in ('fcfs', 'weighted', 'fair10', 'fair8', 'queue10') if policies[n]['feasible']]
    colors = plt.get_cmap('tab10').colors
    fig, axes = plt.subplots(len(names), 1, figsize=(10, 2.2*len(names)), sharex=True)
    for ax, name in zip(axes, names):
        for i, (train, start) in enumerate(zip(data['trains'], policies[name]['starts'])):
            ax.barh(i, train['duration'], left=start, color=colors[i % 10], height=.65)
            ax.barh(i, data['clearance_minutes'], left=start+train['duration'], color='#dddddd', height=.65)
            ax.plot(train['planned'], i, '|', color='black', markersize=9)
        ax.set_yticks(range(len(data['trains'])), [t['id'] for t in data['trains']], fontsize=8)
        ax.invert_yaxis(); ax.grid(axis='x', alpha=.2)
        ax.set_title(f"{name}: {policies[name]['passenger_minutes']:,.0f} passenger-min; max delay {policies[name]['max_delay']:.0f} min", fontsize=11, loc='left')
    axes[-1].set_xlabel('Minutes after 08:00; black tick = planned entry; grey = clearance')
    fig.tight_layout(); fig.savefig(out/'rail-timetable.png', dpi=150); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, key, label in zip(axes, ('passenger_minutes', 'max_delay'), ('Passenger-minutes of delay', 'Worst train delay (minutes)')):
        ax.bar(names, [policies[n][key] for n in names], color=['#718096', '#176b87', '#21845b', '#9f6d27', '#8e6c9c'][:len(names)])
        ax.set_ylabel(label); ax.tick_params(axis='x', labelrotation=25); ax.grid(axis='y', alpha=.2)
    fig.tight_layout(); fig.savefig(out/'rail-tradeoffs.png', dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4))
    for name, rows in stress.items():
        ax.plot([r['extra_delay'] for r in rows], [r['max_delay'] for r in rows], marker='o', label=name)
    ax.axhline(10, color='#b33a3a', linestyle='--', label='10-minute policy cap')
    ax.set(xlabel='Additional incoming delay of ICE101 (minutes)', ylabel='Worst train delay after fixed-order replay (minutes)')
    ax.legend(); ax.grid(alpha=.2); fig.tight_layout(); fig.savefig(out/'rail-stress.png', dpi=150); plt.close(fig)
