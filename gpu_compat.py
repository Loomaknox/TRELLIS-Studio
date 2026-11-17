"""Compatibility switches for the pinned Windows inference stack."""
import importlib


def configure_xformers(torch):
    """The pinned FA3 dispatcher treats every capability >= 9 as Hopper.

    Blackwell must use the remaining xformers operators instead of its Hopper
    FA3 binary. Keep normal dispatch on Ada/Ampere and real Hopper devices.
    """
    if torch.cuda.get_device_capability()[0] >= 10:
        dispatch = importlib.import_module('xformers.ops.fmha.dispatch')
        dispatch._set_use_fa3(False)
        return 'xformers without Hopper FlashAttention 3'
    return 'xformers default dispatch'
