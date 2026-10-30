"""Test independent release images with no external network and no real GPU/model.

Only uses image tags supplied by the operator. No source checkout imports across services.
"""

import argparse
import json
import subprocess
import uuid

SETUP = """
from llm_relay.store import Store
import json
store=Store('/data/relay.sqlite3')
print(json.dumps({role:store.add_token(role,role) for role in ['client','worker']}))
"""
PROBE = r"""
import json, os, threading, time, uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from llm_gpu_worker.client import Client, RelayHTTPError
from llm_gpu_worker.worker import Worker, Spool

os.umask(0o077)
answer='Plain text is a valid model answer. ' + 'абв' * 200000
client=Client('http://127.0.0.1:8100', keys['client'])
gpu=Client('http://127.0.0.1:8100', keys['worker'])
for _ in range(100):
    try:
        if client.call('GET','/health')['protocol']==1: break
    except (httpx.HTTPError,RelayHTTPError): time.sleep(.1)
else: raise AssertionError('Relay not ready')

if phase == 'compute':
    assert httpx.get('http://127.0.0.1:8100/bridge/v1/health').status_code==401
    try: client.call('POST','/worker/claim',{})
    except RelayHTTPError as error: assert error.status==403
    else: raise AssertionError('Client could execute worker operations')
    calls=[]
    class Model(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_POST(self):
            assert self.headers['Authorization']=='Bearer fake-local-key'
            calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            for part in [
                {'id':'test-model-call','choices':[{'delta':{'content':answer},'finish_reason':'stop'}]},
                {'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':8}},
            ]: self.wfile.write(('data: '+json.dumps(part)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    model=ThreadingHTTPServer(('127.0.0.1',0),Model)
    threading.Thread(target=model.serve_forever,daemon=True).start()
    ident=str(uuid.uuid4())
    payload={'model':'qwen38','messages':[{'role':'user','content':'Test'}],'max_tokens':32,'stream':True}
    client.call('PUT','/jobs/'+ident,{'payload':payload})
    client.call('PUT','/jobs/'+ident,{'payload':payload})
    executor=Worker(gpu,Spool('/data/spool.sqlite3'),upstream={
        'url':f'http://127.0.0.1:{model.server_port}/v1','key':'fake-local-key',
        'connect_timeout':5,'read_timeout':5})
    executor.step()
    assert len(calls)==1
    assert executor.spool.get(ident)['state']=='complete'
    original=gpu.call
    def offline(*args,**kwargs): raise httpx.ConnectError('simulated external outage')
    gpu.call=offline
    try: executor.step()
    except httpx.ConnectError: pass
    else: raise AssertionError('Expected delivery outage')
    assert executor.spool.get(ident)['state']=='complete'
    Path('/data/test-id').write_text(ident)
    model.shutdown()
    print('Saved full response before delivery, one local model call')
else:
    ident=Path('/data/test-id').read_text()
    def forbidden(*args,**kwargs): raise AssertionError('Model must not be called again')
    executor=Worker(gpu,Spool('/data/spool.sqlite3'),upstream={},infer=forbidden)
    executor.spool.recover()
    original=gpu.call
    def lose_ack(method,path,body=None):
        result=original(method,path,body)
        if path.endswith('/receipt'): raise httpx.ReadError('ACK lost after relay commit')
        return result
    gpu.call=lose_ack
    try: executor.step()
    except httpx.ReadError: pass
    else: raise AssertionError('Expected lost ACK')
    assert executor.spool.get(ident)['state']=='complete'
    gpu.call=original
    executor.step()
    assert executor.spool.get(ident)['state']=='delivered'
    status=client.call('GET','/jobs/'+ident)
    assert status['state']=='completed'
    assert status['receipt']['result']['response']['choices'][0]['message']['content']==answer
    assert status['receipt']['result']['response']['usage']['completion_tokens']==8
    # Boot the actual entrypoint with file credentials; exercise drain/status/backup.
    import subprocess
    for role in ['client', 'worker']:
        Path('/data/'+role+'.token').write_text(keys[role])
    Path('/data/vllm.key').write_text('fake-local-key')
    env={**os.environ, 'BRIDGE_RELAY_URL':'http://127.0.0.1:8100',
         'BRIDGE_WORKER_TOKEN_FILE':'/data/worker.token',
         'BRIDGE_VLLM_API_KEY_FILE':'/data/vllm.key'}
    process=subprocess.Popen(['python','-m','llm_gpu_worker.worker'],env=env)
    try:
        subprocess.run(['python','-m','llm_gpu_worker.admin','drain'],check=True)
        for _ in range(100):
            if process.poll() is not None: raise AssertionError('Worker entrypoint exited')
            if Path('/data/IDLE').exists(): break
            time.sleep(.1)
        else: raise AssertionError('Drain did not reach idle')
        status=json.loads(subprocess.check_output(['python','-m','llm_gpu_worker.admin','status']))
        assert status['draining'] and status['idle'] and status['jobs']=={'delivered':1}
        subprocess.run(['python','-m','llm_gpu_worker.admin','backup','--output','/data/backup.sqlite3'],check=True)
    finally:
        process.terminate(); process.wait(timeout=30)
    print('Restarted both services; file credentials, drain and backup; no repeated model call')
client.close(); gpu.close()
"""


def docker(*args, data=None):
    return subprocess.run(
        ["docker", *args], input=data, text=True, capture_output=True, check=True, timeout=90
    ).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay-image", default="llm-relay:0.2.0")
    parser.add_argument("--worker-image", default="llm-gpu-worker:0.2.0")
    args = parser.parse_args()
    ident = "llm-smoke-" + uuid.uuid4().hex[:10]
    spool = ident + "-spool"
    hardening = [
        "--platform",
        "linux/amd64",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "256m",
        "--pids-limit",
        "64",
        "--tmpfs",
        "/tmp",
    ]
    try:
        docker("volume", "create", spool)
        docker(
            "run",
            "-d",
            "--name",
            ident,
            "--network",
            "none",
            *hardening,
            "--tmpfs",
            "/data:uid=10001,gid=10001,mode=0700",
            args.relay_image,
        )
        keys = json.loads(docker("exec", "-i", ident, "python", "-", data=SETUP))
        for phase in ["compute", "deliver"]:
            if phase == "deliver":
                # HUP restarts the actual relay worker while retaining its memory-independent DB.
                # Its tmpfs volume remains attached; the other service starts from a fresh container.
                docker("kill", "--signal=HUP", ident)
            output = docker(
                "run",
                "--rm",
                "-i",
                "--network",
                "container:" + ident,
                *hardening,
                "--mount",
                f"type=volume,src={spool},dst=/data",
                "--entrypoint",
                "python",
                args.worker_image,
                "-",
                data=f"keys={keys!r}\nphase={phase!r}\n" + PROBE,
            )
            print(output)
        print("STACK OK: independent images, auth, durable delivery, restart, no external network")
    except subprocess.CalledProcessError as error:
        # Only synthetic test credentials are used; never include the program stdin.
        print(error.stderr[-4000:])
        raise SystemExit("Container contract check failed") from None
    finally:
        subprocess.run(["docker", "rm", "-f", ident], capture_output=True, check=False)
        subprocess.run(["docker", "volume", "rm", spool], capture_output=True, check=False)


if __name__ == "__main__":
    main()
