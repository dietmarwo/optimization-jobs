#!/usr/bin/env python3
"""Command/file contracts using real child processes and the shared fake worker."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

from test_review import Node, RUN, envelope, job_id, proc_entry


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(argv=None, wall=30, grace=0.2):
    return {"schema_version": "execution.command/0.1", "request_key": "command",
            "argv": argv or ["/bin/true"], "env": {}, "resources": {"cpu_slots": 8},
            "limits": {"wall_seconds": wall, "grace_seconds": grace},
            "replay": "never", "inputs": [], "outputs": []}


class Commands(Node):
    def setUp(self):
        super().setUp()
        self.call("node", "commands", "--enable")

    def script(self, code, **kw):
        data = code.encode()
        file = self.base / "script.py"
        file.write_bytes(data)
        spec = command([sys.executable, "scripts/run.py"], **kw)
        spec["inputs"] = [{"path": "scripts/run.py", "file": "script.py", "bytes": len(data), "sha256": sha(data)}]
        return spec

    def run_command(self, spec):
        self.validate_record("execution.command-0.1.schema.json", spec)
        path, key = self.write(spec)
        job = self.call("run", "--spec", path)
        result = self.call("result", job["directory"])
        self.validate_record("execution.command.result-0.1.schema.json", result)
        record = self.call("jobs", "execution", job_id(key))
        self.validate_record("execution.record-0.1.schema.json", record)
        self.assertEqual(record["kind"], "command")
        self.assertEqual(record["state"], result["state"])
        self.assertEqual(record["native_result"]["sha256"], sha((Path(job["directory"]) / "command-result.json").read_bytes()))
        for field in ("objective", "feasible", "claim", "work", "requested_tasks"):
            self.assertNotIn(field, result)
        return path, job, result, record

    def test_opt_in_discovery_and_disable(self):
        self.call("node", "commands", "--disable")
        caps = self.call("node", "capabilities")
        self.validate_record("execution.capabilities-0.2.schema.json", caps)
        self.assertFalse(caps["command_jobs"])
        path, _ = self.write(command())
        self.assertEqual(self.error("run", "--spec", path)["code"], "commands_disabled")
        self.call("node", "commands", "--enable")
        self.assertTrue(self.call("node", "doctor")["capabilities"]["command_jobs"])
        self.assertEqual(self.call("run", "--spec", path)["state"], "completed")

    def test_literal_arguments_and_environment(self):
        spec = self.script("import json, os, sys\nprint(json.dumps([sys.argv[1:],os.environ.get('EXPLICIT'),os.environ.get('INHERITED_SECRET')]))")
        args = ["$(touch SHOULD_NOT_EXIST)", "; echo bad", "a b", "*", "'quoted'"]
        spec["argv"] += args
        spec["env"] = {"EXPLICIT": "a;b $HOME"}
        path, _ = self.write(spec)
        value = self.call("run", "--spec", path, env=dict(os.environ, INHERITED_SECRET="do-not-inherit"))
        directory = Path(value["directory"])
        self.assertEqual(json.loads((directory / "stdout.log").read_text()), [args, "a;b $HOME", None])
        self.assertFalse((directory / "work/SHOULD_NOT_EXIST").exists())

    def test_exit_code_signal_and_output_failure(self):
        for argv, state, code, sig in [(["/bin/true"], "completed", 0, None),
                                       ([sys.executable,"-c","raise SystemExit(7)"], "failed", 7, None),
                                       ([sys.executable,"-c","import os,signal; os.kill(os.getpid(),signal.SIGTERM)"], "failed", None, signal.SIGTERM)]:
            with self.subTest(argv=argv):
                _, _, result, record = self.run_command(command(argv))
                self.assertEqual((result["state"],result["process"]), (state,{"code":code,"signal":sig}))
                self.assertEqual(record["observation"]["containment"], "stopped")
        spec = command()
        spec["outputs"] = [{"name":"missing","path":"missing","max_bytes":10,"required":True}]
        _, _, result, _ = self.run_command(spec)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(len(result["output_errors"]), 1)

    def test_binary_outputs_snapshot_and_no_clobber(self):
        spec = self.script("from pathlib import Path\nPath('data.bin').write_bytes(bytes(range(256)))")
        spec["outputs"] = [{"name":"data","path":"data.bin","max_bytes":256,"required":True}]
        _, job, result, _ = self.run_command(spec)
        dest = self.base / "collected.bin"
        self.call("jobs", "collect", job["id"], "data", "--destination", dest)
        self.assertEqual(dest.read_bytes(), bytes(range(256)))
        self.error("jobs", "collect", job["id"], "data", "--destination", dest)
        (Path(job["directory"]) / "work/data.bin").write_bytes(b"later")
        second = self.base / "again.bin"
        self.call("jobs", "collect", job["id"], "data", "--destination", second)
        self.assertEqual(second.read_bytes(), dest.read_bytes())
        self.assertEqual(result["outputs"]["data"]["bytes"], 256)
        (Path(job["directory"]) / ".command-outputs/data").write_bytes(b"tampered")
        self.error("jobs", "collect", job["id"], "data", "--destination", self.base / "bad.bin")
        self.assertFalse((self.base / "bad.bin").exists())
        self.assertEqual(self.error("jobs", "artifact", job["id"], "data")["code"], "unsupported_job_kind")
        self.assertEqual(self.error("compare", job["directory"], job["directory"])["code"], "unsupported_job_kind")

    def test_output_limits_symlinks_and_optional_missing(self):
        for code, maximum in [("from pathlib import Path; Path('data').write_bytes(b'1234')",3),
                              ("import os; os.symlink('/etc/hostname','data')",4096),
                              ("import os; os.mkfifo('data')",4096)]:
            with self.subTest(code=code):
                spec=self.script(code)
                spec["outputs"]=[{"name":"out","path":"data","max_bytes":maximum,"required":True}]
                _,_,result,_=self.run_command(spec)
                self.assertEqual(result["state"],"failed")
                self.assertEqual(result["outputs"],{})
        spec=command();spec["outputs"]=[{"name":"optional","path":"absent","max_bytes":0,"required":False}]
        self.assertEqual(self.run_command(spec)[2]["state"],"completed")

    def test_identity_and_no_replay(self):
        spec=self.script("print('once')")
        path,job,_,record=self.run_command(spec)
        self.assertEqual(self.call("run","--spec",path)["id"],job["id"])
        self.assertEqual(self.call("jobs","execution",job["id"]),record)
        changed=json.loads(path.read_text());changed["env"]={"CHANGED":"1"};path.write_text(json.dumps(changed))
        self.assertEqual(self.error("run","--spec",path)["code"],"request_key_conflict")
        spec=json.loads(path.read_text());spec["env"]={}
        (self.base/"script.py").write_text("print('twice')")
        path.write_text(json.dumps(spec));self.error("validate","--spec",path)
        data=(self.base/"script.py").read_bytes();spec["inputs"][0].update(bytes=len(data),sha256=sha(data));path.write_text(json.dumps(spec))
        self.assertEqual(self.error("run","--spec",path)["code"],"request_key_conflict")

    def test_reject_unsafe_and_unknown_fields(self):
        cases=[]
        for path in ["../outside","/outside","a/../outside","job.json",".execution.json"]:
            spec=command();spec["outputs"]=[{"name":"out","path":path,"max_bytes":10,"required":True}];cases.append(spec)
        for field,value in [("replay","always"),("shell",True),("argv",["true"]),("resources",{"cpu_slots":0})]:
            spec=command();spec[field]=value;cases.append(spec)
        spec=command();spec["outputs"]=[{"name":"x","path":"x","max_bytes":67108865,"required":True}];cases.append(spec)
        spec=command();spec["outputs"]=[{"name":"x","path":"x","max_bytes":1,"required":True},{"name":"y","path":"x/y","max_bytes":1,"required":True}];cases.append(spec)
        for spec in cases:
            with self.subTest(spec=spec):
                path,_=self.write(spec);self.error("validate","--spec",path)
        (self.base/"link.py").symlink_to(self.base/"outside.py")
        (self.base/"outside.py").write_text("print('outside')")
        spec=self.script("print('inside')");spec["inputs"][0]["file"]="link.py"
        path,_=self.write(spec);self.error("validate","--spec",path)

    def test_timeout_and_descendant_cancellation(self):
        code="""import os, signal, time
from pathlib import Path
signal.signal(signal.SIGTERM,signal.SIG_IGN)
child=os.fork()
Path('child' if child==0 else 'parent').write_text(str(os.getpid()))
while True: time.sleep(.05)
"""
        for mode in ["timeout","graceful","immediate"]:
            with self.subTest(mode=mode):
                spec=self.script(code, wall=1 if mode=="timeout" else 30, grace=.2)
                process,ident,directory=self.start(spec)
                self.wait_for(lambda:(directory/"work/child").exists())
                pids=[int((directory/f"work/{name}").read_text()) for name in ["child","parent"]]
                if mode!="timeout": self.call("jobs","cancel",ident,*(["--now"] if mode=="immediate" else []))
                _,err=process.communicate(timeout=8);self.assertEqual(process.returncode,0,err)
                record=self.call("jobs","execution",ident)
                self.assertEqual(record["state"],"timed_out" if mode=="timeout" else "cancelled")
                self.assertEqual(record["observation"]["containment"],"stopped")
                for pid in pids:
                    try: self.assertEqual((proc_entry(pid)/"stat").read_text().split(') ')[1][0],"Z")
                    except (AssertionError,FileNotFoundError):
                        # A missing /proc entry is stopped too; live processes fail below.
                        self.assertFalse(any(p==pid for p,_ in __import__('test_review').processes()))
                self.assertEqual(json.loads((self.root/"slots.json").read_text()),{})

    def test_mixed_admission_and_queued_cancel(self):
        for first_command in [False,True]:
            hold_spec=self.script("import time; time.sleep(30)") if first_command else envelope("fake",{"mode":"sleep"},wall=60)
            hold,hold_id,hold_dir=self.start(hold_spec)
            self.wait_for(lambda:self.state(hold_dir)=="running")
            queued_spec=envelope("fake",{"mode":"complete"}) if first_command else command()
            queued,qid,qdir=self.start(queued_spec)
            self.wait_for(lambda:self.state(qdir)=="waiting")
            self.assertFalse((qdir/"worker-process.json").exists())
            if not first_command:
                self.call("jobs","cancel",qid)
                queued.communicate(timeout=5)
                record=self.call("jobs","execution",qid)
                self.assertEqual((record["state"],record["observation"]["containment"]),("cancelled","not_started"))
            self.call("jobs","cancel",hold_id,"--now")
            hold.communicate(timeout=5);queued.communicate(timeout=5)
            if first_command:self.assertEqual(self.call("jobs","get",qid)["state"],"completed")

    def test_changed_external_executable_before_admission(self):
        hold,hid,hdir=self.start(envelope("fake",{"mode":"sleep"},wall=60))
        self.wait_for(lambda:self.state(hdir)=="running")
        tool=self.base/"tool";tool.write_bytes(Path('/bin/true').read_bytes());tool.chmod(0o700)
        queued,qid,qdir=self.start(command([str(tool)]))
        self.wait_for(lambda:self.state(qdir)=="waiting")
        tool.write_bytes(Path('/bin/false').read_bytes())
        self.call("jobs","cancel",hid,"--now");hold.communicate(timeout=5)
        _,err=queued.communicate(timeout=5);self.assertEqual(queued.returncode,2,err)
        record=self.call("jobs","execution",qid)
        self.assertEqual((record["state"],record["observation"]["containment"]),("failed","not_started"))

    def test_launcher_loss_requires_repair_no_automatic_replay(self):
        process,ident,directory=self.start(self.script("import time; time.sleep(30)"))
        self.wait_for(lambda:(directory/"worker-process.json").exists())
        process.kill();process.communicate(timeout=5)
        self.assertEqual(self.call("jobs","get",ident)["observed_state"],"launcher_lost")
        self.assertEqual(self.error("jobs","repair",ident)["code"],"liveness_unknown")
        os.killpg(json.loads((directory/"worker-process.json").read_text())["pgid"],signal.SIGKILL)
        time.sleep(.1)
        repaired=self.call("jobs","repair",ident)
        self.assertEqual(repaired["state"],"interrupted")
        result=self.call("result",directory)
        self.assertIsNone(result["process"]);self.assertIsNone(result["elapsed_seconds"])
        self.assertEqual(self.error("launch",ident)["code"],"runner_error")
        self.assertEqual(self.error("jobs","repair",ident)["code"],"already_terminal")

    def test_accepted_input_is_rechecked_after_queueing(self):
        hold,hid,hdir=self.start(envelope("fake",{"mode":"sleep"},wall=60))
        self.wait_for(lambda:self.state(hdir)=="running")
        queued,qid,qdir=self.start(self.script("print('original')"))
        self.wait_for(lambda:self.state(qdir)=="waiting")
        (qdir/"work/scripts/run.py").write_text("print('changed')")
        self.call("node","commands","--disable")
        self.call("jobs","cancel",hid,"--now");hold.communicate(timeout=5)
        queued.communicate(timeout=5)
        record=self.call("jobs","execution",qid)
        self.assertEqual((record["state"],record["observation"]["containment"]),("failed","not_started"))
        self.assertFalse((qdir/"worker-process.json").exists())

    def test_command_and_optimization_keys_share_namespace(self):
        path,key=self.write(envelope("fake",{"mode":"complete"}))
        self.call("run","--spec",path)
        spec=command();spec['request_key']=key;path.write_text(json.dumps(spec))
        self.assertEqual(self.error("run","--spec",path)['code'],"request_key_conflict")

    def test_native_result_directories_without_job_metadata(self):
        path,_=self.write(envelope("fake",{"mode":"complete"}))
        job=self.call("run","--spec",path)
        result=self.call("result",job['directory'])
        exported=self.base/'exported';exported.mkdir()
        (exported/'run.json').write_text(json.dumps(result))
        self.assertEqual(self.call("result",exported),result)
        self.call("compare",exported,exported)

    def test_blob_roundtrip_input_and_interrupted_upload(self):
        data=bytes(range(256));source=self.base/'source';source.write_bytes(data);hash_=sha(data)
        self.call('files','put','--source',source,'--bytes',len(data),'--sha256',hash_)
        dest=self.base/'download'
        self.call('files','get',hash_,'--bytes',len(data),'--destination',dest)
        self.assertEqual(dest.read_bytes(),data)
        spec=self.script("from pathlib import Path; assert Path('data').read_bytes()==bytes(range(256))")
        spec['inputs'].append({'path':'data','sha256':hash_,'bytes':len(data)})
        self.assertEqual(self.run_command(spec)[2]['state'],'completed')
        self.assertTrue(self.call('files','put','--source',source,'--bytes',len(data),'--sha256',hash_)['reused'])
        truncated=subprocess.run([str(RUN),'--root',str(self.root),'files','put','--source','-','--bytes','3','--sha256',sha(b'abc')],input=b'ab',capture_output=True,timeout=5)
        self.assertEqual(truncated.returncode,2)
        self.assertFalse((self.root/'blobs'/sha(b'abc')).exists())
        upload=subprocess.Popen([str(RUN),'--root',str(self.root),'files','put','--source','-','--bytes','3','--sha256',sha(b'abc')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            upload.stdin.write(b'a');upload.stdin.flush()
            self.wait_for(lambda:bool(list((self.root/'blobs').glob('.transfer-*'))))
            upload.kill();upload.communicate(timeout=5)
        finally:
            if upload.poll() is None:upload.kill();upload.communicate(timeout=5)
        self.assertFalse((self.root/'blobs'/sha(b'abc')).exists())
        self.assertEqual(self.call('files','cleanup')['removed_partials'],1)
        self.assertTrue((self.root/'blobs'/hash_).exists())


if __name__ == '__main__':
    unittest.main()
