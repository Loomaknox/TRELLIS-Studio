"""Data-only queue, checkpoint and collection recovery through isolated Desktop routes."""
import asyncio
import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from _support import isolated_workspace
from fastapi import HTTPException, UploadFile
from starlette.requests import Request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_transfer as transfer
from studio_workspace import Workspace,checkpoint,file_digest,job_status,read,restore_checkpoint,revisions,write


def glb():
    doc=json.dumps({'asset':{'version':'2.0'},'meshes':[{'primitives':[]}],
                    'animations':[{'name':'Walk','channels':[],'samplers':[]}]}).encode()
    doc+=b' '*(-len(doc)%4)
    return struct.pack('<4sIIII',b'glTF',2,20+len(doc),len(doc),0x4e4f534a)+doc


def fixture(folder,name):
    folder.mkdir(parents=True)
    (folder/'model.glb').write_bytes(glb())
    write(folder/'settings.json',dict(name=name,asset_type='imported'))
    write(folder/'metadata.json',dict(display_name=name))
    write(folder/'status.json',dict(state='done',stage='Ready',progress=100))


class WorkspaceRecovery(unittest.TestCase):
    def test_compaction_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            folder=lambda identifier:root/'outputs'/identifier
            ids=[format(i,'032x') for i in range(2002)]
            w=Workspace(root/'state',folder)
            for idx,state in ((0,'queued'),(1,'running'),(3,'done'),(4,'cancelled')):
                write(folder(ids[idx])/'status.json',dict(state=state))
            broken=folder(ids[2]);broken.mkdir();(broken/'status.json').write_bytes(b'{')
            w.enqueue_many(ids[:-1],held=True)
            w.queue['paused']=True
            w.enqueue(ids[-1])
            saved=Workspace(root/'state',folder).queue
            actual=[e['id'] for e in saved['items']]
            self.assertEqual(actual,ids[:3]+ids[5:])
            self.assertTrue(saved['paused'] and all(e['held'] for e in saved['items'][:-1]))
            self.assertTrue(job_status(broken)['status_unreadable'])
            model=folder('f'*32);fixture(model,'Recovery')
            original=file_digest(model/'model.glb')
            with self.assertRaises(ValueError):checkpoint(model,'')
            self.assertFalse((model/'Revisions').exists())
            with patch('studio_workspace.shutil.copy2',side_effect=OSError(28,'No space')):
                with self.assertRaises(OSError):checkpoint(model,'Disk full')
            self.assertEqual(list((model/'Revisions').iterdir()),[])
            version=checkpoint(model,'Good')
            restored=folder(restore_checkpoint(model,version['id'],())['id'])
            self.assertEqual(file_digest(restored/'model.glb'),original)
            (model/'Revisions'/version['id']/'model.glb').write_bytes(b'incomplete')
            before=set(model.parent.iterdir())
            with self.assertRaises(ValueError):restore_checkpoint(model,version['id'],())
            self.assertEqual(set(model.parent.iterdir()),before)
            self.assertEqual(file_digest(model/'model.glb'),original)
            self.assertEqual(revisions(model),[version])

    def test_bounds_and_expiry(self):
        transfer.check_budget(transfer.MAX_TOTAL,transfer.MAX_ENTRIES)
        for b,n in ((transfer.MAX_TOTAL+1,1),(1,transfer.MAX_ENTRIES+1)):
            with self.assertRaises(ValueError):transfer.check_budget(b,n)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);sources=root/'sources';model=sources/('a'*32);fixture(model,'Limits')
            (model/'raw_state.pt').write_bytes(b'excluded')
            items,_=transfer.collection_inventory([model],False)
            self.assertNotIn(model/'raw_state.pt',[path for _,path in items])
            with patch.object(transfer,'MAX_MANIFEST',1):
                with self.assertRaisesRegex(ValueError,'manifest'):transfer.build(sources,root/'test.tmp',{},[])
            preview=root/('b'*32);legacy=root/('c'*32)
            for p in (preview,legacy):(p/'verified').mkdir(parents=True)
            write(preview/'preview-lease.json',dict(expires_at=20))
            transfer.expire_transfer_previews(root,19)
            self.assertTrue((preview/'verified').is_dir())
            transfer.expire_transfer_previews(root,21)
            self.assertFalse((preview/'verified').exists())
            self.assertTrue((legacy/'verified').is_dir())

    def test_export_and_restore(self):
        def request(payload):
            async def receive():return {'type':'http.request','body':json.dumps(payload).encode()}
            return Request({'type':'http','method':'POST','headers':[]},receive)
        async def scenario(app,root):
            routes={route.name:route.endpoint for route in app.app.routes if hasattr(route,'endpoint')}
            parent=app.OUTPUT/('a'*32);child=app.OUTPUT/('b'*32)
            fixture(parent,'Parent');fixture(child,'Child')
            write(child/'settings.json',dict(name='Child',parent_id=parent.name,asset_type='imported'))
            checkpoint(child,'Archive revision')
            material=child/'material.png';material.write_bytes(b'fixture texture')
            (parent/'raw_state.pt').write_bytes(b'master cache')
            result=await app.create_export(request(dict(ids=[parent.name,child.name],target='library',include_revisions=True)))
            app.EXPORT_PROCESS.wait(timeout=40)
            task=app.EXPORT_ROOT/result['id'];status=app.export_status(result['id'])
            self.assertEqual(status['state'],'done',str(status))
            self.assertFalse((task/'sources').exists())
            self.assertFalse((task/'package.zip.tmp').exists())
            archive=task/'package.zip'
            with zipfile.ZipFile(archive) as zip_file:
                self.assertFalse(any(n.endswith('.pt') for n in zip_file.namelist()))
            async def inspect(raw):
                return await routes['transfer_inspect'](UploadFile(file=io.BytesIO(raw),filename='backup.zip'))
            with self.assertRaises(HTTPException):await inspect(b'incomplete archive')
            imports=app.STUDIO.workspace.root/'imports'
            self.assertEqual(list(imports.iterdir()),[])
            offline=root/'offline';offline.mkdir()
            for model in (parent,child):model.rename(offline/model.name)
            try:
                self.assertFalse(list(app.OUTPUT.iterdir()))
                preview=await inspect(archive.read_bytes())
                self.assertFalse((imports/preview['id']/'archive.zip').exists())
                result=await routes['transfer_restore'](preview['id'],request(dict(name='Restored collection')))
            finally:
                for model in (parent,child):(offline/model.name).rename(model)
            output={read(app.OUTPUT/i/'settings.json')['name']:app.OUTPUT/i for i in result['ids']}
            self.assertEqual(read(output['Child']/'settings.json')['parent_id'],output['Parent'].name)
            self.assertEqual(file_digest(output['Child']/'model.glb'),file_digest(child/'model.glb'))
            self.assertEqual(file_digest(output['Child']/'material.png'),file_digest(material))
            self.assertEqual(revisions(output['Child']),revisions(child))
            self.assertFalse((imports/preview['id']/'verified').exists())
            self.assertTrue((parent/'raw_state.pt').is_file())
            old=app.EXPORT_ROOT/('c'*32);old.mkdir()
            (old/'package').mkdir()
            write(old/'status.json',dict(state='done',target='glb'))
            write(old/'request.json',dict(target='glb',ids=[child.name]))
            app.export_status(old.name)
            self.assertTrue((old/'package').is_dir())
            # Cancel a real child process deterministically before it can pack.
            spawn=app.subprocess.Popen
            def waiting_worker(args,**kwargs):
                return spawn([sys.executable,'-c','import time; time.sleep(60)'],**kwargs)
            with patch.object(app.subprocess,'Popen',side_effect=waiting_worker):
                cancelled=await app.create_export(request(dict(ids=[child.name],target='glb')))
            await app.cancel_export(cancelled['id'])
            directory=app.EXPORT_ROOT/cancelled['id']
            self.assertEqual(app.export_status(cancelled['id'])['state'],'cancelled')
            self.assertFalse(any((directory/n).exists() for n in ('sources','package','package.zip.tmp','package.zip')))
            self.assertEqual(file_digest(child/'model.glb'),file_digest(output['Child']/'model.glb'))
            # The process can publish after a client starts a GET or a cancel.
            # Cross both boundaries deterministically with a real validated ZIP.
            finished=read(task/'status.json')
            working={**finished,'state':'running','progress':90,'stage':'Compressing export package'}
            def publish():
                write(task/'status.json',finished)
                return 0
            with patch.object(app,'EXPORT_TASK',task.name),patch.object(app,'EXPORT_SETTLED',task.name),patch.object(app,'EXPORT_PROCESS') as process:
                write(task/'status.json',working)
                process.poll.side_effect=publish
                self.assertEqual(app.export_status(task.name)['state'],'done')
                write(task/'status.json',working)
                process.poll.side_effect=None;process.poll.return_value=None
                with patch.object(app,'stop_export',side_effect=publish):
                    await app.cancel_export(task.name)
                self.assertEqual(read(task/'status.json')['state'],'done')
                # A killed worker can leave the ZIP atomically published before
                # its final JSON. Recover the correct items as well as the state.
                process.poll.return_value=0
                write(task/'status.json',working)
                recovered=app.export_status(task.name)
                self.assertEqual(recovered['state'],'done')
                self.assertEqual(recovered['items'],finished['items'])
                self.assertTrue(archive.is_file())
                archive.write_bytes(b'incomplete')
                write(task/'status.json',working)
                self.assertEqual(app.export_status(task.name)['state'],'error')

        with isolated_workspace('storage') as root:
            import app
            try:asyncio.run(scenario(app,root))
            finally:
                if app.EXPORT_PROCESS and app.EXPORT_PROCESS.poll() is None:app.stop_export()
                if app.EXPORT_LOG:app.EXPORT_LOG.close()


if __name__=='__main__':unittest.main(verbosity=2)
