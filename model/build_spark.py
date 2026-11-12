#!/usr/bin/env python3.13
"""Reproducible generator for assets/spark.glb (DGX Spark, dismantlable).

Own geometry and procedural textures only: no logos, no lettering, no foreign images. Comments that name a photo
or a teardown note mean positions and sizes read off it; no photo is part of this repository or of the GLB, and
every texture is drawn by this file.

    blender -b -P build_spark.py                      build, export, verify
    blender -b -P build_spark.py -- --render DIR      render QA views of the exported GLB

Axes while building: millimetres, glTF convention (X right, Y up, Z front).
Origin: centre of the bottom plane of the housing (the pad hangs below it).
"""

import json
import math
import os
import struct
import sys
import tempfile
import time

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import tessellate_polygon

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "assets", "spark.glb")
TMP = tempfile.mkdtemp(prefix="spark_tex_")

MM = 0.001
BODY_H = 45.5  # housing height; with the 5 mm pad = 50.5 mm overall
TOP_T, WALL, FOAM_T = 1.5, 3.0, 5.0
PCB_TOP, PCB_BOT = 7.25, 5.65
PCB_X0, PCB_X1, PCB_Z0, PCB_Z1 = -67.6, 69.0, -66.8, 46.9
FAN_Y0, FAN_Y1 = 22.0, 42.0
INLET = [(-34.9, 18.65), (30.4, 18.65)]  # impeller axes (x, z)


def srgb(r, g, b):
    def f(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return (f(r), f(g), f(b), 1.0)


MATS = {
    "gold_matte": dict(color=srgb(214, 183, 139), metal=1.0, rough=0.46),
    "gold_satin": dict(color=srgb(224, 192, 145), metal=1.0, rough=0.30),
    "gold_mirror": dict(color=srgb(226, 193, 138), metal=1.0, rough=0.13),
    "alu": dict(color=srgb(158, 158, 155), metal=1.0, rough=0.48),
    "black_port": dict(color=srgb(11, 11, 12), metal=0.0, rough=0.5),
    "black_metal": dict(color=srgb(30, 30, 33), metal=0.25, rough=0.42),
    "black_fan": dict(color=srgb(46, 46, 49), metal=0.0, rough=0.48),
    "rotor": dict(color=srgb(58, 58, 62), metal=0.0, rough=0.38),
    "fin": dict(color=srgb(24, 24, 26), metal=0.55, rough=0.32),
    "nickel": dict(color=srgb(205, 198, 188), metal=1.0, rough=0.34),
    "copper": dict(color=srgb(220, 136, 89), metal=1.0, rough=0.26),
    "steel": dict(color=srgb(168, 168, 164), metal=1.0, rough=0.40),
    "steel_dark": dict(color=srgb(82, 82, 84), metal=1.0, rough=0.38),
    "silver": dict(color=srgb(205, 207, 204), metal=1.0, rough=0.30),
    "teal": dict(color=srgb(36, 112, 128), metal=0.0, rough=0.38),
    "gold_pin": dict(color=srgb(232, 190, 100), metal=1.0, rough=0.24),
    "chip": dict(color=srgb(50, 52, 57), metal=0.0, rough=0.44),
    "lpddr": dict(color=srgb(47, 49, 54), metal=0.0, rough=0.42),
    "ceramic": dict(color=srgb(212, 212, 206), metal=0.0, rough=0.45),
    "tan_cap": dict(color=srgb(190, 164, 122), metal=0.0, rough=0.42),
    "inductor": dict(color=srgb(98, 104, 112), metal=0.5, rough=0.42),
    "fr4": dict(color=srgb(36, 44, 44), metal=0.0, rough=0.55),
    "ssd_pcb": dict(color=srgb(18, 58, 50), metal=0.0, rough=0.42),
    "usb_blue": dict(color=srgb(56, 74, 110), metal=0.0, rough=0.4),
    "foam": dict(color=srgb(190, 165, 120), metal=1.0, rough=0.55),
    "pcb_top": dict(color=srgb(20, 20, 24), metal=0.0, rough=0.4),
    "pcb_bottom": dict(color=srgb(20, 20, 24), metal=0.0, rough=0.4),
    "die_gpu": dict(color=srgb(60, 70, 110), metal=1.0, rough=0.16),
    "die_cpu": dict(color=srgb(60, 70, 110), metal=1.0, rough=0.16),
}
TEX = {}  # material -> {slot: image}

# ---------------------------------------------------------------------------
# Procedural textures (numpy only, deterministic)
# ---------------------------------------------------------------------------


def write_jpeg(name, arr, quality, colorspace):
    """arr: float HxWx3 in display-ready values (sRGB colour or raw data)."""
    h, w = arr.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=False)
    rgba = np.dstack([np.clip(arr[::-1], 0, 1), np.ones((h, w))])
    img.pixels.foreach_set(rgba.ravel().astype(np.float32))
    path = os.path.join(TMP, name + ".jpg")
    img.filepath_raw = path
    img.file_format = "JPEG"
    img.save(quality=quality)
    bpy.data.images.remove(img)
    out = bpy.data.images.load(path)
    out.colorspace_settings.name = colorspace
    out.name = name
    return out


def lin2srgb(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


def blur_periodic(a, sigma):
    h, w = a.shape
    fy, fx = np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :]
    g = np.exp(-2 * (math.pi * sigma) ** 2 * (fx**2 + fy**2))
    return np.fft.ifft2(np.fft.fft2(a) * g).real


def tile_noise(rng, s, sigma):
    n = blur_periodic(rng.standard_normal((s, s)), sigma)
    return n / (n.std() + 1e-9)


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def voronoi(s, pitch, jitter, wspread, rng):
    """Tileable weighted Voronoi: returns F1, F2 (pixels), nearest-seed index and seed count."""
    n = int(s / pitch)
    step = s / n
    gx, gy = np.meshgrid(np.arange(n), np.arange(n))
    sx = (gx + 0.5 + rng.uniform(-jitter, jitter, gx.shape)) * step
    sy = (gy + 0.5 + rng.uniform(-jitter, jitter, gy.shape)) * step
    w = rng.normal(0, wspread, gx.shape)
    r = int(step * 2.7)
    f1, f2 = np.full((s, s), 1e9, np.float32), np.full((s, s), 1e9, np.float32)
    ids = np.full((s, s), -1, np.int32)
    for k, (x, y, ww) in enumerate(zip(sx.ravel(), sy.ravel(), w.ravel())):
        ix = np.arange(int(x) - r, int(x) + r + 1)
        iy = np.arange(int(y) - r, int(y) + r + 1)
        dx = ((ix - x + s / 2) % s) - s / 2
        dy = ((iy - y + s / 2) % s) - s / 2
        d = np.hypot(dy[:, None], dx[None, :]) - ww
        idx = np.ix_(iy % s, ix % s)
        a, b, c = f1[idx], f2[idx], ids[idx]
        m = d < a
        b[m] = a[m]
        a[m] = d[m]
        c[m] = k
        m2 = (~m) & (d < b)
        b[m2] = d[m2]
        f1[idx], f2[idx], ids[idx] = a, b, c
    return f1, f2, ids, n * n


def height_to_normal(h, k):
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    dy = (np.roll(h, 1, 0) - np.roll(h, -1, 0)) * 0.5  # image row 0 is the top
    n = np.dstack([-k * dx, -k * dy, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return n * 0.5 + 0.5


def build_foam_textures():
    """Open-cell metal foam: 1024 px = 100 mm, tileable. Emissive mask: pores white."""
    rng = np.random.default_rng(23)
    s = 1024
    pitch = 12.8  # cells ~1.25 mm at 10.24 px/mm; holes ~0.8-1.6 mm like the photo
    f1, _, ids, cells = voronoi(s, pitch, 0.46, 1.2, rng)
    n1, n2 = tile_noise(rng, s, 2.2), tile_noise(rng, s, 0.8)
    rad = ((0.34 + 0.2 * rng.random(cells) ** 2.2) * (s / int(s / pitch)))[ids]
    warp = 1.1 * tile_noise(rng, s, 1.6)  # irregular rims instead of perfect circles
    pore = smooth(rad + 1.4, rad - 1.4, f1 + warp * 0.8)
    strut = 1 - pore
    deep1, deep2, _, _ = voronoi(s, 9.5, 0.5, 1.0, rng)  # second cell layer seen through pores
    deep = (1 - smooth(1.0, 2.8, deep2 - deep1)) * pore
    depth_shade = np.clip(1 - f1 / (rad + 1e-6), 0, 1) * pore  # darker towards pore centres
    # colour (linear): warm champagne struts with speckle, dark bronze pores
    speck = np.clip(0.94 + 0.2 * n2 + 0.12 * n1, 0.6, 1.4)
    strut_col = np.array([0.71, 0.53, 0.30])[None, None] * speck[..., None]
    glint = np.clip(smooth(1.1, 2.4, n2 + n1 * 0.6), 0, 1)[..., None] * strut[..., None]
    strut_col = strut_col * (1 - glint) + np.array([0.92, 0.83, 0.66])[None, None] * glint
    pore_col = np.array([0.06, 0.036, 0.016])[None, None] * (1.0 - 0.7 * depth_shade[..., None])
    deep_col = np.array([0.18, 0.125, 0.07])[None, None] * (0.8 + 0.2 * speck[..., None])
    col = pore_col * (1 - deep[..., None]) + deep_col * deep[..., None]
    col = col * pore[..., None] + strut_col * strut[..., None]
    base = lin2srgb(blur_periodic(col[..., 0], 0.6))[..., None]
    base = np.dstack(
        [base[..., 0], lin2srgb(blur_periodic(col[..., 1], 0.6)), lin2srgb(blur_periodic(col[..., 2], 0.6))]
    )
    height = blur_periodic(strut, 1.2) * 2.6 + deep * 0.35 + 0.3 * n2 * strut
    nrm = height_to_normal(height, 1.1)
    mask = np.clip(blur_periodic(pore, 0.9), 0, 1)[..., None].repeat(3, 2)
    TEX["foam"] = dict(
        base=write_jpeg("foam_base", base, 90, "sRGB"),
        normal=write_jpeg("foam_normal", nrm, 90, "Non-Color"),
        emissive=write_jpeg("foam_mask", mask, 88, "Non-Color"),
    )


class Canvas:
    """2x supersampled painter for board textures; colours are sRGB 0..1."""

    SS = 2

    def __init__(self, w, h, to_px, bg, seed):
        self.w, self.h = w * self.SS, h * self.SS
        self.to_px = to_px
        self.rng = np.random.default_rng(seed)
        self.rgb = np.empty((self.h, self.w, 3), np.float32)
        self.rgb[...] = bg
        self.rough = np.full((self.h, self.w), 0.42, np.float32)
        self.metal = np.zeros((self.h, self.w), np.float32)
        self.scale = self.to_px(1.0, 0.0)[0] - self.to_px(0.0, 0.0)[0]

    def rect(self, x0, z0, x1, z1, col, rough=None, metal=None):
        (c0, r0), (c1, r1) = self.to_px(x0, z0), self.to_px(x1, z1)
        c0, c1, r0, r1 = (int(round(v)) for v in (min(c0, c1), max(c0, c1), min(r0, r1), max(r0, r1)))
        c0, c1, r0, r1 = max(c0, 0), min(c1, self.w), max(r0, 0), min(r1, self.h)
        if c1 <= c0 or r1 <= r0:
            return
        self.rgb[r0:r1, c0:c1] = col
        if rough is not None:
            self.rough[r0:r1, c0:c1] = rough
        if metal is not None:
            self.metal[r0:r1, c0:c1] = metal

    def disc(self, x, z, r, col, rough=None, metal=None):
        cx, cy = self.to_px(x, z)
        rp = r * abs(self.scale)
        c0, c1, r0, r1 = int(cx - rp - 1), int(cx + rp + 2), int(cy - rp - 1), int(cy + rp + 2)
        if c0 < 0 or r0 < 0 or c1 > self.w or r1 > self.h:
            return
        yy, xx = np.ogrid[r0:r1, c0:c1]
        m = (xx - cx) ** 2 + (yy - cy) ** 2 <= rp**2
        view = self.rgb[r0:r1, c0:c1]
        view[m] = col
        if rough is not None:
            self.rough[r0:r1, c0:c1][m] = rough
        if metal is not None:
            self.metal[r0:r1, c0:c1][m] = metal

    def line(self, x0, z0, x1, z1, half, col):
        if abs(x0 - x1) > abs(z0 - z1):
            self.rect(min(x0, x1), z0 - half, max(x0, x1), z0 + half, col)
        else:
            self.rect(x0 - half, min(z0, z1), x0 + half, max(z0, z1), col)

    def finish(self, name, q_base, q_mr):
        k = self.SS

        def down(a):
            h, w = a.shape[0] // k, a.shape[1] // k
            return a[: h * k, : w * k].reshape(h, k, w, k, *a.shape[2:]).mean(axis=(1, 3))

        rgb, rough, metal = down(self.rgb), down(self.rough), down(self.metal)
        mr = np.dstack([np.zeros_like(rough), np.clip(rough, 0, 1), np.clip(metal, 0, 1)])
        TEX[name] = dict(
            base=write_jpeg(name + "_base", rgb, q_base, "sRGB"),
            mr=write_jpeg(name + "_mr", mr[::2, ::2], q_mr, "Non-Color"),
        )


MASK = (0.035, 0.037, 0.045)
TRACE = (0.075, 0.08, 0.092)
TAN = (0.74, 0.64, 0.46)
DARK = (0.05, 0.05, 0.055)
GRAY = (0.45, 0.45, 0.44)
PIN = (0.86, 0.72, 0.42)


def scatter_passives(c, x0, z0, x1, z1, count, tan_ratio=0.45, exclude=()):
    rng = c.rng
    for _ in range(count):
        x, z = rng.uniform(x0, x1), rng.uniform(z0, z1)
        if any(a - 0.5 <= x <= d + 0.5 and b - 0.5 <= z <= e + 0.5 for a, b, d, e in exclude):
            continue
        w, h = (1.0, 0.5) if rng.random() < 0.7 else (0.6, 0.3)
        if rng.random() < 0.5:
            w, h = h, w
        if rng.random() < tan_ratio:
            c.rect(x, z, x + w, z + h, TAN, 0.4, 0.0)
            c.rect(x, z, x + w * 0.18, z + h, GRAY, 0.3, 0.6)
            c.rect(x + w * 0.82, z, x + w, z + h, GRAY, 0.3, 0.6)
        else:
            c.rect(x, z, x + w, z + h, (0.09, 0.09, 0.095), 0.5, 0.0)
            c.rect(x, z, x + w * 0.2, z + h, GRAY, 0.3, 0.6)
            c.rect(x + w * 0.8, z, x + w, z + h, GRAY, 0.3, 0.6)


def bga_pads(c, x0, z0, x1, z1, pitch, col=PIN, rough=0.3, metal=1.0):
    n = int((x1 - x0) / pitch)
    m = int((z1 - z0) / pitch)
    r = pitch * 0.32
    for i in range(n):
        for j in range(m):
            x, z = x0 + (i + 0.5) * pitch, z0 + (j + 0.5) * pitch
            c.rect(x - r, z - r, x + r, z + r, col, rough, metal)


def screw_ring(c, x, z):
    """Pale pad with a ring of small vias, as on the real board."""
    c.disc(x, z, 2.5, (0.72, 0.72, 0.70), 0.35, 0.8)
    c.disc(x, z, 1.25, (0.10, 0.10, 0.11), 0.5, 0.2)
    for a in range(0, 360, 20):
        c.disc(
            x + 3.3 * math.cos(math.radians(a)), z + 3.3 * math.sin(math.radians(a)), 0.18, (0.8, 0.8, 0.78), 0.4, 0.6
        )


def traces(c, n):
    rng = c.rng
    for _ in range(n):
        x, z = rng.uniform(PCB_X0 + 2, PCB_X1 - 2), rng.uniform(PCB_Z0 + 2, PCB_Z1 - 2)
        for _ in range(rng.integers(2, 6)):
            if rng.random() < 0.5:
                nx = x + rng.uniform(-9, 9)
                c.line(x, z, nx, z, 0.09, TRACE)
                x = nx
            else:
                nz = z + rng.uniform(-9, 9)
                c.line(x, z, x, nz, 0.09, TRACE)
                z = nz
    for _ in range(n):
        x, z = rng.uniform(PCB_X0 + 2, PCB_X1 - 2), rng.uniform(PCB_Z0 + 2, PCB_Z1 - 2)
        c.disc(x, z, 0.15, (0.20, 0.19, 0.17), 0.4, 0.5)


def r4(x, y):
    """Top-side reference photo pixel -> board mm (mapping measured on the ports)."""
    return (x - 613.8) / 5.6, PCB_Z0 + (y - 108) / 5.6


def r5(x, y):
    """Bottom-side reference photo pixel -> board mm."""
    return 51 - (x - 323) / 5.46, PCB_Z0 + (y - 112) / 5.5


def paint_pcb_top():
    px = 2048 / (PCB_X1 - PCB_X0)
    h = int(round((PCB_Z1 - PCB_Z0) / (PCB_X1 - PCB_X0) * 1024))
    c = Canvas(1024, h, lambda x, z: ((x - PCB_X0) * px, (z - PCB_Z0) * px), MASK, 41)
    traces(c, 900)
    # footprints left visible when the chips are lifted away
    bga_pads(c, 15.9, -27.6, 38.0, 11.8, 0.85)  # GB10
    for cx in (2.2, 51.5):
        for cz in (-21.8, -8.6, 4.6, 17.8):
            c.rect(cx - 7.5, cz - 6.4, cx + 7.5, cz + 6.4, (0.03, 0.03, 0.035), 0.5, 0.0)
            bga_pads(c, cx - 6.5, cz - 5.6, cx + 6.5, cz + 5.6, 0.8)
    bga_pads(c, -60.2, -2.1, -34.8, 23.3, 1.0)  # ConnectX-7
    for x, y in ((290, 442), (408, 442), (290, 626), (408, 626), (690, 280), (838, 280), (688, 592), (835, 592)):
        screw_ring(c, *r4(x, y))
    # upper power stage: six DrMOS with cap rows
    for x in (627, 670, 712, 753, 794, 836):
        (a, b) = r4(x - 14, 190)
        (d, e) = r4(x + 14, 219)
        c.rect(a, b, d, e, (0.055, 0.06, 0.065), 0.5, 0.0)
        c.rect(a + 1.0, b + 1.0, d - 1.0, e - 1.0, (0.09, 0.095, 0.10), 0.55, 0.0)
    for x0, x1 in ((603, 682), (712, 802)):
        (a, b), (d, e) = r4(x0, 268), r4(x1, 299)
        for i in range(10):
            xx = a + i * (d - a) / 10
            for zz in (b, b + (e - b) / 2):
                c.rect(xx + 0.2, zz + 0.15, xx + (d - a) / 10 - 0.2, zz + (e - b) / 2 - 0.15, TAN, 0.4, 0.0)
    # lower power stage: DrMOS row and tan caps
    for x in (681, 726, 772, 820, 867):
        (a, b), (d, e) = r4(x - 15, 658), r4(x + 15, 692)
        c.rect(a, b, d, e, (0.055, 0.06, 0.065), 0.5, 0.0)
        (a, b), (d, e) = r4(x - 16, 705), r4(x + 16, 735)
        for i in range(2):
            xx = a + i * (d - a) / 2
            c.rect(xx + 0.2, b, xx + (d - a) / 2 - 0.2, e, (0.66, 0.42, 0.26), 0.4, 0.0)
    # small ICs between ConnectX-7 and GB10 and around the board
    for x, y, w, hh in (
        (451, 466, 34, 30),
        (480, 520, 22, 22),
        (540, 300, 30, 30),
        (505, 345, 26, 26),
        (570, 620, 36, 28),
        (335, 655, 30, 30),
        (420, 690, 30, 26),
        (500, 690, 28, 24),
        (940, 665, 28, 28),
        (960, 330, 22, 22),
    ):
        (a, b), (d, e) = r4(x - w / 2, y - hh / 2), r4(x + w / 2, y + hh / 2)
        c.rect(a, b, d, e, (0.07, 0.07, 0.075), 0.5, 0.0)
        c.rect(a - 0.35, b - 0.35, a, b, PIN, 0.3, 1.0)
    # passives everywhere the real board is crowded; lifted-chip footprints stay clean
    keepouts = [
        (*r4(670, 292), *r4(858, 580)),
        (*r4(575, 315), *r4(672, 625)),
        (*r4(855, 315), *r4(952, 625)),
        (*r4(262, 95), *r4(497, 395)),
        (*r4(268, 455), *r4(428, 618)),
        (*r4(600, 188), *r4(880, 262)),
        (*r4(600, 262), *r4(810, 302)),
    ]
    (a, b), (d, e) = r4(245, 118), r4(995, 745)
    scatter_passives(c, a, b, d, e, 5200, exclude=keepouts)
    for pad_box, n in (
        ((r4(432, 300), r4(575, 620)), 900),
        ((r4(245, 620), r4(612, 735)), 900),
        ((r4(620, 590), r4(880, 730)), 300),
        ((r4(885, 240), r4(995, 310)), 260),
        ((r4(950, 320), r4(1000, 700)), 320),
        ((r4(245, 400), r4(432, 462)), 280),
    ):
        (a, b), (d, e) = pad_box
        scatter_passives(c, a, b, d, e, n, exclude=keepouts)
    # silkscreen frames (no text)
    for x0, y0, x1, y1 in ((679, 300, 851, 573), (583, 322, 669, 619), (858, 322, 947, 619), (270, 460, 426, 612)):
        (a, b), (d, e) = r4(x0, y0), r4(x1, y1)
        for k in (0, 1):
            c.line(a, (b, e)[k], d, (b, e)[k], 0.07, (0.72, 0.72, 0.68))
            c.line((a, d)[k], b, (a, d)[k], e, 0.07, (0.72, 0.72, 0.68))
    return c


def paint_pcb_bottom():
    px = 2048 / (PCB_X1 - PCB_X0)
    h = int(round((PCB_Z1 - PCB_Z0) / (PCB_X1 - PCB_X0) * 1024))
    c = Canvas(1024, h, lambda x, z: ((PCB_X1 - x) * px, (z - PCB_Z0) * px), MASK, 53)
    traces(c, 700)
    # capacitor field under the GB10 and the ConnectX-7 (photo positions)
    rng = c.rng
    for x0, y0, x1, y1, n, m in ((386, 338, 516, 535, 26, 34), (818, 482, 916, 596, 16, 16)):
        (a, b), (d, e) = r5(x0, y0), r5(x1, y1)
        a, d = min(a, d), max(a, d)
        cw, ch = (d - a) / n, (e - b) / m
        for i in range(n):
            for j in range(m):
                if rng.random() < 0.82:
                    xx, zz = a + i * cw, b + j * ch
                    col = TAN if rng.random() < 0.8 else (0.8, 0.8, 0.78)
                    c.rect(xx + cw * 0.12, zz + ch * 0.2, xx + cw * 0.88, zz + ch * 0.8, col, 0.4, 0.0)
    # upper cap row
    (a, b), (d, e) = r5(280, 612), r5(500, 640)
    a, d = min(a, d), max(a, d)
    for i in range(18):
        xx = a + i * (d - a) / 18
        for zz in (b, (b + e) / 2):
            c.rect(xx + 0.15, zz + 0.1, xx + (d - a) / 18 - 0.15, zz + (e - b) / 2 - 0.1, TAN, 0.4, 0.0)
    # polymer caps upper left, ICs, rings
    for x, y, w, hh in (
        (410, 233, 58, 26),
        (470, 233, 40, 26),
        (525, 233, 40, 26),
        (360, 262, 60, 24),
        (430, 262, 40, 24),
        (660, 580, 48, 40),
        (775, 190, 42, 42),
        (880, 175, 44, 44),
        (760, 680, 70, 56),
        (880, 665, 34, 34),
        (250, 195, 34, 36),
        (345, 185, 42, 30),
        (548, 188, 36, 30),
    ):
        (a, b), (d, e) = r5(x - w / 2, y - hh / 2), r5(x + w / 2, y + hh / 2)
        c.rect(min(a, d), b, max(a, d), e, (0.075, 0.08, 0.085), 0.5, 0.0)
    for x, y in ((375, 273), (521, 278), (375, 585), (521, 585), (802, 442), (923, 442), (800, 628), (922, 628)):
        screw_ring(c, *r5(x, y))
    for box, n in (
        ((r5(240, 300), r5(380, 560)), 620),
        ((r5(540, 320), r5(760, 480)), 640),
        ((r5(620, 500), r5(800, 640)), 540),
        ((r5(300, 640), r5(480, 720)), 320),
        ((r5(640, 120), r5(960, 300)), 760),
        ((r5(230, 120), r5(600, 220)), 520),
    ):
        (a, b), (d, e) = box
        scatter_passives(c, min(a, d), b, max(a, d), e, n)
    # M.2 socket footprint gold fingers
    (a, b), (d, e) = r5(610, 256), r5(655, 379)
    for j in range(38):
        zz = b + j * (e - b) / 38
        c.rect(min(a, d) - 1.2, zz, max(a, d) + 1.2, zz + 0.2, PIN, 0.3, 1.0)
    return c


def build_board_textures():
    paint_pcb_top().finish("pcb_top", 88, 78)
    paint_pcb_bottom().finish("pcb_bottom", 84, 75)


def die_texture(name, w_mm, h_mm, seed, gpu):
    """Fantasy die shot: functional blocks with thin-film colours, no markings."""
    rng = np.random.default_rng(seed)
    w, h = 512, int(round(512 * h_mm / w_mm))
    img = np.empty((h, w, 3), np.float32)
    img[...] = (0.03, 0.05, 0.11)
    pal = np.array(
        [
            [0.08, 0.16, 0.38],
            [0.20, 0.10, 0.34],
            [0.05, 0.28, 0.33],
            [0.42, 0.30, 0.10],
            [0.10, 0.34, 0.20],
            [0.34, 0.12, 0.20],
        ],
        np.float32,
    )

    def block(r0, c0, r1, c1, tone):
        base = pal[tone]
        rows, cols = np.ogrid[r0:r1, c0:c1]
        fine = 0.70 + 0.30 * ((rows // 3 + cols // 2) % 2)
        n = rng.normal(1.0, 0.09, (r1 - r0, c1 - c0))
        img[r0:r1, c0:c1] = base[None, None] * (fine * n)[..., None]

    if gpu:  # many identical arrays around a central fabric
        nx, ny = 6, 5
        cw, ch = w / nx, h / ny
        for i in range(nx):
            for j in range(ny):
                c0, r0 = int(i * cw + 5), int(j * ch + 5)
                c1, r1 = int((i + 1) * cw - 5), int((j + 1) * ch - 5)
                block(r0, c0, r1, c1, (i + j) % 3)
                for k in range(1, 4):
                    img[r0 + k * (r1 - r0) // 4 - 1 : r0 + k * (r1 - r0) // 4, c0:c1] *= 0.35
        img[h // 2 - 8 : h // 2 + 8, 14:-14] = (0.42, 0.33, 0.14)
    else:  # 20 cores in two columns plus shared cache
        cw = w * 0.20
        rows = 5
        ch = h / rows
        for side in (0, 1):
            for j in range(rows):
                c0 = int(8 + side * (w - cw - 16))
                c1 = int(c0 + cw)
                r0, r1 = int(j * ch + 5), int((j + 1) * ch - 5)
                block(r0, c0, r1, c1, 4 if j % 2 else 3)
        block(int(h * 0.08), int(w * 0.28), int(h * 0.92), int(w * 0.72), 1)
        for j in range(1, 8):
            r = int(h * 0.08 + j * h * 0.84 / 8)
            img[r : r + 2, int(w * 0.28) : int(w * 0.72)] *= 0.25
    # guard ring and scribe
    img[:6, :] = img[-6:, :] = (0.32, 0.26, 0.14)
    img[:, :6] = img[:, -6:] = (0.32, 0.26, 0.14)
    TEX[name] = dict(base=write_jpeg(name + "_base", lin2srgb(img), 88, "sRGB"))


def lpddr_texture():
    """Matte package with a faint laser-marked block and a pin-1 dot; no characters."""
    w, h = 256, 217
    img = np.full((h, w, 3), srgb(47, 49, 54)[:3], np.float32)
    rng = np.random.default_rng(9)
    img += rng.normal(0, 0.004, (h, w))[..., None]
    for row in range(5):
        y0 = 62 + row * 22
        for col in range(14):
            x0 = 34 + col * 14 + int(rng.integers(0, 2))
            img[y0 : y0 + 12, x0 : x0 + 10] += 0.022 + 0.012 * rng.random()
    img[20:38, 20:38] = np.array(srgb(120, 120, 120)[:3], np.float32) * 0.4
    TEX["lpddr"] = dict(base=write_jpeg("lpddr_base", lin2srgb(img), 86, "sRGB"))


def make_material(name):
    spec = MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.use_backface_culling = True  # all shells are closed and wound outwards (checked at build time)
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = spec["color"]
    bsdf.inputs["Metallic"].default_value = spec["metal"]
    bsdf.inputs["Roughness"].default_value = spec["rough"]
    tex = TEX.get(name, {})

    def node(img):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        n.extension = "REPEAT"
        return n

    if "base" in tex:
        nt.links.new(node(tex["base"]).outputs["Color"], bsdf.inputs["Base Color"])
    if "normal" in tex:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(node(tex["normal"]).outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if "emissive" in tex:
        nt.links.new(node(tex["emissive"]).outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0
    if "mr" in tex:
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(node(tex["mr"]).outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    return m


# ---------------------------------------------------------------------------
# Geometry helpers (millimetres, polygons with outward winding)
# ---------------------------------------------------------------------------


class Part:
    def __init__(self):
        self.polys = []

    def add(self, pts, mat, uvs=None):
        self.polys.append(([tuple(float(c) for c in p) for p in pts], mat, uvs))


def to3d(axis, u, v, h):
    if axis == "y":
        return (u, h, -v)
    if axis == "z":
        return (u, v, h)
    return (h, u, v)


def signed_area(loop):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, loop[1:] + loop[:1])) / 2


def clean(loop):
    out = []
    for p in loop:
        p = (float(p[0]), float(p[1]))
        if not out or math.dist(out[-1], p) > 1e-6:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) < 1e-6:
        out.pop()
    return out if signed_area(out) > 0 else out[::-1]


def rrect(w, h, r, n=4, cx=0.0, cy=0.0):
    r = min(r, w / 2, h / 2)
    if r < 1e-6:
        return clean(
            [(cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2), (cx - w / 2, cy - h / 2)]
        )
    pts = []
    for ax, ay, a0 in (
        (w / 2 - r, h / 2 - r, 0),
        (-w / 2 + r, h / 2 - r, 90),
        (-w / 2 + r, -h / 2 + r, 180),
        (w / 2 - r, -h / 2 + r, 270),
    ):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + ax + r * math.cos(a), cy + ay + r * math.sin(a)))
    return clean(pts)


def circle(r, n, cx=0.0, cy=0.0):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rect(u0, u1, v0, v1):
    return clean([(u1, v0), (u1, v1), (u0, v1), (u0, v0)])


def offset_loop(loop, d):
    """Shift a CCW loop inwards by d (negative = outwards, miter joins)."""
    n = len(loop)
    out = []
    for i in range(n):
        p, a, b = Vector(loop[i]), Vector(loop[i - 1]), Vector(loop[(i + 1) % n])
        e1, e2 = (p - a).normalized(), (b - p).normalized()
        n1, n2 = Vector((-e1.y, e1.x)), Vector((-e2.y, e2.x))
        m = n1 + n2
        if m.length < 1e-6:
            m = n1
        m.normalize()
        k = 1 / max(0.3, m.dot(n1))
        out.append(tuple(p + m * d * k))
    return out


def _band(part, a, b, ha, hb, axis, mat, flip=False):
    n = len(a)
    for i in range(n):
        j = (i + 1) % n
        q = [to3d(axis, *a[i], ha), to3d(axis, *a[j], ha), to3d(axis, *b[j], hb), to3d(axis, *b[i], hb)]
        part.add(q[::-1] if flip else q, mat)


def _cap(part, loops, h, axis, mat, down):
    pts3 = [Vector((p[0], p[1], 0)) for lp in loops for p in lp]
    tris = tessellate_polygon([[Vector((p[0], p[1], 0)) for p in lp] for lp in loops])
    area = 0.0
    for t in tris:
        a, b, c = pts3[t[0]], pts3[t[1]], pts3[t[2]]
        s = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
        area += abs(s) / 2
        order = (t[0], t[1], t[2]) if (s > 0) != down else (t[0], t[2], t[1])
        part.add([to3d(axis, pts3[k].x, pts3[k].y, h) for k in order], mat)
    want = abs(signed_area(loops[0])) - sum(abs(signed_area(lp)) for lp in loops[1:])
    assert abs(area - want) < max(0.02 * abs(want), 0.05), (area, want)


def loft(part, outer, holes, axis, levels, mat, caps=(True, True), hole_d=True, hole_walls=True):
    """levels: (inset, height) from the lowest to the highest ring; mat may be (wall, top, bottom)."""
    wall_mat, top_mat, bot_mat = mat if isinstance(mat, tuple) else (mat, mat, mat)
    outer = clean(outer)
    holes = [clean(h) for h in holes]
    rings = [(offset_loop(outer, d), [offset_loop(h, -d if hole_d else 0.0) for h in holes], h_) for d, h_ in levels]
    for (oa, ha, ya), (ob, hb, yb) in zip(rings, rings[1:]):
        _band(part, oa, ob, ya, yb, axis, wall_mat)
        if hole_walls:
            for x, y in zip(ha, hb):
                _band(part, x, y, ya, yb, axis, wall_mat, flip=True)
    if caps[0]:
        _cap(part, [rings[0][0]] + rings[0][1], rings[0][2], axis, bot_mat, True)
    if caps[1]:
        _cap(part, [rings[-1][0]] + rings[-1][1], rings[-1][2], axis, top_mat, False)


def bowl(part, loop, axis, rim_h, rings, mat, up=True, back=True):
    """Recess whose opening faces +axis (up) or -axis: rings are (inset, depth), outermost first."""
    s = 1.0 if up else -1.0
    prev, ph = clean(loop), rim_h
    for inset, depth in rings:
        cur = offset_loop(clean(loop), inset)
        hb = rim_h - s * depth
        _band(part, prev, cur, ph, hb, axis, mat, flip=not up)
        prev, ph = cur, hb
    if back:
        _cap(part, [prev], ph, axis, mat, down=not up)


def box(part, x0, x1, y0, y1, z0, z1, mat, top=True, bottom=True):
    loft(part, rect(x0, x1, -z1, -z0), [], "y", [(0, y0), (0, y1)], mat, caps=(bottom, top))


def cbox(part, x0, x1, y0, y1, z0, z1, c, mat):
    """Box with chamfered horizontal edges."""
    loft(part, rect(x0, x1, -z1, -z0), [], "y", [(c, y0), (0, y0 + c), (0, y1 - c), (c, y1)], mat)


def cyl(part, axis, cu, cv, r, h0, h1, mat, n=24, chamfer=0.0):
    if chamfer:
        loft(part, circle(r, n, cu, cv), [], axis, [(0, h0), (0, h1 - chamfer), (chamfer, h1)], mat)
    else:
        loft(part, circle(r, n, cu, cv), [], axis, [(0, h0), (0, h1)], mat)


def poly_normal(pts):
    nx = ny = nz = 0.0
    for a, b in zip(pts, pts[1:] + pts[:1]):
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return (nx / length, ny / length, nz / length)


def uv_box(p, n):
    ax = max(range(3), key=lambda i: abs(n[i]))
    if ax == 1:
        return (p[0] / 100, p[2] / 100)
    if ax == 2:
        return (p[0] / 100, p[1] / 100)
    return (p[2] / 100, p[1] / 100)


def chaikin(path, it=2):
    pts = [Vector(p) for p in path]
    for _ in range(it):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out += [a.lerp(b, 0.25), a.lerp(b, 0.75)]
        out.append(pts[-1])
        pts = out
    return pts


def tube(part, path, a, b, mat, n=8):
    """Flattened heat pipe along a polyline (kept wide in the horizontal plane)."""
    up = Vector((0, 1, 0))
    rings = []
    for i, p in enumerate(path):
        t = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
        side = t.cross(up).normalized()
        up2 = side.cross(t).normalized()
        rings.append(
            [p + side * a * math.cos(2 * math.pi * k / n) + up2 * b * math.sin(2 * math.pi * k / n) for k in range(n)]
        )
    for r0, r1 in zip(rings, rings[1:]):
        c0, c1 = sum(r0, Vector()) / n, sum(r1, Vector()) / n
        for k in range(n):
            q = [r0[k], r0[(k + 1) % n], r1[(k + 1) % n], r1[k]]
            mid = (q[0] + q[1] + q[2] + q[3]) / 4
            nrm = (q[1] - q[0]).cross(q[3] - q[0])
            if nrm.dot(mid - (c0 + c1) / 2) < 0:
                q = q[::-1]
            part.add(q, mat)
    for r, sign in ((rings[0], -1), (rings[-1], 1)):
        d = (path[-1] - path[-2] if sign > 0 else path[0] - path[1]).normalized()
        nrm = (r[1] - r[0]).cross(r[2] - r[0])
        part.add(r if nrm.dot(d) > 0 else r[::-1], mat)


# ---------------------------------------------------------------------------
# The parts
# ---------------------------------------------------------------------------


def build_shell():
    p = Part()
    h_plan = [
        (75, -75),
        (75, 75),
        (72, 75),
        (72, 70),
        (-72, 70),
        (-72, 75),
        (-75, 75),
        (-75, -75),
        (-72, -75),
        (-72, -70),
        (72, -70),
        (72, -75),
    ]
    loft(p, h_plan, [], "y", [(0, BODY_H - TOP_T), (0, BODY_H - 0.45), (0.45, BODY_H)], "gold_matte")
    for s in (-1, 1):
        x0, x1 = sorted((s * 72.0, s * 75.0))
        loft(
            p,
            rect(x0, x1, -75, 75),
            [],
            "y",
            [(0.25, 0), (0, 0.25), (0, BODY_H - TOP_T)],
            "gold_matte",
            caps=(True, False),
        )
    box(p, -70, 70, BODY_H - TOP_T - 5, BODY_H - TOP_T, -13.5, -12, "gold_matte", top=False)
    box(p, -1.2, 1.2, BODY_H - TOP_T - 3, BODY_H - TOP_T, -12, 60, "gold_matte", top=False)
    for x, z in ((66, 62), (-66, 62), (66, -62), (-66, -62)):
        cyl(p, "y", x, -z, 3.2, BODY_H - TOP_T - 6, BODY_H - TOP_T, "gold_matte", n=12)
    return p


GRIP_CX, GRIP_CY, GRIP_W, GRIP_H = 55.5, 22.05, 24.1, 36.5
PILL_CX, PILL_CY, PILL_W, PILL_H = 62.0, 22.2, 9.0, 33.0


def build_foam(front):
    p = Part()
    holes = []
    z0, z1 = (70, 75) if front else (-75, -70)
    if front:
        for s in (-1, 1):
            holes.append(rrect(GRIP_W + 0.1, GRIP_H + 0.1, 3.5, n=5, cx=s * GRIP_CX, cy=GRIP_CY))
    else:
        holes.append(rrect(128.1, 15.1, 4.05, n=6, cy=12.0))
    loft(p, rect(-72, 72, 0, BODY_H), holes, "z", [(0, z0), (0, z1)], "foam", hole_d=False)
    return p


def build_grip(s):
    p = Part()
    outline = rrect(GRIP_W, GRIP_H, 3.4, n=5, cx=s * GRIP_CX, cy=GRIP_CY)
    pill = rrect(PILL_W, PILL_H, PILL_W / 2, n=8, cx=s * PILL_CX, cy=PILL_CY)
    loft(p, outline, [pill], "z", [(0, 71.0), (0, 74.8), (0.2, 75.0)], "gold_satin", hole_d=False, hole_walls=False)
    bowl(p, pill, "z", 75.0, [(0.45, 0.5), (1.0, 1.7), (1.9, 2.9), (3.0, 3.4)], "gold_satin")
    return p


USB_X = (51.0, 43.5, 36.1, 28.6)
PLATE_CY = 12.0
HDMI_X, HDMI_Y, RJ_X, RJ_Y = 12.5, 10.2, -8.3, 10.9
QSFP_XC, QSFP_W, QSFP_H = -40.65, 38.0, 9.0


def hdmi_outline():
    x, y, w, h, c = HDMI_X, HDMI_Y, 15.0, 5.6, 2.0
    return clean(
        [
            (x + w / 2, y + h / 2),
            (x - w / 2, y + h / 2),
            (x - w / 2, y - h / 2 + c * 0.45),
            (x - w / 2 + c, y - h / 2),
            (x + w / 2 - c, y - h / 2),
            (x + w / 2, y - h / 2 + c * 0.45),
        ]
    )


def rj45_outline():
    x, y, w, h = RJ_X, RJ_Y, 12.5, 9.8
    top_step, s1, s2 = 1.1, 8.0, 5.6
    return clean(
        [
            (x + w / 2, y - h / 2),
            (x + w / 2, y + h / 2 - 2 * top_step),
            (x + s1 / 2, y + h / 2 - 2 * top_step),
            (x + s1 / 2, y + h / 2 - top_step),
            (x + s2 / 2, y + h / 2 - top_step),
            (x + s2 / 2, y + h / 2),
            (x - s2 / 2, y + h / 2),
            (x - s2 / 2, y + h / 2 - top_step),
            (x - s1 / 2, y + h / 2 - top_step),
            (x - s1 / 2, y + h / 2 - 2 * top_step),
            (x - w / 2, y + h / 2 - 2 * top_step),
            (x - w / 2, y - h / 2),
        ]
    )


def build_io_plate():
    p = Part()
    btn = rrect(3.4, 9.5, 1.7, n=5, cx=58.4, cy=PLATE_CY)
    usb = [rrect(3.4, 8.8, 1.7, n=6, cx=x, cy=PLATE_CY) for x in USB_X]
    hdmi, rj = hdmi_outline(), rj45_outline()
    qsfp = rrect(QSFP_W, QSFP_H, 0.8, n=2, cx=QSFP_XC, cy=PLATE_CY)
    plate = rrect(128, 15, 4, n=6, cy=PLATE_CY)
    # mirror-finish plate; level order runs from the outer (-Z) face inwards
    loft(
        p,
        plate,
        [btn] + usb + [hdmi, rj, qsfp],
        "z",
        [(0.2, -75.0), (0, -74.8), (0, -73.5)],
        "gold_mirror",
        hole_d=False,
    )
    d = 2.3
    # black port throats that travel with the plate
    for x, ol in zip(USB_X, usb):
        bowl(p, ol, "z", -75.0, [(0.02, d)], "black_port", up=False)
        # thin metal shell at the mouth, dark tongue inside
        loft(p, ol, [offset_loop(clean(ol), 0.32)], "z", [(0, -75.0), (0, -74.25)], "steel_dark", hole_d=False)
        box(p, x - 0.3, x + 0.3, PLATE_CY - 3.0, PLATE_CY + 3.0, -74.35, -75 + d, "usb_blue")
    bowl(p, hdmi, "z", -75.0, [(0.02, d)], "black_port", up=False)
    loft(p, hdmi, [offset_loop(clean(hdmi), 0.3)], "z", [(0, -75.0), (0, -74.3)], "steel_dark", hole_d=False)
    box(p, HDMI_X - 5.2, HDMI_X + 5.2, HDMI_Y + 0.15, HDMI_Y + 0.95, -74.3, -75 + d, "steel_dark")
    bowl(p, rj, "z", -75.0, [(0.02, d)], "black_port", up=False)
    for i in range(8):
        cx = RJ_X + (i - 3.5) * 1.02
        box(p, cx - 0.17, cx + 0.17, RJ_Y + 1.8, RJ_Y + 3.4, -74.2, -75 + d, "gold_pin")
    bowl(p, qsfp, "z", -75.0, [(0.02, d)], "black_port", up=False)
    box(p, QSFP_XC - 0.22, QSFP_XC + 0.22, PLATE_CY - 4.55, PLATE_CY + 4.55, -74.6, -75 + d, "steel")
    # power button: free-standing pill with a black gap behind it
    loft(
        p,
        rrect(2.9, 9.0, 1.45, n=5, cx=58.4, cy=PLATE_CY),
        [],
        "z",
        [(0.06, -74.92), (0, -74.86), (0, -73.7)],
        "gold_mirror",
        caps=(True, False),
    )
    box(p, 58.4 - 2.3, 58.4 + 2.3, PLATE_CY - 5.3, PLATE_CY + 5.3, -73.7, -73.4, "black_port")
    return p


BOSS_LEVELS = [(6.5 * t, -3.3 * (3 * t * t - 2 * t * t * t)) for t in (1.0, 0.75, 0.5, 0.25, 0.0)]


def build_bottom_pad():
    p = Part()
    loft(p, rrect(113, 103, 10, n=8), [], "y", [(0.55, -5.0), (0, -4.45), (0, -3.3)], "gold_matte")
    return p


WIN_A = rect(23.7, 53.2, -36.5, 19.3)
WIN_B = rect(-53.5, -28.4, -35.6, 14.9)


def build_bottom_cover():
    p = Part()
    outer = rrect(143.6, 139.6, 1.0, n=2)
    boss0 = rrect(129, 119, 16, n=8)
    slot = rrect(134, 3, 1.5, n=4, cy=-61.6)
    # flat underside ring (y=0) with the boss opening and the intake slot
    _cap(p, [clean(outer), clean(boss0), clean(slot)], 0.0, "y", "gold_matte", True)
    # boss: S-curve flare from y=0 down to the plateau the pad sits on
    loft(p, boss0, [], "y", sorted(BOSS_LEVELS, key=lambda lv: lv[1]), "gold_matte", caps=(False, False))
    plateau = offset_loop(clean(boss0), 6.5)
    _cap(p, [plateau, clean(WIN_A), clean(WIN_B)], -3.3, "y", "gold_matte", True)
    # inner face with the antenna windows and the slot
    _cap(p, [clean(outer), clean(WIN_A), clean(WIN_B), clean(slot)], 1.5, "y", "gold_matte", False)
    _band(p, clean(outer), clean(outer), 0.0, 1.5, "y", "gold_matte")
    _band(p, clean(slot), clean(slot), 0.0, 1.5, "y", "gold_matte", flip=True)
    for w in (WIN_A, WIN_B):
        _band(p, clean(w), clean(w), -3.3, 1.5, "y", "gold_matte", flip=True)
    # antennas (black flexible PCBs behind the two windows)
    for x0, x1, z0, z1 in ((27.0, 51.0, -34.0, 12.0), (-51.0, -31.0, -33.0, 12.0)):
        box(p, x0, x1, 0.2, 0.9, z0, z1, "black_metal")
    return p


def build_base_plate():
    p = Part()
    loft(p, rect(-71.5, 71.5, -48, 68), [rect(-48.6, -5.8, 17.5, 40.2)], "y", [(0, 2.25), (0, 3.45)], "alu")
    for s in (-1, 1):
        for z in (-60, -20, 20):
            cyl(p, "y", s * 69.5, -z, 1.6, 3.45, 3.75, "steel", n=10)
    return p


def build_pcb():
    p = Part()
    u0, u1, v0, v1 = PCB_X0, PCB_X1, -PCB_Z1, -PCB_Z0
    notch = 2.6
    outline = [(u0, v0), (u1, v0)]
    for vn in (-33.0, 12.0, 60.0):  # right edge (rear is +v)
        outline += [(u1 - notch * math.sin(t * math.pi / 8), vn - notch * math.cos(t * math.pi / 8)) for t in range(9)]
    outline += [(u1, v1), (u0, v1)]
    for vn in (60.0, 12.0, -33.0):  # left edge
        outline += [(u0 + notch * math.sin(t * math.pi / 8), vn + notch * math.cos(t * math.pi / 8)) for t in range(9)]
    loft(p, outline, [], "y", [(0, PCB_BOT), (0, PCB_TOP)], ("fr4", "pcb_top", "pcb_bottom"))

    # connectors (the shells behind the rear plate)
    for x in USB_X:
        loft(
            p,
            rrect(3.6, 9.0, 1.8, n=6, cx=x, cy=PLATE_CY),
            [],
            "z",
            [(0, -72.6), (0, -60.0)],
            "steel",
        )
    box(p, HDMI_X - 7.5, HDMI_X + 7.5, 7.0, 13.4, -72.6, -61.7, "steel")
    box(p, -16.75, -0.3, 5.6, 17.8, -72.6, -51.0, "steel")
    # black mating faces, visible once the rear plate has moved away
    faces = [rrect(2.5, 7.6, 1.25, n=5, cx=x, cy=PLATE_CY) for x in USB_X] + [hdmi_outline(), rj45_outline()]
    for ol in faces:
        loft(p, ol, [], "z", [(0, -72.62), (0, -72.5)], "black_port", caps=(True, False))

    # tall components as real boxes (reference-photo pixel boxes)
    def comp(x0, y0, x1, y1, h, mat, c=0.15):
        (a, b), (d, e) = r4(x0, y0), r4(x1, y1)
        cbox(p, a, d, PCB_TOP, PCB_TOP + h, b, e, c, mat)

    comp(925, 160, 1005, 235, 5.5, "silver", 0.3)
    for k in range(3):
        comp(930, 115 + 15 * k, 965, 128 + 15 * k, 2.0, "copper", 0.1)
    for x in (627, 670, 712, 753, 794, 836):
        comp(x - 19, 222, x + 19, 258, 3.1, "ceramic")
    comp(510, 212, 550, 252, 2.6, "ceramic")
    for x in (681, 726, 772, 820, 867):
        comp(x - 15, 625, x + 15, 656, 2.2, "inductor")
        comp(x - 14, 659, x + 14, 691, 0.9, "chip", 0.08)  # DrMOS
    for x in (632, 675, 716, 758, 800, 843):
        comp(x - 14, 190, x + 14, 219, 0.9, "chip", 0.08)  # DrMOS
    for x0, y0, x1, y1, h, m in (
        (590, 633, 625, 668, 2.3, "ceramic"),
        (522, 555, 565, 598, 2.3, "ceramic"),
        (518, 450, 562, 488, 2.2, "tan_cap"),
        (516, 498, 546, 545, 2.0, "chip"),
        (480, 498, 510, 545, 2.0, "chip"),
        (433, 450, 470, 480, 2.0, "chip"),
        (480, 628, 505, 655, 1.8, "tan_cap"),
        (420, 650, 450, 680, 1.8, "tan_cap"),
        (455, 660, 485, 690, 1.8, "tan_cap"),
        (545, 655, 580, 690, 1.8, "tan_cap"),
        (335, 628, 360, 655, 1.8, "tan_cap"),
        (312, 430, 345, 458, 1.6, "inductor"),
        (420, 610, 442, 632, 1.6, "chip"),
        (592, 720, 608, 745, 1.6, "chip"),
    ):
        comp(x0, y0, x1, y1, h, m, 0.12)
    # CR2032 standing in its holder at the board edge
    box(p, -71.8, -64.4, PCB_TOP, PCB_TOP + 2.2, -40.2, -17.4, "chip")
    cyl(p, "x", 18.0, -28.8, 10.0, -69.8, -66.4, "silver", n=28, chamfer=0.2)
    return p


def build_gb10():
    """Package: stiffener frame, teal substrate, small caps; dies are separate nodes."""
    p = Part()
    cx, cz = 26.95, -8.15
    cbox(p, cx - 15.3, cx + 15.3, 7.55, 8.6, cz - 24.4, cz + 24.4, 0.1, "teal")
    loft(
        p,
        rrect(30.6, 48.8, 1.5, n=3, cx=cx, cy=-cz),
        [rect(cx - 11.05, cx + 11.05, -cz - 19.75, -cz + 19.75)],
        "y",
        [(0, 8.6), (0, 9.5), (0.18, 9.68)],
        "silver",
        caps=(False, True),
    )
    # die cavity floor and dark rim around the silicon
    cbox(p, cx - 7.6, cx + 7.6, 8.6, 8.8, -23.5, 7.7, 0.05, "black_port")
    # bypass capacitors along the die window
    for x in (16.7, 17.6, 36.4, 37.3):
        for k in range(22):
            z = -24.0 + k * 1.45
            if k % 7 != 3:
                box(p, x - 0.32, x + 0.32, 8.6, 9.0, z - 0.45, z + 0.45, "gold_pin", bottom=False)
    for k in range(14):
        for z in (-27.0, 11.0):
            x = cx - 6.5 + k * 1.0
            box(p, x - 0.3, x + 0.3, 8.6, 9.0, z - 0.35, z + 0.35, "gold_pin", bottom=False)
    return p


def build_die(z0, z1, name):
    p = Part()
    x0, x1 = 19.75, 34.15
    loft(
        p,
        rrect(x1 - x0, z1 - z0, 0.25, n=2, cx=(x0 + x1) / 2, cy=-(z0 + z1) / 2),
        [],
        "y",
        [(0.05, 8.8), (0, 8.86), (0, 9.42), (0.07, 9.5)],
        name,
    )
    return p


def rect_uv(x0, x1, z0, z1):
    def f(q, n):
        if n[1] > 0.9:
            return ((q[0] - x0) / (x1 - x0), 1 - (q[2] - z0) / (z1 - z0))
        return (0.005, 0.005)

    return f


def die_uv(z0, z1):
    return rect_uv(19.75, 34.15, z0, z1)


LPDDR_POS = [(cx, cz) for cx in (2.2, 51.5) for cz in (-21.8, -8.6, 4.6, 17.8)]


def build_lpddr(i):
    p = Part()
    cx, cz = LPDDR_POS[i]
    cbox(p, cx - 7.25, cx + 7.25, 7.6, 8.7, cz - 6.15, cz + 6.15, 0.12, "lpddr")
    return p


def build_cx7():
    p = Part()
    cx, cz = -47.5, 10.6
    cbox(p, cx - 14.1, cx + 14.1, 7.55, 8.35, cz - 14.1, cz + 14.1, 0.08, "teal")
    loft(p, rrect(25.9, 25.9, 1.6, n=3, cx=cx, cy=-cz), [], "y", [(0.0, 8.35), (0.0, 9.15), (0.25, 9.4)], "silver")
    return p


def build_qsfp():
    p = Part()
    x0, x1 = -61.65, -19.65
    z0, z1 = -70.0, -14.75
    y0, y1 = PCB_TOP, 20.15
    box(p, x0 + 0.5, x1 - 0.5, y0, y1, z0 + 1, z1, "steel")
    # front flange with the two port openings
    holes = [rect(-58.3, -41.9, 9.4, 18.7), rect(-39.4, -23.0, 9.4, 18.7)]
    loft(p, rect(x0, x1, y0 - 0.3, y1 + 0.7), holes, "z", [(0, z0), (0, z0 + 1.0)], "steel", hole_d=False)
    for h0, h1 in ((-58.3, -41.9), (-39.4, -23.0)):
        box(p, h0 + 0.05, h1 - 0.05, 9.45, 18.65, z0 + 0.8, z0 + 1.02, "black_port", bottom=False)
        # guide rails inside the opening
        box(p, h0 + 0.05, h1 - 0.05, 9.4, 10.2, z0 + 0.1, z0 + 0.8, "black_port", bottom=False, top=False)
    # riding heatsinks: ribs in three rows, black labels (blank), retaining straps
    for sx0, sx1 in ((-61.0, -43.5), (-41.6, -24.2)):
        pitch = (sx1 - sx0) / 9
        for rib in range(9):
            a = sx0 + rib * pitch + 0.25
            for zs0, zs1 in ((-56.3, -46.6), (-45.2, -34.9), (-32.6, -23.2)):
                box(p, a, a + pitch - 0.5, y1, y1 + 3.0, zs0, zs1, "nickel", bottom=False)
        box(p, sx0 + 2.2, sx1 - 2.2, y1 + 3.0, y1 + 3.08, -56.3, -46.0, "black_port", bottom=False)
        cx = (sx0 + sx1) / 2
        box(p, cx - 5.5, cx + 5.5, y1 - 0.2, y1 + 0.6, -64.5, -58.2, "black_port", bottom=False)
        box(p, cx - 5.5, cx + 5.5, y1 - 0.2, y1 + 0.6, -21.5, -15.2, "black_port", bottom=False)
    return p


def build_ssd():
    p = Part()
    x0, x1, z0, z1 = -48.5, -6.5, -39.8, -17.8
    y0, y1 = 3.7, 4.5
    box(p, x0, x1, y0, y1, z0, z1, "ssd_pcb")
    box(p, x1 - 3.8, x1, y0 - 0.02, y1 + 0.02, z0 + 1.6, z1 - 1.6, "gold_pin")
    box(p, -41.0, -30.0, y0 - 1.3, y0, z0 + 2.5, z1 - 2.5, "chip")  # controller (downwards)
    box(p, -28.5, -17.0, y0 - 1.35, y0, z0 + 2.3, z1 - 2.3, "chip")  # NAND packages
    box(p, -46.5, -42.0, y1, y1 + 1.0, z0 + 4.0, z1 - 4.0, "chip")
    box(p, -41.0, -30.0, y1, y1 + 1.0, z0 + 2.5, z1 - 2.5, "chip")
    box(p, -28.5, -17.0, y1, y1 + 1.0, z0 + 2.3, z1 - 2.3, "chip")
    cyl(p, "y", -48.6, -(z0 + z1) / 2, 1.9, y1, y1 + 0.45, "steel", n=12)
    return p


def build_wifi():
    p = Part()
    cbox(p, 4.3, 17.7, 3.8, 5.6, 27.3, 44.9, 0.15, "silver")
    box(p, 3.3, 18.7, 5.6, 5.65, 26.3, 45.9, "ssd_pcb", bottom=False)
    return p


def build_thermal():
    p = Part()
    # nickel plate on the chip side (T-shaped, photo coordinates converted)
    plate = clean(
        [(59.9, -23.6), (59.9, 28.5), (46.4, 28.5), (46.4, 40.2), (7.6, 40.2), (7.6, 28.5), (-5.2, 28.5), (-5.2, -23.6)]
    )
    window = rect(17.0, 37.0, -10.1, 26.5)
    loft(p, plate, [window], "y", [(0.0, 9.75), (0.0, 11.6)], "nickel", hole_d=False)
    # copper slab exposed in the window, flush with the top of the plate
    loft(p, window, [], "y", [(0.08, 9.45), (0, 9.6), (0, 11.72)], "copper")
    # black carrier frame above the plate, opened over the nickel
    frame = rrect(78.5, 98.1, 3.0, n=3, cx=28.95, cy=1.45)
    cut = rrect(60.0, 51.0, 2.0, n=2, cx=27.4, cy=2.5)
    loft(p, frame, [cut], "y", [(0, 11.6), (0, 12.8)], "black_metal", hole_d=False)

    # copper heat pipes
    def pipe(pts):
        tube(p, chaikin(pts), 2.75, 1.35, "copper", n=8)

    pipe([(18.0, 13.9, -14.0), (18.0, 13.9, -30.0), (18.0, 13.9, -44.0), (18.0, 15.5, -54.0), (18.0, 18.4, -63.0)])
    pipe([(36.0, 13.9, -14.0), (36.0, 13.9, -30.0), (36.0, 13.9, -44.0), (36.0, 15.5, -54.0), (36.0, 18.4, -63.0)])
    pipe(
        [
            (2.0, 13.9, -14.0),
            (-10.0, 13.9, -14.0),
            (-22.0, 13.6, -6.0),
            (-33.0, 12.8, 2.0),
            (-42.0, 12.6, 8.0),
            (-44.0, 12.6, 14.0),
        ]
    )
    pipe(
        [
            (63.0, 13.9, -2.0),
            (66.5, 13.9, 14.0),
            (66.0, 13.9, 26.0),
            (58.0, 13.9, 35.5),
            (40.0, 13.9, 36.5),
            (13.0, 13.9, 36.5),
        ]
    )
    # ConnectX-7 cooling block
    block = rrect(31.0, 41.4, 2.0, n=2, cx=-49.2, cy=-10.0)
    win2 = rect(-59.2, -39.2, -21.75, 1.75)
    loft(p, block, [win2], "y", [(0.0, 9.6), (0.0, 11.2)], "black_metal", hole_d=False)
    loft(p, win2, [], "y", [(0.06, 9.45), (0, 9.6), (0, 11.3)], "copper")
    return p


FIN_X0, FIN_X1, FIN_Z0, FIN_Z1 = -59.5, 61.9, -68.0, -13.0
FIN_Y1, FIN_Y_LOW, FIN_Y_HIGH = 42.35, 17.75, 23.4


def build_fin_stack():
    p = Part()
    count = 66
    for i in range(count):
        x = FIN_X0 + i * (FIN_X1 - FIN_X0) / (count - 1)
        y0 = FIN_Y_HIGH if x < -19.65 else FIN_Y_LOW
        t = 0.36
        q = [(x - t / 2, y0, FIN_Z0), (x - t / 2, FIN_Y1, FIN_Z0), (x - t / 2, FIN_Y1, FIN_Z1), (x - t / 2, y0, FIN_Z1)]
        p.add(q[::-1], "fin")
        p.add([(a[0] + t, a[1], a[2]) for a in q], "fin")
        for z, flip in ((FIN_Z0, True), (FIN_Z1, False)):
            e = [(x - t / 2, y0, z), (x + t / 2, y0, z), (x + t / 2, FIN_Y1, z), (x - t / 2, FIN_Y1, z)]
            p.add(e[::-1] if flip else e, "fin")
    x0, x1, z0, z1 = FIN_X0 - 0.7, FIN_X1 + 0.7, FIN_Z0 - 0.3, FIN_Z1
    v0, v1 = -z1, -z0
    win = [rect(10.9, 17.9, 39.5, 46.5), rect(36.5, 43.5, 39.5, 46.5)]
    loft(p, rect(x0, x1, v0, v1), win, "y", [(0, FIN_Y1), (0, FIN_Y1 + 0.5)], "black_metal", hole_d=False)
    box(p, x0, -19.2, FIN_Y_HIGH - 0.5, FIN_Y_HIGH, z0, z1, "black_metal")
    box(p, -19.2, x1, FIN_Y_LOW - 0.5, FIN_Y_LOW, z0, z1, "black_metal")
    box(p, FIN_X0 - 1.2, FIN_X0 - 0.7, FIN_Y_HIGH - 0.5, FIN_Y1 + 0.5, z0, z1, "black_metal")
    box(p, FIN_X1 + 0.7, FIN_X1 + 1.2, FIN_Y_LOW - 0.5, FIN_Y1 + 0.5, z0, z1, "black_metal")
    # copper heat-pipe slugs visible through the two cover windows
    for cx in (14.4, 40.0):
        box(p, cx - 3.3, cx + 3.3, FIN_Y1 - 2.4, FIN_Y1 + 0.08, -46.3, -39.7, "copper", bottom=False)
    return p


def fan_outline(cx):
    r, v_rear, v_mid = 31.5, 13.0, -18.5
    pts = [(cx + r, v_rear), (cx - r, v_rear)]
    # round mounting notch in the side wall (photo: towards the rear corner)
    rho, vn = 3.6, v_rear - 12.5
    pts += [(cx - r + rho * math.sin(t * math.pi / 8), vn + rho * math.cos(t * math.pi / 8)) for t in range(9)]
    for i in range(33):
        a = math.radians(180 + 180 * i / 32)
        pts.append((cx + r * math.cos(a), v_mid + r * math.sin(a)))
    return clean(pts)


def build_fan(side):
    """side 0 = left, 1 = right. Housing only; the impeller is a separate node."""
    p = Part()
    cx = -32.05 if side == 0 else 31.95
    ax, az = INLET[side]
    outline = fan_outline(cx)
    r_o, r_i = 20.0, 10.8
    holes = []
    for a0, a1 in ((98, 199), (-28, 78), (219, 303)):
        n = max(4, int((a1 - a0) / 7))
        arc = [
            (
                ax + r_o * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                -az + r_o * math.sin(math.radians(a0 + (a1 - a0) * i / n)),
            )
            for i in range(n + 1)
        ]
        arc += [
            (
                ax + r_i * math.cos(math.radians(a1 - (a1 - a0) * i / n)),
                -az + r_i * math.sin(math.radians(a1 - (a1 - a0) * i / n)),
            )
            for i in range(n + 1)
        ]
        holes.append(arc)
    y0, y1 = FAN_Y0, FAN_Y1
    loft(p, outline, holes, "y", [(0, y1 - 0.9), (0, y1 - 0.25), (0.25, y1)], "black_fan", hole_d=False)
    loft(
        p,
        outline,
        [offset_loop(outline, 1.4)],
        "y",
        [(0, y0 + 0.9), (0, y1 - 0.9)],
        "black_fan",
        caps=(False, False),
        hole_d=False,
    )
    loft(p, outline, [], "y", [(0.25, y0), (0, y0 + 0.25), (0, y0 + 0.9)], "black_fan")
    # thin seam rim of the two-piece housing, visible as an edge line on the real part
    loft(
        p,
        offset_loop(outline, 0.35),
        [offset_loop(outline, 1.2)],
        "y",
        [(0, y1 + 0.01), (0, y1 + 0.08)],
        "black_fan",
        hole_d=False,
    )
    # raised hub-carrier disc and flat fan cable, airflow arrow pointing to the rear
    cyl(p, "y", ax, -az, 9.6, y1, y1 + 0.12, "black_fan", n=24)
    a = math.radians(-57)
    dx, dv = math.cos(a), math.sin(a)
    nx, nv = -dv, dx
    r0, r1, w = 11.5, 36.5, 1.25
    strip = [
        (ax + dx * r0 + nx * w, -az + dv * r0 + nv * w),
        (ax + dx * r0 - nx * w, -az + dv * r0 - nv * w),
        (ax + dx * r1 - nx * w, -az + dv * r1 - nv * w),
        (ax + dx * r1 + nx * w, -az + dv * r1 + nv * w),
    ]
    loft(p, strip, [], "y", [(0, y1), (0, y1 + 0.3)], "black_port")
    ux, uv = ax + 13.0, -az + 24.5
    arrow = [
        (ux + 2.0, uv - 4.2),
        (ux + 2.0, uv + 0.6),
        (ux + 4.2, uv + 0.6),
        (ux, uv + 5.0),
        (ux - 4.2, uv + 0.6),
        (ux - 2.0, uv + 0.6),
        (ux - 2.0, uv - 4.2),
    ]
    loft(p, arrow, [], "y", [(0, y1), (0, y1 + 0.1)], "chip")
    return p


def build_rotor(side):
    """Forward-curved blower impeller around a closed motor cup; axis Y."""
    p = Part()
    cx, cz = INLET[side]
    cv = -cz
    y0, y1 = FAN_Y0 + 2.5, FAN_Y1 - 2.5
    # motor cup (closed top) and web plate at the base of the blades
    loft(p, circle(10.0, 40, cx, cv), [], "y", [(0.0, y1 - 8.5), (0.0, y1 - 0.4), (0.4, y1)], "rotor")
    loft(
        p, circle(23.8, 56, cx, cv), [circle(9.8, 40, cx, cv)], "y", [(0.0, y0), (0.0, y0 + 0.7)], "rotor", hole_d=False
    )
    blades = 92
    r_in, r_out = 15.2, 23.6
    for b in range(blades):
        a0 = 2 * math.pi * b / blades
        stations = [(r_in + (r_out - r_in) * f, math.radians(19 * f**1.5)) for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
        t = 0.3
        out, back = [], []
        for r, da in stations:
            a = a0 + da
            tx, tv = -math.sin(a), math.cos(a)
            mid = (cx + r * math.cos(a), cv + r * math.sin(a))
            out.append((mid[0] + tx * t / 2, mid[1] + tv * t / 2))
            back.append((mid[0] - tx * t / 2, mid[1] - tv * t / 2))
        loft(p, out + back[::-1], [], "y", [(0, y0 + 0.5), (0, y1 - 0.5)], "rotor")
    # thin stabilising ring over the blade tips
    loft(
        p,
        circle(24.0, 56, cx, cv),
        [circle(22.8, 56, cx, cv)],
        "y",
        [(0.0, y1 - 0.5), (0.0, y1)],
        "rotor",
        hole_d=False,
    )
    return p


# ---------------------------------------------------------------------------
# Assembly table: node -> (label, explode vector mm, order, builder)
# ---------------------------------------------------------------------------


def pcb_uv(q, n):
    if n[1] > 0.9:
        return ((q[0] - PCB_X0) / (PCB_X1 - PCB_X0), 1 - (q[2] - PCB_Z0) / (PCB_Z1 - PCB_Z0))
    if n[1] < -0.9:
        return ((PCB_X1 - q[0]) / (PCB_X1 - PCB_X0), 1 - (q[2] - PCB_Z0) / (PCB_Z1 - PCB_Z0))
    return (0.002, 0.002)


def foam_uv(ox, oy):
    def f(q, n):
        u, v = uv_box(q, n)
        return (u + ox, v + oy)

    return f


CPU_Z = (-23.3, -6.95)  # CPU die towards the rear, GPU towards the front (teardown note)
GPU_Z = (-6.55, 7.4)

PARTS = {
    # name: (label, explode mm, order, builder, uv function, explicit origin)
    "shell": ("Aluminium shell", (0, 166, 0), 0, build_shell, None),
    "foam_front": ("Front metal foam", (0, 2, 70), 1, lambda: build_foam(True), foam_uv(0.0, 0.0)),
    "foam_rear": ("Rear metal foam", (0, 2, -70), 1, lambda: build_foam(False), foam_uv(0.37, 0.61)),
    "grip_left": ("Front grip (left)", (-6, 2, 92), 2, lambda: build_grip(-1), None),
    "grip_right": ("Front grip (right)", (6, 2, 92), 2, lambda: build_grip(1), None),
    "io_plate": ("Rear I/O plate", (0, 2, -94), 2, build_io_plate, None),
    "bottom_pad": ("Magnetic base pad", (0, -104, 0), 0, build_bottom_pad, None),
    "bottom_cover": ("Aluminium bottom cover", (0, -72, 0), 1, build_bottom_cover, None),
    "base_plate": ("Aluminium base plate", (0, -40, 0), 2, build_base_plate, None),
    "ssd_m2": (
        "M.2 2242 SSD",
        (-85, -18, 30),
        3,
        build_ssd,
        None,
    ),  # pulled out to the side, or the board and the foam hide it
    "wifi_card": ("Wi-Fi card", (6, -16, 0), 3, build_wifi, None),
    "pcb": ("Mainboard", (0, 0, 0), 0, build_pcb, pcb_uv),
    "qsfp_cage": ("QSFP cage with heatsinks", (-4, 16, -8), 6, build_qsfp, None),
    "cx7": ("ConnectX-7 NIC", (-4, 18, 6), 6, build_cx7, None),
    "gb10_package": ("GB10 package", (6, 62, 90), 7, build_gb10, None),
    "gb10_die_cpu": ("GB10 CPU die", (-2, 118, 98), 8, lambda: build_die(*CPU_Z, "die_cpu"), die_uv(*CPU_Z)),
    "gb10_die_gpu": ("GB10 GPU die", (14, 118, 112), 8, lambda: build_die(*GPU_Z, "die_gpu"), die_uv(*GPU_Z)),
    "thermal_module": ("Cold plate and heat pipes", (0, 46, 0), 5, build_thermal, None),
    "fin_stack": ("Heatsink fin stack", (0, 58, -6), 4, build_fin_stack, None),
    "fan_left": ("Left blower", (-8, 92, 6), 2, lambda: build_fan(0), None),
    "fan_right": ("Right blower", (8, 92, 6), 2, lambda: build_fan(1), None),
    "fan_left_rotor": ("Left impeller", (-8, 128, 6), 3, lambda: build_rotor(0), None),
    "fan_right_rotor": ("Right impeller", (8, 128, 6), 3, lambda: build_rotor(1), None),
}
for i, (xo, zo) in enumerate([(-5, -4), (-5, 0), (-5, 4), (-5, 8), (5, -4), (5, 0), (5, 4), (5, 8)]):
    PARTS[f"lpddr_{i}"] = (
        f"LPDDR5X memory {i + 1}/8",
        (xo, 15 + 2 * (i % 4), zo),
        6,
        (lambda k=i: build_lpddr(k)),
        rect_uv(LPDDR_POS[i][0] - 7.25, LPDDR_POS[i][0] + 7.25, LPDDR_POS[i][1] - 6.15, LPDDR_POS[i][1] + 6.15),
    )

ROTOR_ORIGIN = {"fan_left_rotor": INLET[0], "fan_right_rotor": INLET[1]}


WINDING_ERRORS = []


def winding_check(name, bm):
    """Closed islands must face outwards (the renderer may cull back faces). Open cups are skipped."""
    chk = bm.copy()
    chk.normal_update()
    seen, bad = set(), 0
    for start in chk.faces:
        if start.index in seen:
            continue
        seen.add(start.index)
        stack, island, closed = [start], [], True
        while stack:
            f = stack.pop()
            island.append(f)
            for e in f.edges:
                closed &= len(e.link_faces) == 2
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        if closed:
            before = [f.normal.copy() for f in island]
            bmesh.ops.recalc_face_normals(chk, faces=island)
            chk.normal_update()
            bad += sum(1 for f, b in zip(island, before) if f.normal.dot(b) < 0)
    chk.free()
    if bad:
        WINDING_ERRORS.append((name, bad))


def make_object(name, part, label, explode, order, uv_func, collection, mats):
    pts = [q for poly in part.polys for q in poly[0]]
    lo = [min(q[k] for q in pts) for k in range(3)]
    hi = [max(q[k] for q in pts) for k in range(3)]
    center = [(lo[k] + hi[k]) / 2 for k in range(3)]
    if name in ROTOR_ORIGIN:
        center[0], center[2] = ROTOR_ORIGIN[name]
    uv_func = uv_func or uv_box
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    cache = {}
    slot_map, slot_list = {}, []

    def vert(q):
        key = (round(q[0], 3), round(q[1], 3), round(q[2], 3))
        v = cache.get(key)
        if v is None:
            v = bm.verts.new(((q[0] - center[0]) * MM, -(q[2] - center[2]) * MM, (q[1] - center[1]) * MM))
            cache[key] = v
        return v

    tris = 0
    for poly, mat, uvs in part.polys:
        seen, points = set(), []
        for q in poly:
            key = (round(q[0], 3), round(q[1], 3), round(q[2], 3))
            if key not in seen:
                seen.add(key)
                points.append(q)
        if len(points) < 3:
            continue
        try:
            face = bm.faces.new([vert(q) for q in points])
        except ValueError:
            continue
        tris += len(points) - 2
        if mat not in slot_map:
            slot_map[mat] = len(slot_list)
            slot_list.append(mat)
        face.material_index = slot_map[mat]
        face.smooth = True
        n = poly_normal(points)
        for loop, q in zip(face.loops, points):
            loop[uvl].uv = uv_func(q, n)
    winding_check(name, bm)
    bm.to_mesh(me)
    bm.free()
    for mat in slot_list:
        if mat not in mats:
            mats[mat] = make_material(mat)
        me.materials.append(mats[mat])
    me.set_sharp_from_angle(angle=math.radians(38))
    me.update()
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    ob.location = (center[0] * MM, -center[2] * MM, center[1] * MM)
    ob["label"] = label
    ob["explode"] = [e * MM for e in explode]
    ob["order"] = int(order)
    return ob, tris, lo, hi


def jpeg_size(data):
    i = 2
    while i < len(data) - 8:
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            return struct.unpack(">HH", data[i + 5 : i + 9])[::-1]
        i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
    raise ValueError("no SOF")


def verify_glb(path):
    """Hard contract check of the exported file; raises on violations."""
    data = open(path, "rb").read()
    assert data[:4] == b"glTF"
    jlen = struct.unpack("<I", data[12:16])[0]
    gl = json.loads(data[20 : 20 + jlen])
    bin_start = 20 + jlen + 8
    binary = data[bin_start:]
    names = [n.get("name") for n in gl["nodes"]]
    want = set(PARTS)
    assert set(names) == want, f"node set differs: {set(names) ^ want}"
    assert len(data) <= 5 * 1024 * 1024, f"file too big: {len(data)}"
    assert "animations" not in gl and "cameras" not in gl
    assert not any(m.get("doubleSided") for m in gl["materials"])
    assert not gl.get("extensionsRequired"), gl.get("extensionsRequired")
    tris_total = 0
    world_lo = [1e9] * 3
    world_hi = [-1e9] * 3
    report = []
    acc = gl["accessors"]
    for node in gl["nodes"]:
        name = node.get("name")
        if name not in want:
            continue
        ex = node.get("extras", {})
        assert isinstance(ex.get("label"), str) and ex["label"], (name, ex)
        assert len(ex.get("explode", [])) == 3, (name, ex)
        assert isinstance(ex.get("order"), int), (name, ex)
        assert "mesh" in node and "rotation" not in node and "scale" not in node, name
        t = node.get("translation", [0, 0, 0])
        mesh = gl["meshes"][node["mesh"]]
        lo = [1e9] * 3
        hi = [-1e9] * 3
        tris = 0
        for prim in mesh["primitives"]:
            attrs = prim["attributes"]
            assert set(attrs) == {"POSITION", "NORMAL", "TEXCOORD_0", "TEXCOORD_1"}, (name, sorted(attrs))
            a = acc[attrs["POSITION"]]
            lo = [min(x, y) for x, y in zip(lo, a["min"])]
            hi = [max(x, y) for x, y in zip(hi, a["max"])]
            tris += acc[prim["indices"]]["count"] // 3
        tris_total += tris
        center = [(a + b) / 2 for a, b in zip(lo, hi)]
        assert all(abs(c) < 1e-4 for c in center), (name, "mesh not centred", center)
        for k in range(3):
            world_lo[k] = min(world_lo[k], lo[k] + t[k])
            world_hi[k] = max(world_hi[k], hi[k] + t[k])
        report.append((name, tris, ex["explode"], ex["order"], [round((b - a) * 1000, 2) for a, b in zip(lo, hi)]))
    # textures
    for mat in gl.get("materials", []):
        for slot in ("normalTexture", "emissiveTexture"):
            if slot in mat:
                assert "texCoord" not in mat[slot] or mat[slot]["texCoord"] == 0
    images = gl.get("images", [])
    for img in images:
        view = gl["bufferViews"][img["bufferView"]]
        chunk = binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]]
        if img["mimeType"] == "image/jpeg":
            w, h = jpeg_size(chunk)
        else:
            w, h = struct.unpack(">II", chunk[16:24])
        assert max(w, h) <= 1024, (img.get("name"), w, h)
        print(f"  image {img.get('name')}: {w}x{h} {img['mimeType']} {view['byteLength'] // 1024} KiB")
    foam = next(m for m in gl["materials"] if m["name"] == "foam")
    assert "emissiveTexture" in foam and "baseColorTexture" in foam["pbrMetallicRoughness"]
    assert tris_total <= 60000, tris_total
    size = [(b - a) * 1000 for a, b in zip(world_lo, world_hi)]
    print(
        f"VERIFY size={len(data) / 1024 / 1024:.2f} MiB tris={tris_total} bbox_mm={[round(s, 2) for s in size]} y=[{world_lo[1] * 1000:.2f},{world_hi[1] * 1000:.2f}]"
    )
    assert abs(size[0] - 150) < 0.3 and abs(size[2] - 150) < 0.3, size
    assert abs(size[1] - 50.5) < 0.3, size
    return sorted(report, key=lambda r: list(PARTS).index(r[0]))


def check_explosion(objs):
    """Fully exploded pose: no two parts may share a triangle-triangle intersection."""
    trees = {}
    for ob in objs:
        off = np.array(ob["explode"])
        d = (off[0], -off[2], off[1])
        verts = [Vector(v.co) + ob.location + Vector(d) for v in ob.data.vertices]
        trees[ob.name] = BVHTree.FromPolygons(verts, [tuple(p.vertices) for p in ob.data.polygons], epsilon=0.0)
    names = sorted(trees)
    hits = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            ov = trees[a].overlap(trees[b])
            if ov:
                hits.append((a, b, len(ov)))
    if hits:
        raise RuntimeError(f"explosion intersections: {hits}")
    print("EXPLOSION: no intersections between", len(names), "parts")


def build():
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)  # no default cube in the export
    build_foam_textures()
    build_board_textures()
    die_texture("die_gpu", 14.4, GPU_Z[1] - GPU_Z[0], 5, True)
    die_texture("die_cpu", 14.4, CPU_Z[1] - CPU_Z[0], 6, False)
    lpddr_texture()
    print(f"textures done in {time.time() - t0:.1f}s")
    col = bpy.data.collections.new("spark")
    bpy.context.scene.collection.children.link(col)
    mats, objs, totals = {}, [], 0
    for name, (label, ex, order, builder, uv) in PARTS.items():
        ob, tris, lo, hi = make_object(name, builder(), label, ex, order, uv, col, mats)
        objs.append(ob)
        totals += tris
        print(
            f"{name:18s} tris={tris:6d} x[{lo[0]:7.2f},{hi[0]:7.2f}] y[{lo[1]:6.2f},{hi[1]:6.2f}] z[{lo[2]:7.2f},{hi[2]:7.2f}]"
        )
    print("TOTAL tris", totals)
    assert not WINDING_ERRORS, f"inward-facing closed islands: {WINDING_ERRORS}"
    print("WINDING: all closed islands face outwards")
    check_explosion(objs)
    light = bake_light(objs)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=OUT,
        export_format="GLB",
        use_selection=False,
        export_apply=False,
        export_yup=True,
        export_texcoords=True,
        export_normals=True,
        export_tangents=False,
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_extras=True,
        export_draco_mesh_compression_enable=False,
        export_skins=False,
        export_morph=False,
    )
    report = verify_glb(OUT)
    embed_lightmap(OUT, light)
    print(json.dumps([[r[0], r[1], [round(v, 4) for v in r[2]], r[3]] for r in report]))
    print(f"OK {OUT} {os.path.getsize(OUT) / 1024 / 1024:.2f} MiB in {time.time() - t0:.1f}s")


# ---------------------------------------------------------------------------
# Baked studio light: the soft shadows of the open machine, from Cycles, for the realtime page
# ---------------------------------------------------------------------------

BAKE_SIZE, BAKE_SAMPLES = 2048, 256
LIGHT_JPG = os.path.join(TMP, "spark_light.jpg")


def bake_light(objs):
    """One 2048 atlas of diffuse light on a white machine in its exploded pose (second UV map)."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "METAL"
    scene.cycles.samples = BAKE_SAMPLES
    scene.cycles.use_denoising = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    world = bpy.data.worlds.new("bake_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.64, 0.68, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.34
    scene.world = world
    added = []
    for name, pos, power, size in (
        ("bake_key", (-0.34, 0.56, 0.38), 5.2, 0.9),
        ("bake_fill", (0.5, 0.2, 0.3), 1.0, 1.0),
        ("bake_rim", (0.1, 0.3, -0.5), 1.4, 0.8),
    ):
        li = bpy.data.lights.new(name, "AREA")
        li.energy, li.size = power, size
        ob = bpy.data.objects.new(name, li)
        scene.collection.objects.link(ob)
        ob.location = (pos[0], -pos[2], pos[1])
        ob.rotation_euler = (Vector((0, 0, 0.03)) - ob.location).to_track_quat("-Z", "Y").to_euler()
        added.append(ob)
    home = {o.name: o.location.copy() for o in objs}
    for o in objs:
        ex = o["explode"]
        o.location += Vector((ex[0], -ex[2], ex[1]))
    for o in objs:
        o.data.uv_layers.new(name="Bake")
        o.data.uv_layers.active = o.data.uv_layers["Bake"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")
    image = bpy.data.images.new("spark_light", BAKE_SIZE, BAKE_SIZE, float_buffer=True)
    white = bpy.data.materials.new("bake_white")
    white.use_nodes = True
    nodes = white.node_tree.nodes
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 1.0
    node = nodes.new("ShaderNodeTexImage")
    node.image = image
    nodes.active = node
    keep = {}
    for o in objs:  # slot by slot: emptying the list would throw away which face uses which material
        keep[o.name] = list(o.data.materials)
        for i in range(len(keep[o.name])):
            o.data.materials[i] = white
    t1 = time.time()
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, margin=12, use_clear=True)
    print(f"BAKED light in {time.time() - t1:.0f}s")
    pixels = list(image.pixels)
    peak = sorted(pixels[i] for i in range(0, len(pixels), 4 * 97))[-1]
    print(f"light peak {peak:.2f}")
    for o in objs:
        for i, m in enumerate(keep[o.name]):
            o.data.materials[i] = m
        o.location = home[o.name]
    for ob in added:
        bpy.data.objects.remove(ob)
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 90
    scene.render.image_settings.color_mode = "RGB"
    image.save_render(LIGHT_JPG, scene=scene)
    return LIGHT_JPG


def embed_lightmap(path, jpg):
    """Append the baked atlas to the GLB as image asset.extras.lightmap, no exporter support needed."""
    with open(path, "rb") as f:
        data = f.read()
    json_len = struct.unpack("<I", data[12:16])[0]
    js = json.loads(data[20 : 20 + json_len])
    bin_data = bytearray(data[20 + json_len + 8 :])
    with open(jpg, "rb") as f:
        pic = f.read()
    offset = len(bin_data)
    bin_data += pic
    while len(bin_data) % 4:
        bin_data.append(0)
    js["buffers"][0]["byteLength"] = len(bin_data)
    js.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": offset, "byteLength": len(pic)})
    js.setdefault("images", []).append(
        {"bufferView": len(js["bufferViews"]) - 1, "mimeType": "image/jpeg", "name": "spark_light"}
    )
    js["asset"].setdefault("extras", {})["lightmap"] = len(js["images"]) - 1
    blob = json.dumps(js, separators=(",", ":")).encode()
    blob += b" " * ((4 - len(blob) % 4) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(blob) + 8 + len(bin_data))
    out += (
        struct.pack("<II", len(blob), 0x4E4F534A)
        + blob
        + struct.pack("<II", len(bin_data), 0x004E4942)
        + bytes(bin_data)
    )
    assert len(out) <= 6 * 1024 * 1024, f"GLB {len(out) / 1024 / 1024:.2f} MiB is over the 6 MiB budget"  # verify_glb ran before the atlas went in
    with open(path, "wb") as f:
        f.write(out)
    print(f"lightmap {len(pic) / 1024:.0f} KiB embedded, GLB {len(out) / 1024 / 1024:.2f} MiB")


# ---------------------------------------------------------------------------
# QA renders of the exported GLB (Cycles, headless)
# ---------------------------------------------------------------------------


def look_at(cam, pos, target):
    # positions given in glTF metres
    p = Vector((pos[0], -pos[2], pos[1]))
    t = Vector((target[0], -target[2], target[1]))
    cam.location = p
    cam.rotation_euler = (t - p).to_track_quat("-Z", "Y").to_euler()


SHELL_PARTS = ("foam_rear", "io_plate", "shell", "foam_front", "grip_left", "grip_right")
UPPER = SHELL_PARTS + ("fan_left", "fan_right", "fan_left_rotor", "fan_right_rotor", "fin_stack", "thermal_module")
VIEWS = {  # name: camera, target (glTF m), exploded, lens, hidden parts
    "assembled_front_top": ((0.27, 0.205, 0.34), (0.0, 0.018, 0.0), False, 58, ()),
    "rear_ports": ((-0.13, 0.09, -0.40), (-0.008, 0.016, -0.01), False, 58, ()),
    "exploded": ((0.40, 0.33, 0.62), (0.0, 0.052, 0.012), True, 42, ()),
    "front_flat": ((0.0, 0.032, 0.42), (0.0, 0.021, 0.0), False, 80, ()),
    "rear_flat": ((0.0, 0.03, -0.42), (0.0, 0.021, 0.0), False, 80, ()),
    "bottom": ((0.0, -0.42, 0.001), (0.0, 0.0, 0.0), False, 80, ()),
    "board_top": ((0.0, 0.34, 0.001), (0.0, 0.0, -0.01), False, 70, UPPER),
    "board_lifted": (
        (0.1, 0.30, 0.27),
        (0.01, 0.0, 0.0),
        True,
        55,
        UPPER + ("gb10_package", "gb10_die_gpu", "gb10_die_cpu"),
    ),
    "module_front": ((0.1, 0.28, 0.34), (0.0, 0.03, 0.0), False, 50, SHELL_PARTS),
    "module_rear": ((-0.08, 0.06, -0.26), (0.0, 0.02, -0.03), False, 55, SHELL_PARTS),
    "fans_top": ((0.0, 0.42, 0.012), (0.0, 0.03, 0.02), False, 60, SHELL_PARTS),
    "gb10_close": ((0.09, 0.22, 0.24), (0.035, 0.11, 0.075), True, 60, ()),
    "fans_close": ((0.02, 0.33, 0.20), (-0.012, 0.13, 0.04), True, 62, ("shell",)),
    "thermal_top": (
        (0.02, 0.35, 0.05),
        (0.0, 0.05, 0.0),
        True,
        60,
        UPPER[:6] + ("fan_left", "fan_right", "fan_left_rotor", "fan_right_rotor", "fin_stack"),
    ),
    "underside": ((0.14, -0.33, 0.24), (0.0, 0.0, 0.0), False, 60, ()),
    "glow_front": ((0.0, 0.032, 0.42), (0.0, 0.021, 0.0), False, 80, ()),
    "board_under": ((0.0, -0.32, 0.001), (0.0, 0.0, -0.012), False, 70, ("bottom_pad", "bottom_cover", "base_plate")),
    "exploded_below": ((0.30, -0.26, 0.52), (0.0, -0.03, 0.012), True, 45, ()),
}


def render(out_dir, res, samples, only=None):
    os.makedirs(out_dir, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=OUT)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "METAL"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.5, 0.52, 0.55, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.42
    scene.world = world
    # the foam glows only in the app: emission off for the beauty renders
    for m in bpy.data.materials:
        if m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == "BSDF_PRINCIPLED" and n.inputs["Emission Strength"].is_linked is False:
                    n.inputs["Emission Strength"].default_value = 0.0
    # soft studio lights (positions in glTF metres)
    for name, pos, power, size, col in (
        ("key", (0.25, 0.5, 0.35), 4.2, 0.9, (1, 0.98, 0.95)),
        ("fill", (-0.5, 0.2, 0.3), 1.2, 1.0, (0.92, 0.95, 1.0)),
        ("rim", (0.1, 0.25, -0.5), 1.8, 0.8, (1, 1, 1)),
        ("under", (0, -0.5, 0.1), 0.9, 1.0, (1, 1, 1)),
    ):
        li = bpy.data.lights.new(name, "AREA")
        li.energy, li.size, li.color = power, size, col
        ob = bpy.data.objects.new(name, li)
        scene.collection.objects.link(ob)
        ob.location = (pos[0], -pos[2], pos[1])
        ob.rotation_euler = (Vector((0, 0, 0.03)) - ob.location).to_track_quat("-Z", "Y").to_euler()
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    parts = [o for o in bpy.data.objects if o.type == "MESH" and "explode" in o]
    base = {o.name: o.location.copy() for o in parts}
    # ground plane
    ground_me = bpy.data.meshes.new("ground")
    s = 1.5
    ground_me.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
    ground = bpy.data.objects.new("ground", ground_me)
    scene.collection.objects.link(ground)
    gm = bpy.data.materials.new("groundmat")
    gm.use_nodes = True
    bsdf = next(n for n in gm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0.62, 0.64, 0.67, 1)
    bsdf.inputs["Roughness"].default_value = 0.5
    ground_me.materials.append(gm)
    for vname, (pos, target, exploded, lens, hidden) in VIEWS.items():
        if only and vname not in only:
            continue
        for o in parts:
            o.location = base[o.name].copy()
            o.hide_render = o.name in hidden
            if exploded:
                ex = o["explode"]
                o.location += Vector((ex[0], -ex[2], ex[1]))
        ground.location = (0, 0, -0.113 if exploded else -0.0052)
        ground.hide_render = vname in ("bottom", "underside", "exploded_below", "board_under")
        for m in bpy.data.materials:  # pore glow is an app feature; on only for the mask check
            if m.name.startswith("foam") and m.use_nodes:
                for n in m.node_tree.nodes:
                    if n.type == "BSDF_PRINCIPLED":
                        n.inputs["Emission Strength"].default_value = 3.0 if vname == "glow_front" else 0.0
        cam_data.lens = lens
        look_at(cam, pos, target)
        scene.render.filepath = os.path.join(out_dir, vname + ".png")
        scene.render.image_settings.file_format = "PNG"
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"RENDERED {vname} in {time.time() - t1:.0f}s -> {scene.render.filepath}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if argv[:1] == ["--render"]:
        final = len(argv) > 3 and argv[3] == "final"
        res = (1800, 1266) if final else (1280, 900)
        samples = 256 if final else 96
        only = None
        if len(argv) > 2:
            only = argv[2].split(",")
        render(argv[1], res, samples, only)
        return
    build()


main()
