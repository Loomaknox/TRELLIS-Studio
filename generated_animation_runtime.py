"""Optional CPU motion runtime, installed only after an explicit administrator opt-in."""
from pathlib import Path, PurePosixPath
import json, os, re, shutil, subprocess, sys

CONFIG_NAME='generated-animation-runtime.json'

def load_config(root):
    path=Path(root)/'config'/CONFIG_NAME
    if not path.is_file():raise ValueError('Animation generation is not configured on this installation.')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or data.get('enabled') is not True:raise ValueError('Animation generation is disabled by the administrator.')
    backend=data.get('backend')
    if backend not in ('wsl_cpu','native_cpu'):raise ValueError('Choose a supported CPU animation runtime.')
    for key in ('executable','motion_model','text_model'):
        value=data.get(key)
        if not isinstance(value,str) or not PurePosixPath(value).is_absolute() or any(ord(c)<32 for c in value):
            raise ValueError('Animation runtime paths must be absolute Linux paths.')
    libraries=data.get('library_directory')
    if libraries is not None and (not isinstance(libraries,str) or not PurePosixPath(libraries).is_absolute()
                                  or ':' in libraries or any(ord(c)<32 for c in libraries)):
        raise ValueError('The optional runtime library directory must be one absolute Linux path.')
    if backend=='wsl_cpu':
        distro=data.get('distribution')
        if not isinstance(distro,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',distro):raise ValueError('Invalid animation runtime distribution.')
        if os.name!='nt' or not shutil.which('wsl.exe'):raise ValueError('The configured WSL runtime is unavailable.')
    elif os.name=='nt':raise ValueError('Use WSL for this CPU runtime on Windows.')
    skeleton=Path(data.get('skeleton',''))
    if not skeleton.is_absolute() or not skeleton.is_file() or skeleton.stat().st_size>65536:raise ValueError('A valid SOMA30 skeleton file is required.')
    for key,default,minimum,maximum in (('threads',8,1,64),('steps',100,10,200),('timeout_seconds',1200,60,3600)):
        value=data.get(key,default)
        if type(value) is not int or not minimum<=value<=maximum:raise ValueError('Invalid animation runtime limits.')
        data[key]=value
    for key in ('model','runtime','source_revision','model_sha256','text_encoder_sha256'):
        value=data.get(key,'')
        if not isinstance(value,str) or len(value)>160 or any(ord(c)<32 for c in value):raise ValueError('Invalid animation runtime provenance.')
    return data

def public_status(root):
    try:
        config=load_config(root)
        return dict(ready=True,label=config.get('model') or 'Kimodo CPU',backend='CPU',experimental=True,
                    message='Generated humanoid motions require a deformation and contact review.')
    except (OSError,ValueError,TypeError):
        return dict(ready=False,label='Kimodo CPU',backend='CPU',experimental=True,
                    message='An administrator must install or enable the optional Kimodo component.')

def linux_path(path):
    value=str(Path(path).resolve())
    if os.name=='nt':
        match=re.fullmatch(r'([A-Za-z]):[\\/](.*)',value)
        if not match:raise ValueError('The runtime needs a local drive path.')
        return '/mnt/'+match[1].lower()+'/'+match[2].replace('\\','/')
    return value

def command(root, folder, config, cancel=False):
    snapshot=Path(folder)/'runtime-config.json'
    arguments=[linux_path(Path(root)/'generated_animation_runner.py'),linux_path(folder),
               linux_path(snapshot if snapshot.is_file() else Path(root)/'config'/CONFIG_NAME)]
    if cancel:arguments.append('--cancel')
    if config['backend']=='wsl_cpu':return ['wsl.exe','-d',config['distribution'],'--','python3',*arguments]
    return [sys.executable,*arguments]

def stop_runtime(root,folder):
    """Stop only the identified Linux process group belonging to this active operation."""
    if not (Path(folder)/'generated-runtime.json').is_file():return
    try:
        snapshot=Path(folder)/'runtime-config.json'
        config=json.loads(snapshot.read_text()) if snapshot.is_file() else load_config(root)
        subprocess.run(command(root,folder,config,cancel=True),timeout=10,capture_output=True,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,ValueError,subprocess.SubprocessError):pass
