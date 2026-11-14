"""Private CPU runtime subprocess bridge. Standard library only, also runnable inside WSL."""
from pathlib import Path
import json, os, re, signal, subprocess, sys, time

def write(path,data):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data))
    temporary.replace(path)

def stop(folder):
    marker=folder/'generated-runtime.json'
    if not marker.is_file():return
    info=json.loads(marker.read_text());pid=info['pid']
    if type(pid) is not int or pid<=1:return
    try:
        command=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if command[0].decode()!=info['executable'] or str(folder/'decoded').encode() not in command:return
        os.killpg(pid,signal.SIGTERM)
        for _ in range(25):
            if not Path(f'/proc/{pid}').exists():return
            time.sleep(.1)
        os.killpg(pid,signal.SIGKILL)
    except (FileNotFoundError,ProcessLookupError):pass

def main():
    folder=Path(sys.argv[1]).resolve();config=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig'))
    if len(sys.argv)>3 and sys.argv[3]=='--cancel':stop(folder);return
    manifest=json.loads((folder/'manifest.json').read_text());output=folder/'decoded';output.mkdir()
    prompt=folder/'prompt.txt';prompt.write_text(manifest['prompt'],encoding='utf-8')
    args=[config['executable'],config['motion_model'],config['text_model'],str(prompt),
          str(manifest['frames']),str(config['steps']),str(manifest['seed']),str(output)]
    env=os.environ.copy();env.update(KIMODO_BACKEND='cpu',KIMODO_THREADS=str(config['threads']),KIMODO_PROFILE='1')
    if config.get('library_directory'):env['LD_LIBRARY_PATH']=config['library_directory']
    started=time.monotonic();peak=0;position=0;tail='';last_progress=5
    log_path=folder/'runtime.log'
    with log_path.open('w') as log:
        process=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        write(folder/'generated-runtime.json',dict(pid=process.pid,executable=args[0]))
        try:
            while process.poll() is None:
                if time.monotonic()-started>config['timeout_seconds']:
                    stop(folder);raise TimeoutError('Animation generation exceeded its time limit.')
                try:
                    status=Path(f'/proc/{process.pid}/status').read_text()
                    match=re.search(r'^VmHWM:\s+(\d+)',status,re.M)
                    if match:peak=max(peak,int(match[1]))
                except FileNotFoundError:pass
                with log_path.open() as progress:
                    progress.seek(position);tail=(tail+progress.read())[-8192:];position=progress.tell()
                indexes=re.findall(r'profile motion.diffusion_step index=(\d+)',tail)
                if indexes:
                    value=10+int(80*(config['steps']-int(indexes[-1]))/config['steps'])
                    if value!=last_progress:
                        last_progress=value
                        write(folder/'status.json',dict(state='running',stage='Generating motion on CPU',progress=value))
                time.sleep(.5)
            if process.returncode:raise RuntimeError('The configured motion runtime failed. See the private runtime log.')
            write(folder/'runtime-result.json',dict(seconds=round(time.monotonic()-started,3),peak_rss_mib=peak/1024,backend='CPU'))
        finally:
            if process.poll() is None:stop(folder)
            (folder/'generated-runtime.json').unlink(missing_ok=True)

if __name__=='__main__':main()
