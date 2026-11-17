"""Validated generation controls shared by the API, worker and studio schema."""
import math

TRIANGLE_MIN = 1_000
TRIANGLE_MAX = 8_000_000

DEFAULT_PROFILE = 'game_d'
HUMANOID_EXPERIMENTAL = 'humanoid_experimental'
DENSE_MASTER = 'dense_master'
DENSE_MASTER_NAME = 'Dense Master'
DENSE_MASTER_TRIANGLES = 1_200_000
MASTER_FINISHING_TRIANGLES = 3_000_000
MASTER_FINISHING_TEXTURE = 4096
MASTER_FINISHING_METHODS = ('wtivo_1024', 'studio_768')
DENSE_MASTER_FINISHING = dict(mesh_mode='direct', pre_simplify=False, repair_holes=False)
SURFACE_REPAIR_FINISHING = dict(mesh_mode='remesh', pre_simplify=False, repair_holes=True,
                                remesh_project=.45, remesh_band=1.)
HD_RECONSTRUCTION_FINISHING = dict(
    mesh_mode='remesh', pre_simplify=False, repair_holes=True, remesh_project=0.,
    remesh_band=1., remesh_resolution=768, qem_edge_weight=.01, qem_skinny_weight=.001,
)


def validate_hd_reconstruction(enabled, *, preset=None, resolution, repair_surface=False, refinish=False):
    if type(enabled) is not bool:
        raise ValueError('HD Reconstruction must be true or false.')
    if not enabled:
        return
    if repair_surface:
        raise ValueError('Choose either HD Reconstruction or Repair holes.')
    if not refinish and preset != DENSE_MASTER:
        raise ValueError('Choose Dense Master to use HD Reconstruction.')
    if resolution < HD_RECONSTRUCTION_FINISHING['remesh_resolution']:
        raise ValueError('HD Reconstruction requires a 1024 or 1536 geometry source.')


def validate_create_master_finishing(method, *, preset, resolution, triangles,
                                     repair_surface=False, hd_reconstruction=False):
    if method is None or method == '':
        return
    if method not in MASTER_FINISHING_METHODS:
        raise ValueError('Choose a supported master finishing method.')
    if preset != DENSE_MASTER or resolution < 1024:
        raise ValueError('Master finishing requires the HD Master profile at 1024 or higher.')
    if repair_surface or hd_reconstruction:
        raise ValueError('Choose one master finishing method.')
    if not TRIANGLE_MIN <= triangles <= MASTER_FINISHING_TRIANGLES:
        raise ValueError(f'Choose an HD Master triangle ceiling between {TRIANGLE_MIN:,} and {MASTER_FINISHING_TRIANGLES:,}.')


def master_finishing_options(method, options):
    if method == 'studio_768':
        return {**options, **HD_RECONSTRUCTION_FINISHING}
    if method == 'wtivo_1024':
        return {**options, **HD_RECONSTRUCTION_FINISHING, 'repair_holes': False, 'remesh_resolution': 1024}
    return options


GENERATION_PRESETS = {
    'game_d': (20, 28000, 2048), 'high_detail': (20, 250000, 2048),
    HUMANOID_EXPERIMENTAL: (20, 250000, 2048), DENSE_MASTER: (20, DENSE_MASTER_TRIANGLES, 2048),
    'fast': (8, 25000, 1024), 'balanced': (12, 50000, 2048), 'detail': (20, 100000, 2048),
}
DEFAULT_GENERATION = dict(preset=DEFAULT_PROFILE, resolution=1024, triangles=28000, texture_size=2048)

GROUPS = [
    dict(id='geometry',title='3D construction',hint='Zero steps uses the profile. Guidance strengthens the reference; excessive values can cause artifacts.'),
    dict(id='texture',title='Textures',hint='Material generation settings. A larger texture does not recreate missing geometry detail.'),
    dict(id='mesh',title='Mesh and simplification',hint='Simplification prioritises regions with lower shape error. Final triangle count is approximate.'),
    dict(id='uv',title='UV unwrapping',hint='Smaller angles create more UV islands. Review seams and stretching in Textures & UV.'),
]

def number(key,group,label,default,low,high,step=0.1,integer=False,hint=''):
    return dict(key=key,group=group,label=label,default=default,min=low,max=high,step=step,type='integer' if integer else 'number',hint=hint)

FIELDS=[]
for prefix,label,rescale,timing in [('structure','Structure',.7,5),('shape','Shape',.5,3)]:
    FIELDS += [
        number(prefix+'_steps','geometry',label+' · steps',0,0,50,1,True,'0 = profile step count.'),
        number(prefix+'_guidance','geometry',label+' · guidance',7.5,0,15,.1),
        number(prefix+'_rescale','geometry',label+' · rescale',rescale,0,1,.05,hint='Guidance rescale moderates excessive guidance.'),
        number(prefix+'_rescale_t','geometry',label+' · timestep distribution',timing,1,6,.1,hint='Changes how diffusion timesteps are distributed.'),
    ]
FIELDS += [
    number('texture_steps','texture','Texture · steps',0,0,50,1,True,'0 = profile step count.'),
    number('texture_guidance','texture','Texture · guidance',1,0,10,.1),
    number('texture_rescale','texture','Texture · rescale',0,0,1,.05),
    number('texture_rescale_t','texture','Texture · timestep distribution',3,1,6,.1),
    number('texture_seed','texture','Texture seed',-1,-1,2147483647,1,True,'-1 continues the generation random sequence; a separate seed allows independent material comparisons.'),
    dict(key='texture_sampling',group='texture',label='Material voxel interpolation',type='choice',default='trilinear',choices=[
        dict(value='trilinear',label='Trilinear (smooth)'),dict(value='nearest',label='Nearest voxel (experimental)')]),
    dict(key='mesh_mode',group='mesh',label='Mesh finishing method',type='choice',default='remesh',choices=[
        dict(value='remesh',label='Remesh and simplify'),dict(value='direct',label='Direct simplification')]),
    dict(key='pre_simplify',group='mesh',label='Pre-simplify dense meshes to 2M',type='boolean',default=True,
         hint='Disable to keep the raw surface for finishing, at a higher processing cost.'),
    dict(key='repair_holes',group='mesh',label='Fill small holes',type='boolean',default=False),
    number('remesh_project','mesh','Surface projection',0,0,1,.05,hint='0 = reconstructed surface; 1 = maximum projection toward the source surface.'),
    number('remesh_band','mesh','Remesh band width',1,.5,3,.1),
    number('remesh_resolution','mesh','Reconstruction grid ceiling',512,512,1024,256,True),
    number('qem_edge_weight','mesh','QEM · edge length',.01,0,.1,.00001,hint='0 prioritizes shape error; this can create large, elongated triangles on flat areas.'),
    number('qem_skinny_weight','mesh','QEM · skinny triangles',.001,0,.1,.00001,hint='Additional penalty for very thin triangles.'),
    number('uv_angle','uv','UV grouping angle',90,10,180,1,hint='Angle in degrees used to group surface regions before UV unwrapping.'),
    number('uv_refine','uv','UV island refinement',0,0,10,1,True),
    number('uv_global','uv','Global passes',1,1,5,1,True),
    number('uv_smooth','uv','UV island smoothing',1,0,1,.1),
]
HELP={'structure_steps': 'Diffusion steps for the initial volume. Zero uses the profile. More steps increase computation without guaranteeing a better model.', 'structure_guidance': 'How strongly the initial volume follows the reference image. Excessive guidance can distort the result.', 'structure_rescale': 'Regulates the amplitude of volume guidance. Higher values can change detail while reducing excessive guidance.', 'structure_rescale_t': 'Changes the timing distribution of volume diffusion steps without increasing their count.', 'shape_steps': 'Steps per geometry generation pass. Zero uses the profile. More steps take longer.', 'shape_guidance': 'Reference strength for geometry and surface detail. Excessive guidance may produce bumps or artifacts.', 'shape_rescale': 'Regulates geometry guidance when its strength is high.', 'shape_rescale_t': 'Redistributes geometry diffusion steps over time; the step count remains unchanged.', 'texture_steps': 'Material generation steps. Zero uses the profile. More steps may add detail but take longer.', 'texture_guidance': 'Reference strength for colour and materials. Excessive guidance may amplify defects or contrast.', 'texture_rescale': 'Regulates material guidance when texture guidance is high.', 'texture_rescale_t': 'Redistributes texture diffusion steps over time without increasing their count.', 'texture_seed': 'Separate random seed for materials. Minus one continues the main random sequence; a fixed seed helps compare material settings.', 'mesh_mode': 'Remesh rebuilds a surface then simplifies it and may soften detail. Direct simplifies the generated surface while keeping more irregularities.', 'pre_simplify': 'First reduces dense surfaces towards two million triangles to limit processing cost. Disable to retain the raw surface for finishing.', 'repair_holes': 'Fills small openings before surface reconstruction. Enabled by profile D; it does not guarantee a closed mesh or preservation of every thin detail.', 'remesh_project': 'Projects the rebuilt surface towards the source. Zero keeps the reconstruction; one applies maximum projection. Used with remeshing only.', 'remesh_band': 'Width of the reconstruction band in voxels. This can affect thin parts and processing cost.', 'qem_edge_weight': 'Edge-length penalty during simplification. Higher values favour a more regular triangle distribution. Zero prioritises shape error and can create elongated triangles.', 'qem_skinny_weight': 'Penalises simplifications that produce very thin triangles while keeping the target triangle count.', 'uv_angle': 'Face grouping angle in degrees. Smaller values create more UV islands; larger values group more broadly and can affect stretching.', 'uv_refine': 'Iterations to refine UV groups before unwrapping. Zero disables refinement; higher values take longer and may change islands.', 'uv_global': 'Global grouping passes before UV unwrapping. More passes take longer and can reorganise islands.', 'uv_smooth': 'Smoothing strength for grouping faces into UV regions. Changes island boundaries without smoothing model geometry.'}
HELP.update(
    texture_sampling='Interpolation inside the generated material volume. Nearest voxel can expose blocky steps; trilinear blends neighbouring voxels. Both project the finished mesh to the nearest point on the source surface first.',
    remesh_resolution='Reconstruction grid ceiling: 512, 768 or 1024. Limited by the generated resolution. Higher values cost more memory and may preserve more detail; no automatic fallback on memory failure. Unused with direct simplification.',
)
for field in FIELDS:field['hint']=HELP[field['key']]
ENGLISH_LABELS={'structure_steps': 'Structure · steps', 'structure_guidance': 'Structure · guidance', 'structure_rescale': 'Structure · rescale', 'structure_rescale_t': 'Structure · timestep distribution', 'shape_steps': 'Shape · steps', 'shape_guidance': 'Shape · guidance', 'shape_rescale': 'Shape · rescale', 'shape_rescale_t': 'Shape · timestep distribution', 'texture_steps': 'Texture · steps', 'texture_guidance': 'Texture · guidance', 'texture_rescale': 'Texture · rescale', 'texture_rescale_t': 'Texture · timestep distribution', 'texture_seed': 'Texture seed', 'mesh_mode': 'Finishing method', 'pre_simplify': 'Pre-simplify dense meshes to 2M', 'repair_holes': 'Fill small holes', 'remesh_project': 'Surface projection', 'remesh_band': 'Remesh band width', 'qem_edge_weight': 'QEM · edge length', 'qem_skinny_weight': 'QEM · skinny triangles', 'uv_angle': 'UV grouping angle', 'uv_refine': 'Island refinement', 'uv_global': 'Global passes', 'uv_smooth': 'Island smoothing'}
ENGLISH_LABELS.update(texture_sampling='Material voxel interpolation',remesh_resolution='Reconstruction grid ceiling')
for field in FIELDS:field['label']=ENGLISH_LABELS[field['key']]
BY_KEY={f['key']:f for f in FIELDS}
# Keep historical fallback values in FIELDS so old job records are not reinterpreted.
# The new-game default is explicit both in submitted settings and the UI schema.
GAME_D_ADVANCED={f['key']:f['default'] for f in FIELDS}
GAME_D_ADVANCED.update(texture_guidance=2.0,repair_holes=True)
PROFILE_ADVANCED = {'game_d': GAME_D_ADVANCED, 'high_detail': {**GAME_D_ADVANCED, 'mesh_mode': 'direct'},
                    HUMANOID_EXPERIMENTAL: {**GAME_D_ADVANCED, 'mesh_mode': 'direct'},
                    DENSE_MASTER: {**GAME_D_ADVANCED, **DENSE_MASTER_FINISHING}}

def normalize_options(overrides=None,base_steps=12):
    if overrides is None:overrides={}
    if not isinstance(overrides,dict) or set(overrides)-set(BY_KEY):
        raise ValueError('Unknown or malformed advanced settings.')
    result={}
    for field in FIELDS:
        key=field['key'];value=overrides.get(key,field['default'])
        if field['type']=='boolean':
            if type(value) is not bool:raise ValueError(field['label']+' : expected true or false.')
        elif field['type']=='choice':
            if not isinstance(value,str) or value not in [c['value'] for c in field['choices']]:raise ValueError(field['label']+' : invalid selection.')
        else:
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError(field['label']+' : expected a finite number.')
            if field['type']=='integer' and int(value)!=value:raise ValueError(field['label']+' : expected an integer.')
            if not field['min']<=value<=field['max']:raise ValueError(f"{field['label']} : enter a value between {field['min']} and {field['max']}.")
            value=int(value) if field['type']=='integer' else float(value)
            if key=='remesh_resolution' and value not in (512,768,1024):
                raise ValueError('Reconstruction grid ceiling: choose 512, 768 or 1024.')
            if key.endswith('_steps') and value==0:value=base_steps
        result[key]=value
    return result

def options_for_job(settings):
    """Read old laboratory settings without changing the original records."""
    base=int(settings.get('steps',GENERATION_PRESETS.get(settings.get('preset'),(12,))[0]))
    profile_base=PROFILE_ADVANCED.get(settings.get('preset'), {})
    repair = SURFACE_REPAIR_FINISHING if settings.get('repair_surface') is True else {}
    if settings.get('hd_reconstruction') is True:
        repair = HD_RECONSTRUCTION_FINISHING
    if isinstance(settings.get('generation_options'),dict):
        return normalize_options({**profile_base,**settings['generation_options'],**repair},base)
    overrides={**profile_base,**{k:settings[k] for k in BY_KEY if k in settings}}
    if 'remesh' in settings:
        overrides['mesh_mode']='remesh' if settings['remesh'] else 'direct'
        overrides['pre_simplify']=bool(settings.get('predecimate',False))
    if isinstance(settings.get('qem_options'),dict):
        for source,target in [('lambda_edge_length','qem_edge_weight'),('lambda_skinny','qem_skinny_weight')]:
            if source in settings['qem_options']:overrides[target]=settings['qem_options'][source]
    return normalize_options({**overrides,**repair},base)

def sampler_options(options):
    return {name:dict(steps=options[name+'_steps'],guidance_strength=options[name+'_guidance'],
        guidance_rescale=options[name+'_rescale'],rescale_t=options[name+'_rescale_t']) for name in ('structure','shape','texture')}

def export_options(options):
    return dict(remesh=options['mesh_mode']=='remesh',repair_holes=options['repair_holes'],remesh_band=options['remesh_band'],remesh_project=options['remesh_project'],
        remesh_resolution=options['remesh_resolution'],texture_sampling=options['texture_sampling'],
        mesh_cluster_threshold_cone_half_angle_rad=math.radians(options['uv_angle']),
        mesh_cluster_refine_iterations=options['uv_refine'],mesh_cluster_global_iterations=options['uv_global'],
        mesh_cluster_smooth_strength=options['uv_smooth'])

def configure_simplifier(cumesh,options):
    """One worker process per job; configure both pre-reduction and final QEM."""
    original=cumesh.CuMesh.simplify
    weights=dict(lambda_edge_length=options['qem_edge_weight'],lambda_skinny=options['qem_skinny_weight'])
    def simplify(self,target_num_faces,verbose=False,options=None):
        return original(self,target_num_faces,verbose=verbose,options={**(options or {}),**weights})
    cumesh.CuMesh.simplify=simplify

def schema():
    return dict(version=2,groups=GROUPS,fields=[dict(f,default=GAME_D_ADVANCED[f['key']]) for f in FIELDS],
        default_generation=DEFAULT_GENERATION,default_profile=DEFAULT_PROFILE,triangle_min=TRIANGLE_MIN,triangle_max=TRIANGLE_MAX,
        note='Experimental settings: compare geometry, materials and UVs. Settings alone do not guarantee quality.')
