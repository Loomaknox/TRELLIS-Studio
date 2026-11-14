"""Execute and cancel an isolated CPU bridge fixture without model weights or inference."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json, subprocess, sys, time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from generated_animation_runtime import command,linux_path,load_config,stop_runtime
from studio_workspace import read,write

ROOT=Path(__file__).resolve().parents[1]

def run():
    try:config=load_config(ROOT)
    except (OSError,ValueError):
        print('SKIP: optional CPU animation runtime is not configured on this installation.')
        return
    with TemporaryDirectory(prefix='trellis-motion-cancel-') as temporary:
        folder=Path(temporary).resolve()
        script=folder/'fixture.py'
        script.write_text('from pathlib import Path\nimport sys,time,os\nPath(sys.argv[-1],"started").write_text(os.environ.get("LD_LIBRARY_PATH",""))\nwhile True: time.sleep(.1)\n')
        # The real generator remains untouched; python runs a sleeping fixture as its first argument.
        fixture={**config,'executable':'/usr/bin/python3','motion_model':linux_path(script),'text_model':'fixture',
                 'steps':100,'threads':1,'timeout_seconds':30,'library_directory':'/tmp/trellis-fixture-libraries'}
        validation=folder/'config';validation.mkdir()
        for invalid in ('relative/path','/one:/two','/one\n','',False):
            write(validation/'generated-animation-runtime.json',{**config,'library_directory':invalid})
            try:load_config(folder)
            except ValueError:pass
            else:raise AssertionError('Invalid library directory accepted.')
        write(folder/'runtime-config.json',fixture)
        write(folder/'manifest.json',dict(prompt='Fixture cancellation',frames=60,seed=42))
        with (folder/'fixture.log').open('w') as log:
            process=subprocess.Popen(command(ROOT,folder,fixture),stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(200):
                    if (folder/'decoded/started').is_file():break
                    if process.poll() is not None:raise AssertionError((folder/'fixture.log').read_text())
                    time.sleep(.05)
                assert (folder/'decoded/started').is_file(),'The isolated runtime fixture did not start.'
                assert (folder/'decoded/started').read_text()==fixture['library_directory']
                identifier=read(folder/'generated-runtime.json')['pid']
                stop_runtime(ROOT,folder)
                process.wait(timeout=10)
                assert process.returncode!=0
                assert not (folder/'generated-runtime.json').exists()
                check=['wsl.exe','-d',fixture['distribution'],'--','test','-e',f'/proc/{identifier}'] if fixture['backend']=='wsl_cpu' else ['test','-e',f'/proc/{identifier}']
                assert subprocess.run(check,capture_output=True,timeout=5).returncode==1,'The child process survived cancellation.'
            finally:
                if process.poll() is None:
                    stop_runtime(ROOT,folder);process.terminate();process.wait(timeout=10)
    print('Actual CPU runtime bridge cancellation passed; fixture child and process group are gone, no inference ran.')

if __name__=='__main__':run()
