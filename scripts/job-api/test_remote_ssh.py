#!/usr/bin/env python3
"""Real OpenSSH authentication/encryption/disconnect; simulated user manager.
No test here establishes actual systemd, cgroup or home-host durability.
"""
import copy,hashlib,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from test_review import RUN,TARGET,REAL,LP_MODEL,envelope,SCHEMAS,jsonschema
from test_commands import command
SERVER=Path(__file__).resolve().parent/'remote-fixtures/ssh_server.py'
class SSH(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(cls.tmp.name)
        for key in ['host','client']:
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(cls.base/key)],check=True,capture_output=True)
        cls.root=cls.base/'coordinator';cls.node=cls.base/'node root;literal'
        cls.sub('node','init','--capacity','1','--allow-commands',root=cls.node)
        cls.server_log=(cls.base/'server.log').open('w')
        cls.server=subprocess.Popen([sys.executable,str(SERVER),str(cls.base),str(RUN)],stdout=cls.server_log,stderr=subprocess.STDOUT,start_new_session=True)
        cls.wait(lambda:(cls.base/'ready.json').exists())
        cls.port=json.loads((cls.base/'ready.json').read_text())['port']
        cls.sub('fleet','nodes','add','loopback','--host','127.0.0.1','--user','research','--port',cls.port,'--remote-root',cls.node,'--helper',RUN,'--known-hosts',cls.base/'known_hosts','--identity-file',cls.base/'client','--timeout-seconds','15')
    @classmethod
    def sub(cls,*args,root=None,check=True):
        p=subprocess.run([str(RUN),'--root',str(root or cls.root),*map(str,args)],capture_output=True,text=True,timeout=25)
        if check and p.returncode:raise AssertionError(p.stderr)
        return json.loads(p.stdout) if check else p
    @classmethod
    def wait(cls,condition,timeout=20):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            x=condition()
            if x:return x
            time.sleep(.03)
        raise AssertionError('SSH condition timed out')
    @classmethod
    def tearDownClass(cls):
        for path in cls.node.glob('jobs/*/worker-process.json'):
            try:os.killpg(json.loads(path.read_text())['pgid'],signal.SIGKILL)
            except (ProcessLookupError,FileNotFoundError):pass
        if cls.server.poll() is None:cls.server.terminate();cls.server.wait(timeout=5)
        cls.server_log.close();cls.tmp.cleanup()
    def spec(self,key,spec):
        spec=copy.deepcopy(spec);spec['request_key']=key;path=self.base/(key+'.json');path.write_text(json.dumps(spec));return path,hashlib.sha256(key.encode()).hexdigest()[:32]
    def finished(self,id):return self.wait(lambda:(x:=self.sub('fleet','reconcile',id))['phase']=='finished' and x)
    def test_authenticated_binary_roundtrip(self):
        data=bytes(range(256))*4096;(self.base/'data.bin').write_bytes(data)
        spec=command([sys.executable,'-c',"from pathlib import Path; import sys; assert sys.argv[1]=='$(touch marker); *'; Path('out').write_bytes(Path('input').read_bytes())",'$(touch marker); *']);spec['resources']['cpu_slots']=1
        spec['inputs']=[{'path':'input','file':'data.bin','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}]
        spec['outputs']=[{'name':'out','path':'out','max_bytes':len(data),'required':True}]
        path,id=self.spec('ssh-binary',spec);self.sub('fleet','submit','--node','loopback','--spec',path);self.finished(id)
        dest=self.base/'download';self.sub('fleet','collect',id,'--kind','output','--name','out','--destination',dest)
        self.assertEqual(dest.read_bytes(),data)
        record=self.sub('fleet','execution',id);self.assertEqual(record['kind'],'command')
        native=self.base/'native.json';self.sub('fleet','collect',id,'--destination',native);self.assertEqual(json.loads(native.read_text())['state'],'completed')
    def test_real_disconnect_after_simulated_detached_launch(self):
        spec=command([sys.executable,'-c','import time; time.sleep(30)'],wall=60);spec['resources']['cpu_slots']=1
        path,id=self.spec('ssh-disconnect',spec);(self.base/'drop-next-submit').touch()
        p=self.sub('fleet','submit','--node','loopback','--spec',path,check=False)
        self.assertEqual(p.returncode,2,p.stderr);self.assertEqual(json.loads(p.stderr)['error']['code'],'start_unknown')
        observed=self.wait(lambda:(x:=self.sub('fleet','reconcile',id)).get('remote',{}).get('job',{}).get('state')=='running' and x)
        self.assertEqual(observed['phase'],'accepted')
        self.sub('fleet','submit','--node','loopback','--spec',path)
        self.sub('fleet','cancel',id,'--now');self.finished(id)
        units=[json.loads(s) for s in (self.base/'units.jsonl').read_text().splitlines()]
        local_id=observed['remote']['dispatch']['job_id'];self.assertEqual(sum(row['argv'][-1]==local_id for row in units),1)
    def test_real_workers_on_the_explicit_ssh_node(self):
        for name,(binary,_,payload) in REAL.items():
            with self.subTest(worker=name):
                worker=TARGET/binary;self.assertTrue(worker.exists(),f'required worker missing: {worker}')
                self.sub('workers','add','--id',name,'--executable',worker,root=self.node)
                spec=envelope(name,copy.deepcopy(payload));spec['resources']={'cpu_slots':1,'outer_workers':1,'inner_threads':1}
                if name=='lp-ip':
                    (self.base/'model.json').write_bytes(LP_MODEL)
                    spec['inputs']=[{'name':'model','file':'model.json','sha256':hashlib.sha256(LP_MODEL).hexdigest()}]
                path,id=self.spec('ssh-native-'+name,spec)
                self.sub('fleet','submit','--node','loopback','--spec',path);self.finished(id)
                native=self.base/(name+'-run.json');self.sub('fleet','collect',id,'--destination',native)
                value=json.loads(native.read_text());self.assertEqual(value['schema_version'],'optimization.result/0.2')
                jsonschema.Draft202012Validator(json.loads((SCHEMAS/'optimization.result-0.2.schema.json').read_text())).validate(value)
                self.assertTrue(value['runner']['accounting_complete']);self.assertNotEqual(value['results'][0]['outcome']['claim'],'none')

    def test_wrong_host_key_refuses_connection(self):
        known=self.base/'known_hosts';old=known.read_bytes()
        try:
            key=(self.base/'client.pub').read_bytes();known.write_bytes(f'[127.0.0.1]:{self.port} '.encode()+key)
            p=self.sub('fleet','nodes','probe','loopback',check=False)
            self.assertEqual(p.returncode,2,p.stderr);self.assertEqual(json.loads(p.stderr)['error']['code'],'remote_transport')
        finally:known.write_bytes(old)

if __name__=='__main__':unittest.main()
