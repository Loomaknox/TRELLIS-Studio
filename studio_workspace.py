"""Local workspace records, queue ordering and immutable model checkpoints."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib,json,re,shutil,time,uuid

ID=re.compile(r'^[a-f0-9]{32}$')
def read(path,default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).is_file() else default
def job_status(folder, default=None):
    try:
        value = json.loads((Path(folder)/'status.json').read_text(encoding='utf-8'))
        if not isinstance(value, dict) or not isinstance(value.get('state'), str):
            raise ValueError('Invalid job status.')
        return value
    except FileNotFoundError:
        return default if default is not None else {}
    except (ValueError, OSError):
        return dict(state='error', stage='Unreadable job status', progress=0,
                    error='The saved job status could not be read.', status_unreadable=True)
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    # A Windows reader can briefly hold the destination without delete sharing.
    for attempt in range(30):
        try:temp.replace(path);break
        except PermissionError:
            if attempt==29:raise
            time.sleep(.02)
def name(value,limit=80):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):raise ValueError('Choose a name of 1–'+str(limit)+' characters.')
    return value.strip()

def finishing_source(folder, settings):
    linked_cache = settings.get('source_kind') in ('refinish', 'multiview_texture_refinement')
    identifier = settings.get('finish_source_id') if linked_cache else folder.name
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        return None
    source = folder.parent / identifier
    cache = source / 'raw_state.pt'
    if source.resolve().parent == folder.parent and not cache.is_symlink() and cache.is_file():
        return identifier
    return None


class Workspace:
    def __init__(self,root,job_folder=None):
        self.root=Path(root);self.path=self.root/'workspace.json';self.queue_path=self.root/'queue.json'
        self.job_folder=job_folder
        self.compact_after=2000
        self.data=read(self.path,dict(version=1,folders=[],views=[]))
        self.queue=read(self.queue_path,dict(version=1,paused=False,items=[]))
    def save(self):write(self.path,self.data)
    def save_queue(self):write(self.queue_path,self.queue)
    def folder(self,identifier):
        if identifier=='':return None
        result=next((f for f in self.data['folders'] if f['id']==identifier),None)
        if result is None:raise ValueError('Folder not found.')
        return result
    def save_folder(self,raw,identifier=None):
        title=name(raw.get('name'));parent=raw.get('parent_id','');self.folder(parent)
        if identifier:
            current=self.folder(identifier);cursor=parent
            while cursor:
                if cursor==identifier:raise ValueError('A folder cannot contain itself.')
                cursor=self.folder(cursor)['parent_id']
            current.update(name=title,parent_id=parent)
        else:
            if len(self.data['folders'])>=500:raise ValueError('Folder limit reached.')
            current=dict(id=uuid.uuid4().hex,name=title,parent_id=parent,created=time.time());self.data['folders'].append(current)
        self.save();return current
    def save_view(self,raw,identifier=None):
        value=dict(name=name(raw.get('name')),query=raw.get('query',''),filter=raw.get('filter','all'),folder_id=raw.get('folder_id','*'))
        if any(not isinstance(value[k],str) or len(value[k])>160 for k in ('query','filter','folder_id')):raise ValueError('Invalid saved view.')
        if value['folder_id']!='*':self.folder(value['folder_id'])
        if identifier:
            current=next((v for v in self.data['views'] if v['id']==identifier),None)
            if current is None:raise ValueError('Saved view not found.')
            current.update(value)
        else:
            if len(self.data['views'])>=100:raise ValueError('Saved view limit reached.')
            current=dict(id=uuid.uuid4().hex,**value);self.data['views'].append(current)
        self.save();return current
    def enqueue(self,identifier,priority=0,held=False):
        self.enqueue_many([identifier], priority, held)

    def enqueue_many(self, identifiers, priority=0, held=False):
        if type(priority) is not int or not -2<=priority<=2:raise ValueError('Priority must be between -2 and 2.')
        previous = self.queue['items']
        items = previous.copy()
        compacted=len(previous)>=self.compact_after and self.job_folder is not None
        if compacted:
            keep = []
            for item in previous[:-1000]:
                status = job_status(self.job_folder(item['id']))
                if status.get('status_unreadable') or status.get('state') not in ('done','error','cancelled'):
                    keep.append(item)
            items = keep + previous[-1000:]
        items.extend(dict(id=identifier, priority=priority, held=held, created=time.time()) for identifier in identifiers)
        self.queue['items'] = items
        try:
            self.save_queue()
            if compacted:self.compact_after=max(2000,len(items)+1000)
        except OSError:
            self.queue['items'] = previous
            raise
    def pending(self,identifier):return any(i['id']==identifier and not i.get('cancelled') for i in self.queue['items'])
    def ordered(self):return sorted(self.queue['items'],key=lambda i:(-i['priority'],i['created']))

SNAPSHOT_FILES=('model.glb','model.blend','settings.json','metadata.json','result.json','physics.json','lod-manifest.json','motion-report.json','presentation.json')
SNAPSHOT_DIRS=('LODs','Collisions','Presentation')
def file_digest(path):
    with Path(path).open('rb') as stream:
        checksum=hashlib.sha256()
        for block in iter(lambda:stream.read(4*1024*1024),b''):
            checksum.update(block)
        return checksum.hexdigest()

def copy_snapshot(folder, target):
    for filename in SNAPSHOT_FILES:
        if (folder/filename).is_file():shutil.copy2(folder/filename,target/filename)
    for dirname in SNAPSHOT_DIRS:
        if (folder/dirname).is_dir():shutil.copytree(folder/dirname,target/dirname)

def checkpoint(folder,label,operation='checkpoint'):
    folder=Path(folder)
    label=name(label,100)
    if not (folder/'model.glb').is_file():raise ValueError('This model has no completed geometry.')
    identifier=uuid.uuid4().hex
    parent=folder/'Revisions';parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='.checkpoint-',dir=parent) as temp:
        target=Path(temp)/identifier;target.mkdir()
        copy_snapshot(folder,target)
        digest=file_digest(target/'model.glb')
        if digest!=file_digest(folder/'model.glb'):raise ValueError('Checkpoint model checksum mismatch.')
        entry=dict(id=identifier,label=label,operation=operation,created=time.time(),sha256=digest,bytes=sum(p.stat().st_size for p in target.rglob('*') if p.is_file()))
        write(target/'revision.json',entry)
        target.rename(parent/identifier)
    return entry

def restore_checkpoint(folder, revision, references):
    source=folder/'Revisions'/revision
    entry=read(source/'revision.json')
    if not isinstance(entry,dict) or entry.get('id')!=revision:
        raise ValueError('Invalid checkpoint manifest.')
    identifier=uuid.uuid4().hex
    with TemporaryDirectory(prefix='.restore-',dir=folder.parent) as temp:
        target=Path(temp)/identifier;target.mkdir()
        copy_snapshot(source,target)
        if not (target/'model.glb').is_file() or file_digest(target/'model.glb')!=entry.get('sha256'):
            raise ValueError('Checkpoint model checksum mismatch.')
        for filename in references:
            if (folder/filename).is_file():shutil.copy2(folder/filename,target/filename)
        settings=read(target/'settings.json')
        if not isinstance(settings,dict) or not isinstance(settings.get('name'),str):
            raise ValueError('Invalid checkpoint settings.')
        settings.update(parent_id=folder.name,created=time.time(),restored_revision=revision,source_kind='restored')
        write(target/'settings.json',settings)
        metadata=read(target/'metadata.json',{})
        metadata['display_name']=(metadata.get('display_name',settings['name'])+' · restored')[:80]
        write(target/'metadata.json',metadata)
        write(target/'status.json',dict(state='done',stage='Checkpoint restored as new version',progress=100,result=read(target/'result.json',{})))
        target.rename(folder.parent/identifier)
    return dict(id=identifier)
def revisions(folder):
    return sorted([read(p) for p in (Path(folder)/'Revisions').glob('*/revision.json')],key=lambda r:r['created'],reverse=True)
