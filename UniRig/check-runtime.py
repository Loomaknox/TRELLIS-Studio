"""Startup probe: small CUDA kernels, no model weights or persistent allocation."""
from pathlib import Path
import importlib, json, os, sys, tempfile, time


def verify_gpu(torch):
    import flash_attn
    import spconv.pytorch as spconv
    from torch_cluster import fps
    from torch_scatter import segment_csr

    device = 'cuda'
    with torch.inference_mode():
        matrix = torch.ones((32, 32), device=device)
        torch.testing.assert_close(matrix @ matrix, torch.full_like(matrix, 32))
        position = torch.arange(24, dtype=torch.float32, device=device).reshape(8, 3)
        if fps(position, ratio=0.5, random_start=False).numel() != 4:
            raise RuntimeError('GPU farthest point sampling failed.')
        segments = torch.tensor([0, 4, 8], dtype=torch.long, device=device)
        reduced = segment_csr(torch.ones((8, 3), device=device), segments, reduce='sum')
        torch.testing.assert_close(reduced, torch.full((2, 3), 4., device=device))
        sequence = torch.ones((8, 2, 32), dtype=torch.float16, device=device)
        offsets = segments.int()
        attention = flash_attn.flash_attn_varlen_func(sequence, sequence, sequence, offsets, offsets, 4, 4)
        torch.testing.assert_close(attention, sequence)
        coords = torch.tensor([[0, 0, 0, 0], [0, 1, 1, 1]], dtype=torch.int32, device=device)
        for channels in (32, 256):
            features = torch.ones((2, channels), dtype=torch.float16, device=device)
            convolution = spconv.SubMConv3d(channels, channels, 3, bias=False).to(device).half()
            output = convolution(spconv.SparseConvTensor(features, coords, [2, 2, 2], 1))
            if output.features.shape != features.shape or not torch.isfinite(output.features).all():
                raise RuntimeError(f'GPU sparse convolution failed for {channels} channels.')


def check_runtime(root, result, gpu_only):
    import torch
    if os.environ.get('UNIRIG_PREBUILT_BLACKWELL') == '1':
        if torch.__version__ != '2.8.0+cu128' or torch.version.cuda != '12.8':
            raise RuntimeError('UniRig Blackwell requires the pinned Linux Torch 2.8.0+cu128 packages.')
        if not torch.compiled_with_cxx11_abi():
            raise RuntimeError('The selected FlashAttention wheel requires Torch built with CXX11 ABI.')
    from gpu_probe import probe
    result.update(probe(torch))
    for name in ('flash_attn','torch_scatter','torch_cluster','spconv','bpy','open3d'):
        importlib.import_module(name)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable under WSL on the selected GPU.')
    compute = '.'.join(map(str, torch.cuda.get_device_capability()))
    if expected_compute := os.environ.get('UNIRIG_COMPUTE_CAP'):
        if compute != expected_compute:
            raise RuntimeError(f'UniRig is using CUDA compute {compute}, expected {expected_compute}.')
        result.update(runtime_profile=os.environ['UNIRIG_PROFILE'], compute_capability=compute)
    verify_gpu(torch)
    if not gpu_only:
        for filename in ('skeleton.ckpt','skin.ckpt'):
            if not (root/'models'/filename).is_file():
                raise RuntimeError('Missing model weights: '+filename)
        from model_config import prepare_skeleton_config
        from transformers import AutoConfig
        import yaml
        with tempfile.TemporaryDirectory(prefix='trellis-rig-probe-') as work:
            model=yaml.safe_load(prepare_skeleton_config(root/'source',work).read_text(encoding='utf-8'))
            config=AutoConfig.from_pretrained(**model['llm'])
            assert config.num_hidden_layers==24 and config.num_attention_heads==16
    result.update(
        ready=True, gpu=torch.cuda.get_device_name(), torch=torch.__version__,
        message=(f'UniRig CUDA kernels passed on {torch.cuda.get_device_name()} ({compute}).'
                 if gpu_only else 'UniRig ready · on-demand compute'),
    )


def main():
    gpu_only = sys.argv[1:] == ['--gpu-only']
    root=Path(__file__).resolve().parent
    result=dict(ready=False,checked_at=time.time(),python=sys.version.split()[0],message='')
    try:
        check_runtime(root,result,gpu_only)
    except Exception as error:
        result['message']=str(error) or type(error).__name__
    if not gpu_only:
        path=root.parent/'logs'/'components.json'
        path.parent.mkdir(exist_ok=True)
        try:
            records=json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):
            records={}
        if not isinstance(records,dict):records={}
        records['unirig']=result
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as pending:
            json.dump(records,pending,indent=2,ensure_ascii=False)
        Path(pending.name).replace(path)
    print(result['message'],flush=True)
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    sys.exit(main())
