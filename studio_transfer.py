"""Data-only, hashed collection archives; restoring always allocates fresh IDs."""
from pathlib import Path,PurePosixPath
import hashlib,json,os,re,shutil,stat,time,uuid,zipfile
from studio_workspace import read,write,ID,file_digest
from studio_import import validate_glb
from studio_version import VERSION
from asset_provenance import export_provenance, fields

EXTENSIONS={'.json','.glb','.blend','.png','.jpg','.jpeg','.webp','.stl','.fbx','.obj','.ply','.raw','.mtl','.webm'}
EXCLUDED={'Blender','rig-work','before-animations','__pycache__'}
MAX_TOTAL=12*1024**3
MAX_ENTRIES=25000
MAX_MANIFEST=20*1024**2
PREVIEW_LIFETIME=7*24*3600
digest=file_digest

def check_budget(size, count):
    if size>MAX_TOTAL or count>MAX_ENTRIES:
        raise ValueError('Archive exceeds the 12 GB / 25,000 file limit.')

def collection_inventory(folders, include_revisions):
    inventory=[]
    total=0
    for folder in folders:
        folder=folder.resolve()
        def report_error(error):raise error
        for parent, dirs, files in os.walk(folder,onerror=report_error):
            parent=Path(parent)
            dirs[:]=[d for d in sorted(dirs) if d not in EXCLUDED and not d.startswith('.')
                     and (d!='Revisions' or include_revisions or parent!=folder)
                     and (parent/d).resolve()==parent/d]
            for filename in sorted(files):
                path=parent/filename
                if filename.startswith('.') or path.suffix.lower() not in EXTENSIONS or path.resolve()!=path or not path.is_file():continue
                total+=path.stat().st_size
                inventory.append((folder,path))
                check_budget(total,len(inventory)+1)
    return inventory, total

def validate_model(folder):
    validate_glb(folder/'model.glb')
    settings=read(folder/'settings.json')
    if not isinstance(settings,dict) or not isinstance(settings.get('name'),str) or len(settings['name'])>80:
        raise ValueError('Invalid model settings.')
    return settings

def staging_directory(path):
    path = Path(path).absolute()
    try:
        resolved = path.resolve(strict=True)
        if resolved != path:
            # An NTFS short name is safe to expand. Refuse symlinks and junctions
            # anywhere in a redirected cleanup path.
            for part in (path, *path.parents):
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    return None
        return resolved if resolved.is_dir() else None
    except OSError:
        return None


def expire_transfer_previews(root, now=None):
    now=time.time() if now is None else now
    root=staging_directory(root)
    if root is None:return
    for path in root.iterdir():
        if not ID.fullmatch(path.name) or path.resolve()!=path or not path.is_dir():continue
        try:
            lease=read(path/'preview-lease.json',{})
            expires=lease.get('expires_at') if isinstance(lease,dict) else None
            if isinstance(expires,(int,float)) and expires<=now:
                verified=path/'verified'
                if verified.is_dir() and verified.resolve()==verified:shutil.rmtree(verified)
        except (OSError,ValueError):continue

def verify_transfer_preview(archive,target):
    manifest=inspect(archive)
    extract(archive,target/'verified',manifest)
    archive.unlink()
    write(target/'manifest.json',manifest)
    write(target/'preview-lease.json',dict(expires_at=time.time()+PREVIEW_LIFETIME))
    return manifest

def cleanup_export_staging(task):
    task=staging_directory(task)
    if task is None:return False
    complete=True
    for name in ('sources','package','package.zip.tmp'):
        path=task/name
        try:
            if path.is_symlink():path.unlink(missing_ok=True)
            elif path.resolve()==path and path.is_dir():shutil.rmtree(path)
            elif path.resolve()==path:path.unlink(missing_ok=True)
            else:complete=False
        except FileNotFoundError:pass
        except OSError:complete=False
    return complete


def export_staging_inventory(root, active=None):
    root=staging_directory(root)
    entries=[]
    if not root:return entries
    for task in sorted(root.iterdir()):
        if not ID.fullmatch(task.name) or task.name==active or staging_directory(task)!=task:continue
        try:
            status=read(task/'status.json',{})
            if status.get('state')!='done' or not (task/'package.zip').is_file():continue
            for component in ('package','sources'):
                folder=task/component
                if staging_directory(folder)!=folder:continue
                total=count=0
                members=[]
                for current,dirs,files in os.walk(folder,followlinks=False):
                    parent=Path(current)
                    dirs[:]=[d for d in dirs if staging_directory(parent/d)==parent/d]
                    for name in files:
                        path=parent/name
                        if path.resolve()==path and path.is_file():
                            size=path.stat().st_size
                            total+=size
                            count+=1
                            if len(members)<250:members.append(dict(path=path.relative_to(folder).as_posix(),bytes=size))
                entries.append(dict(export_id=task.name,path=component,bytes=total,files=count,members=members))
        except (ValueError,OSError):continue
    return entries

def published_export(task,request):
    """Recover the short gap between the worker's validated ZIP rename and status write."""
    path=task/'package.zip'
    if not request.get('clean_staging') or not path.is_file():return None
    target=request['target']
    with zipfile.ZipFile(path) as archive:
        if target=='library':
            items=inspect(path)['models']
        else:
            manifest=json.loads(archive.read('export-manifest.json'))
            if manifest.get('target')!=target:raise ValueError('Invalid export manifest.')
            items=manifest['models']
        if sorted(item['id'] for item in items)!=sorted(request['ids']):raise ValueError('Invalid export manifest.')
        if archive.testzip() is not None:raise ValueError('Export package failed the integrity check.')
    return dict(state='done',stage='Collection backup ready' if target=='library' else 'Export ready',
                target=target,progress=100,count=len(items),items=items,bytes=path.stat().st_size)

def export_lineage(folder, settings):
    library = folder.resolve().parent
    seen = {folder.name}
    ancestors = []
    status = 'origin'
    while settings.get('parent_id') and settings.get('source_kind'):
        identifier = settings['parent_id']
        if not isinstance(identifier, str) or not ID.fullmatch(identifier) or identifier in seen or len(seen) >= 64:
            status = 'invalid_or_cyclic'
            break
        parent = library / identifier
        if settings.get('source_kind') == 'restored':
            revision = settings.get('restored_revision')
            if not isinstance(revision, str) or not ID.fullmatch(revision):
                status = 'revision_unavailable'
                break
            parent = parent/'Revisions'/revision
            record_file = parent/'revision.json'
            try:
                verified = record_file.resolve() == record_file and fields(read(record_file, {})).get('id') == revision
            except (OSError, UnicodeError, ValueError):
                verified = False
            if not verified:
                status = 'revision_unavailable'
                break
        files = [parent / name for name in ('settings.json', 'result.json')]
        if any(path.resolve() != path for path in files) or not files[0].is_file():
            status = 'parent_unavailable'
            break
        try:
            settings = fields(read(files[0], {}))
            result = fields(read(files[1], {}))
        except (OSError, UnicodeError, ValueError):
            status = 'parent_unreadable'
            break
        ancestors.append((identifier, settings, result))
        seen.add(identifier)
    if status == 'origin' and settings.get('source_kind') == 'import' and not settings.get('parent_id'):
        status = 'imported_origin'
    receipt = {}
    for _, settings, result in reversed(ancestors):
        receipt = export_provenance(settings, result, receipt)
    return dict(chain=[row[0] for row in ancestors], status=status, ancestor=receipt)


def release_export_copy(task, collection, component):
    """Release an explicitly selected legacy copy only while an identical original exists."""
    task=staging_directory(task)
    collection=staging_directory(collection)
    if not task or not collection or component not in ('package','sources'):raise ValueError('Invalid export copy.')
    source=task/component
    if (read(task/'status.json',{}).get('state')!='done' or staging_directory(source)!=source or
            (task/'package.zip').resolve()!=task/'package.zip'):
        raise ValueError('Export copy is unavailable or active.')
    with zipfile.ZipFile(task/'package.zip') as archive:
        if archive.testzip() is not None:raise ValueError('Export ZIP failed its integrity check.')
        for path in source.rglob('*'):
            if path.resolve()!=path:raise ValueError('Redirected export copy.')
            if path.is_dir():continue
            relative=path.relative_to(source)
            if component=='package':
                try:
                    with archive.open(relative.as_posix()) as stream:
                        expected=hashlib.file_digest(stream,'sha256').hexdigest()
                except KeyError as error:raise ValueError('This file has no verified archived copy.') from error
            else:
                original=collection/relative
                if not ID.fullmatch(relative.parts[0]) or original.resolve()!=original or not original.is_file():
                    raise ValueError('This source copy has no verified original in the collection.')
                expected=digest(original)
            if digest(path)!=expected:raise ValueError('Export copy differs from the preserved original.')
    shutil.rmtree(source)

def snapshot_export(assets,task,target,include_revisions):
    if target=='library':
        files,total=collection_inventory([folder for folder,_ in assets],include_revisions)
        if shutil.disk_usage(task).free<total*2:
            raise ValueError('Insufficient disk space for the collection snapshot and ZIP. Select fewer models or revisions.')
        for folder,path in files:
            destination=task/'sources'/folder.name/path.relative_to(folder)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination)
    for folder,record in assets:
        snapshot=task/'sources'/folder.name
        snapshot.mkdir(parents=True,exist_ok=True)
        write(snapshot/'metadata.json',record['metadata'])
        write(snapshot/'settings.json',record['settings'])
        if (folder/'Diagnostics/report.json').is_file():
            shutil.copy2(folder/'Diagnostics/report.json',snapshot/'diagnostics.json')
        if target=='library':continue
        write(snapshot/'export-lineage.json',export_lineage(folder,record['settings']))
        for child in ('LODs','Collisions'):
            if (folder/child).is_dir():shutil.copytree(folder/child,snapshot/child)
        for filename in ('model.glb','model.stl','result.json','print-report.json','lod-manifest.json','physics.json','motion-report.json'):
            if (folder/filename).is_file():shutil.copy2(folder/filename,snapshot/filename)

def build(sources,destination,workspace,profiles,include_revisions=False,notify=lambda *args:None):
    sources=Path(sources).resolve();manifest=dict(format='trellis-collection',version=1,studio_version=VERSION,models=[],workspace=workspace,profiles=profiles,files=[])
    folders=[p for p in sources.iterdir() if p.is_dir() and ID.fullmatch(p.name)]
    inventory,_=collection_inventory(folders,include_revisions)
    if not 1<=len(folders)<=500:raise ValueError('Invalid model list.')
    members={folder:[] for folder in folders}
    for folder,path in inventory:members[folder].append(path)
    used={read(p/'metadata.json',{}).get('folder_id','') for p in folders};catalog={f['id']:f for f in workspace.get('folders',[])}
    for _ in range(500):
        parents={catalog[i].get('parent_id','') for i in used if i in catalog}-used
        if not parents:break
        used.update(parents)
    manifest['workspace']={**workspace,'folders':[f for f in workspace.get('folders',[]) if f['id'] in used],'views':[v for v in workspace.get('views',[]) if v.get('folder_id') in used|{'*',''}]}
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as archive:
        for index,folder in enumerate(folders):
            settings=validate_model(folder);metadata=read(folder/'metadata.json',{})
            manifest['models'].append(dict(id=folder.name,name=metadata.get('display_name',settings['name']),parent_id=settings.get('parent_id','')))
            manifest['models'][-1]['hd_cache_included']=False
            for path in members[folder]:
                relative=path.relative_to(folder)
                file='models/'+folder.name+'/'+relative.as_posix()
                checksum=hashlib.sha256()
                with path.open('rb') as src, archive.open(file,'w',force_zip64=True) as dst:
                    while block:=src.read(4*1024**2):
                        checksum.update(block);dst.write(block)
                manifest['files'].append(dict(path=file,bytes=archive.getinfo(file).file_size,sha256=checksum.hexdigest()))
            notify((index+1)/max(1,len(folders))*.9,'Packing '+manifest['models'][-1]['name'])
        payload=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
        if len(payload)>MAX_MANIFEST:raise ValueError('Archive manifest is too large.')
        check_budget(sum(e['bytes'] for e in manifest['files'])+len(payload),len(inventory)+1)
        archive.writestr('trellis-collection.json',payload)
    verified=inspect(destination)
    with zipfile.ZipFile(destination) as archive:
        for entry in verified['files']:
            with archive.open(entry['path']) as stream:
                checksum=hashlib.sha256()
                for block in iter(lambda:stream.read(4*1024**2),b''):checksum.update(block)
                if checksum.hexdigest()!=entry['sha256']:raise ValueError('Archive checksum mismatch: '+entry['path'])
    return verified

def inspect(path):
    if Path(path).stat().st_size>MAX_TOTAL:raise ValueError('Archive exceeds 12 GB.')
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        check_budget(sum(i.file_size for i in entries),len(entries))
        names=set();folded=set()
        for info in entries:
            p=PurePosixPath(info.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or ':' in info.filename or stat.S_ISLNK(info.external_attr>>16) or info.filename.casefold() in folded or any(part.endswith((' ','.')) or len(part)>180 or re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?',part,re.I) for part in p.parts):raise ValueError('Unsafe or duplicate archive path.')
            names.add(info.filename);folded.add(info.filename.casefold())
        if 'trellis-collection.json' not in names:raise ValueError('Choose a TRELLIS collection archive.')
        info=archive.getinfo('trellis-collection.json')
        if info.file_size>MAX_MANIFEST:raise ValueError('Archive manifest is too large.')
        data=json.loads(archive.read(info))
        if data.get('format')!='trellis-collection' or data.get('version')!=1:raise ValueError('Unsupported collection format.')
        models=data.get('models',[]);ids=[m['id'] for m in models]
        if not 1<=len(ids)<=500 or len(set(ids))!=len(ids) or any(not ID.fullmatch(i) for i in ids):raise ValueError('Invalid model list.')
        parents={m['id']:m.get('parent_id','') for m in models}
        for identifier in ids:
            seen=set();cursor=identifier
            while cursor in parents:
                if cursor in seen:raise ValueError('Cyclic model lineage.')
                seen.add(cursor);cursor=parents[cursor]
        workspace=data.get('workspace',{});folders=workspace.get('folders',[]);views=workspace.get('views',[]);profiles=data.get('profiles',[])
        if not isinstance(folders,list) or len(folders)>500 or not isinstance(views,list) or len(views)>100 or not isinstance(profiles,list) or len(profiles)>200:raise ValueError('Invalid workspace catalogue.')
        from studio_workspace import name
        catalog={f['id']:f for f in folders}
        if len(catalog)!=len(folders):raise ValueError('Duplicate folder IDs.')
        for f in folders:
            name(f['name']);identifier=f['id'];parent=f.get('parent_id','')
            if not ID.fullmatch(identifier) or parent and parent not in catalog:raise ValueError('Invalid folder hierarchy.')
            seen={identifier}
            while parent:
                if parent in seen:raise ValueError('Cyclic folder hierarchy.')
                seen.add(parent);parent=catalog[parent].get('parent_id','')
        for v in views:
            name(v['name'])
            if any(not isinstance(v.get(k),str) or len(v[k])>160 for k in ('query','filter','folder_id')) or v['folder_id'] not in {'*','',*catalog}:raise ValueError('Invalid saved view.')
        from generation_profiles import validate_recipe
        seen_ids=set()
        custom=0
        for p in profiles:
            identifier=p.get('id') if isinstance(p,dict) else None
            if not isinstance(identifier,str) or not identifier or len(identifier)>100 or identifier in seen_ids:
                raise ValueError('Invalid collection profile list.')
            seen_ids.add(identifier)
            if p.get('builtin') is True:
                # Workflow presets have a different settings schema. Their local
                # definitions remain authoritative when restoring the collection.
                continue
            custom+=1
            if custom>100:raise ValueError('Invalid collection profile list.')
            validate_recipe(dict(name=p['name'],settings=p['settings']))
        expected={'trellis-collection.json'}
        for entry in data['files']:
            p=PurePosixPath(entry['path'])
            if len(p.parts)<3 or p.parts[0]!='models' or p.parts[1] not in ids or p.suffix.lower() not in EXTENSIONS or any(part in EXCLUDED or part.startswith('.') for part in p.parts):raise ValueError('Unsupported collection file.')
            info=archive.getinfo(entry['path'])
            if info.file_size!=entry['bytes'] or not re.fullmatch('[a-f0-9]{64}',entry['sha256']):raise ValueError('Archive file size or hash is invalid.')
            if entry['path'] in expected:raise ValueError('Duplicate manifest file.')
            expected.add(entry['path'])
        if names!=expected:raise ValueError('Archive contains unlisted files.')
        for identifier in ids:
            for required in ('settings.json','model.glb'):
                if f'models/{identifier}/{required}' not in expected:raise ValueError('A model is incomplete.')
        return data

def extract(path,target,data):
    target=Path(target).resolve();target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for entry in data['files']:
            destination=(target/entry['path']).resolve()
            if not destination.is_relative_to(target):raise ValueError('Archive target rejected.')
            destination.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry['path']) as src,destination.open('wb') as dst:shutil.copyfileobj(src,dst,4*1024*1024)
            if digest(destination)!=entry['sha256']:raise ValueError('Archive checksum mismatch: '+entry['path'])
    for entry in data['models']:
        validate_model(target/'models'/entry['id'])
    return target/'models'
