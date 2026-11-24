"""Verify an asymmetric lateral placement through FBX skin transfer and final GLB."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio_import import find_blender


def run(output=None):
    executable = find_blender()
    if not executable:
        raise RuntimeError('Blender is required.')
    blender = [str(executable), '-b', '-t', '3', '--factory-startup', '--disable-autoexec', '--python-exit-code', '1']

    def stage(command):
        result = subprocess.run(blender+command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        if result.returncode:
            raise RuntimeError(f'Blender exit {result.returncode}: ' + result.stdout.decode(errors='replace')[-1800:])

    def adapter(script, args):
        path = str(ROOT/'UniRig'/script)
        if os.name=='nt' and os.environ.get('TRELLIS_TEST_INSTALL'):
            def wsl_path(value):
                windows=Path(value).resolve()
                return '/mnt/'+windows.drive[0].lower()+'/'+windows.as_posix()[3:]
            installed=Path(os.environ['TRELLIS_TEST_INSTALL'])
            command=('set -e; source "$1/UniRig/runtime.sh"; require_unirig_python; '
                     'export PYTHONPATH="$1/UniRig/source:${PYTHONPATH:-}"; '
                     'shift; exec "$UNIRIG_PYTHON" -B "$@"')
            subprocess.run(['wsl.exe','-d',os.environ.get('TRELLIS_TEST_DISTRO','Ubuntu-22.04'),'--exec',
                            'bash','-s','--',wsl_path(installed),wsl_path(path),*[wsl_path(a) for a in args]],
                           input=command.encode()+b'\n',timeout=120,check=True)
            return
        code = (f'import sys,runpy;sys.path.insert(0,{str(ROOT/"UniRig")!r});'
                f'sys.argv={[path,*map(str,args)]!r};runpy.run_path({path!r},run_name="__main__")')
        stage(['--python-expr', code])

    with TemporaryDirectory(prefix='trellis-lateral-') as temp:
        job = Path(temp)/'character'
        work = job/'rig-work'
        def scene(action):
            stage(['-P',str(ROOT/'tests/rig_landmarks_blender.py'),'--',action,str(job)])
        scene('create')
        settings = json.loads((job/'settings.json').read_text())
        settings['rig_options']['landmarks']['left_knee'].append(.06)
        settings['rig_options']['landmarks']['left_ankle'].append(-.01)
        (job/'settings.json').write_text(json.dumps(settings))
        adapter('apply-landmarks.py', [job])
        scene('verify')
        scene('skin')
        adapter('transfer-skin.py', [work/'skin-fixture.fbx',work/'input.glb',work/'rigged.glb'])
        adapter('verify-landmarks.py', [job])
        scene('verify')
        report=json.loads((work/'landmarks-report.json').read_text())
        if output:
            Path(output).write_text(json.dumps(report,indent=2), encoding='utf8')
        print(report['final_rig_verification'])


if __name__=='__main__':
    run(sys.argv[1] if len(sys.argv)>1 else None)
