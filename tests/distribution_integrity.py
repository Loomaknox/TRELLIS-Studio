"""Validate the hashes and provenance used by the Windows distribution."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from studio_version import VERSION,build_identity


class Distribution(unittest.TestCase):
    def test_native_component_wheels_cover_documented_versions(self):
        for name in ('hi3d','pixal3d','facial-head'):
            base=ROOT/'installer'
            pins=(base/f'requirements-{name}.txt').read_text().splitlines()
            locked=(base/'locks'/f'{name}-win-cp311.txt').read_text().splitlines()
            def normalized(value):
                return re.sub('[-_.]+','-',value).lower()
            expected={normalized(p) for p in pins if p.strip() and not p.startswith('#')}
            found=set()
            for line in locked:
                if line.startswith('#'):continue
                match=re.fullmatch(r'([\w.-]+==[\w.+-]+) --hash=sha256:[a-f0-9]{64}',line)
                self.assertIsNotNone(match,line)
                found.add(normalized(match[1]))
            self.assertTrue(expected.issubset(found),f'{name}: {expected-found}')

    def test_wheelhouse_matches_both_windows_environments(self):
        locks=ROOT/'installer/locks'
        manifest=json.loads((locks/'offline-workshop-win-cp311.json').read_text())
        expected=set()
        for name in ('workshop','mcp'):
            for line in (locks/f'{name}-win-cp311.txt').read_text().splitlines():
                if line.startswith('#'):continue
                match=re.fullmatch(r'[\w.-]+==[\w.+-]+ --hash=sha256:([a-f0-9]{64})',line)
                self.assertIsNotNone(match,line)
                expected.add(match[1])
        self.assertEqual(expected,{w['sha256'] for w in manifest['wheels']})
        self.assertEqual(len(expected),len(manifest['wheels']))
        self.assertTrue(all(w['bytes']>0 and Path(w['path']).name==w['path'] for w in manifest['wheels']))

    def test_existing_packages_keep_payload_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bundled-web.json'
            p.write_text(json.dumps(dict(version=VERSION,source_revision='a'*64)))
            legacy=build_identity(p.parent)
            self.assertIsNone(legacy['fork_commit'])
            self.assertEqual(legacy['package_payload_sha256'],'a'*64)
            p.write_text(json.dumps(dict(version=VERSION,source_revision='a'*64,fork_commit='b'*40,source_modified=False)))
            self.assertEqual(build_identity(p.parent),dict(upstream_version=VERSION,fork_commit='b'*40,
                package_payload_sha256='a'*64,package_source_modified=False))

    def test_actions_pinned(self):
        for workflow in (ROOT/'.github/workflows').glob('*.yml'):
            for action in re.findall(r'\buses:\s*([^\s#]+)',workflow.read_text()):
                if action.startswith('./'):continue
                self.assertRegex(action,r'@[a-f0-9]{40}$',str(workflow))


if __name__=='__main__':
    unittest.main()
