"""Save or reattach a trusted local HD cache alongside a portable Studio backup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio_transfer import MAX_TOTAL, staging_directory
from studio_workspace import ID, file_digest


def checked_model(directory):
    folder=staging_directory(directory)
    if not folder or not ID.fullmatch(folder.name) or not (folder/'model.glb').is_file():
        raise ValueError('Select the model directory in a local Studio collection.')
    if (folder/'model.glb').resolve()!=folder/'model.glb':raise ValueError('Redirected model.')
    return folder


def save(model, destination):
    model=checked_model(model)
    cache=model/'raw_state.pt'
    destination=Path(destination).absolute()
    if not staging_directory(destination.parent) or destination.exists():
        raise ValueError('Choose a new backup directory under an existing local directory.')
    if cache.resolve()!=cache or not cache.is_file() or not 0<cache.stat().st_size<=MAX_TOTAL:
        raise ValueError('This model has no supported local HD master cache.')
    with TemporaryDirectory(dir=destination.parent) as work:
        bundle=Path(work)/'bundle'
        bundle.mkdir()
        model_hash=file_digest(model/'model.glb')
        shutil.copyfile(cache,bundle/'raw_state.pt')
        receipt=dict(schema=1,model_sha256=model_hash,bytes=cache.stat().st_size,
                     cache_sha256=file_digest(bundle/'raw_state.pt'))
        if receipt['cache_sha256']!=file_digest(cache) or model_hash!=file_digest(model/'model.glb'):
            raise ValueError('The master or its cache changed during backup.')
        (bundle/'receipt.json').write_text(json.dumps(receipt,sort_keys=True),encoding='utf-8')
        digest=file_digest(bundle/'receipt.json')
        bundle.rename(destination)
        return digest


def restore(model, bundle, expected):
    model=checked_model(model)
    bundle=staging_directory(bundle)
    if not bundle or any((bundle/n).resolve()!=bundle/n for n in ('receipt.json','raw_state.pt')):
        raise ValueError('Invalid local cache directory.')
    receipt=bundle/'receipt.json'
    if receipt.stat().st_size>4096:raise ValueError('Invalid cache receipt.')
    raw=receipt.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('The trusted backup receipt does not match.')
    record=json.loads(raw)
    if record['schema']!=1 or record['model_sha256']!=file_digest(model/'model.glb'):
        raise ValueError('The verified cache belongs to a different model.')
    if not 0<record['bytes']<=MAX_TOTAL or (bundle/'raw_state.pt').stat().st_size!=record['bytes']:
        raise ValueError('Invalid cache length.')
    with TemporaryDirectory(dir=model) as work:
        staged=Path(work)/'cache'
        shutil.copyfile(bundle/'raw_state.pt',staged)
        if file_digest(staged)!=record['cache_sha256']:raise ValueError('Cache checksum mismatch.')
        cache=model/'raw_state.pt'
        if cache.exists():
            if cache.resolve()==cache and file_digest(cache)==record['cache_sha256']:return
            raise ValueError('A different cache is already present.')
        # Windows rename and POSIX link both fail if a concurrent writer published first.
        if os.name=='nt':staged.rename(cache)
        else:cache.hardlink_to(staged)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='operation',required=True)
    for name in ('save','restore'):
        sub=commands.add_parser(name)
        sub.add_argument('model',type=Path)
        sub.add_argument('bundle',type=Path)
        if name=='restore':sub.add_argument('--receipt',required=True,help='SHA-256 retained separately at backup time')
    args=parser.parse_args()
    if args.operation=='save':print(save(args.model,args.bundle))
    else:restore(args.model,args.bundle,args.receipt)
