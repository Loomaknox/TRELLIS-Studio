"""Bounded, per-workspace change hints. Records are always read through the usual job reader."""
import hashlib
import os
import stat
from collections import OrderedDict
from threading import Lock

from studio_workspace import ID


def index(output):
    rows = {}
    with os.scandir(output) as folders:
        for folder in folders:
            if not ID.fullmatch(folder.name):
                continue
            try:
                if not folder.is_dir(follow_symlinks=False):
                    continue
                info = folder.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            rows[folder.name] = info.st_mtime_ns
    revision = hashlib.blake2s(repr(sorted(rows.items())).encode(), digest_size=12).hexdigest()
    return revision, rows


class CollectionHistory:
    def __init__(self):
        self.history = OrderedDict()
        self.lock = Lock()

    def changes(self, output, read_record, since=None, watch=(), review_after=None):
        revision, rows = index(output)
        with self.lock:
            old = self.history.get(since)
            self.history[revision] = rows
            self.history.move_to_end(revision)
            if len(self.history) > 4:
                self.history.popitem(last=False)
        order = sorted(rows, key=lambda key: (-rows[key], key))
        refresh = set(watch)
        cursor = None
        if old is not None and review_after is not None:
            # Bound occasional checks of nested files independently of collection size.
            remainder = sorted(key for key in rows if key > review_after)
            refresh.update(remainder[:32])
            cursor = remainder[31] if len(remainder) > 32 else ''
        changes, unavailable = [], []
        for key in order:
            if old is not None and old.get(key) == rows[key] and key not in refresh:
                continue
            folder = output / key
            if folder.resolve().parent != output:
                unavailable.append(key)
                continue
            record = read_record(folder)
            if record is None:
                unavailable.append(key)
            else:
                changes.append(record)
        return dict(revision=revision, full=old is None, order=order if old is None or since != revision else None,
                    changes=changes, unavailable=unavailable, review_after=cursor)
