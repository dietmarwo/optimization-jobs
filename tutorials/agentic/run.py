#!/usr/bin/env python3
"""Build or execute nine prompt tutorials with retained specs and results.

Requires Python 3.10+, jsonschema and matplotlib; Linux/Rust 1.88+ for builds.
The agent chooses and interprets experiments; this driver handles reproducibility.
"""
import argparse
import cmath
import copy
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CHAPTERS = ('trebuchet', 'production', 'energy', 'curve-fit', 'gtoc1', 'surrogate', 'lp-ip', 'sqp', 'rail-traffic')
TUTORIALS = {'trebuchet': ('rapier-trebuchet', 'trebuchet-job-worker'),
             'production': ('nexosim-production-line', 'production-job-worker'),
             'energy': ('energy-hub-bilevel', 'energy-job-worker'),
             'gtoc1': ('gtoc1-route-search', 'gtoc1-job-worker')}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, log=None):
    p = subprocess.run(list(map(str, argv)), capture_output=True, text=True)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('$ ' + ' '.join(map(str, argv)) + '\n' + p.stdout + p.stderr)
    if p.returncode:
        raise RuntimeError(f'Command failed ({p.returncode}): {argv}\n{p.stderr[-6000:]}')
    return p.stdout


def build(args):
    selected = set(CHAPTERS if args.chapter == 'all' else [args.chapter])
    target = args.build_dir.resolve()
    bindir = args.bin_dir.resolve()
    bindir.mkdir(parents=True, exist_ok=True)
    logdir = bindir / 'build-logs'
    def cargo(repo, tail, binaries):
        command(['cargo', 'build', '--release', '--locked', '--target-dir', target,
                 '--manifest-path', repo / 'Cargo.toml', *tail],
                logdir / (binaries[0][1] + '.log'))
        for source, dest in binaries:
            shutil.copy2(target / 'release' / source, bindir / dest)
    cargo(REPO, [], [('optimization-run', 'optimization-run'), ('optimization-mcp', 'optimization-mcp')])
    for chapter, (name, exe) in TUTORIALS.items():
        if chapter not in selected:
            continue
        cargo(args.sources / 'fcmaes-rust/tutorials' / name, ['--features', 'job-worker'],
              [(exe, exe)] + ([(name, name)] if name == 'rapier-trebuchet' else [])
              + ([('gtoc1-route-card', 'gtoc1-route-card')] if name == 'gtoc1-route-search' else []))
    for repo, package, dest in [('fcmaes-rust', 'fcmaes-job-worker', 'fcmaes-curve-worker'),
                                ('SQP-craft', 'sqp-job-worker', 'sqp-curve-worker')]:
        if 'curve-fit' not in selected:
            continue
        cargo(args.sources / repo, ['-p', package, '--example', 'custom_worker'],
              [('examples/custom_worker', dest)])
    if selected & {'energy', 'lp-ip', 'rail-traffic'}:
        cargo(args.sources / 'LP-IP-craft', ['-p', 'lp-ip-job-worker'], [('lp-ip-job-worker', 'lp-ip-job-worker')])
    if 'sqp' in selected:
        cargo(args.sources / 'SQP-craft', ['-p', 'sqp-job-worker'], [('sqp-job-worker', 'sqp-job-worker')])
    if 'surrogate' in selected:
        cargo(args.sources / 'fcmaes-rust', ['-p', 'fcmaes-job-worker'], [('fcmaes-job-worker', 'fcmaes-job-worker')])
        cargo(args.sources / 'fcmaes-rust', ['-p', 'fcmaes-job-worker', '--example', 'simulation_worker'],
              [('examples/simulation_worker', 'surrogate-simulation-worker')])
    manifest = {'chapters': [c for c in CHAPTERS if c in selected],
                'source_revisions': revisions(args.sources),
                'binaries': {p.name: digest(p) for p in bindir.iterdir()
                             if p.is_file() and os.access(p, os.X_OK)}}
    write(bindir / 'build-manifest.json', manifest)
    print(json.dumps(manifest, indent=2))


def revisions(sources):
    result = {}
    for name in ('fcmaes-rust', 'LP-IP-craft', 'SQP-craft', 'fast-cma-es', 'optimization-jobs'):
        p = sources / name
        if (p / '.git').exists():
            result[name] = {'commit': command(['git', '-C', p, 'rev-parse', 'HEAD']).strip(),
                            'dirty': bool(command(['git', '-C', p, 'status', '--porcelain']).strip())}
    return result


class Campaign:
    def __init__(self, args):
        import jsonschema
        self.validator = jsonschema.Draft202012Validator
        self.args = args
        self.out = args.output.resolve()
        if self.out.exists() and any(self.out.iterdir()):
            raise ValueError('output must be new or empty; retain previous experiment evidence')
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / 'specs').mkdir()
        self.runner = args.bin_dir.resolve() / 'optimization-run'
        self.descriptions = {}
        self.jobs = []
        self.job_handles = {}
        self.call('node', 'init', '--capacity', args.cores)
        self.job_schema = json.loads((REPO / 'docs/job-api/schemas/optimization.job-0.1.schema.json').read_text())
        self.result_schema = json.loads((REPO / 'docs/job-api/schemas/optimization.result-0.2.schema.json').read_text())

    def call(self, *argv):
        return json.loads(command([self.runner, '--root', self.out / 'node', *argv]))

    def register(self, worker, exe):
        if worker not in self.descriptions:
            binary = self.args.bin_dir.resolve() / exe
            self.call('workers', 'add', '--id', worker, '--executable', binary)
            self.descriptions[worker] = self.call('problems', 'describe', worker)
            write(self.out / 'discovery' / (worker + '.json'), self.descriptions[worker])

    def problem(self, worker, model):
        d = self.descriptions[worker]
        for example in d['examples']:
            p = example['payload'].get('problem')
            if isinstance(p, dict) and p.get('id') == model:
                return copy.deepcopy(p)
        raise ValueError(f'{model} has no runnable discovery example')

    def run(self, name, worker, profile, payload, inputs=None, parallel='outer',
            inner_threads=None, allowed_claimed=()):
        cpus = self.args.cores
        resources = {'cpu_slots': cpus, 'outer_workers': cpus if parallel == 'outer' else 1,
                     'inner_threads': 1 if parallel == 'outer' else cpus}
        if inner_threads is not None:
            resources['inner_threads'] = inner_threads
        spec = {'schema_version': 'optimization.job/0.1', 'request_key': name,
                'worker': worker, 'payload_schema': profile, 'payload': payload,
                'resources': resources, 'limits': {'wall_time_seconds': 300.0, 'grace_seconds': 2.0},
                'inputs': inputs or []}
        # The schemas are supplied by the worker actually registered on this node.
        schemas = self.descriptions[worker]['payload_schemas']
        schema = schemas[profile] if isinstance(schemas, dict) else next(s['schema'] for s in schemas if s['profile'] == profile)
        self.validator(schema).validate(payload)
        self.validator(self.job_schema).validate(spec)
        path = self.out / 'specs' / (name + '.json')
        write(path, spec)
        self.call('validate', '--spec', path)
        started = time.monotonic()
        job = self.call('run', '--spec', path)
        result = self.call('result', job['directory'])
        self.validator(self.result_schema).validate(result)
        if job['state'] != 'completed' or not result['runner']['accounting_complete']:
            raise AssertionError(f'{name}: job did not complete with full accounting')
        check_evidence(result['results'], allowed_claimed)
        self.job_handles[name] = job
        write(self.out / 'results' / (name + '.json'), result)
        self.jobs.append({'name': name, 'profile': profile, 'worker': worker,
                          'seconds': time.monotonic() - started, 'work': result['work'],
                          'claims': [r['outcome']['claim'] for r in result['results']],
                          'spec': f'specs/{name}.json', 'result': f'results/{name}.json'})
        print(f'{name}: completed; claims={self.jobs[-1]["claims"]}', flush=True)
        return result

    def model_input(self, worker, filename, model, schema_id):
        self.validator(self.descriptions[worker]['input_schemas'][schema_id]).validate(model)
        path = self.out / 'specs' / filename
        write(path, model)
        return [{'name': 'model', 'file': filename, 'sha256': digest(path)}]

    def surrogate_artifacts(self, name, worker, result):
        """Retain indexed bytes and checksum-verified decoded trace pages."""
        job = self.job_handles[name]
        index = result['runner']['artifact_index']
        directory = Path(job['directory']).resolve()
        for key, item in index.items():
            path = (directory / item['file']).resolve()
            if not path.is_relative_to(directory) or digest(path) != item['sha256']:
                raise AssertionError('artifact path or checksum mismatch')
            dest = self.out / 'artifacts' / name / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        trace, offset = [], 0
        while True:
            page = self.call('jobs', 'artifact', job['id'], 'surrogate-0', '--offset', offset, '--limit', 32)
            trace.extend(page['records'])
            next_offset = page['next_offset']
            if next_offset >= page['available']:
                break
            if next_offset <= offset:
                raise AssertionError('artifact pagination did not advance')
            offset = next_offset
        completed = sum(r['record'] == 'event' and r['data']['event'] == 'completed' for r in trace)
        assert completed == result['work']['evaluations'], (completed, result['work'])
        write(self.out / 'artifacts' / name / 'decoded-trace.json', trace)
        content = self.call('jobs', 'artifact', job['id'], 'surrogate-observations-0')['content'].encode()
        assert hashlib.sha256(content).hexdigest() == index['surrogate-observations-0']['sha256']
        snapshot = json.loads(content)
        self.validator(self.descriptions[worker]['input_schemas']['fcmaes.surrogate.observations/1']).validate(snapshot)
        return content, snapshot

    def evaluate(self, name, worker, problem, points):
        return self.run(name, worker, 'fcmaes.evaluate/1', {'problem': problem, 'points': points})

    def retry(self, name, worker, problem, calls, guess=None):
        p = {'problem': problem, 'optimizer': {'kind': 'biteopt', 'parameters': {}},
             'seed': self.args.seed, 'retries': 2, 'evaluations_per_retry': calls,
             'evaluation_limit_mode': 'hard'}
        if guess is not None:
            p['guess'] = guess
        return self.run(name, worker, 'fcmaes.retry/1', p)

    def mode(self, name, worker, problem, generations=4):
        return self.run(name, worker, 'fcmaes.mode/1', {
            'problem': problem, 'optimizer': {'kind': 'mode', 'parameters': {'population': 16}},
            'seed': self.args.seed, 'runs': 1, 'generations': generations}, parallel='inner')

    def qd(self, name, worker, problem, generations=8):
        return self.run(name, worker, 'fcmaes.map-elites/1', {
            'problem': problem, 'optimizer': {'kind': 'map_elites', 'parameters': {'chunk_size': 16}},
            'archive': {'capacity': 16}, 'seed': self.args.seed, 'runs': 1, 'generations': generations}, parallel='inner')


def check_evidence(records, allowed_claimed=()):
    """Allow only explicitly expected non-certificate claims, such as infeasibility."""
    for record in records:
        o = record['outcome']
        if o['evidence'].get('refuted'):
            raise AssertionError('a numerical claim was refuted')
        if o['claim'] != 'none':
            required = 'claimed' if o['claim'] in allowed_claimed else 'rechecked'
            if o['evidence']['level'] != required:
                raise AssertionError(f'{o["claim"]} requires evidence level {required}')


def best(result):
    candidates = [r['outcome'] for r in result['results'] if r['outcome']['claim'] != 'none'
                  and r['outcome'].get('x') is not None and r['outcome'].get('objective') is not None]
    if not candidates:
        raise AssertionError('no usable scalar incumbent; inspect failure results')
    return min(candidates, key=lambda o: o['objective'])


def outcome(result):
    return result['results'][0]['outcome']


def trebuchet(c):
    c.register('trebuchet', 'trebuchet-job-worker')
    def p(kind):
        v = c.problem('trebuchet', 'app.trebuchet.' + kind)
        v['parameters']['target_m'] = c.args.target_m
        return v
    initial = [3.5, 80., 4., 2.5, -.75, -.05, 2., 2.]
    c.evaluate('trebuchet-baseline', 'trebuchet', p('checked'), [initial])
    r = c.retry('trebuchet-scalar', 'trebuchet', p('scalar'), 1000 * c.args.budget_scale)
    winner = best(r)
    c.evaluate('trebuchet-recheck', 'trebuchet', p('checked'), [winner['x']])
    mo = c.mode('trebuchet-pareto', 'trebuchet', p('pareto'), 8 * c.args.budget_scale)
    qd = c.qd('trebuchet-qd', 'trebuchet', p('qd'), 32 * c.args.budget_scale)
    command([c.args.bin_dir / 'rapier-trebuchet', '--mode', 'simulate', '--target', c.args.target_m,
             '--x', ','.join(map(str, winner['x'])), '--output', c.out / 'trebuchet-replay'], c.out / 'trebuchet-replay.log')
    # Replay up to three distinct archive niches, including the extremes in
    # apex height. A sparse archive is reported as sparse, never fabricated.
    elites = sorted(outcome(qd)['details'].get('elites', []), key=lambda e: e['descriptor'][0])
    indices = sorted({0, len(elites) // 2, len(elites) - 1}) if elites else []
    selected = [elites[i] for i in indices]
    if selected:
        c.evaluate('trebuchet-diversity-recheck', 'trebuchet', p('checked'), [e['x'] for e in selected])
    for e in selected:
        name = f'trebuchet-niche-{e["niche"]}'
        command([c.args.bin_dir / 'rapier-trebuchet', '--mode', 'simulate', '--target', c.args.target_m,
                 '--x', ','.join(map(str, e['x'])), '--output', c.out / name], c.out / (name + '.log'))
    write(c.out / 'trebuchet-replays.json', {'scalar': 'trebuchet-replay/replay.html',
          'archive_occupied': len(elites), 'diverse': [dict(niche=e['niche'], descriptor=e['descriptor'],
          replay=f'trebuchet-niche-{e["niche"]}/replay.html') for e in selected]})
    plot_front(c, 'trebuchet', mo, ['Target error (m)', 'Input energy (J)'])
    plot_front(c, 'trebuchet-load', mo, ['Target error (m)', 'Peak joint force (N)'], (0, 2))


def production(c):
    c.register('production', 'production-job-worker')
    def p(kind, seed):
        v = c.problem('production', 'app.production.' + kind)
        v['parameters'].update(replications=2, horizon_minutes=120., simulation_seed=seed)
        return v
    r = c.mode('production-pareto', 'production', p('pareto', 42), 4 * c.args.budget_scale)
    front = outcome(r)['details']['front']
    if not front:
        raise AssertionError('production front is empty')
    # Select by training throughput only; holdout cannot affect the selection.
    points = [z['x'] for z in sorted(front, key=lambda z: z['objectives'][0])[:3]]
    c.evaluate('production-training-recheck', 'production', p('pareto', 42), points)
    c.evaluate('production-holdout', 'production', p('pareto', 314159), points)
    c.qd('production-qd', 'production', p('qd', 42), 4 * c.args.budget_scale)
    plot_front(c, 'production', r, ['Negative throughput', 'Lead time'])


def energy(c):
    c.register('energy', 'energy-job-worker')
    p = c.problem('energy', 'app.energy.scalar')
    seed = [.48, .42, math.log(4000 / 100) / math.log(20000 / 100),
            math.log(1000 / 50) / math.log(5000 / 50), .4, .3, 3.5 / 6, .75, .75, .25]
    baseline = c.evaluate('energy-baseline', 'energy', p, [seed])
    r = c.retry('energy-scalar', 'energy', p, 24 * c.args.budget_scale, seed)
    # Retain the measured baseline if a small search fails to improve it.
    selected = min([best(baseline), best(r)], key=lambda o: o['objective'])
    checked = c.problem('energy', 'app.energy.checked')
    c.evaluate('energy-engineering-recheck', 'energy', checked, [selected['x']])
    checked['parameters']['scenario_set'] = 'holdout'
    c.evaluate('energy-holdout', 'energy', checked, [selected['x']])
    mo = c.mode('energy-pareto', 'energy', c.problem('energy', 'app.energy.pareto'), 2 * c.args.budget_scale)
    c.qd('energy-qd', 'energy', c.problem('energy', 'app.energy.qd'), 2 * c.args.budget_scale)
    plot_front(c, 'energy', mo, ['Annualized capital cost', 'Worst unserved energy'])
    plot_front(c, 'energy-emissions', mo, ['Annualized capital cost', 'Mean grid CO2 (kg/year)'], (0, 2))
    # A separate, exactly checkable one-hour dispatch lesson. This is not a
    # replacement of the tutorial's multi-scenario microlp dispatch model.
    c.register('lp-ip', 'lp-ip-job-worker')
    model = {'schema_version': 'lp-ip.model/1', 'sense': 'minimize', 'objective': [.25, 0., 10.],
             'objective_offset': 0., 'variable_lower': [0., 0., 0.], 'variable_upper': [500., 200., 400.],
             'kinds': ['continuous'] * 3, 'matrix': {'indptr': [0, 3], 'indices': [0, 1, 2], 'values': [1., 1., 1.]},
             'row_lower': [400.], 'row_upper': [400.]}
    path = c.out / 'specs/dispatch.json'; write(path, model)
    r = c.run('energy-one-hour-lp', 'lp-ip', 'lp-ip.solve/1', {'model_input': 'model', 'starts': [None],
              'node_limit': 1000, 'iteration_limit': 10000, 'feasibility_tolerance': 1e-7,
              'integrality_tolerance': 1e-7, 'presolve': True},
              [{'name': 'model', 'file': 'dispatch.json', 'sha256': digest(path)}])
    o = outcome(r)
    assert o['claim'] == 'numerical_optimum' and math.isclose(o['objective'], 50., abs_tol=1e-6), o
    assert all(math.isclose(a, b, abs_tol=1e-6) for a, b in zip(o['x'], [200., 200., 0.])), o


def curve_fit(c):
    for repo, worker, exe, filename, expected in [
            ('fcmaes-rust', 'curve-fit', 'fcmaes-curve-worker', 'exponential-fit.json', 'best_found'),
            ('SQP-craft', 'sqp-curve-fit', 'sqp-curve-worker', 'decay-fit.json', 'first_order')]:
        c.register(worker, exe)
        original = c.args.sources / repo / 'tutorials/job-api'
        spec = json.loads((original / filename).read_text())
        inputs = []
        for i in spec['inputs']:
            dest = c.out / 'specs' / (worker + '-' + i['file'])
            shutil.copy2(original / i['file'], dest)
            inputs.append({**i, 'file': dest.name, 'sha256': digest(dest)})
        r = c.run(worker, worker, spec['payload_schema'], spec['payload'], inputs)
        o = best(r)
        assert o['claim'] == expected, o
        rows = [tuple(map(float, l.split(','))) for l in (c.out / 'specs' / inputs[0]['file']).read_text().splitlines()[1:] if l.strip()]
        a, b, offset = o['x']
        loss = sum((a * math.exp(-b*t) + offset-y)**2 for t, y in rows)
        # The two original model definitions deliberately differ: SQP uses
        # half the sum of squares; fcmaes uses the full sum of squares.
        if worker.startswith('sqp'):
            loss *= .5
        assert math.isclose(loss, o['objective'], rel_tol=1e-7, abs_tol=1e-9), (loss, o)
        if worker.startswith('sqp'):
            anchor = next(y for t, y in rows if t == 1.)
            assert abs(a * math.exp(-b) + offset - anchor) <= 1e-7
        import matplotlib.pyplot as plt
        ts = [t for t, _ in rows]
        fig, ax = plt.subplots(); ax.scatter(ts, [y for _, y in rows], label='Data')
        ax.plot(ts, [a*math.exp(-b*t)+offset for t in ts], label='Fit'); ax.legend(); ax.set(xlabel='t', ylabel='y')
        fig.savefig(c.out / (worker + '.png'), dpi=150); plt.close(fig)


def gtoc1(c):
    c.register('gtoc1', 'gtoc1-job-worker')
    # These fixed smoke candidates test plumbing; they are not an
    # agent-vs-random study. Each route gets its own derived bounds below.
    routes = [[3, 2, 3, 5, 10], [3, 3, 2, 5, 10]]
    scores = []
    for i, bodies in enumerate(routes):
        p = c.problem('gtoc1', 'app.gtoc1.mga')
        p['parameters']['bodies'] = bodies
        # Bounds are route dependent. Query a helper generated by the worker's
        # standalone route-card example rather than guessing them.
        card = json.loads(command([c.args.bin_dir / 'gtoc1-route-card', ','.join(map(str, bodies))]))
        p['config']['dimension'] = len(bodies)
        p['bounds'] = {'lower': card['lower'], 'upper': card['upper'], 'broadcast': False}
        base = c.evaluate(f'gtoc1-{i}-baseline', 'gtoc1', p, [card['guess']])
        r = c.retry(f'gtoc1-{i}-search', 'gtoc1', p, 128 * c.args.budget_scale, card['guess'])
        incumbent = min([best(base), best(r)], key=lambda o: o['objective'])
        c.evaluate(f'gtoc1-{i}-recheck', 'gtoc1', p, [incumbent['x']])
        scores.append({'bodies': bodies, 'objective': incumbent['objective'], 'mga_score': -incumbent['objective']})
    write(c.out / 'route-portfolio.json', {'claim': 'MGA screening only', 'protocol': 'generic-biteopt-retry', 'routes': scores})


def branin_value(x):
    return (x[1] - 5.1*x[0]**2/(4*math.pi**2) + 5*x[0]/math.pi - 6)**2 + 10*(1 - 1/(8*math.pi))*math.cos(x[0]) + 10


def oscillator_position(damping, stiffness, t):
    """Independent analytic ODE solution, used only for validation and plotting."""
    a = damping / 2
    w = cmath.sqrt(stiffness - a*a)
    shape = 1 + a*t if abs(w) < 1e-12 else cmath.cos(w*t) + a*cmath.sin(w*t)/w
    return (cmath.exp(-a*t) * shape).real


def surrogate(c):
    c.register('surrogate', 'fcmaes-job-worker')
    c.register('surrogate-simulation', 'surrogate-simulation-worker')
    original = c.args.sources / 'fcmaes-rust/tutorials/surrogate'
    p = json.loads((original / 'branin.json').read_text())['payload']
    p.update(seed=c.args.seed, concurrent=min(c.args.cores, 2), evaluation_threads=1)
    threads = min(c.args.cores, 8)
    cold = c.run('surrogate-branin', 'surrogate', 'fcmaes.surrogate/1', p,
                 parallel='inner', inner_threads=threads)
    data, history = c.surrogate_artifacts('surrogate-branin', 'surrogate', cold)
    assert cold['work']['evaluations'] == 48 and len(history['observations']) == 48
    assert math.isclose(branin_value(best(cold)['x']), best(cold)['objective'], abs_tol=1e-10)
    previous = c.out / 'specs/surrogate-previous.json'
    previous.write_bytes(data)
    warm_payload = copy.deepcopy(p)
    warm_payload.update(evaluations=8, warm_start={'input': 'previous'})
    warm = c.run('surrogate-warm', 'surrogate', 'fcmaes.surrogate/1', warm_payload,
                 [{'name': 'previous', 'file': previous.name, 'sha256': digest(previous)}],
                 parallel='inner', inner_threads=threads)
    _, combined = c.surrogate_artifacts('surrogate-warm', 'surrogate', warm)
    assert warm['work']['evaluations'] == 8 and outcome(warm)['details']['warm_start_points'] == 48
    assert len(combined['observations']) == 56
    assert combined['observations'][:48] == history['observations']
    assert best(warm)['objective'] <= best(cold)['objective'] + 1e-12
    assert math.isclose(branin_value(best(warm)['x']), best(warm)['objective'], abs_tol=1e-10)

    sim = json.loads((original / 'oscillator.json').read_text())['payload']
    sim.update(seed=c.args.seed, concurrent=1, evaluation_threads=min(2, c.args.cores))
    fitted = c.run('surrogate-oscillator', 'surrogate-simulation', 'fcmaes.surrogate/1', sim,
                   parallel='inner', inner_threads=threads)
    c.surrogate_artifacts('surrogate-oscillator', 'surrogate-simulation', fitted)
    baseline = c.run('surrogate-biteopt', 'surrogate-simulation', 'fcmaes.retry/1', {
        'problem': sim['problem'], 'optimizer': {'kind': 'biteopt', 'parameters': {}},
        'seed': c.args.seed, 'retries': 1, 'evaluations_per_retry': 32, 'evaluation_limit_mode': 'hard'})
    assert fitted['work']['evaluations'] == baseline['work']['evaluations'] == 32
    points = [best(fitted)['x'], best(baseline)['x'], [.4, 2.3]]
    checked = c.evaluate('surrogate-oscillator-recheck', 'surrogate-simulation', sim['problem'], points)
    for record, x in zip(checked['results'], points):
        o = record['outcome']
        analytic = sum(((1 + .1*i) * (oscillator_position(*x, j/2) - oscillator_position(.4, 2.3, j/2)))**2
                       for i in range(4) for j in range(1, 9)) / 32
        assert math.isclose(analytic, o['objective'], rel_tol=1e-6, abs_tol=1e-9), (analytic, o)
    assert checked['results'][-1]['outcome']['objective'] <= 1e-14
    write(c.out / 'surrogate-summary.json', {
        'branin_cold': best(cold), 'branin_warm': best(warm),
        'new_calls': {'branin': 48, 'warm': 8, 'oscillator_gp': 32, 'oscillator_biteopt': 32},
        'retained_observations': 48, 'combined_observations': 56,
        'oscillator_gp': best(fitted), 'oscillator_biteopt': best(baseline),
        'scope': 'One-seed budget-matched pilot; warm observations initialize a new optimizer state'})
    import matplotlib.pyplot as plt
    values = [v['value']['value'] for v in combined['observations'] if v['value']['kind'] == 'finite']
    running = list(itertools.accumulate(values, min))
    fig, ax = plt.subplots()
    ax.plot(range(1, len(running)+1), running)
    ax.axvline(48.5, color='grey', linestyle='--', label='Warm job starts')
    ax.set(xlabel='Completed observations (48 retained + 8 new)', ylabel='Best observed Branin value')
    ax.legend(); fig.tight_layout(); fig.savefig(c.out / 'surrogate-history.png', dpi=150); plt.close(fig)
    ts = [i/50 for i in range(201)]
    fig, ax = plt.subplots()
    for x, label in [([.4, 2.3], 'Reference'), (points[0], 'Surrogate'), (points[1], 'BiteOpt')]:
        ax.plot(ts, [oscillator_position(*x, t) for t in ts], label=label)
    ax.set(xlabel='Time', ylabel='Displacement, unit initial amplitude')
    ax.legend(); fig.tight_layout(); fig.savefig(c.out / 'surrogate-oscillator.png', dpi=150); plt.close(fig)


def lp_ip(c):
    c.register('lp-ip', 'lp-ip-job-worker')
    capacity = c.args.lp_capacity
    weights, profits = [6., 5., 4.], [9., 8., 7.]
    model = {'schema_version': 'lp-ip.model/1', 'sense': 'maximize', 'objective': profits,
             'objective_offset': 0., 'variable_lower': [0.]*3, 'variable_upper': [1.]*3,
             'kinds': ['binary']*3, 'matrix': {'indptr': [0, 3], 'indices': [0, 1, 2], 'values': weights},
             'row_lower': [None], 'row_upper': [capacity]}
    original = json.loads((c.args.sources / 'LP-IP-craft/tutorials/job-api/assignment-mip.json').read_text())['payload']
    def submit(name, m, starts):
        inputs = c.model_input('lp-ip', name+'-model.json', m, 'lp-ip.model/1')
        p = {**original, 'starts': starts}
        return c.run(name, 'lp-ip', 'lp-ip.solve/1', p, inputs), inputs
    relaxation = copy.deepcopy(model); relaxation['kinds'] = ['continuous']*3
    lp, _ = submit('lp-ip-relaxation', relaxation, [None])
    # A simple density-greedy feasible candidate, not the enumeration oracle.
    greedy, remaining = [0.]*3, capacity
    for i in sorted(range(3), key=lambda j: profits[j]/weights[j], reverse=True):
        if weights[i] <= remaining:
            greedy[i] = 1.; remaining -= weights[i]
    mip, inputs = submit('lp-ip-integer', model, [None, greedy])
    feasible = [list(x) for x in itertools.product((0, 1), repeat=3) if sum(a*b for a,b in zip(weights,x)) <= capacity]
    integer_optimum = max(sum(a*b for a,b in zip(profits,x)) for x in feasible)
    # Fractional-knapsack oracle for this one-row continuous relaxation only.
    remaining, lp_oracle = capacity, 0.
    for i in sorted(range(3), key=lambda j: profits[j]/weights[j], reverse=True):
        portion = min(1., remaining/weights[i]); lp_oracle += portion*profits[i]; remaining -= portion*weights[i]
    for result, expected in [(lp, lp_oracle), (mip, integer_optimum)]:
        for record in result['results']:
            o = record['outcome']; x = o['x']
            assert o['claim'] == 'numerical_optimum' and o['objective_bounds']['sense'] == 'maximize', o
            assert math.isclose(o['objective'], expected, abs_tol=1e-7), o
            assert math.isclose(sum(a*b for a,b in zip(profits,x)), o['objective'], abs_tol=1e-7)
            assert sum(a*b for a,b in zip(weights,x)) <= capacity + 1e-7
            assert all(-1e-7 <= v <= 1+1e-7 for v in x)
            if result is mip:
                assert all(abs(v-round(v)) <= 1e-7 for v in x)
            assert math.isclose(o['objective_bounds']['dual'], expected, abs_tol=1e-7)
    points = [outcome(mip)['x'], outcome(lp)['x'], [1., 1., 1.]]
    check = c.run('lp-ip-point-check', 'lp-ip', 'lp-ip.evaluate/1', {
        'model_input': 'model', 'points': points, 'feasibility_tolerance': 1e-7, 'integrality_tolerance': 1e-7}, inputs)
    for r, x in zip(check['results'], points):
        valid = all(abs(v-round(v)) <= 1e-7 for v in x) and sum(a*b for a,b in zip(weights,x)) <= capacity + 1e-7
        assert r['outcome']['feasible'] == valid
        assert r['outcome']['claim'] == ('feasible' if valid else 'none')
    impossible = copy.deepcopy(model)
    impossible['variable_lower'] = [1., 1., 1.]
    bad_inputs = c.model_input('lp-ip', 'lp-ip-impossible-model.json', impossible, 'lp-ip.model/1')
    bad = c.run('lp-ip-infeasible', 'lp-ip', 'lp-ip.solve/1', {**original, 'starts': [None]},
                bad_inputs, allowed_claimed=('infeasible',))
    assert outcome(bad)['claim'] == 'infeasible' and sum(weights) > capacity
    write(c.out / 'lp-ip-summary.json', {'capacity': capacity, 'costs': weights, 'values': profits,
          'lp': outcome(lp), 'mip': outcome(mip), 'greedy_start': greedy,
          'enumerated_feasible_choices': feasible, 'enumerated_optimum': integer_optimum,
          'fractional_oracle': lp_oracle, 'relaxation_gap': lp_oracle-integer_optimum,
          'infeasibility': outcome(bad), 'infeasibility_reason': 'All three selections require 15 units, above the capacity'})
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    ax.bar([i-.18 for i in range(3)], outcome(lp)['x'], width=.36, label='LP relaxation')
    ax.bar([i+.18 for i in range(3)], outcome(mip)['x'], width=.36, label='Binary decision')
    ax.set(xticks=range(3), xticklabels=['A (6, 9)', 'B (5, 8)', 'C (4, 7)'],
           xlabel='Project (cost, value)', ylabel='Selected fraction', ylim=(0, 1.15))
    ax.legend(); fig.tight_layout(); fig.savefig(c.out / 'lp-ip-allocation.png', dpi=150); plt.close(fig)


def sqp(c):
    c.register('sqp', 'sqp-job-worker')
    original = c.args.sources / 'SQP-craft/tutorials/job-api'
    n = c.args.sqp_dimension
    uniform, corner = [1/n]*n, [1.] + [0.]*(n-1)
    starts = [uniform, corner, [(i+1)/(n*(n+1)/2) for i in range(n)], [0.]*n]
    template = json.loads((original / 'simplex.json').read_text())['payload']
    summaries = {}
    for backend in ('active_set', 'clarabel'):
        p = {**template, 'dimension': n, 'starts': starts, 'backend': backend}
        result = c.run('sqp-simplex-'+backend, 'sqp', 'sqp.solve/1', p)
        for r in result['results']:
            o = r['outcome']; x = o['x']
            assert o['claim'] == 'first_order' and 'kkt' in o['evidence']['checks'], o
            assert abs(sum(x)-1) <= p['feasibility_tolerance']
            assert all(-1e-7 <= v <= 1+1e-7 for v in x)
            assert math.isclose(sum(v*v for v in x), o['objective'], abs_tol=1e-10)
            assert math.isclose(o['objective'], 1/n, abs_tol=1e-7)
            # At this interior solution, equality stationarity is g = lambda*1.
            assert max(abs(2*v-2/n) for v in x) <= p['stationarity_tolerance']
        summaries[backend] = [r['outcome'] for r in result['results']]
    points = [uniform, corner, [0.]*n]
    evaluated = c.run('sqp-feasibility', 'sqp', 'sqp.evaluate/1', {
        'problem': 'benchmark.simplex', 'dimension': n, 'points': points, 'feasibility_tolerance': 1e-7})
    assert [r['outcome']['claim'] for r in evaluated['results']] == ['feasible', 'feasible', 'none']
    p = json.loads((original / 'rosenbrock.json').read_text())['payload']
    p['starts'] = [[-1.2, 1.], [0., 0.], [2., 2.], [-1., -1.]]
    nonconvex = c.run('sqp-rosenbrock', 'sqp', 'sqp.solve/1', p)
    audit = []
    for r in nonconvex['results']:
        o = r['outcome']; a, b = o['x']
        f = 100*(b-a*a)**2 + (1-a)**2
        gradient = [-400*a*(b-a*a)+2*(a-1), 200*(b-a*a)]
        assert math.isclose(f, o['objective'], abs_tol=1e-10)
        if o['claim'] == 'first_order':
            assert max(map(abs, gradient)) <= p['stationarity_tolerance']
        audit.append({'start': p['starts'][r['task_id']], 'outcome': o, 'recomputed_gradient': gradient})
    c.run('sqp-rosenbrock-recheck', 'sqp', 'sqp.evaluate/1', {
        'problem': 'benchmark.rosenbrock', 'dimension': 2,
        'points': [r['outcome']['x'] for r in nonconvex['results']], 'feasibility_tolerance': 1e-7})
    write(c.out / 'sqp-summary.json', {'dimension': n, 'starts': starts, 'analytic_simplex_optimum': 1/n,
          'simplex': summaries, 'evaluated_points': [r['outcome'] for r in evaluated['results']],
          'rosenbrock': audit, 'scope': 'Known models; first-order evidence is not a general global or second-order certificate'})
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    for backend, values in summaries.items():
        ax.plot(range(1, n+1), values[0]['x'], marker='o', label=backend)
    ax.axhline(1/n, color='grey', linestyle='--', label='Analytic 1/n')
    ax.set(xlabel='Allocation coordinate', ylabel='Optimized allocation', ylim=(0, max(.5, 1.4/n)))
    ax.legend(); fig.tight_layout(); fig.savefig(c.out / 'sqp-allocation.png', dpi=150); plt.close(fig)
    fig, ax = plt.subplots()
    ax.bar(range(1, len(audit)+1), [max(a['outcome']['objective'], 1e-30) for a in audit])
    ax.set(yscale='log', xlabel='Distinct start number', ylabel='Rosenbrock objective (plot floor 1e-30)')
    fig.tight_layout(); fig.savefig(c.out / 'sqp-multistart.png', dpi=150); plt.close(fig)


def rail_traffic(c):
    import importlib.util
    spec = importlib.util.spec_from_file_location('rail_traffic', HERE / 'rail-traffic/rail.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.execute(c, write)


def plot_front(c, name, result, labels, indices=(0, 1)):
    import matplotlib.pyplot as plt
    points = outcome(result)['details'].get('front', [])
    fig, ax = plt.subplots()
    if points:
        ax.scatter([p['objectives'][indices[0]] for p in points], [p['objectives'][indices[1]] for p in points])
    else:
        ax.text(.5, .5, 'No feasible Pareto points at this budget', ha='center', transform=ax.transAxes)
    ax.set(xlabel=labels[0], ylabel=labels[1], title=f'{name}: measured pilot results')
    fig.tight_layout(); fig.savefig(c.out / (name + '-pareto.png'), dpi=150); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'run'])
    parser.add_argument('--sources', type=Path, required=True, help='Parent of the five repository checkouts')
    parser.add_argument('--bin-dir', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, default=Path('target/prompt-tutorials'))
    parser.add_argument('--output', type=Path, default=Path('prompt-results'))
    parser.add_argument('--chapter', choices=['all', *CHAPTERS], default='all',
                        help='Chapter to build or run; all builds/runs the complete series')
    parser.add_argument('--cores', type=int, default=2)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--target-m', type=float, default=35.)
    parser.add_argument('--budget-scale', type=int, default=1, help='1 is a smoke/pilot campaign, not publication quality')
    parser.add_argument('--lp-capacity', type=float, default=10., help='LP/MIP project budget, 0 < capacity < 15')
    parser.add_argument('--sqp-dimension', type=int, default=4, help='Simplex allocation coordinates, 2..32')
    parser.add_argument('--rail-scenario', type=Path, default=HERE / 'rail-traffic/scenario.json',
                        help='Synthetic rail scenario JSON; used only by rail-traffic')
    args = parser.parse_args()
    args.sources = args.sources.resolve(); args.bin_dir = args.bin_dir.resolve()
    if not 1 <= args.cores <= 16 or not 1 <= args.budget_scale <= 100 or not math.isfinite(args.target_m) or args.target_m <= 0:
        parser.error('cores must be 1..16, budget-scale 1..100, target-m finite and positive')
    if not 0 < args.lp_capacity < 15 or not 2 <= args.sqp_dimension <= 32:
        parser.error('lp-capacity must be finite in (0,15); sqp-dimension must be 2..32')
    if args.action == 'build':
        build(args); return
    c = Campaign(args)
    for chapter in CHAPTERS if args.chapter == 'all' else [args.chapter]:
        {'trebuchet': trebuchet, 'production': production, 'energy': energy, 'curve-fit': curve_fit,
         'gtoc1': gtoc1, 'surrogate': surrogate, 'lp-ip': lp_ip, 'sqp': sqp, 'rail-traffic': rail_traffic}[chapter](c)
    report = {'schema_version': 'prompt-tutorial.report/1', 'scope': 'executed pilot; no publication-quality or independent-model claim',
              'seed': args.seed, 'cores': args.cores, 'target_m': args.target_m, 'budget_scale': args.budget_scale,
              'lp_capacity': args.lp_capacity, 'sqp_dimension': args.sqp_dimension,
              'sources': revisions(args.sources), 'jobs': c.jobs,
              'binaries': {p.name: digest(p) for p in args.bin_dir.iterdir() if p.is_file() and os.access(p, os.X_OK)}}
    write(c.out / 'report.json', report)
    files = [p for p in c.out.rglob('*') if p.is_file() and 'node' not in p.relative_to(c.out).parts]
    write(c.out / 'checksums.json', {str(p.relative_to(c.out)): digest(p) for p in sorted(files)})
    print(f'Report: {c.out / "report.json"}')


if __name__ == '__main__':
    main()
