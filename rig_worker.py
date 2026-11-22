"""Studio rig worker: isolated UniRig inference, followed by local Blender export."""
from pathlib import Path
import hashlib, json, math, shutil, subprocess, sys, time, traceback
from studio_import import find_blender, validate_glb
from rig_landmarks import validate_rig_options
from studio_workspace import write

ROOT=Path(__file__).resolve().parent;JOB=Path(sys.argv[1]).resolve();started=time.time()
work = JOB / 'rig-work'
distro = 'Ubuntu-22.04'

def status(state,stage,progress,**extra):
    write(JOB/'status.json', dict(state=state, stage=stage, progress=progress,
                                 elapsed=round(time.time()-started,1), **extra))

def linux_path(path):
    return subprocess.check_output(['wsl.exe','-d',distro,'--exec','wslpath','-a','-u',str(path)],encoding='utf-8').strip()

def read_landmark_verification():
    try:
        report = json.loads((work / 'landmarks-report.json').read_text(encoding='utf-8'))
        verification = report['final_rig_verification']
        return verification if isinstance(verification, dict) else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def failure_status(phase, error):
    if creature_phase == 'final' and phase == 'UniRig':
        try:
            message = json.loads((work / 'creature-error.json').read_text(encoding='utf-8'))['message']
            if isinstance(message, str) and message.strip():
                return 'Creature skeleton could not be applied', dict(error=message, error_code='creature_skeleton_invalid')
        except (OSError, ValueError, TypeError, KeyError):
            pass
    verification = read_landmark_verification() if phase == 'UniRig' else {}
    if verification.get('passed') is False:
        message = verification.get('error')
        if not isinstance(message, str) or not message.strip():
            message = 'The final rig did not preserve the requested joint landmarks.'
        details = {}
        tolerance = verification.get('tolerance_m')
        if type(tolerance) in (int, float) and math.isfinite(tolerance) and tolerance >= 0:
            details['tolerance_m'] = tolerance
        distances = verification.get('errors_m')
        if isinstance(distances, dict):
            details['errors_m'] = {
                name: distance for name, distance in distances.items()
                if type(distance) in (int, float) and math.isfinite(distance) and distance >= 0
            }
        return 'Joint landmark verification failed', dict(
            error=message, error_code='rig_landmark_verification_failed', error_details=details)
    if phase == 'Preparing standard animations':
        try:
            rejection = json.loads((work / 'rig-profile-error.json').read_text(encoding='utf-8'))
            message = rejection.get('message')
            if isinstance(message, str) and message:
                return 'Rig profile could not be applied', dict(error=message, error_code='rig_profile_incompatible')
        except (OSError, ValueError, AttributeError):
            pass
    if isinstance(error, subprocess.TimeoutExpired):
        message = f'{phase} timed out. See the generation log for details.'
    elif isinstance(error, subprocess.CalledProcessError):
        message = f'{phase} failed. See the generation log for details.'
    else:
        message = str(error) or 'See the generation log for details.'
    return 'Rig interrupted', dict(error=message)


phase = 'Rig setup'
creature_phase = None
try:
    config_path=ROOT/'config'/'runtime.json'
    config=json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
    distro=config.get('wsl_distribution',distro)
    settings=json.loads((JOB/'settings.json').read_text(encoding='utf-8'))
    if settings.get('rig_options'):
        settings['rig_options']=validate_rig_options(settings['rig_options'])
    rig_options = settings.get('rig_options') or {}
    if rig_options.get('mode') == 'creature':
        creature_phase = settings.get('creature_phase')
        if creature_phase not in ('draft', 'final'):
            raise ValueError('The creature rig phase is missing or invalid.')
    source = JOB / 'source.glb'
    expected = settings.get('rig_source_sha256')
    if creature_phase and (not isinstance(expected, str) or len(expected) != 64):
        raise ValueError('The creature source fingerprint is missing. Create a new draft.')
    if expected:
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError('The rig source changed. Create a new variant from the source model.')
    data=validate_glb(source);work.mkdir(exist_ok=True)
    if creature_phase and data.get('skins'):
        raise ValueError('Creature skeleton prediction requires an unrigged source mesh.')
    if creature_phase == 'final':
        from creature_rig import validate_creature_edit
        edit = validate_creature_edit(json.loads((JOB / 'creature-edit.json').read_text(encoding='utf-8')))
        if hashlib.sha256((JOB / 'rig-preview.json').read_bytes()).hexdigest() != edit['revision']:
            raise ValueError('The creature draft changed. Open the current preview and try again.')
        if not (work / 'skeleton.fbx').is_file():
            raise ValueError('The original creature prediction is unavailable. Create a new draft.')
    blender = find_blender()
    if not blender:
        raise RuntimeError('Blender is unavailable. Configure Blender before rigging a model.')
    rig_input=source
    if settings.get('rig_options') and not creature_phase:
        phase = 'Character orientation and height'
        status('running','Character orientation and height',4)
        subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(ROOT/'prepare_rig.py'),'--',str(JOB)],stdout=sys.stdout,stderr=subprocess.STDOUT,check=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        rig_input=work/'input.glb'
    if data.get('skins'):
        if rig_options.get('landmarks'):
            raise ValueError('Landmark placement requires an unrigged model; existing skin weights cannot be silently reused.')
        status('running','Existing skeleton retained · preparing animations',80)
        shutil.copy2(rig_input,work/'rigged.glb')
        rig_engine='existing'
    else:
        phase = 'UniRig'
        status('running','Starting UniRig',5)
        (work / 'creature-error.json').unlink(missing_ok=True)
        command=['wsl.exe','-d',distro,'--exec','setsid','--wait','bash',linux_path((ROOT/'UniRig'/'run-model.sh').resolve()),linux_path(JOB)]
        subprocess.run(command,stdout=sys.stdout,stderr=subprocess.STDOUT,check=True,timeout=2400,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if creature_phase == 'draft':
            from creature_rig import validate_creature_bones
            preview = json.loads((JOB / 'rig-preview.json').read_text(encoding='utf-8'))
            bones = validate_creature_bones(preview.get('bones'))
            if preview.get('aligned_to_model') is not True or not (work / 'skeleton.fbx').is_file():
                raise ValueError('UniRig did not produce an aligned creature skeleton to edit.')
            result = dict(rigged=False, rig_phase='draft', bones=len(bones),
                          creature_rig=dict(phase='draft', editable=True), rig_engine='UniRig')
            write(JOB / 'result.json', result)
            status('done', 'Creature skeleton ready to edit', 100, rig_phase='draft', result=result)
            sys.exit(0)
        if rig_options.get('landmarks') and read_landmark_verification().get('passed') is not True:
            raise RuntimeError('UniRig did not complete joint landmark verification.')
        rig_engine='UniRig'
    phase = 'Preparing standard animations'
    status('running','Preparing standard animations',88)
    timeout = 240 + 20 * max(0, len(settings.get('animation_clips', [])) - 1)
    subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(ROOT/'standard_animations.py'),'--',str(JOB)],stdout=sys.stdout,stderr=subprocess.STDOUT,check=True,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    data=validate_glb(JOB/'model.glb')
    if not data.get('skins'): raise RuntimeError('The result does not contain a skinned skeleton.')
    result=json.loads((JOB/'result.json').read_text(encoding='utf-8'));result['rig_engine']=rig_engine
    if creature_phase == 'final':
        from creature_verification import verify_creature
        phase = 'Checking the creature rig'
        result['creature_verification'] = verify_creature(JOB / 'model.glb', edit['bones'])
        result.update(rig_phase='final', creature_rig=dict(phase='final', editable=False))
    profile = result.get('rig_profile')
    if profile:
        if len(data['skins']) != 1 or len(data['skins'][0]['joints']) != profile['joint_count']:
            raise ValueError('The exported skeleton does not match the selected profile.')
        exported_names = {clip.get('name') for clip in data.get('animations', [])}
        authored = result['animation_set']
        if ({clip['id'] for clip in authored} != {clip['id'] for clip in settings.get('animation_clips', [])}
                or any(clip.get('clip') not in exported_names for clip in authored)):
            raise ValueError('The rig profile export is missing a retargeted animation.')
    landmarks_report=work/'landmarks-report.json'
    if landmarks_report.is_file():result['rig_landmarks']=json.loads(landmarks_report.read_text(encoding='utf-8'))
    (JOB/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    if creature_phase == 'final':
        status('done', 'Creature rig ready', 100, result=result, rig_phase='final')
    else:
        status('done','Rig and animations ready' if result.get('animation_set') else 'Rig ready' if result.get('humanoid_mapping') else 'Rig ready · character mapping needs adjustment',100,result=result)
except Exception as error:
    stage, details = failure_status(phase, error)
    pid_path=work/'runtime.pid'
    if pid_path.is_file():
        try:
            pid=int(pid_path.read_text().strip())
            if pid>1:subprocess.run(['wsl.exe','-d',distro,'--exec','kill','-TERM','--','-'+str(pid)],capture_output=True,timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,ValueError,subprocess.TimeoutExpired):pass
    traceback.print_exc()
    if creature_phase:
        details['rig_phase'] = creature_phase
    status('error', stage, 0, **details)
