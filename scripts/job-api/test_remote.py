#!/usr/bin/env python3
"""Real local helper/lifecycle with explicitly simulated SSH and user manager."""
import copy,hashlib,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from test_review import RUN,FAKE,proc_entry,SCHEMAS,jsonschema
from test_commands import command
FIXTURES=Path(__file__).resolve().parent/'remote-fixtures'

def digest(data):return hashlib.sha256(data).hexdigest()
class Remote(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.base=Path(tmp.name)
        self.root=self.base/'coordinator';self.nodes=[self.base/'node A;literal',self.base/'node-B'];self.counter=0
        self.env=dict(os.environ,PATH=str(FIXTURES)+os.pathsep+os.environ['PATH'],REMOTE_FIXTURE_LOG=str(self.base/'calls.jsonl'),REMOTE_MANAGER_LOG=str(self.base/'units.jsonl'))
        self.children=[];self.addCleanup(self.cleanup)
        self.known=self.base/'known_hosts';self.known.write_text('fixture only\n')
        for i,node in enumerate(self.nodes):
            self.call('node','init','--capacity','2','--allow-commands',root=node)
            self.call('workers','add','--id','fake','--executable',FAKE,root=node)
            self.add_node('a' if i==0 else 'b',node)
    def raw(self,*args,root=None,env=None):
        return subprocess.run([str(RUN),'--root',str(root or self.root),*map(str,args)],env=env or self.env,capture_output=True,text=True,timeout=20)
    def call(self,*args,**kw):
        p=self.raw(*args,**kw);self.assertEqual(p.returncode,0,p.stderr);value=json.loads(p.stdout)
        schema={'execution.node/0.1':'execution.node-0.1.schema.json','execution.fleet.job/0.1':'execution.fleet.job-0.1.schema.json'}.get(value.get('schema_version')) if isinstance(value,dict) else None
        if schema:
            self.assertIsNotNone(jsonschema,'jsonschema is required for remote contracts')
            jsonschema.Draft202012Validator(json.loads((SCHEMAS/schema).read_text())).validate(value)
        return value
    def error(self,*args,**kw):
        p=self.raw(*args,**kw);self.assertEqual(p.returncode,2,p.stdout);return json.loads(p.stderr.splitlines()[-1])['error']
    def add_node(self,name,node,**kw):
        return self.call('fleet','nodes','add',name,'--host','fixture.example','--user','research','--remote-root',node,'--helper',RUN,'--known-hosts',self.known,'--timeout-seconds',3,**kw)
    def write(self,spec):
        self.counter+=1;spec=copy.deepcopy(spec);spec['request_key']=f'remote-{self.counter}'
        path=self.base/f'spec-{self.counter}.json';path.write_text(json.dumps(spec));return path,digest(spec['request_key'].encode())[:32]
    def submit(self,spec,node='a',env=None):
        path,id=self.write(spec);return self.call('fleet','submit','--node',node,'--spec',path,env=env),path,id
    def wait(self,condition,timeout=12):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=condition()
            if value:return value
            time.sleep(.02)
        self.fail('condition timed out')
    def finished(self,id):
        return self.wait(lambda:(x:=self.call('fleet','reconcile',id))['phase']=='finished' and x)
    def units(self):
        path=self.base/'units.jsonl';return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    def cleanup(self):
        for node in self.nodes:
            for path in node.glob('jobs/*/worker-process.json'):
                try:os.killpg(json.loads(path.read_text())['pgid'],signal.SIGKILL)
                except (ProcessLookupError,FileNotFoundError):pass
        for row in self.units():
            try:
                if b'optimization-run' in (proc_entry(row['pid'])/'cmdline').read_bytes():os.killpg(row['pid'],signal.SIGKILL)
            except (ProcessLookupError,AssertionError,FileNotFoundError):pass
        for child in self.children:
            if child.poll() is None:child.kill()
            try:child.communicate(timeout=3)
            except subprocess.TimeoutExpired:pass
        for name in ['pause-submit','pause-download','pause-put']:
            (self.base/name).with_suffix('.go').touch()
    def test_discovery_identity_and_launcher_gate(self):
        a=self.call('fleet','nodes','probe','a');b=self.call('fleet','nodes','probe','b')
        self.assertNotEqual(a['node_id'],b['node_id']);self.assertEqual(a['protocol'],'execution.remote/0.1')
        spec=command();spec['resources']['cpu_slots']=1;path,id=self.write(spec)
        env=dict(self.env,REMOTE_NO_LINGER='1')
        self.assertEqual(self.error('fleet','submit','--node','a','--spec',path,env=env)['code'],'durable_launcher_unavailable')
        self.assertFalse((self.root/'fleet/jobs'/id).exists());self.assertFalse(self.units())
        node=json.loads((self.nodes[0]/'node.json').read_text());node['node_id']='f'*64;(self.nodes[0]/'node.json').write_text(json.dumps(node))
        self.assertEqual(self.error('fleet','nodes','probe','a')['code'],'node_identity_mismatch')
    def test_literal_command_binary_collection_and_idempotency(self):
        code="from pathlib import Path; import sys; assert sys.argv[1]=='$(touch forbidden); *'; Path('result').write_bytes(bytes(range(256)))"
        spec=command([sys.executable,'-c',code,'$(touch forbidden); *']);spec['resources']['cpu_slots']=1
        spec['outputs']=[{'name':'answer','path':'result','max_bytes':256,'required':True}]
        job,path,id=self.submit(spec);self.assertEqual(job['node_name'],'a');job=self.finished(id)
        record=self.call('fleet','execution',id);self.assertEqual(record['kind'],'command');self.assertEqual(job['remote_identity'],record['identity'])
        dest=self.base/'answer.bin';self.call('fleet','collect',id,'--kind','output','--name','answer','--destination',dest)
        self.assertEqual(dest.read_bytes(),bytes(range(256)));self.assertFalse((self.base/'forbidden').exists())
        self.call('fleet','collect',id,'--kind','output','--name','answer','--destination',dest)
        self.call('fleet','submit','--node','a','--spec',path);self.assertEqual(len(self.units()),1)
        self.assertEqual(self.error('fleet','submit','--node','b','--spec',path)['code'],'request_key_conflict')
        native=self.base/'result.json';self.call('fleet','collect',id,'--destination',native);self.assertEqual(json.loads(native.read_text())['process']['code'],0)
    def test_optimizer_inputs_and_native_artifact(self):
        from test_review import envelope
        spec=envelope('fake',{'mode':'complete'});spec['resources']={'cpu_slots':1,'outer_workers':1,'inner_threads':1}
        data=b'{"model":"declared"}';(self.base/'model').write_bytes(data)
        spec['inputs']=[{'name':'model','file':'model','sha256':digest(data)}]
        _,_,id=self.submit(spec);self.finished(id)
        native=self.base/'run.json';self.call('fleet','collect',id,'--destination',native)
        result=json.loads(native.read_text());self.assertEqual(result['schema_version'],'optimization.result/0.2')
        dest=self.base/'records';self.call('fleet','collect',id,'--kind','artifact','--name','results','--destination',dest)
        self.assertGreater(dest.stat().st_size,0)
    def test_lost_ack_is_reconciled_without_second_launch(self):
        spec=command();spec['resources']['cpu_slots']=1;path,id=self.write(spec)
        env=dict(self.env,REMOTE_DROP_ACK=str(self.base/'dropped'))
        self.assertEqual(self.error('fleet','submit','--node','a','--spec',path,env=env)['code'],'start_unknown')
        state=self.call('fleet','get',id);self.assertEqual(state['phase'],'unknown')
        self.finished(id);self.call('fleet','submit','--node','a','--spec',path)
        self.assertEqual(len(self.units()),1)
    def test_launch_failure_stays_uncertain_and_does_not_replay(self):
        spec=command();spec['resources']['cpu_slots']=1;path,id=self.write(spec)
        state=self.call('fleet','submit','--node','a','--spec',path,env=dict(self.env,REMOTE_FAIL_START='1'))
        self.assertEqual(state['phase'],'unknown');self.call('fleet','resume',id);self.call('fleet','reconcile',id)
        self.assertFalse(self.units())
        self.assertEqual(self.error('fleet','submit','--node','b','--spec',path)['code'],'request_key_conflict')
    def test_coordinator_death_during_dispatch(self):
        spec=command();spec['resources']['cpu_slots']=1;path,id=self.write(spec);pause=self.base/'pause-submit'
        process=subprocess.Popen([str(RUN),'--root',str(self.root),'fleet','submit','--node','a','--spec',str(path)],env=dict(self.env,REMOTE_PAUSE_SUBMIT=str(pause)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.children.append(process);self.wait(pause.exists);process.kill();process.communicate(timeout=3)
        self.assertEqual(self.call('fleet','reconcile',id)['phase'],'unknown');pause.with_suffix('.go').touch()
        self.finished(id);self.assertEqual(len(self.units()),1)
    def test_collection_transfer_retry_never_submits(self):
        spec=command([sys.executable,'-c',"from pathlib import Path; Path('out').write_bytes(b'hello')"]);spec['resources']['cpu_slots']=1
        spec['outputs']=[{'name':'out','path':'out','max_bytes':5,'required':True}]
        _,_,id=self.submit(spec);self.finished(id);dest=self.base/'download'
        self.error('fleet','collect',id,'--kind','output','--name','out','--destination',dest,env=dict(self.env,REMOTE_TRUNCATE='1'))
        self.assertFalse(dest.exists());self.call('fleet','collect',id,'--kind','output','--name','out','--destination',dest)
        self.assertEqual(dest.read_bytes(),b'hello');self.assertEqual(len(self.units()),1)
    def test_coordinator_death_during_collection(self):
        spec=command();spec['resources']['cpu_slots']=1;_,_,id=self.submit(spec);self.finished(id)
        dest=self.base/'native';pause=self.base/'pause-download'
        process=subprocess.Popen([str(RUN),'--root',str(self.root),'fleet','collect',id,'--destination',str(dest)],env=dict(self.env,REMOTE_PAUSE_DOWNLOAD=str(pause)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.children.append(process);self.wait(pause.exists);process.kill();process.communicate(timeout=3)
        self.assertFalse(dest.exists());self.call('fleet','collect',id,'--destination',dest);pause.with_suffix('.go').touch()
        self.assertEqual(json.loads(dest.read_text())['state'],'completed');self.assertEqual(len(self.units()),1)
    def test_staging_can_resume_from_snapshot_after_client_loss(self):
        data=b'explicit data';(self.base/'data').write_bytes(data)
        spec=command([sys.executable,'-c',"from pathlib import Path; assert Path('data').read_bytes()==b'explicit data'"]);spec['resources']['cpu_slots']=1
        spec['inputs']=[{'path':'data','file':'data','sha256':digest(data),'bytes':len(data)}]
        path,id=self.write(spec);pause=self.base/'pause-put'
        process=subprocess.Popen([str(RUN),'--root',str(self.root),'fleet','submit','--node','a','--spec',str(path)],env=dict(self.env,REMOTE_PAUSE_PUT=str(pause)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.children.append(process);self.wait(pause.exists);process.kill();process.communicate(timeout=3)
        (self.base/'data').unlink();self.assertEqual(self.call('fleet','reconcile',id)['phase'],'staging');pause.with_suffix('.go').touch()
        self.call('fleet','resume',id);self.finished(id);self.assertEqual(len(self.units()),1)
    def test_protocol_timeout_and_invalid_helper(self):
        self.assertEqual(self.error('fleet','nodes','probe','a',env=dict(self.env,REMOTE_BAD_PROTOCOL='1'))['code'],'remote_protocol')
        self.assertEqual(self.error('fleet','nodes','probe','a',env=dict(self.env,REMOTE_STALL='1'))['code'],'remote_transport')
        self.assertEqual(self.error('fleet','nodes','add','bad','--host','fixture.example','--user','research','--remote-root',self.nodes[0],'--helper','/tmp/helper;touch /tmp/forbidden','--known-hosts',self.known)['code'],'invalid_remote_node')
    def test_helper_rejects_unknown_fields_and_truncated_put(self):
        identity=self.call('node','identity',root=self.nodes[0])['node_id']
        for operation,body in [({'kind':'lookup','dispatch_id':'a'*64,'unexpected':True},b''),({'kind':'put','bytes':3,'sha256':digest(b'abc')},b'ab')]:
            request={'schema_version':'execution.remote/0.1','root':str(self.nodes[0]),'node_id':identity,'operation':operation}
            raw=subprocess.run([str(RUN),'remote','serve'],input=json.dumps(request).encode()+b'\n'+body,capture_output=True,timeout=10)
            self.assertEqual(raw.returncode,0,raw.stderr)
            response=json.loads(raw.stdout);self.assertIsNotNone(response['error'])
            jsonschema.Draft202012Validator(json.loads((SCHEMAS/'execution.remote-0.1.schema.json').read_text())).validate(response)
        self.assertFalse((self.nodes[0]/'blobs'/digest(b'abc')).exists());self.assertFalse(self.units())

    def test_remote_repair_reuses_the_existing_liveness_guards(self):
        spec=command([sys.executable,'-c','import time; time.sleep(30)'],wall=60);spec['resources']['cpu_slots']=1
        state,_,id=self.submit(spec)
        local=state['remote']['dispatch']['job_id'];directory=self.nodes[0]/'jobs'/local
        self.wait(lambda:(directory/'worker-process.json').exists())
        error=self.error('fleet','repair',id);self.assertEqual((error['code'],error['retryable']),('attempt_active',True))
        os.kill(self.units()[0]['pid'],signal.SIGKILL)
        os.killpg(json.loads((directory/'worker-process.json').read_text())['pgid'],signal.SIGKILL)
        self.wait(lambda:self.call('jobs','get',local,root=self.nodes[0]).get('observed_state')=='launcher_lost')
        repaired=self.call('fleet','repair',id);self.assertEqual(repaired['remote']['job']['state'],'interrupted')
        record=self.call('fleet','execution',id);self.assertEqual(record['source'],'repair');self.assertIsNone(record['observation']['process'])
        self.assertEqual(len(self.units()),1)

    def test_remote_command_opt_in_and_capacity(self):
        self.call('node','commands','--disable',root=self.nodes[0]);spec=command();spec['resources']['cpu_slots']=1;path,_=self.write(spec)
        self.assertEqual(self.error('fleet','submit','--node','a','--spec',path)['code'],'commands_disabled')
        self.call('node','commands','--enable',root=self.nodes[0]);spec['resources']['cpu_slots']=3;path,_=self.write(spec)
        self.assertEqual(self.error('fleet','submit','--node','a','--spec',path)['code'],'capacity_exceeded')

if __name__=='__main__':unittest.main()
