"""PyTorch CUDA equivalent of Hi3D's two packed, non-causal attention calls."""

from collections import defaultdict

import torch
from torch.nn.functional import scaled_dot_product_attention


def _attention(q, k, v, scale):
    q, k, v = (value.transpose(1, 2).contiguous() for value in (q, k, v))
    return scaled_dot_product_attention(q, k, v, dropout_p=0.0, scale=scale).transpose(1, 2)


def flash_attn_varlen_qkvpacked_func(qkv, cu_seqlens, max_seqlen, dropout_p=0.0, softmax_scale=None):
    if dropout_p != 0:
        raise ValueError('This inference adapter requires disabled dropout')
    offsets = cu_seqlens.cpu().tolist()
    groups = defaultdict(list)
    for start, end in zip(offsets, offsets[1:]):
        if end > start:
            groups[end - start].append(start)
    output = torch.empty_like(qkv[:, 0])
    for length, starts in groups.items():
        for start_list in (starts[index:index + 512] for index in range(0, len(starts), 512)):
            if len(start_list) == 1:
                start = start_list[0]
                q, k, v = qkv[start:start + length].unsqueeze(0).unbind(2)
                output[start:start + length] = _attention(q, k, v, softmax_scale)[0]
            else:
                indices = torch.as_tensor(start_list, device=qkv.device)[:, None]
                indices = indices + torch.arange(length, device=qkv.device)[None, :]
                q, k, v = qkv[indices].unbind(2)
                output[indices] = _attention(q, k, v, softmax_scale)
    return output


def flash_attn_varlen_kvpacked_func(query, kv, cu_query, cu_key, max_query, max_key):
    queries, keys = cu_query.cpu().tolist(), cu_key.cpu().tolist()
    output = torch.empty_like(query)
    for q0, q1, k0, k1 in zip(queries, queries[1:], keys, keys[1:]):
        q = query[q0:q1].unsqueeze(0)
        k, v = kv[k0:k1].unsqueeze(0).unbind(2)
        output[q0:q1] = _attention(q, k, v, None)[0]
    return output
