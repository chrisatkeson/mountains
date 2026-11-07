#!/usr/bin/env python
"""Generate a tileable greyscale rock detail texture (viewer/data/rock.png).

Fractal noise built in the frequency domain is periodic by construction, so the
texture tiles seamlessly. Two layers: broad blocky relief and fine grain, with
a few sharp dark cracks."""
import numpy as np
from PIL import Image

N = 1024
rng = np.random.default_rng(7)


def periodic_noise(beta, seed):
    r = np.random.default_rng(seed)
    f = np.fft.fftfreq(N)[:, None] ** 2 + np.fft.fftfreq(N)[None, :] ** 2
    f[0, 0] = 1
    spec = (r.standard_normal((N, N)) + 1j * r.standard_normal((N, N))) / f ** (beta / 2)
    spec[0, 0] = 0
    x = np.fft.ifft2(spec).real
    return (x - x.mean()) / x.std()


blocky = periodic_noise(1.8, 1)
blocky = np.sign(blocky) * np.abs(blocky) ** 0.6          # flatten faces, sharpen edges
grain = periodic_noise(1.0, 2)
cracks = np.clip(1 - np.abs(periodic_noise(1.6, 3)) * 2.5, 0, 1) ** 3   # thin dark lines
g = 0.5 + 0.18 * blocky + 0.08 * grain - 0.35 * cracks
img = (np.clip(g, 0, 1) * 255).astype(np.uint8)
Image.fromarray(img).save("viewer/data/rock.png", optimize=True)
print("wrote viewer/data/rock.png", img.mean().round(1), img.std().round(1))
