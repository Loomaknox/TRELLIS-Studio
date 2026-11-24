"""Make a static print derivative in a private Blender process; never change its parent."""
from pathlib import Path
import json,subprocess,sys,time,traceback
from print_prepare import verify_stl
from studio_import import find_blender,validate_glb

ROOT=Path(__file__).resolve().parent;JOB=Path(sys.argv[1]).resolve();started=time.time()
def status(state,stage,progress,**extra):
    path=JOB/'status.tmp'
    path.write_text(json.dumps(dict(state=state,stage=stage,progress=progress,elapsed=round(time.time()-started,1),**extra)),encoding='utf-8')
    path.replace(JOB/'status.json');print(stage,flush=True)
try:
    status('running','Rebuilding a static surface for printing',10)
    process=subprocess.Popen([str(find_blender()),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
        '--python',str(ROOT/'print_blender.py'),'--',str(JOB)],stdout=sys.stdout,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:code=process.wait(timeout=600)
    except subprocess.TimeoutExpired:
        process.kill();process.wait();raise RuntimeError('Print preparation exceeded 10 minutes. Try a coarser voxel size.')
    if code:raise RuntimeError('Print preparation failed. The original model is unchanged; see this copy’s log.')
    status('running','Checking exported STL topology and dimensions',92)
    report=json.loads((JOB/'print-report.json').read_text(encoding='utf-8'))
    verify_stl(JOB/'model.stl',report)
    (JOB/'print-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    validate_glb(JOB/'model.glb')
    result=json.loads((JOB/'result.json').read_text(encoding='utf-8'));result['print_report']=report
    (JOB/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    settings=json.loads((JOB/'settings.json').read_text(encoding='utf-8'));settings.update(triangles=result['triangles'],height_m=result['height_m'])
    (JOB/'settings.json').write_text(json.dumps(settings,indent=2),encoding='utf-8')
    status('done','Print copy prepared · review in your slicer' if report['closed_surface'] else 'Print copy needs repair',100,result=result)
except Exception as error:
    traceback.print_exc();status('error','Print preparation failed',0,error=str(error))
