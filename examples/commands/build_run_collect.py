#!/usr/bin/env python3
"""Local build -> verified executable input -> run -> verified binary collection.
Requires a C compiler; does not submit SSH, fleet or campaign work.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runner', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new directory for specs, node and collected files')
    args = parser.parse_args()
    runner = args.runner.resolve()
    base = args.output.resolve()
    base.mkdir(parents=True, exist_ok=False)
    compiler = shutil.which('cc')
    if not compiler:
        raise SystemExit('a C compiler (cc) is required')
    calls = []

    def call(*argv):
        completed = subprocess.run([str(runner), '--root', str(base/'node'), *map(str,argv)],
                                   capture_output=True, text=True, timeout=180, check=True)
        result = json.loads(completed.stdout)
        calls.append({'argv':list(map(str,argv)), 'result':result})
        (base/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')
        return result

    def run(key, argv, inputs, outputs):
        spec = {'schema_version':'execution.command/0.1', 'request_key':key,
                'argv':argv, 'env':{}, 'resources':{'cpu_slots':1},
                'limits':{'wall_seconds':120,'grace_seconds':1}, 'replay':'never',
                'inputs':inputs, 'outputs':outputs}
        path=base/(key+'.json');path.write_text(json.dumps(spec,indent=2)+'\n')
        call('validate','--spec',path)
        job=call('run','--spec',path)
        if job['state']!='completed':raise RuntimeError(job)
        record=call('jobs','execution',job['id'])
        result=call('result',job['directory'])
        assert record['kind']=='command' and result['process']['code']==0
        return job,result

    call('node','init','--capacity',1,'--allow-commands')
    source=b'#include <stdio.h>\nint main(void) { FILE *f=fopen("answer.bin","wb"); unsigned char b[]={0,42,255}; if(!f)return 1; size_t n=fwrite(b,1,3,f); return fclose(f) || n!=3; }\n'
    (base/'program.c').write_bytes(source)
    job,result=run('build',[str(Path(compiler).resolve()),'program.c','-O2','-o','program'],
        [{'path':'program.c','file':'program.c','sha256':hashlib.sha256(source).hexdigest(),'bytes':len(source)}],
        [{'name':'program','path':'program','max_bytes':1048576,'required':True}])
    artifact=result['outputs']['program'];program=base/'program'
    call('jobs','collect',job['id'],'program','--destination',program)
    call('files','put','--source',program,'--sha256',artifact['sha256'],'--bytes',artifact['bytes'])
    job,result=run('execute',['./bin/program'],
        [{'path':'bin/program','sha256':artifact['sha256'],'bytes':artifact['bytes'],'executable':True}],
        [{'name':'answer','path':'answer.bin','max_bytes':3,'required':True}])
    answer=base/'answer.bin'
    call('jobs','collect',job['id'],'answer','--destination',answer)
    assert answer.read_bytes()==b'\x00\x2a\xff'
    summary={'status':'passed','answer_hex':answer.read_bytes().hex(),
             'output':str(answer),'command_jobs':2,'calls':len(calls)}
    (base/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
