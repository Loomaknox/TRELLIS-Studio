from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collection_sync import CollectionHistory, index


def check(output):
    history = CollectionHistory()
    calls = []
    def read(folder):
        calls.append(folder.name)
        return {'id': folder.name}

    ids = [f'{i:032x}' for i in range(100)]
    for key in ids:
        (output / key).mkdir()
    (output / 'user-files').mkdir()
    first = history.changes(output, read)
    assert first['full'] and set(calls) == set(ids)
    calls.clear()
    idle = history.changes(output, read, first['revision'])
    assert not idle['full'] and not idle['changes'] and not calls
    assert index(output)[0] == idle['revision'] and idle['order'] is None
    partial = history.changes(output, read, idle['revision'], review_after='')
    assert len(calls) == 32 and partial['review_after'] == ids[31] and partial['order'] is None
    calls.clear()
    os.utime(output / ids[0], ns=(1000000000, 1000000000))
    (output / ids[2]).rmdir()
    updated = history.changes(output, read, first['revision'], [ids[1]])
    assert set(calls) == {ids[0], ids[1]} and ids[2] not in updated['order']
    assert not updated['full'] and first['revision'] != updated['revision']
    unavailable = history.changes(output, lambda _: None, updated['revision'], [ids[1]])
    assert unavailable['unavailable'] == [ids[1]]
    # A new process or evicted cursor always returns a fresh complete view.
    assert CollectionHistory().changes(output, read, first['revision'])['full']


if __name__ == '__main__':
    with TemporaryDirectory() as temp:
        check(Path(temp).resolve())
    print('PASS collection snapshots, idle reads, changed and watched records, deletion and restart.')
