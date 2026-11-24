"""Validated, bounded settings for an explicitly separate print derivative."""
import math
import hashlib

def validate_options(data):
    if not isinstance(data,dict) or set(data)-{'height_mm','voxel_mm','measure_walls'}:raise ValueError('Unknown print setting.')
    result={}
    for key,default,low,high in [('height_mm',120,20,500),('voxel_mm',.4,.15,2)]:
        value=data.get(key,default)
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ValueError('Invalid '+key)
        result[key]=float(value)
    if 'measure_walls' in data:
        if type(data['measure_walls']) is not bool:raise ValueError('Invalid wall measurement setting.')
        result['measure_walls']=data['measure_walls']
    return result


def verify_stl(path, report):
    import trimesh
    mesh = trimesh.load(path, force='mesh', process=True)
    report.update(stl_watertight=bool(mesh.is_watertight), stl_winding_consistent=bool(mesh.is_winding_consistent),
                  stl_dimensions_mm=mesh.extents.tolist(), stl_volume_mm3=float(mesh.volume), stl_triangles=len(mesh.faces))
    report['closed_surface'] = bool(report['boundary_edges'] == report['nonmanifold_edges'] == report['nonmanifold_vertices'] == 0
                                    and mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0)
    if not report['closed_surface']:
        report['warnings'].append('The surface still needs repair before slicing. Review the topology report.')
    with path.open('rb') as stream:
        report['stl_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return report
