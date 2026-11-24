import hashlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from installer import hd_cache_backup as cache
from installer.setup import fetch
from studio_transfer import export_staging_inventory, release_export_copy


class MaintenanceRecovery(unittest.TestCase):
    def test_orphan_preview_ownership(self):
        import collection_preview_renderer as renderer
        with TemporaryDirectory() as directory:
            root=Path(directory).resolve()/'cache'
            with patch.object(renderer,'_profile_root',return_value=root):
                with renderer._preview_profile() as active:
                    orphan=root/'preview-old';orphan.mkdir()
                    (orphan/'.trellis-profile').write_bytes(b'TRELLIS-collection-preview-v1')
                    unrelated=root/'preview-user';unrelated.mkdir()
                    renderer.cleanup_orphan_profiles()
                    self.assertTrue(active.parent.exists())
                    self.assertFalse(orphan.exists())
                    self.assertTrue(unrelated.exists())

    def test_interrupted_download(self):
        class Response(io.BytesIO):
            status=206
            headers={'Content-Range':'bytes 3-5/6'}
        with TemporaryDirectory() as directory:
            root=Path(directory);dest=root/'artifact';part=root/'artifact.part'
            entry=dict(bytes=6,sha256=hashlib.sha256(b'abcdef').hexdigest(),url='https://example.invalid/file')
            part.write_bytes(b'abc')
            with patch('urllib.request.urlopen',return_value=Response(b'def')) as network:
                fetch(entry,dest,root=root)
                self.assertEqual(network.call_args.args[0].headers['Range'],'bytes=3-')
            self.assertEqual(dest.read_bytes(),b'abcdef')
            dest.unlink()
            part.write_bytes(b'xxxxxx')
            full=Response(b'abcdef');full.status=200
            with patch('urllib.request.urlopen',return_value=full) as network:
                fetch(entry,dest,root=root)
                self.assertNotIn('Range',network.call_args.args[0].headers)
            dest.unlink();part.write_bytes(b'abc')
            full=Response(b'abcdef');full.status=200
            with patch('urllib.request.urlopen',side_effect=[HTTPError(entry['url'],416,'Range',{},None),full]),patch('time.sleep'):
                fetch(entry,dest,root=root)
            self.assertEqual(dest.read_bytes(),b'abcdef')

    def test_verified_legacy_copies(self):
        with TemporaryDirectory() as temporary:
            folder=Path(temporary).resolve()
            collection=folder/'collection'
            model=collection/('c'*32);model.mkdir(parents=True);(model/'model.glb').write_bytes(b'original')
            task=folder/'exports'/('d'*32)
            source=task/'sources'/model.name;source.mkdir(parents=True)
            (source/'model.glb').write_bytes(b'artist change')
            package=task/'package';package.mkdir();(package/'asset').write_bytes(b'packed')
            with zipfile.ZipFile(task/'package.zip','w') as zipf:zipf.writestr('asset',b'packed')
            (task/'status.json').write_text('{"state":"done"}')
            self.assertEqual(export_staging_inventory(task.parent,task.name),[])
            self.assertEqual(len(export_staging_inventory(task.parent)),2)
            with self.assertRaises(ValueError):release_export_copy(task,collection,'sources')
            self.assertTrue((source/'model.glb').is_file())
            release_export_copy(task,collection,'package')
            self.assertFalse(package.exists());self.assertTrue((task/'package.zip').is_file())

    def test_separate_trusted_cache(self):
        from studio_workspace import finishing_source
        with TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            master=root/('1'*32);restored=root/('2'*32)
            for path in (master,restored):
                path.mkdir();(path/'model.glb').write_bytes(b'same published model')
            (master/'raw_state.pt').write_bytes(b'cache bytes')
            bundle=root/'cache-backup'
            receipt=cache.save(master,bundle)
            self.assertIsNone(finishing_source(restored,{}))
            with self.assertRaises(ValueError):cache.restore(restored,bundle,'0'*64)
            cache.restore(restored,bundle,receipt)
            self.assertEqual(finishing_source(restored,{}),restored.name)
            cache.restore(restored,bundle,receipt)
            (bundle/'raw_state.pt').write_bytes(b'bad data!!!')
            with self.assertRaises(ValueError):cache.restore(restored,bundle,receipt)
            self.assertEqual((restored/'raw_state.pt').read_bytes(),b'cache bytes')


if __name__=='__main__':unittest.main(verbosity=2)
