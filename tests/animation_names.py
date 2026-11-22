"""Long Unicode/Kimodo names survive Blender-safe aliases without binary edits."""
from pathlib import Path
import json,struct,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio_import import blender_animation_source,rewrite_animation_names,validate_glb

def tail(path):
    raw=path.read_bytes()
    return raw[20+struct.unpack_from('<I',raw,12)[0]:]

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);source=root/'source.glb';safe=root/'safe.glb'
    names=['TS_walk_3.0s','Generated_12345678_'+('a'*60),'salut_'+('é'*40),'__TS_preserved_1']
    data={'asset':{'version':'2.0'},'meshes':[{'primitives':[]}],
          'animations':[{'name':name,'channels':[],'samplers':[]} for name in names]}
    desc=json.dumps(data,ensure_ascii=False).encode();desc+=b' '*(-len(desc)%4)
    payload=struct.pack('<II',16,0x004e4942)+b'opaque payload!!'
    source.write_bytes(struct.pack('<4sIIII',b'glTF',2,20+len(desc)+len(payload),len(desc),0x4e4f534a)+desc+payload)
    aliases=blender_animation_source(source,safe)
    result=validate_glb(safe)
    assert len(aliases)==2
    assert len({a['name'] for a in result['animations']})==len(names)
    assert all(len(a['name'].encode())<=58 for a in result['animations'])
    assert tail(source)==tail(safe)
    rewrite_animation_names(safe,safe,aliases)
    assert validate_glb(safe)==data
    assert tail(source)==tail(safe)
print('PASS: long names, UTF-8 byte limits, alias collisions and opaque binary preservation')
