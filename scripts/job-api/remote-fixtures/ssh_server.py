#!/usr/bin/env python3
"""Disposable authenticated SSH endpoint. The user manager is a named fixture."""
import asyncio,json,os,sys
from pathlib import Path
import asyncssh
base=Path(sys.argv[1]);runner=sys.argv[2];fixtures=Path(__file__).resolve().parent
host=asyncssh.read_private_key(str(base/'host'));client=asyncssh.read_public_key(str(base/'client.pub'))
class Server(asyncssh.SSHServer):
    def begin_auth(self,username):return True
    def public_key_auth_supported(self):return True
    def validate_public_key(self,username,key):return username=='research' and key==client
async def execute(process):
    if process.command!=runner+' remote serve':process.exit(126);return
    data=await process.stdin.read();request=json.loads(data.split(b'\n',1)[0])
    env=dict(os.environ,PATH=str(fixtures)+os.pathsep+os.environ['PATH'],REMOTE_MANAGER_LOG=str(base/'units.jsonl'))
    child=await asyncio.create_subprocess_exec(runner,'remote','serve',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
    out,err=await child.communicate(data)
    drop=base/'drop-next-submit'
    if request['operation']['kind']=='submit' and drop.exists():
        drop.unlink();process.channel.get_connection().abort();return
    process.stdout.write(out);process.stderr.write(err);process.exit(child.returncode)
async def main():
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[host],process_factory=execute,encoding=None)
    port=server.get_port()
    (base/'known_hosts').write_bytes(f'[127.0.0.1]:{port} '.encode()+host.export_public_key('openssh'))
    (base/'ready.json').write_text(json.dumps({'port':port,'server':'AsyncSSH '+asyncssh.__version__,'launcher':'simulated user manager'}))
    await server.wait_closed()
asyncio.run(main())
