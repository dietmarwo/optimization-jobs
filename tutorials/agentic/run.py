#!/usr/bin/env python3
"""Build or execute the five prompt tutorials with retained specs and results.

Requires Python 3.10+, jsonschema and matplotlib; Linux/Rust 1.88+ for builds.
The agent chooses and interprets experiments; this driver handles reproducibility.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CHAPTERS = ('trebuchet', 'production', 'energy', 'curve-fit', 'gtoc1')
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
    for name, exe in TUTORIALS.values():
        cargo(args.sources / 'fcmaes-rust/tutorials' / name, ['--features', 'job-worker'],
              [(exe, exe)] + ([(name, name)] if name == 'rapier-trebuchet' else [])
              + ([('gtoc1-route-card', 'gtoc1-route-card')] if name == 'gtoc1-route-search' else []))
    for repo, package, dest in [('fcmaes-rust', 'fcmaes-job-worker', 'fcmaes-curve-worker'),
                                ('SQP-craft', 'sqp-job-worker', 'sqp-curve-worker')]:
        cargo(args.sources / repo, ['-p', package, '--example', 'custom_worker'],
              [('examples/custom_worker', dest)])
    cargo(args.sources / 'LP-IP-craft', ['-p', 'lp-ip-job-worker'], [('lp-ip-job-worker', 'lp-ip-job-worker')])
    manifest = {'source_revisions': revisions(args.sources),
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

    def run(self, name, worker, profile, payload, inputs=None, parallel='outer'):
        cpus = self.args.cores
        resources = {'cpu_slots': cpus, 'outer_workers': cpus if parallel == 'outer' else 1,
                     'inner_threads': 1 if parallel == 'outer' else cpus}
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
        for record in result['results']:
            outcome = record['outcome']
            if outcome['evidence'].get('refuted'):
                raise AssertionError(f'{name}: a numerical claim was refuted')
            if outcome['claim'] != 'none' and outcome['evidence']['level'] != 'rechecked':
                raise AssertionError(f'{name}: unverified numerical claim')
        write(self.out / 'results' / (name + '.json'), result)
        self.jobs.append({'name': name, 'profile': profile, 'worker': worker,
                          'seconds': time.monotonic() - started, 'work': result['work'],
                          'claims': [r['outcome']['claim'] for r in result['results']],
                          'spec': f'specs/{name}.json', 'result': f'results/{name}.json'})
        print(f'{name}: completed; claims={self.jobs[-1]["claims"]}', flush=True)
        return result

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
    parser.add_argument('--chapter', choices=['all', *CHAPTERS], default='all')
    parser.add_argument('--cores', type=int, default=2)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--target-m', type=float, default=35.)
    parser.add_argument('--budget-scale', type=int, default=1, help='1 is a smoke/pilot campaign, not publication quality')
    args = parser.parse_args()
    args.sources = args.sources.resolve(); args.bin_dir = args.bin_dir.resolve()
    if not 1 <= args.cores <= 16 or not 1 <= args.budget_scale <= 100 or not math.isfinite(args.target_m) or args.target_m <= 0:
        parser.error('cores must be 1..16, budget-scale 1..100, target-m finite and positive')
    if args.action == 'build':
        build(args); return
    c = Campaign(args)
    for chapter in CHAPTERS if args.chapter == 'all' else [args.chapter]:
        {'trebuchet': trebuchet, 'production': production, 'energy': energy, 'curve-fit': curve_fit, 'gtoc1': gtoc1}[chapter](c)
    report = {'schema_version': 'prompt-tutorial.report/1', 'scope': 'executed pilot; no publication-quality or independent-model claim',
              'seed': args.seed, 'cores': args.cores, 'target_m': args.target_m, 'budget_scale': args.budget_scale,
              'sources': revisions(args.sources), 'jobs': c.jobs,
              'binaries': {p.name: digest(p) for p in args.bin_dir.iterdir() if p.is_file() and os.access(p, os.X_OK)}}
    write(c.out / 'report.json', report)
    files = [p for p in c.out.rglob('*') if p.is_file() and 'node' not in p.relative_to(c.out).parts]
    write(c.out / 'checksums.json', {str(p.relative_to(c.out)): digest(p) for p in sorted(files)})
    print(f'Report: {c.out / "report.json"}')


if __name__ == '__main__':
    main()
