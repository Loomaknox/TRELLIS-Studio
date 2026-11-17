"""Small CUDA checks using UniRig's actual operators; no model weights loaded."""


def check_torch(torch):
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable under WSL.')
    details = dict(gpu=torch.cuda.get_device_name(), torch=str(torch.__version__),
                   cuda=torch.version.cuda, capability=list(torch.cuda.get_device_capability()))
    try:
        with torch.inference_mode():
            value = torch.ones((8, 8), device='cuda')
            result = value @ value
            torch.cuda.synchronize()
            if not bool(torch.all(result == 8).item()):
                raise RuntimeError('Unexpected CUDA matrix result.')
    except Exception as error:
        raise RuntimeError(
            f"CUDA execution failed on {details['gpu']} (sm_{details['capability'][0]}"
            f"{details['capability'][1]}), torch {details['torch']}, CUDA {details['cuda']}: {error}. "
            'Run the matching UniRig installer profile; detecting CUDA alone is insufficient.') from error
    return details


def check_extensions(torch):
    from flash_attn import flash_attn_varlen_qkvpacked_func
    from torch_cluster import fps
    from torch_scatter import segment_csr
    import spconv.pytorch as spconv

    with torch.inference_mode():
        # Exercise the varlen FP16 attention path used by PointTransformerV3.
        qkv = torch.zeros((8, 3, 2, 32), device='cuda', dtype=torch.float16)
        bounds = torch.tensor([0, 8], device='cuda', dtype=torch.int32)
        attention = flash_attn_varlen_qkvpacked_func(qkv, bounds, 8, dropout_p=0.0)
        if attention.shape != (8, 2, 32) or not bool(torch.isfinite(attention).all().item()):
            raise RuntimeError('FlashAttention returned invalid results.')
        points = torch.arange(12, device='cuda', dtype=torch.float32).reshape(4, 3)
        selected = fps(points, ratio=0.5, random_start=False)
        if selected.numel() != 2:
            raise RuntimeError('torch-cluster FPS returned invalid results.')
        offsets = torch.tensor([0, 2, 4], device='cuda', dtype=torch.int64)
        reduced = segment_csr(points, offsets, reduce='min')
        if not torch.equal(reduced, points[[0, 2]]):
            raise RuntimeError('torch-scatter segment_csr returned invalid results.')
        indices = torch.tensor([[0, 1, 1, 1], [0, 1, 1, 2], [0, 1, 2, 1], [0, 2, 1, 1]],
                               device='cuda', dtype=torch.int32)
        # PTv3 uses SubMConv3d. Importing spconv does not launch its CUDA kernels.
        # Include the >128 channel path used by the real model as well.
        for channels in (32, 256):
            features = torch.ones((4, channels), device='cuda')
            sparse = spconv.SparseConvTensor(features, indices, [4, 4, 4], 1)
            convolution = spconv.SubMConv3d(channels, channels, 3, bias=False).cuda().eval()
            convolution.weight.fill_(1)
            result = convolution(sparse).features
            if result.shape != (4, channels) or not bool(torch.all(result == 4 * channels).item()):
                raise RuntimeError('spconv SubMConv3d returned invalid results.')
        torch.cuda.synchronize()


def probe(torch, extensions=True):
    try:
        details = check_torch(torch)
        if extensions:
            check_extensions(torch)
        return details
    finally:
        # This diagnostic process exits before inference starts.
        torch.cuda.empty_cache()
