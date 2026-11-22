"""Regression: a fitted narrow A-pose remains animatable without accepting vertical arms."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from humanoid_mapping import infer_positions
data=json.loads(Path(__file__).with_suffix('.json').read_text())
points={b['name']:b['head'] for b in data};parents={b['name']:b['parent'] for b in data}
mapping=infer_positions(points,parents,(0,0,0),(1,1.8,1))
assert mapping.get('left_arm')=='bone_7' and mapping.get('right_forearm')=='bone_27'
assert mapping.get('right_hand')=='bone_28' and mapping.get('left_leg')=='bone_44'
vertical={k:list(v) for k,v in points.items()}
for name in ['bone_8','bone_9','bone_27','bone_28']:vertical[name][0]=.18 if name in ['bone_8','bone_9'] else -.18
assert not infer_positions(vertical,parents,(0,0,0),(1,1.8,1))
assert not infer_positions(points,{**parents,'bone_49':'bone_7'},(0,0,0),(1,1.8,1))
print('PASS: narrow A-pose, vertical-arm refusal and invalid topology refusal')
