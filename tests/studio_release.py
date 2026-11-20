"""Check stable release selection, the shared cache and offline behavior."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_release import FAILURE_TTL, LATEST_RELEASE, MAX_METADATA_BYTES, RELEASE_PAGE, SUCCESS_TTL, ReleaseCheck, render_studio_version


def release(tag, **updates):
    return {'tag_name': tag, 'html_url': RELEASE_PAGE + tag, 'draft': False, 'prerelease': False, **updates}


def response(data, etag='"fixture-etag"'):
    result = BytesIO(data if isinstance(data, bytes) else json.dumps(data).encode())
    result.headers = {'ETag': etag}
    return result


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.clock = 1
        self.open_url = Mock()

    def checker(self, current='3.9.9'):
        return ReleaseCheck(current, clock=lambda: self.clock, open_url=self.open_url)

    def test_page_revision_and_header_follow_the_runtime_version(self):
        page = (Path(__file__).resolve().parents[1] / 'web/studio.html').read_text(encoding='utf-8')
        for version in ('3.10.0', '4.12.3'):
            with self.subTest(version=version), patch('studio_release.VERSION', version):
                rendered = render_studio_version(page)
                self.assertIn(f'<meta name="trellis-ui-revision" content="{version}">', rendered)
                self.assertIn(f'title="Installed Studio version">{version}</span>', rendered)
                self.assertNotIn('<!--studio-ui-revision-->', rendered)
                self.assertNotIn('<!--studio-current-version-->', rendered)

    def test_numeric_and_prerelease_versions(self):
        for current, tag, expected in (
                ('3.9.9', 'v3.10.0', '3.10.0'), ('3.10.0', 'v3.9.12', None),
                ('3.10.0', 'v3.10.0', None), ('3.10.0+local.1', 'v3.10.0', None),
                ('3.10.0-rc.2', 'v3.10.0', '3.10.0'), ('custom', 'v3.10.0', None)):
            with self.subTest(current=current, tag=tag):
                self.open_url.return_value = response(release(tag))
                actual = self.checker(current).status()
                self.assertEqual(actual['current_version'], current)
                self.assertEqual(actual['update'], {'version': expected, 'url': RELEASE_PAGE + tag} if expected else None)

    def test_non_stable_or_unexpected_github_metadata_is_hidden(self):
        for data in (release('v3.10.0', draft=True), release('v3.10.0', prerelease=True), release('v3.10.0-rc.1'),
                     release('v3.10.0', html_url='https://example.org/files'), release('v3.010.0'),
                     release('v3.10.0', html_url=RELEASE_PAGE + 'wrong-version'),
                     b'not JSON', b'x' * (MAX_METADATA_BYTES + 1)):
            with self.subTest(kind=type(data).__name__):
                self.open_url.return_value = response(data)
                self.assertIsNone(self.checker().status()['update'])

    def test_shared_daily_cache_and_conditional_lookup(self):
        self.open_url.side_effect = [response(release('v3.10.0')),
                                     HTTPError(LATEST_RELEASE, 304, '', {}, BytesIO())]
        lookup = self.checker()
        with ThreadPoolExecutor(max_workers=6) as executor:
            statuses = list(executor.map(lambda _: lookup.status(), range(12)))
        self.assertEqual(self.open_url.call_count, 1)
        self.assertTrue(all(status == statuses[0] for status in statuses))
        self.clock += SUCCESS_TTL - 1
        self.assertEqual(statuses[0], lookup.status())
        self.assertEqual(self.open_url.call_count, 1)
        self.clock += 1
        self.assertEqual(statuses[0], lookup.status())
        request = self.open_url.call_args.args[0]
        self.assertEqual(request.full_url, LATEST_RELEASE)
        self.assertEqual(request.get_header('If-none-match'), '"fixture-etag"')
        self.assertFalse(request.has_header('Authorization'))
        self.assertFalse(request.has_header('Cookie'))
        self.assertEqual(self.open_url.call_args.kwargs['timeout'], 3)

    def test_failed_check_is_quiet_and_retries_after_failure_ttl(self):
        self.open_url.side_effect = [URLError('offline'), response(release('v3.10.0'))]
        lookup = self.checker()
        self.assertEqual(lookup.status(), {'current_version': '3.9.9', 'update': None})
        self.clock += FAILURE_TTL - 1
        self.assertIsNone(lookup.status()['update'])
        self.assertEqual(self.open_url.call_count, 1)
        self.clock += 1
        self.assertIsNotNone(lookup.status()['update'])
        self.assertEqual(self.open_url.call_count, 2)


if __name__ == '__main__':
    unittest.main()
