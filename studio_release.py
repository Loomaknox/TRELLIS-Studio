"""Read release metadata for the optional notification in the Studio header."""
from html import escape
from http.client import HTTPException
import json
import re
from threading import Lock
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from studio_version import VERSION


REPOSITORY = 'yoslo59/TRELLIS-Studio'
LATEST_RELEASE = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
RELEASE_PAGE = f'https://github.com/{REPOSITORY}/releases/tag/'
VERSION_PATTERN = re.compile(r'v?(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})'
                             r'(-[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)?(?:\+[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)?')
SUCCESS_TTL = 24 * 60 * 60
FAILURE_TTL = 60 * 60
MAX_METADATA_BYTES = 512 * 1024
UI_REVISION = f'{VERSION}-figure-master-ultratex'


def render_studio_version(page, *, ui_revision=None):
    version = escape(VERSION)
    revision = escape(ui_revision) if ui_revision is not None else version
    return page.replace('<!--studio-current-version-->', version, 1).replace('<!--studio-ui-revision-->', revision, 1)


def _version(value):
    match = VERSION_PATTERN.fullmatch(value) if isinstance(value, str) and len(value) <= 80 else None
    return (tuple(int(number) for number in match.groups()[:3]), match[4] is None) if match else None


def _notification(current, release):
    if not isinstance(release, dict) or release.get('draft') is not False or release.get('prerelease') is not False:
        raise ValueError('Expected a published stable release.')
    tag = release.get('tag_name')
    latest = _version(tag)
    if latest is None or not latest[1] or '+' in tag or release.get('html_url') != RELEASE_PAGE + tag:
        raise ValueError('Invalid stable release metadata.')
    if current is not None and latest > current:
        return {'version': tag.removeprefix('v'), 'url': release['html_url']}
    return None


class ReleaseCheck:
    def __init__(self, current, *, clock=monotonic, open_url=urlopen):
        self.current = current
        self.clock = clock
        self.open_url = open_url
        self.lock = Lock()
        self.expires = 0
        self.etag = None
        self.last_verified = None
        self.update = None

    def _refresh(self):
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10',
                   'User-Agent': 'TRELLIS-Studio-Release-Check'}
        if self.etag:
            headers['If-None-Match'] = self.etag
        try:
            with self.open_url(Request(LATEST_RELEASE, headers=headers), timeout=3) as response:
                payload = response.read(MAX_METADATA_BYTES + 1)
                if len(payload) > MAX_METADATA_BYTES:
                    raise ValueError('Release metadata exceeds the size limit.')
                self.last_verified = _notification(_version(self.current), json.loads(payload))
                self.etag = response.headers.get('ETag')
        except HTTPError as error:
            error.close()
            if error.code != 304 or not self.etag:
                raise
        return self.last_verified

    def status(self):
        with self.lock:
            if self.clock() >= self.expires:
                try:
                    self.update = self._refresh()
                except (OSError, HTTPException, ValueError, RecursionError):
                    self.update = None
                    self.expires = self.clock() + FAILURE_TTL
                else:
                    self.expires = self.clock() + SUCCESS_TTL
            return {'current_version': self.current, 'update': self.update}


release_status = ReleaseCheck(VERSION).status
