import os
import sys
import json
import shutil
import subprocess
import time
import uuid
import ctypes
import threading
from io import BytesIO
from PIL import Image, ImageChops, ImageEnhance, ImageFilter
import numpy as np
import psutil
import hashlib
from concurrent.futures import ThreadPoolExecutor

try:
    import oead
except ImportError:
    oead = None

from core import bfstm_nx, bfsar_sfx

_DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STUDIO_ROOT = os.environ.get("SWITCH_STUDIO_ROOT", _DEFAULT_ROOT if os.path.isdir(os.path.join(_DEFAULT_ROOT, "odyssey_romfs")) else r"C:\Users\adria\.gemini\antigravity\scratch\spriteswap-studio")
ROMFS_ROOT = os.environ.get("ODYSSEY_ROMFS_DIR", os.path.join(STUDIO_ROOT, "odyssey_romfs"))
TOOLBOX_DIR = os.environ.get("SWITCH_TOOLBOX_DIR", os.path.join(STUDIO_ROOT, "toolbox"))
TEXCONV = os.environ.get("TEXCONV_EXE", os.path.join(STUDIO_ROOT, "texconv.exe"))
INJECT_EXE = os.path.join(TOOLBOX_DIR, "InjectMarioTexture.exe")
HIDE_SHAPES_EXE = os.path.join(TOOLBOX_DIR, "HideShapes.exe")
PATCH_VERTICES_EXE = os.path.join(TOOLBOX_DIR, "PatchVertices.exe")
EXPORT_EXE = os.path.join(TOOLBOX_DIR, "ExportMarioFace.exe")
CONVERT_AUDIO_EXE = os.path.join(TOOLBOX_DIR, "ConvertAudio.exe")
EDEN_EXE = os.environ.get("EDEN_EXE", os.path.join(os.path.expanduser("~"), "Desktop", "Switch Emu", "eden.exe"))
EDEN_LOAD_DIR = os.environ.get("EDEN_LOAD_DIR", os.path.join(os.environ.get("APPDATA", ""), "eden", "load", "0100000000010000"))
ISO_DIR = os.environ.get("ODYSSEY_ISO_DIR", os.path.join(os.path.expanduser("~"), "Desktop", "Switch Emu", "ISO"))

def find_mario_nsp():
    if os.path.isdir(ISO_DIR):
        for f in os.listdir(ISO_DIR):
            if "0100000000010000" in f and "v0" in f and f.endswith(".nsp"):
                return os.path.join(ISO_DIR, f)
        for f in os.listdir(ISO_DIR):
            if "0100000000010000" in f and f.endswith(".nsp"):
                return os.path.join(ISO_DIR, f)
    return ""

GAME_NSP = find_mario_nsp()

CACHE_DIR = os.path.join(STUDIO_ROOT, "switch_studio", "cache")
SETTINGS_PATH = os.path.join(STUDIO_ROOT, "switch_studio", "cache", "studio_settings.json")
os.makedirs(CACHE_DIR, exist_ok=True)

TEXTURE_SLOTS = {
    "mario_body": {
        "title": "Mario Body & Outfit",
        "description": "Overalls, shirt, boots, and brass buttons",
        "szs": "Mario.szs",
        "bfres": "Mario.bfres",
        "texture": "MarioBody_alb",
        "format": "BC1_UNORM",
        "width": 512,
        "height": 256,
        "category": "Character",
    },
    "mario_cap": {
        "title": "Mario Felt Cap & Emblem",
        "description": "Red felt cap and circular 'M' insignia",
        "szs": "MarioHeadTexture.szs",
        "bfres": "MarioHeadTexture.bfres",
        "texture": "MarioCap_alb",
        "format": "BC1_UNORM",
        "width": 256,
        "height": 256,
        "category": "Character",
    },
    "mario_face": {
        "title": "Mario Facial Skin & Features",
        "description": "Cheeks, nose, forehead, mouth cavity",
        "szs": "MarioFace.szs",
        "bfres": "MarioFace.bfres",
        "texture": "MarioFace_alb",
        "format": "BC1_UNORM",
        "width": 256,
        "height": 256,
        "category": "Face",
    },
    "mario_eye": {
        "title": "Mario Eyes & Iris",
        "description": "Pupil, iris color, highlights, and eye texture",
        "szs": "MarioEye.szs",
        "bfres": "MarioEye.bfres",
        "texture": "MarioEyePupil_alb",
        "format": "BC3_UNORM",
        "width": 256,
        "height": 256,
        "category": "Face",
    },
    "mario_hair": {
        "title": "Mario Mustache & Eyebrows",
        "description": "Facial hair and eyebrows",
        "szs": "MarioFace.szs",
        "bfres": "MarioFace.bfres",
        "texture": "MarioHairFace_alb",
        "format": "BC1_UNORM",
        "width": 512,
        "height": 512,
        "category": "Character",
    },
}

# every archive a slot's deploy writes into the mod (the main model plus the variants that share the texture)
SLOT_ARCHIVES = {
    "mario_body": ["Mario.szs", "MarioColorLuigi.szs"],
    "mario_cap": ["MarioHeadTexture.szs", "MarioCaptainHeadTexture.szs", "MarioColorLuigiHeadTexture.szs"],
    "mario_face": ["MarioFace.szs", "MarioHighFace.szs"],
    "mario_eye": ["MarioEye.szs", "MarioHighEye.szs"],
    "mario_hair": ["MarioFace.szs"],
}


class SwitchEngine:
    def __init__(self):
        self.active_mod_name = "ClaraMarioReshaped"
        self.model_view = None          # set by the server; needed to project photos onto the real face mesh
        self._face_map_cache = {}
        self.face_reshape = None        # set by the server (core.face_reshape.FaceReshape)
        self.settings = {"hide_face_parts": True, "deployed_hide_face_parts": False,
                         "reshape_strength": 0.0, "deployed_reshape_sig": ""}
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                self.settings.update(json.load(f))
        except (OSError, ValueError):
            pass
        self.track_specs = {}
        specs_path = os.path.join(STUDIO_ROOT, "switch_studio", "track_specs.json")
        if os.path.isfile(specs_path):
            try:
                with open(specs_path, "r", encoding="utf-8") as f:
                    self.track_specs = json.load(f)
            except Exception as e:
                print(f"Error loading track specs: {e}")

    def get_status(self):
        eden_found = os.path.isfile(EDEN_EXE)
        nsp_found = os.path.isfile(GAME_NSP)
        romfs_found = os.path.isdir(ROMFS_ROOT)
        
        mods = []
        if os.path.isdir(EDEN_LOAD_DIR):
            for d in os.listdir(EDEN_LOAD_DIR):
                full_d = os.path.join(EDEN_LOAD_DIR, d)
                if os.path.isdir(full_d):
                    mods.append(d)

        return {
            "game": "Super Mario Odyssey [0100000000010000]",
            "eden_available": eden_found,
            "eden_path": EDEN_EXE,
            "nsp_available": nsp_found,
            "nsp_path": GAME_NSP,
            "romfs_available": romfs_found,
            "active_mod": self.active_mod_name,
            "installed_mods": mods,
            "texture_slots_count": len(TEXTURE_SLOTS)
        }

    def get_texture_slots(self):
        res = []
        for slot_id, info in TEXTURE_SLOTS.items():
            res.append({
                "id": slot_id,
                "title": info["title"],
                "description": info["description"],
                "category": info["category"],
                "width": info["width"],
                "height": info["height"],
                "format": info["format"],
                "texture_name": info["texture"],
                "preview_url": f"/api/texture/preview?slot={slot_id}&type=orig",
                "modded_url": f"/api/texture/preview?slot={slot_id}&type=mod"
            })
        return res

    def get_texture_png(self, slot_id, modded=False):
        if slot_id not in TEXTURE_SLOTS:
            return None
        info = TEXTURE_SLOTS[slot_id]
        tex_name = info["texture"]
        
        cache_orig = os.path.join(CACHE_DIR, f"{slot_id}_orig.png")
        cache_mod = os.path.join(CACHE_DIR, f"{slot_id}_mod.png")

        if modded and os.path.isfile(cache_mod):
            return cache_mod

        if not os.path.isfile(cache_orig):
            # Check if exported DDS exists in studio
            dds_orig = os.path.join(STUDIO_ROOT, f"{tex_name}.dds")
            if not os.path.isfile(dds_orig):
                # Run export tool
                bfres_path = os.path.join(TOOLBOX_DIR, info["bfres"])
                if os.path.isfile(bfres_path):
                    subprocess.run([EXPORT_EXE, bfres_path], cwd=TOOLBOX_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.isfile(dds_orig):
                subprocess.run([TEXCONV, "-ft", "png", "-y", "-o", CACHE_DIR, dds_orig], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                gen_png = os.path.join(CACHE_DIR, f"{tex_name}.png")
                if os.path.isfile(gen_png):
                    shutil.move(gen_png, cache_orig)

        if modded and not os.path.isfile(cache_mod):
            # Fallback to orig if no modded version yet
            return cache_orig

        return cache_mod if modded else cache_orig

    def apply_color_transform(self, slot_id, hue_shift=0, sat_mult=1.0, val_mult=1.0, invert=False):
        orig_png = self.get_texture_png(slot_id, modded=False)
        if not orig_png or not os.path.isfile(orig_png):
            return None

        img = Image.open(orig_png).convert("RGBA")
        r, g, b, a = img.split()
        rgb_img = Image.merge("RGB", (r, g, b))
        
        # Convert to HSV
        hsv = np.array(rgb_img.convert("HSV"), dtype=np.float32)
        
        # Apply Hue shift (-180..180 -> -128..128 in 255 space)
        h_shift_byte = (hue_shift / 360.0) * 255.0
        hsv[:, :, 0] = (hsv[:, :, 0] + h_shift_byte) % 256.0
        
        # Saturation & Value
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * sat_mult, 0, 255)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * val_mult, 0, 255)
        
        mod_rgb = Image.fromarray(hsv.astype(np.uint8), mode="HSV").convert("RGB")
        if invert:
            from PIL import ImageOps
            mod_rgb = ImageOps.invert(mod_rgb)
            
        r2, g2, b2 = mod_rgb.split()
        res_img = Image.merge("RGBA", (r2, g2, b2, a))
        
        mod_cache = os.path.join(CACHE_DIR, f"{slot_id}_mod.png")
        res_img.save(mod_cache)
        return mod_cache

    @staticmethod
    def composite_base_center(slot_id):
        """Where (as a fraction of the texture) a composited image is centred before offsets are applied."""
        if slot_id == "mario_face":
            # Hand-tuned: the front of Mario's face (nose and cheeks) in the top-left quadrant of the UV texture.
            return 0.28, 0.25
        return 0.5, 0.5

    # ---- photo projected onto the real face mesh ---------------------------------------------------------
    FACE_PHOTO_WIDTH = 64.0     # model units spanned by the photo at scale 1.0 (the face is ~60 units wide)
    FACE_CENTRE_Y = 8.0         # model-space height of the photo centre at offset 0
    FACE_OFFSET_UNITS_PER_PX = 0.25

    @staticmethod
    def _shift2d(arr, dy, dx):
        """Shift a 2D or 3D array by (dy, dx) without wrapping across image edges."""
        res = np.zeros_like(arr)
        h, w = arr.shape[:2]
        sy0, sy1 = max(0, -dy), min(h, h - dy)
        dy0, dy1 = max(0, dy), min(h, h + dy)
        sx0, sx1 = max(0, -dx), min(w, w - dx)
        dx0, dx1 = max(0, dx), min(w, w + dx)
        if sy1 > sy0 and sx1 > sx0:
            res[dy0:dy1, dx0:dx1] = arr[sy0:sy1, sx0:sx1]
        return res

    def face_position_map(self, size):
        """For every texel of the face texture covered by the front of the face mesh: its model-space position.

        Triangles are rasterised in UV space and the mesh positions interpolated, so each texel knows where it sits
        on the 3D face. Returns (pos[H,W,3] float32, covered[H,W] bool)."""
        if size in self._face_map_cache:
            return self._face_map_cache[size]
        P, N, UV, tris = self.model_view.face_geometry()
        pos = np.zeros((size, size, 3), np.float32)
        cov = np.zeros((size, size), bool)
        for tri in tris:
            uv = UV[tri]
            if uv.min() < 0.0 or uv.max() > 1.0:
                continue                                   # outside the main UV tile (teeth, tongue...)
            is_nose_island = (uv[:, 0].mean() > 0.72) and (uv[:, 1].mean() < 0.58)
            if N[tri][:, 2].mean() < 0.05 and not is_nose_island:
                continue                                   # include cheek sides down to Nz=0.05 to avoid a stair-step on the cheek
            pts = uv * size
            x0, y0 = np.floor(pts.min(axis=0)).astype(int)
            x1, y1 = np.ceil(pts.max(axis=0)).astype(int)
            x0, y0 = max(x0, 0), max(y0, 0)
            x1, y1 = min(x1, size - 1), min(y1, size - 1)
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            a, b, c = pts
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-9:
                continue
            w0 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / den
            w1 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / den
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -0.02) & (w1 >= -0.02) & (w2 >= -0.02)   # slight overlap closes the seams between triangles
            if not inside.any():
                continue
            xyz = w0[..., None] * P[tri[0]] + w1[..., None] * P[tri[1]] + w2[..., None] * P[tri[2]]
            ys, xs = np.nonzero(inside)
            pos[y0 + ys, x0 + xs] = xyz[ys, xs]
            cov[y0 + ys, x0 + xs] = True
        # Grow the covered area a few texels without wrapping across texture boundaries (x=0 must never wrap to x=255).
        for _ in range(6):
            grown = cov.copy()
            acc = np.zeros_like(pos)
            cnt = np.zeros(cov.shape, np.float32)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                sh_cov = self._shift2d(cov, dy, dx)
                sh_pos = self._shift2d(pos, dy, dx)
                acc += sh_pos * sh_cov[..., None]
                cnt += sh_cov
            new = (~cov) & (cnt > 0)
            pos[new] = acc[new] / cnt[new][:, None]
            grown |= new
            cov = grown
        self._face_map_cache[size] = (pos, cov)
        return pos, cov

    def face_reference_color(self):
        """Mean colour of Mario's vanilla cheeks (what his lighting and the rest of his look are built around)."""
        if getattr(self, "_face_ref", None) is None:
            pos, cov = self.face_position_map(256)
            orig = np.asarray(Image.open(self.get_texture_png("mario_face", modded=False)).convert("RGB"), dtype=np.float64)
            x, y = pos[..., 0], pos[..., 1]
            cheek = cov & (np.abs(x) > 12) & (np.abs(x) < 26) & (y > -4) & (y < 16)
            m = orig[cheek].mean(axis=0)
            self._face_ref = {"rgb": [round(float(v), 1) for v in m],
                              "luminance": round(float(0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]), 1)}
        return self._face_ref

    def face_point_at_uv(self, u, v, size=256):
        """Model-space (x, y) under a UV position of the face texture, or None."""
        pos, cov = self.face_position_map(size)
        x, y = int(u * size), int(v * size)
        if 0 <= x < size and 0 <= y < size and cov[y, x]:
            return float(pos[y, x, 0]), float(pos[y, x, 1])
        return None

    @staticmethod
    def _bilinear(arr, px, py):
        h, w = arr.shape[:2]
        px = np.clip(px, 0, w - 1)
        py = np.clip(py, 0, h - 1)
        x0 = np.floor(px).astype(int)
        y0 = np.floor(py).astype(int)
        x1 = np.minimum(x0 + 1, w - 1)
        y1 = np.minimum(y0 + 1, h - 1)
        fx = (px - x0)[..., None]
        fy = (py - y0)[..., None]
        return (arr[y0, x0] * (1 - fx) * (1 - fy) + arr[y0, x1] * fx * (1 - fy) +
                arr[y1, x0] * (1 - fx) * fy + arr[y1, x1] * fx * fy)

    def apply_projected_face(self, slot_id, photo_stream_or_path, scale=1.0, offset_x=0, offset_y=0,
                             rotation=0.0, feather=8, opacity=1.0):
        """Project a portrait onto the real face mesh from the front, then bake it into the face texture.

        Unlike pasting a rectangle into the UV layout (which is stretched and rotated relative to the face), this keeps
        the photo undistorted when seen on the model. rotation is degrees, positive = clockwise."""
        from scipy.ndimage import gaussian_filter
        if slot_id != "mario_face" or self.model_view is None:
            return None
        orig_png = self.get_texture_png(slot_id, modded=False)
        if not orig_png or not os.path.isfile(orig_png):
            return None
        base = Image.open(orig_png).convert("RGBA")
        bw, bh = base.size
        pos, cov = self.face_position_map(bw)

        if isinstance(photo_stream_or_path, str):
            photo = Image.open(photo_stream_or_path).convert("RGBA")
        else:
            photo = Image.open(BytesIO(photo_stream_or_path)).convert("RGBA")
        if feather > 0:
            r, g, b, a = photo.split()
            a = a.filter(ImageFilter.GaussianBlur(radius=feather * max(1.0, photo.width / 256.0)))
            photo = Image.merge("RGBA", (r, g, b, a))
        ph = np.asarray(photo, dtype=np.float32)
        pw_px, ph_px = photo.size

        width_u = self.FACE_PHOTO_WIDTH * scale
        height_u = width_u * ph_px / pw_px
        X = pos[..., 0] - offset_x * self.FACE_OFFSET_UNITS_PER_PX
        Y = pos[..., 1] - (self.FACE_CENTRE_Y - offset_y * self.FACE_OFFSET_UNITS_PER_PX)
        th = np.radians(rotation)
        xr = X * np.cos(th) - Y * np.sin(th)
        yr = X * np.sin(th) + Y * np.cos(th)
        u = xr / width_u + 0.5
        v = 0.5 - yr / height_u
        inside = cov & (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
        side_taper = np.clip((20.5 - np.abs(pos[..., 0])) / 6.5, 0.0, 1.0)
        soft_inside = gaussian_filter((inside.astype(np.float32) * side_taper), 2.5)

        samp = self._bilinear(ph, u * (pw_px - 1), v * (ph_px - 1))
        alpha = (samp[..., 3] / 255.0 * opacity * soft_inside)[..., None]
        alpha = alpha * (1.0 - self._mouth_cavity(base))[..., None]      # never paint the inside of the mouth
        out = np.asarray(base, dtype=np.float32).copy()
        out[..., :3] = out[..., :3] * (1 - alpha) + samp[..., :3] * alpha
        out = self._match_uncovered_skin(np.asarray(base, dtype=np.float32), out, alpha[..., 0], pos, cov, self._skin_tint_path())
        res = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")

        mod_cache = os.path.join(CACHE_DIR, f"{slot_id}_mod.png")
        res.save(mod_cache)
        return mod_cache

    @staticmethod
    def _mouth_cavity(base):
        """1 where Mario's original texture is the dark red mouth-interior & tongue UV region (bottom-right), else 0."""
        from scipy.ndimage import gaussian_filter
        rgb = np.clip(np.asarray(base, dtype=np.float32)[..., :3], 0, 255).astype(np.uint8)
        H, W = rgb.shape[:2]
        yy, xx = np.mgrid[0:H, 0:W]
        hsv = np.asarray(Image.fromarray(rgb, "RGB").convert("HSV"), dtype=np.float32)
        hue = hsv[..., 0] * 360.0 / 255.0
        sat, val = hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
        red_dark = (val < 0.68) & ((hue < 18) | (hue > 330)) & (sat > 0.28)
        mouth_box = (xx >= int(0.41 * W)) & (yy >= int(0.59 * H))
        cav = (red_dark & mouth_box).astype(np.float32)
        return gaussian_filter(cav, 1.2)

    @staticmethod
    def _skin_tint_path():
        return os.path.join(CACHE_DIR, "skin_tint.json")

    @staticmethod
    def _match_uncovered_skin(base, out, photo_alpha, pos, cov, tint_path=None):
        """Give the skin the photo doesn't cover (ears, edges of the head) the photo's skin tone, and clean dark/dirty
        patches (2D eye-socket/nostril shadows on the 3D nose, under-eye circles, mouth-corner smudges, blemishes)."""
        from scipy.ndimage import gaussian_filter, maximum_filter, median_filter
        H, W = base.shape[:2]
        yy, xx = np.mgrid[0:H, 0:W]

        hsv = np.asarray(Image.fromarray(np.clip(base[..., :3], 0, 255).astype(np.uint8), "RGB").convert("HSV"), dtype=np.float32)
        hue = hsv[..., 0] * 360.0 / 255.0
        sat, val = hsv[..., 1] / 255.0, hsv[..., 2] / 255.0

        # Strictly protect only the actual white teeth and the bottom-right dark red mouth/tongue box
        teeth_uv = (xx <= int(0.125 * W)) & (yy >= int(0.73 * H)) & (yy <= int(0.86 * H)) & (sat < 0.28) & (val > 0.50)
        cav_mask = SwitchEngine._mouth_cavity(base) > 0.15
        non_skin_uv = teeth_uv | cav_mask

        x, y, z = pos[..., 0], pos[..., 1], pos[..., 2]
        cheek = cov & (~non_skin_uv) & (np.abs(x) > 10) & (np.abs(x) < 25) & (y > -4) & (y < 15)
        solid = cheek & (photo_alpha > 0.75)
        if solid.sum() < 50:
            solid = cov & (~non_skin_uv) & (photo_alpha > 0.75)
        if solid.sum() < 50 or cheek.sum() < 50:
            return out
        ref = base[cheek][:, :3].mean(axis=0)
        target = np.median(out[solid][:, :3], axis=0)
        gain = target / np.maximum(ref, 1.0)
        if tint_path:                       # the eyelid textures are tinted with the same gain when the eyes are deployed
            with open(tint_path, "w", encoding="utf-8") as f:
                json.dump({"gain": [float(v) for v in gain]}, f)

        # Which texels of Mario's texture are skin: orange-ish hue, reasonably saturated and bright
        skin = ((hue >= 4) & (hue <= 38) & (sat >= 0.22) & (val >= 0.35) & (~non_skin_uv)).astype(np.float32)
        skin = gaussian_filter(skin, 1.0)

        cover = gaussian_filter(np.clip(photo_alpha, 0, 1), 3.0) * (~non_skin_uv)
        w = (skin * (1.0 - cover))[..., None]
        base_lum = (0.2126 * base[..., 0] + 0.7152 * base[..., 1] + 0.0722 * base[..., 2])[..., None]
        ref_lum = float(0.2126 * ref[0] + 0.7152 * ref[1] + 0.0722 * ref[2])
        flat_base = base[..., :3] * np.clip((ref_lum / np.maximum(base_lum, 1.0)) ** 0.75, 0.85, 2.2)
        tinted = base.copy()
        tinted[..., :3] = np.clip(0.65 * (flat_base * gain) + 0.35 * target[None, None, :], 0, 255)
        res = out.copy()
        res[..., :3] = out[..., :3] * (1 - w) + tinted[..., :3] * w

        # Mario's 3D nose sticks far out (Z > 27, plus the top-right Nose UV island x >= 0.72*W, y <= 0.55*H).
        # Give Mario's 3D nose a clean, uniform skin tone matched to the photo so 3D lighting shades the nose naturally.
        nose_uv = (xx >= int(0.72 * W)) & (yy <= int(0.55 * H))
        nose_3d = cov & (z > 27.0) & (y > -1.0) & (y < 17.5) & (np.abs(x) < 10.5)
        nose_mask = ((nose_uv | nose_3d) & (~non_skin_uv)).astype(np.float32)
        nose_w = (gaussian_filter(nose_mask, 2.5) * 0.88)[..., None]
        smooth_nose = 0.65 * target[None, None, :] + 0.35 * np.stack([gaussian_filter(tinted[..., c], 3.0) for c in range(3)], axis=-1)
        res[..., :3] = res[..., :3] * (1.0 - nose_w) + smooth_nose * nose_w

        # Mario's texture has dark brown-grey shadow blocks beside the eye sockets, ears, and teeth box, plus dark red eye/nose shadows.
        brown_raw = (
            (((hue >= 10) & (hue <= 52) & (sat >= 0.10) & (sat <= 0.80) & (val >= 0.15) & (val < 0.64)) |
             ((val < 0.68) & ((hue < 18) | (hue > 330)) & (sat > 0.28)) |
             ((sat < 0.27) & (val < 0.78)))
            & (~non_skin_uv)
        ).astype(np.float32)
        brown = gaussian_filter(maximum_filter(brown_raw, size=5), 1.2) * (~non_skin_uv)
        wb = np.clip(brown * (1.0 - 0.85 * cover), 0, 1)[..., None]
        good = (np.clip(skin + cover, 0, 1) * (1.0 - (brown > 0.15)) * (~non_skin_uv)).astype(np.float32)
        num = gaussian_filter(res[..., :3] * good[..., None], (10, 10, 0))
        den = gaussian_filter(good, 10)[..., None]
        fill = np.where(den > 0.03, num / np.maximum(den, 1e-3), target * 0.98)
        res[..., :3] = res[..., :3] * (1 - wb) + fill * wb

        # Despeckle small dark blemishes/dots on the skin (e.g. moles/specks under the mouth that mirror onto both sides)
        eyebrow_band = cov & (y > 20.5) & (y < 29.5) & (np.abs(x) > 2.5) & (np.abs(x) < 18.5)
        cleanable_skin = (~non_skin_uv) & (~eyebrow_band)
        lum0 = 0.2126 * res[..., 0] + 0.7152 * res[..., 1] + 0.0722 * res[..., 2]
        med5_rgb = np.stack([median_filter(res[..., c], size=5) for c in range(3)], axis=-1)
        med5_lum = 0.2126 * med5_rgb[..., 0] + 0.7152 * med5_rgb[..., 1] + 0.0722 * med5_rgb[..., 2]
        speck = cleanable_skin & ((med5_lum - lum0) > 5.0)
        speck_w = gaussian_filter(maximum_filter(speck.astype(np.float32), size=3), 0.8)[..., None]
        res[..., :3] = res[..., :3] * (1.0 - speck_w) + med5_rgb * speck_w

        # Lift dark/muddy shadow patches across ALL skin (under-eye crescent, nose-crease blob, mouth-corner shadows).
        rgb8 = np.clip(res[..., :3], 0, 255).astype(np.uint8)
        h2 = np.asarray(Image.fromarray(rgb8, "RGB").convert("HSV"), dtype=np.float32)
        hue2, sat2, val2 = h2[..., 0] * 360.0 / 255.0, h2[..., 1] / 255.0, h2[..., 2] / 255.0
        lum = 0.2126 * res[..., 0] + 0.7152 * res[..., 1] + 0.0722 * res[..., 2]
        cav2 = (val2 < 0.50) & ((hue2 < 14) | (hue2 > 330)) & (sat2 > 0.45) & (yy >= int(0.44 * H))
        white2 = (sat2 < 0.14) & (val2 > 0.78)
        liftable = (cleanable_skin & (~cav2) & (~white2) & (sat2 > 0.03)).astype(np.float32)
        med_l = float(np.median(lum[solid]))
        lb_fine = gaussian_filter(lum * liftable, 2.5) / np.maximum(gaussian_filter(liftable, 2.5), 1e-3)
        goal = 0.98 * med_l
        dark_raw = np.clip((goal - lb_fine) / (0.13 * med_l), 0, 1) * liftable
        grey_raw = np.clip((0.20 - sat2) / 0.10, 0, 1) * liftable       # muddy/desaturated grey shadow patches
        dark_raw = np.maximum(dark_raw, grey_raw)
        dark_w = np.clip(gaussian_filter(dark_raw, 1.5) * 0.92, 0, 1)[..., None]
        ok = liftable * (dark_raw < 0.10) * (1.0 - (brown > 0.15))
        num = gaussian_filter(res[..., :3] * ok[..., None], (22, 22, 0))
        den = gaussian_filter(ok, 22)[..., None]
        around = np.where(den > 0.02, 0.55 * (num / np.maximum(den, 1e-3)) + 0.45 * target[None, None, :], target)
        detail = np.clip(lum / np.maximum(lb_fine, 1.0), 0.93, 1.07)[..., None]
        lifted = around * detail
        res[..., :3] = res[..., :3] * (1 - dark_w) + lifted * dark_w

        # Eliminate any vertical join/seam on the side of the cheek (where the projected photo meets the sideburn/ear skin)
        # by matching the outer cheek/ear region to the row-by-row color profile of the mid-cheek (x = 0.175*W .. 0.23*W).
        cheek_ref = np.median(res[int(0.31 * H):int(0.61 * H), int(0.175 * W):int(0.23 * W), :3].reshape(-1, 3), axis=0)
        row_ref = np.median(res[:, int(0.175 * W):int(0.23 * W), :3], axis=1)
        row_ref_smooth = np.stack([gaussian_filter(row_ref[:, c], 10.0) for c in range(3)], axis=-1)
        sx = xx / float(W)
        sy = yy / float(H)
        wx_far = np.clip((sx - 0.26) / 0.22, 0.0, 1.0)[..., None]
        outer_skin = row_ref_smooth[:, None, :] * (1.0 - 0.70 * wx_far) + cheek_ref[None, None, :] * (0.70 * wx_far)
        pre = res.copy()
        hard_outer = (sx >= 0.262) & (~non_skin_uv)
        pre[hard_outer, :3] = outer_skin[hard_outer]
        valid = (~non_skin_uv).astype(np.float32)
        num_c = np.stack([gaussian_filter(pre[..., c] * valid, (4.0, 8.0)) for c in range(3)], axis=-1)
        den_c = gaussian_filter(valid, (4.0, 8.0))[..., None]
        pre_smooth = np.where(den_c > 0.05, num_c / np.maximum(den_c, 1e-3), outer_skin)
        w_outer = np.clip((sx - 0.180) / 0.082, 0.0, 1.0)
        brow_tip = np.exp(-0.5 * ((sy - 0.115) / 0.032) ** 2) * np.clip((0.235 - sx) / 0.04, 0.0, 1.0)
        w_outer = np.clip(w_outer - 0.65 * brow_tip, 0.0, 1.0)
        w_outer = gaussian_filter(w_outer * valid, 2.5)
        w_outer[non_skin_uv] = 0.0
        w_pure = gaussian_filter(np.clip((sx - 0.245) / 0.055, 0.0, 1.0) * valid, 2.5)[..., None]
        target_blend = pre_smooth * (1.0 - w_pure) + outer_skin * w_pure
        res[..., :3] = res[..., :3] * (1.0 - w_outer[..., None]) + target_blend * w_outer[..., None]

        # Ensure white teeth & mouth cavity remain 100% crisp vanilla
        res[non_skin_uv, :3] = base[non_skin_uv, :3]
        return res

    def apply_composite_face(self, slot_id, photo_stream_or_path, scale=1.0, offset_x=0, offset_y=0, feather=8, opacity=1.0):
        orig_png = self.get_texture_png(slot_id, modded=False)
        if not orig_png or not os.path.isfile(orig_png):
            return None

        base_img = Image.open(orig_png).convert("RGBA")
        bw, bh = base_img.size

        if isinstance(photo_stream_or_path, str):
            overlay = Image.open(photo_stream_or_path).convert("RGBA")
        else:
            overlay = Image.open(BytesIO(photo_stream_or_path)).convert("RGBA")

        # Resize overlay according to scale
        target_w = int(bw * scale)
        target_h = int(bh * scale)
        overlay_resized = overlay.resize((max(1, target_w), max(1, target_h)), Image.Resampling.LANCZOS)

        # Alpha mask and feathering
        ov_r, ov_g, ov_b, ov_a = overlay_resized.split()
        if feather > 0:
            ov_a = ov_a.filter(ImageFilter.GaussianBlur(radius=feather))

        if opacity < 1.0:
            a_arr = np.array(ov_a, dtype=np.float32) * opacity
            ov_a = Image.fromarray(np.clip(a_arr, 0, 255).astype(np.uint8))

        # Positioning: the portrait is centred on the slot's base centre, shifted by the offsets (in texture pixels)
        cx, cy = self.composite_base_center(slot_id)
        pos_x = int(int(bw * cx) - target_w / 2 + offset_x)
        pos_y = int(int(bh * cy) - target_h / 2 + offset_y)

        # Special handling for iris/eye
        if slot_id == "mario_eye":
            # Clip to original iris circle boundary
            orig_a = base_img.split()[3]
            comp = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            comp.paste(overlay_resized, (pos_x, pos_y), ov_a)
            # Combine alphas
            comp_arr = np.array(comp)
            orig_a_arr = np.array(orig_a)
            comp_arr[:, :, 3] = np.minimum(comp_arr[:, :, 3], orig_a_arr)
            res_img = Image.fromarray(comp_arr)
        else:
            res_img = base_img.copy()
            res_img.paste(overlay_resized, (pos_x, pos_y), ov_a)

        mod_cache = os.path.join(CACHE_DIR, f"{slot_id}_mod.png")
        res_img.save(mod_cache)
        return mod_cache

    def save_settings(self):
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=2)

    def set_setting(self, key, value):
        if key not in ("hide_face_parts", "reshape_strength"):
            raise KeyError(key)
        self.settings[key] = float(min(1.0, max(0.0, value))) if key == "reshape_strength" else bool(value)
        self.save_settings()

    def reshape_signature(self):
        """Identifies the reshape that would be deployed right now ("" = none)."""
        fr = self.face_reshape
        strength = float(self.settings.get("reshape_strength", 0))
        if fr is None or not fr.has_depth() or strength <= 0:
            return ""
        return "%s@%.2f" % (fr.signature(), strength)

    def _reshape_face_bfres(self, bfres_path, szs):
        """Move the face mesh's vertices towards the photographed face's depth profile (see core/face_reshape.py)."""
        fr = self.face_reshape
        strength = float(self.settings.get("reshape_strength", 0))
        if fr is None or not fr.has_depth() or strength <= 0:
            return 0
        text, moved = fr.patch_text(szs, strength)
        if moved == 0:
            return 0
        patch = bfres_path + ".patch.txt"
        tmp = bfres_path + ".reshape_tmp"
        with open(patch, "w", encoding="ascii") as f:
            f.write(text)
        r = subprocess.run([PATCH_VERTICES_EXE, bfres_path, tmp, patch], cwd=TOOLBOX_DIR, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
        os.remove(patch)
        if r.returncode != 0 or not os.path.isfile(tmp):
            raise RuntimeError("PatchVertices failed: " + (r.stdout + r.stderr).strip()[-300:])
        os.replace(tmp, bfres_path)
        return moved

    def _hide_face_parts(self, bfres_path):
        """Make the moustache and eyebrow meshes of a face BFRES invisible (zeroed triangle data, same file size)."""
        tmp = bfres_path + ".hide_tmp"
        r = subprocess.run([HIDE_SHAPES_EXE, bfres_path, tmp, "mustache", "brow"], cwd=TOOLBOX_DIR,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not os.path.isfile(tmp):
            raise RuntimeError("HideShapes failed: " + (r.stdout + r.stderr).strip()[-300:])
        os.replace(tmp, bfres_path)

    def _slot_dds(self, slot_id, mod_png=None):
        """Edited texture of a slot as a full-mip DDS (Nintendo GPU requires all mips)."""
        info = TEXTURE_SLOTS[slot_id]
        if mod_png is None:
            mod_png = os.path.join(CACHE_DIR, f"{slot_id}_mod.png")
            if not os.path.isfile(mod_png):
                mod_png = self.get_texture_png(slot_id, modded=False)
        dds_temp = os.path.join(CACHE_DIR, f"{slot_id}_temp.dds")
        subprocess.run([TEXCONV, "-f", info["format"], "-y", "-o", CACHE_DIR, mod_png],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        gen_dds = os.path.join(CACHE_DIR, os.path.splitext(os.path.basename(mod_png))[0] + ".dds")
        if not os.path.isfile(gen_dds):
            raise RuntimeError(f"texconv produced no DDS for {slot_id}")
        if os.path.normcase(gen_dds) != os.path.normcase(dds_temp):
            if os.path.isfile(dds_temp):
                os.remove(dds_temp)
            shutil.move(gen_dds, dds_temp)
        return dds_temp

    def _slot_is_edited(self, slot_id):
        """True if the slot's preview texture differs from the vanilla one."""
        mod = os.path.join(CACHE_DIR, f"{slot_id}_mod.png")
        if not os.path.isfile(mod):
            return False
        orig = self.get_texture_png(slot_id, modded=False)
        if not orig or not os.path.isfile(orig):
            return True
        a, b = Image.open(mod).convert("RGBA"), Image.open(orig).convert("RGBA")
        return a.size != b.size or ImageChops.difference(a, b).getbbox(alpha_only=False) is not None

    def _deployed_change_bytes(self, slot_id):
        """How many bytes of the deployed archive differ from vanilla (0 = nothing deployed / identical)."""
        szs = TEXTURE_SLOTS[slot_id]["szs"]
        dep = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "ObjectData", szs)
        van = os.path.join(ROMFS_ROOT, "ObjectData", szs)
        if not os.path.isfile(dep):
            return 0
        with open(dep, "rb") as f1, open(van, "rb") as f2:
            a = bytes(oead.yaz0.decompress(f1.read()))
            b = bytes(oead.yaz0.decompress(f2.read()))
        if len(a) != len(b):
            return max(len(a), len(b))
        return int(np.count_nonzero(np.frombuffer(a, np.uint8) != np.frombuffer(b, np.uint8)))

    def _eyelid_tint_active(self):
        return os.path.isfile(self._skin_tint_path()) and self._slot_is_edited("mario_face")

    def _eyelid_extras(self, high):
        """[(texture name, dds path)] for the eyelid skin textures, tinted to the photo's skin tone; [] when no photo."""
        if not self._eyelid_tint_active() or self.model_view is None:
            return []
        with open(self._skin_tint_path(), "r", encoding="utf-8") as f:
            gain = np.array(json.load(f)["gain"], dtype=np.float32)
        if high:
            self.model_view._export("MarioHighEye.szs")
            tex, fmt = "MarioEyeHighMesh_alb", os.path.join(self.model_view.root, "MarioHighEye", "MarioEyeHighMesh_alb.png")
            tag = "eyelid_high"
        else:
            tex, fmt = "MarioEye_alb", self.model_view.vanilla_texture_png("MarioEye_alb")
            tag = "eyelid"
        if not fmt or not os.path.isfile(fmt):
            raise RuntimeError("vanilla eyelid texture not found: " + tex)
        from scipy.ndimage import gaussian_filter
        img = np.asarray(Image.open(fmt).convert("RGBA"), dtype=np.float32)
        # only the skin: the eyeball white, the grey around it and the dark lash area must keep their own colours
        hsv = np.asarray(Image.fromarray(np.clip(img[..., :3], 0, 255).astype(np.uint8), "RGB").convert("HSV"), dtype=np.float32)
        hue, sat, val = hsv[..., 0] * 360.0 / 255.0, hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
        skin = ((hue >= 6) & (hue <= 40) & (sat >= 0.25) & (val >= 0.45)).astype(np.float32)[..., None]   # crisp: no halo
        img[..., :3] = img[..., :3] * (1 - skin) + np.clip(img[..., :3] * gain, 0, 255) * skin
        png = os.path.join(CACHE_DIR, tag + "_tint.png")
        Image.fromarray(img.astype(np.uint8), "RGBA").save(png)
        subprocess.run([TEXCONV, "-f", "BC1_UNORM", "-y", "-o", CACHE_DIR, png], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dds = os.path.join(CACHE_DIR, tag + "_tint.dds")
        if not os.path.isfile(dds):
            raise RuntimeError("texconv produced no DDS for " + tex)
        return [(tex, dds)]

    def reset_slot(self, slot_id):
        """Put a slot's preview back to the vanilla texture. The edit is kept as <slot>_mod_backup.png."""
        if slot_id not in TEXTURE_SLOTS:
            raise ValueError(f"Unknown slot: {slot_id}")
        mod = os.path.join(CACHE_DIR, f"{slot_id}_mod.png")
        orig = self.get_texture_png(slot_id, modded=False)
        if not orig or not os.path.isfile(orig):
            raise RuntimeError("vanilla texture not available")
        backed_up = None
        if self._slot_is_edited(slot_id):
            backed_up = os.path.join(CACHE_DIR, f"{slot_id}_mod_backup.png")
            shutil.copyfile(mod, backed_up)
        shutil.copyfile(orig, mod)
        if slot_id == "mario_face":
            try:
                os.remove(self._skin_tint_path())
            except OSError:
                pass
        return backed_up

    def _mario_scale_active(self):
        bs = float(self.settings.get("mario_body_scale", 1.0))
        hm = float(self.settings.get("mario_head_mult", 1.0))
        return abs(bs - 1.0) > 1e-3 or abs(hm - 1.0) > 1e-3

    def _patch_mario_bfres_scale(self, bfres_bytes, body_scale):
        import struct
        bs = float(body_scale)
        if abs(bs - 1.0) <= 1e-3:
            return bfres_bytes
        buf = bytearray(bfres_bytes)
        fskl = buf.find(b"FSKL")
        if fskl >= 0:
            ba = struct.unpack_from("<Q", buf, fskl + 0x18)[0]
            b0_name_ptr = struct.unpack_from("<Q", buf, ba)[0]
            # Rename Bone[0] from "nw4f_root" to "nw4f_roo_" so PlayerAnimation.bfres
            # does not overwrite Bone[0]'s scale with identity (1, 1, 1) on every frame.
            if buf[b0_name_ptr + 2 : b0_name_ptr + 11] == b"nw4f_root":
                buf[b0_name_ptr + 10] = 0x5F  # '_'
            # Clear Identity | ScaleVolumeOne flags (0x09000000) -> 0x06001001
            struct.pack_into("<I", buf, ba + 0x34, 0x06001001)
            struct.pack_into("<fff", buf, ba + 0x38, bs, bs, bs)
        fshp = buf.find(b"FSHP")
        if fshp >= 0:
            bound_mult = max(1.0, bs)
            rad_ptr = struct.unpack_from("<Q", buf, fshp + 0x48)[0]
            sub_ptr = struct.unpack_from("<Q", buf, fshp + 0x40)[0]
            if 0 < rad_ptr < len(buf) - 4:
                orig_r = struct.unpack_from("<f", buf, rad_ptr)[0]
                struct.pack_into("<f", buf, rad_ptr, orig_r * bound_mult)
            if 0 < sub_ptr < len(buf) - 24:
                vals = struct.unpack_from("<6f", buf, sub_ptr)
                struct.pack_into("<6f", buf, sub_ptr, *[v * bound_mult for v in vals])
        return bytes(buf)

    def _restore_unneeded_archives(self, edited_slots, face_needed, eye_needed=False):
        """Remove deployed archives nothing needs any more, so the game falls back to its own vanilla files."""
        deployed_dir = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "ObjectData")
        needed = set()
        for sid in edited_slots:
            needed.update(SLOT_ARCHIVES.get(sid, []))
        if face_needed:
            needed.update(SLOT_ARCHIVES["mario_face"])
        if eye_needed:
            needed.update(SLOT_ARCHIVES["mario_eye"])
        if self._mario_scale_active():
            needed.update(SLOT_ARCHIVES["mario_body"])
        restored = []
        for sid, info in TEXTURE_SLOTS.items():
            archives = [a for a in SLOT_ARCHIVES.get(sid, []) if a not in needed]
            removed, locked = [], []
            for a in archives:
                fp = os.path.join(deployed_dir, a)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                        removed.append(a)
                    except OSError:
                        locked.append(a)
            if locked and sid not in edited_slots:
                restored.append({"slot": sid, "title": info["title"], "ok": False, "changed_bytes": 0,
                                 "error": "Eden has these files open - close the game and deploy again: " + ", ".join(locked)})
            elif removed and sid not in edited_slots:
                restored.append({"slot": sid, "title": info["title"], "ok": True, "restored_vanilla": True,
                                 "changed_bytes": 0, "error": None, "removed": removed})
        return restored

    def commit_all_edited(self):
        """Deploy every edited texture (one per slot), verifying each deployed archive really differs from vanilla."""
        results = []
        edited_now = [sid for sid in TEXTURE_SLOTS if self._slot_is_edited(sid)]
        face_needed = (bool(self.settings.get("hide_face_parts")) or "mario_face" in edited_now or "mario_hair" in edited_now
                       or bool(self.reshape_signature()))
        face_option_changed = (bool(self.settings.get("hide_face_parts")) != bool(self.settings.get("deployed_hide_face_parts"))
                               or self.reshape_signature() != self.settings.get("deployed_reshape_sig", ""))
        for slot_id, info in TEXTURE_SLOTS.items():
            if not (self._slot_is_edited(slot_id) or (slot_id == "mario_face" and face_option_changed)
                    or (slot_id == "mario_eye" and self._eyelid_tint_active())
                    or (slot_id == "mario_body" and self._mario_scale_active())):
                continue
            try:
                self.commit_texture_to_model(slot_id)
                changed = self._deployed_change_bytes(slot_id)
                results.append({"slot": slot_id, "title": info["title"], "ok": changed > 0, "changed_bytes": changed,
                                "error": None if changed > 0 else "deployed file is identical to vanilla"})
            except PermissionError:
                results.append({"slot": slot_id, "title": info["title"], "ok": False, "changed_bytes": 0,
                                "error": "Eden has the game files open - close the game and deploy again"})
            except Exception as e:
                results.append({"slot": slot_id, "title": info["title"], "ok": False, "changed_bytes": 0, "error": str(e)})
        # textures reset to vanilla: drop their deployed archives (unless a sibling still needs the file)
        results.extend(self._restore_unneeded_archives(edited_now, face_needed, self._eyelid_tint_active()))
        if not face_needed:
            self.settings["deployed_hide_face_parts"] = False
            self.settings["deployed_reshape_sig"] = ""
            self.save_settings()
        return results

    def commit_texture_to_model(self, slot_id):
        """Converts cache mod PNG -> DDS -> Injects into BFRES -> Repacks into SZS in Eden."""
        if slot_id not in TEXTURE_SLOTS:
            raise ValueError(f"Unknown slot: {slot_id}")
            
        info = TEXTURE_SLOTS[slot_id]
        mod_png = os.path.join(CACHE_DIR, f"{slot_id}_mod.png")
        if not os.path.isfile(mod_png):
            mod_png = self.get_texture_png(slot_id, modded=False)

        dds_temp = self._slot_dds(slot_id, mod_png)

        # 1. Primary Model Injection & Repack.
        # Some textures share one BFRES (the face skin and the moustache/brows both live in MarioFace.bfres). Every
        # commit rebuilds the file from vanilla, so inject every edited texture of this file, not only this one.
        out_bfres = os.path.join(TOOLBOX_DIR, f"{os.path.splitext(info['bfres'])[0]}_mod.bfres")
        src_bfres = os.path.join(TOOLBOX_DIR, info["bfres"])
        group = [sid for sid, i in TEXTURE_SLOTS.items()
                 if i["szs"] == info["szs"] and i["bfres"] == info["bfres"] and (sid == slot_id or self._slot_is_edited(sid))]
        for sid in group:
            sinfo = TEXTURE_SLOTS[sid]
            sdds = dds_temp if sid == slot_id else self._slot_dds(sid)
            subprocess.run([INJECT_EXE, src_bfres, sinfo["texture"], sdds, out_bfres], cwd=TOOLBOX_DIR, check=True)
            src_bfres = out_bfres          # the next texture is injected on top of this result
        if info["bfres"] == "MarioEye.bfres":
            for tex, dds in self._eyelid_extras(False):
                subprocess.run([INJECT_EXE, out_bfres, tex, dds, out_bfres], cwd=TOOLBOX_DIR, check=True)
        hide_parts = bool(self.settings.get("hide_face_parts")) and info["bfres"] == "MarioFace.bfres"
        if hide_parts:
            self._hide_face_parts(out_bfres)
        if info["bfres"] == "MarioFace.bfres":
            self._reshape_face_bfres(out_bfres, "MarioFace.szs")
        self.repack_archive(info["szs"], info["bfres"], out_bfres)

        # 2. Synchronize High-Poly and Costume variants across Odyssey
        if slot_id == "mario_face":
            # High-poly face (512x512) for cinematic cutscenes
            face_img = Image.open(mod_png)
            high_face_png = os.path.join(CACHE_DIR, "mario_face_high_mod.png")
            face_img.resize((512, 512), Image.Resampling.LANCZOS).save(high_face_png)
            subprocess.run([TEXCONV, "-f", "BC1_UNORM", "-y", "-o", CACHE_DIR, high_face_png], check=True, stdout=subprocess.DEVNULL)
            high_face_dds = os.path.join(CACHE_DIR, "mario_face_high_mod.DDS")
            
            high_face_bfres = os.path.join(TOOLBOX_DIR, "MarioHighFace.bfres")
            high_face_mod_bfres = os.path.join(TOOLBOX_DIR, "MarioHighFace_mod.bfres")
            if os.path.isfile(high_face_bfres):
                subprocess.run([INJECT_EXE, high_face_bfres, "MarioFaceHighMesh_alb", high_face_dds, high_face_mod_bfres], check=True, cwd=TOOLBOX_DIR)
                if self.settings.get("hide_face_parts"):
                    self._hide_face_parts(high_face_mod_bfres)
                self._reshape_face_bfres(high_face_mod_bfres, "MarioHighFace.szs")
                self.repack_archive("MarioHighFace.szs", "MarioHighFace.bfres", high_face_mod_bfres)

            self.settings["deployed_hide_face_parts"] = bool(self.settings.get("hide_face_parts"))
            self.settings["deployed_reshape_sig"] = self.reshape_signature()
            self.save_settings()

        elif slot_id == "mario_eye":
            # High-poly eye for close-up camera angles
            high_eye_bfres = os.path.join(TOOLBOX_DIR, "MarioHighEye.bfres")
            high_eye_mod_bfres = os.path.join(TOOLBOX_DIR, "MarioHighEye_mod.bfres")
            if os.path.isfile(high_eye_bfres):
                subprocess.run([INJECT_EXE, high_eye_bfres, "MarioEyePupil_alb", dds_temp, high_eye_mod_bfres], check=True, cwd=TOOLBOX_DIR)
                for tex, dds in self._eyelid_extras(True):
                    subprocess.run([INJECT_EXE, high_eye_mod_bfres, tex, dds, high_eye_mod_bfres], check=True, cwd=TOOLBOX_DIR)
                self.repack_archive("MarioHighEye.szs", "MarioHighEye.bfres", high_eye_mod_bfres)

        elif slot_id == "mario_body":
            # Luigi Costume Overalls
            luigi_bfres = os.path.join(TOOLBOX_DIR, "MarioColorLuigi.bfres")
            luigi_mod_bfres = os.path.join(TOOLBOX_DIR, "MarioColorLuigi_mod.bfres")
            if os.path.isfile(luigi_bfres):
                subprocess.run([INJECT_EXE, luigi_bfres, "MarioColorLuigiBody_alb", dds_temp, luigi_mod_bfres], check=True, cwd=TOOLBOX_DIR)
                self.repack_archive("MarioColorLuigi.szs", "MarioColorLuigi.bfres", luigi_mod_bfres)

        elif slot_id == "mario_cap":
            # Captain's Peaked Cap & Luigi Cap
            capt_bfres = os.path.join(TOOLBOX_DIR, "MarioCaptainHeadTexture.bfres")
            capt_mod_bfres = os.path.join(TOOLBOX_DIR, "MarioCaptainHeadTexture_mod.bfres")
            if os.path.isfile(capt_bfres):
                subprocess.run([INJECT_EXE, capt_bfres, "MarioCaptainCap_alb", dds_temp, capt_mod_bfres], check=True, cwd=TOOLBOX_DIR)
                self.repack_archive("MarioCaptainHeadTexture.szs", "MarioCaptainHeadTexture.bfres", capt_mod_bfres)

            luigi_cap_bfres = os.path.join(TOOLBOX_DIR, "MarioColorLuigiHeadTexture.bfres")
            luigi_cap_mod_bfres = os.path.join(TOOLBOX_DIR, "MarioColorLuigiHeadTexture_mod.bfres")
            if os.path.isfile(luigi_cap_bfres):
                subprocess.run([INJECT_EXE, luigi_cap_bfres, "MarioColorLuigiCap_alb", dds_temp, luigi_cap_mod_bfres], check=True, cwd=TOOLBOX_DIR)
                self.repack_archive("MarioColorLuigiHeadTexture.szs", "MarioColorLuigiHeadTexture.bfres", luigi_cap_mod_bfres)

        return True

    def repack_archive(self, szs_name, internal_name, mod_bfres_path):
        import struct
        if oead is None:
            raise RuntimeError("oead module not loaded")

        romfs_szs = os.path.join(ROMFS_ROOT, "ObjectData", szs_name)
        target_dir = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "ObjectData")
        os.makedirs(target_dir, exist_ok=True)
        target_szs = os.path.join(target_dir, szs_name)

        with open(romfs_szs, "rb") as f:
            raw_szs = f.read()
            orig_align = raw_szs[8:12] # e.g. b'\x00\x00\x10\x00' (4096-byte GPU alignment)
            decomp = bytearray(oead.yaz0.decompress(raw_szs))

        with open(os.path.join(TOOLBOX_DIR, internal_name), "rb") as orig_f:
            orig_bfres = orig_f.read()

        with open(mod_bfres_path, "rb") as mf:
            mod_bfres = mf.read()

        is_mario_body_szs = szs_name in ("Mario.szs", "MarioColorLuigi.szs")
        body_scale = float(self.settings.get("mario_body_scale", 1.0)) if is_mario_body_szs else 1.0
        head_mult = float(self.settings.get("mario_head_mult", 1.0)) if is_mario_body_szs else 1.0

        if is_mario_body_szs and abs(body_scale - 1.0) > 1e-3:
            mod_bfres = self._patch_mario_bfres_scale(mod_bfres, body_scale)

        pos = decomp.find(orig_bfres)
        if pos >= 0 and len(orig_bfres) == len(mod_bfres):
            decomp[pos : pos + len(mod_bfres)] = mod_bfres
            # Patch InitPartsFixInfo*.byml in-place inside decomp so Mario.bfres stays at 0x2000 (4096-byte GPU alignment)
            if is_mario_body_szs and abs(head_mult - 1.0) > 1e-3:
                data_off = struct.unpack_from("<I", decomp, 0x0C)[0]
                node_cnt = struct.unpack_from("<H", decomp, 0x1A)[0]
                sarc = oead.Sarc(bytes(decomp))
                files = list(sarc.get_files())
                target_bymls = {"InitPartsFixInfoFace.byml", "InitPartsFixInfoEye.byml", "InitPartsFixInfoHead.byml"}
                for i in range(node_cnt):
                    fname = files[i].name
                    if fname not in target_bymls:
                        continue
                    nh = 0x20 + i * 16
                    h, fn_off, st, ed = struct.unpack_from("<IIII", decomp, nh)
                    nxt_st = struct.unpack_from("<I", decomp, 0x20 + (i + 1) * 16 + 8)[0] if i + 1 < node_cnt else len(decomp) - data_off
                    capacity = nxt_st - st
                    bobj = oead.byml.from_binary(bytes(files[i].data))
                    bobj["UseLocalScale"] = True
                    bobj["LocalScale"] = oead.byml.Hash({
                        "X": oead.F32(head_mult),
                        "Y": oead.F32(head_mult),
                        "Z": oead.F32(head_mult),
                    })
                    new_bytes = bytes(oead.byml.to_binary(bobj, big_endian=False))
                    if len(new_bytes) <= capacity:
                        abs_st = data_off + st
                        decomp[abs_st : abs_st + capacity] = b"\x00" * capacity
                        decomp[abs_st : abs_st + len(new_bytes)] = new_bytes
                        struct.pack_into("<I", decomp, nh + 12, st + len(new_bytes))
            recompressed = bytearray(oead.yaz0.compress(decomp, data_alignment=0x1000, level=9))
        else:
            sarc = oead.Sarc(decomp)
            writer = oead.SarcWriter.from_sarc(sarc)
            writer.files[internal_name] = mod_bfres
            align, sarc_bytes = writer.write()
            recompressed = bytearray(oead.yaz0.compress(sarc_bytes, data_alignment=0x1000, level=9))

        recompressed[8:12] = orig_align

        with open(target_szs, "wb") as out_f:
            out_f.write(recompressed)

        return target_szs

    def list_bgm_tracks(self):
        stream_dir = os.path.join(ROMFS_ROOT, "SoundData", "stream")
        if not os.path.isdir(stream_dir):
            return []

        tracks = []
        for f in os.listdir(stream_dir):
            if f.endswith(".bfstm"):
                full_p = os.path.join(stream_dir, f)
                size_mb = round(os.path.getsize(full_p) / (1024 * 1024), 2)
                # Parse readable title
                title = f.replace(".dspadpcm.bfstm", "").replace(".pcm16.bfstm", "").replace(".nk.48", "").replace("RsBgm", "")
                tracks.append({
                    "filename": f,
                    "title": title,
                    "size_mb": size_mb,
                    "path": full_p
                })
        return tracks

    def get_track_wav(self, track_filename):
        # 1. Check if a modded track exists in Eden LayeredFS
        modded_path = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", "stream", track_filename)
        if os.path.isfile(modded_path):
            mod_wav_cache = os.path.join(CACHE_DIR, f"mod_{track_filename}.wav")
            if not os.path.isfile(mod_wav_cache) or os.path.getmtime(modded_path) > os.path.getmtime(mod_wav_cache):
                try:
                    subprocess.run([CONVERT_AUDIO_EXE, modded_path, mod_wav_cache], cwd=TOOLBOX_DIR, check=True)
                except Exception:
                    pass
            if os.path.isfile(mod_wav_cache):
                return mod_wav_cache

        # 2. Vanilla RomFS fallback
        stream_dir = os.path.join(ROMFS_ROOT, "SoundData", "stream")
        bfstm_path = os.path.join(stream_dir, track_filename)
        if not os.path.isfile(bfstm_path):
            return None

        wav_cache = os.path.join(CACHE_DIR, f"{track_filename}.wav")
        if not os.path.isfile(wav_cache):
            subprocess.run([CONVERT_AUDIO_EXE, bfstm_path, wav_cache], cwd=TOOLBOX_DIR, check=True)

        return wav_cache

    def _finalize_bfstm(self, path, target_filename, sfx=False):
        """VGAudio only writes Wii U (big-endian) BFSTMs; rewrite as a Switch BFSTM using the vanilla target as template."""
        sub = "streamSe" if sfx else "stream"
        tpl_dir = os.path.join(ROMFS_ROOT, "SoundData", sub)
        bfstm_nx.convert_file_in_place(path, tpl_dir, target_filename)
        return path

    PREFETCH_KINDS = {
        "bgm": ("stream", "BgmResourceStdPrefetch.aras"),
        "se": ("streamSe", "SeResourceStd2nd.aras"),
    }

    def rebuild_prefetch(self, kind="bgm"):
        """Keeps the prefetch archive in step with the deployed streams (see core/bfstm_nx.py).

        kind "bgm": music (BgmResourceStdPrefetch.aras); kind "se": sound effects (SeResourceStd2nd.aras)."""
        sub, aras = self.PREFETCH_KINDS[kind]
        van_dir = os.path.join(ROMFS_ROOT, "SoundData", sub)
        dep_dir = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", sub)
        out_aras = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", aras)
        if not os.path.isdir(dep_dir):
            return {"rebuilt": [], "removed": [], "skipped": []}
        removed = []
        for fn in os.listdir(dep_dir):
            vp = os.path.join(van_dir, fn)
            if not fn.endswith(".bfstm") or not os.path.isfile(vp):
                continue
            is_non_loop_bgm = (kind == "bgm" and not self.track_specs.get(fn, {}).get("loop", True))
            if bfstm_nx.read_codec(vp) != 2 or is_non_loop_bgm or not self._same_format_as_vanilla(os.path.join(dep_dir, fn), vp):
                os.remove(os.path.join(dep_dir, fn))
                removed.append(fn)
        rep = bfstm_nx.rebuild_prefetch_archive(os.path.join(ROMFS_ROOT, "SoundData", aras), van_dir, dep_dir, out_aras)
        # Replacements whose vanilla prefetch can't be rebuilt would play the original snippet and then stall: drop them.
        for fn, why in rep["skipped"]:
            fp = os.path.join(dep_dir, fn)
            if os.path.isfile(fp) and why != "still big-endian":
                os.remove(fp)
                removed.append(fn)
        if kind == "bgm":
            for fn in rep.get("no_prefetch", []):
                fp = os.path.join(dep_dir, fn)
                if os.path.isfile(fp):
                    os.remove(fp)
                    removed.append(fn)
        rep["removed"] = removed
        return rep

    @staticmethod
    def _same_format_as_vanilla(dep_path, van_path):
        """The game sizes its audio buffers from the original stream: sample rate and channel count must match it."""
        try:
            with open(dep_path, "rb") as f:
                d = bfstm_nx._parse(f.read(0x4000))
            with open(van_path, "rb") as f:
                v = bfstm_nx._parse(f.read(0x4000))
            return d["rate"] == v["rate"] and d["channels"] == v["channels"] and d["codec"] == v["codec"]
        except Exception:
            return False

    def _require_kept(self, rep, filename):
        """A single-track replace must not silently disappear: say why it was dropped."""
        if filename in rep.get("removed", []):
            why = dict(rep.get("skipped", [])).get(filename, "its stream type can't be replaced")
            raise RuntimeError(f"{filename} can't be replaced: {why}")

    def repair_deployed_audio(self):
        """Converts any big-endian BFSTMs already deployed to Eden's LayeredFS folder into Switch format."""
        fixed, failed = [], []
        for sub, sfx in (("stream", False), ("streamSe", True)):
            d = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", sub)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                if fn.endswith(".bfstm") and bfstm_nx.is_big_endian_bfstm(p):
                    try:
                        self._finalize_bfstm(p, fn, sfx=sfx)
                        fixed.append(fn)
                    except Exception as ex:
                        failed.append((fn, str(ex)))
        prefetch = self.rebuild_prefetch("bgm")
        prefetch_se = self.rebuild_prefetch("se")
        return {"fixed": fixed, "failed": failed, "prefetch": prefetch, "prefetch_se": prefetch_se}

    def _transcode_to_clean_wav(self, input_path_or_bytes, output_wav, target_channels=2, target_sample_rate=48000, max_duration=180):
        """Uses FFmpeg to transcode ANY audio format to 16-bit PCM with exact channel count and sample rate."""
        temp_raw = os.path.join(CACHE_DIR, "temp_raw_upload.bin")
        if isinstance(input_path_or_bytes, bytes):
            with open(temp_raw, "wb") as f:
                f.write(input_path_or_bytes)
            in_file = temp_raw
        else:
            in_file = input_path_or_bytes

        cmd = ["ffmpeg", "-y", "-nostdin", "-i", in_file]
        if max_duration:
            cmd.extend(["-t", str(int(max_duration))])
        cmd.extend(["-ar", str(target_sample_rate)])
        if target_channels == 1:
            cmd.extend(["-ac", "1"])
        elif target_channels == 2:
            cmd.extend(["-ac", "2"])
        elif target_channels == 4:
            cmd.extend(["-af", "pan=4c|c0=c0|c1=c1|c2=c0|c3=c1"])
        elif target_channels == 6:
            cmd.extend(["-af", "pan=6c|c0=c0|c1=c1|c2=c0|c3=c1|c4=c0|c5=c1"])
        elif target_channels == 8:
            cmd.extend(["-af", "pan=8c|c0=c0|c1=c1|c2=c0|c3=c1|c4=c0|c5=c1|c6=c0|c7=c1"])
        elif target_channels == 10:
            cmd.extend(["-af", "pan=10c|c0=c0|c1=c1|c2=c0|c3=c1|c4=c0|c5=c1|c6=c0|c7=c1|c8=c0|c9=c1"])
        else:
            cmd.extend(["-ac", "2"])

        cmd.extend(["-c:a", "pcm_s16le", output_wav])
        res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            raise RuntimeError(f"Audio transcoding failed: {res.stderr}")
        return output_wav

    def _convert_track_for_target(self, task):
        """Converts a user audio file to match a specific target Odyssey track's channel & sample rate specs."""
        u_track, target_track = task
        fn = target_track["filename"]
        spec = self.track_specs.get(fn, {"channels": 2, "sample_rate": 48000})
        target_ch = spec.get("channels", 2)
        target_sr = spec.get("sample_rate", 48000)

        track_path = u_track["path"]
        mtime = os.path.getmtime(track_path) if os.path.isfile(track_path) else 0
        sz = os.path.getsize(track_path) if os.path.isfile(track_path) else 0
        key_src = f"nx1_{track_path}_{mtime}_{sz}_{target_ch}_{target_sr}"
        cache_hash = hashlib.md5(key_src.encode("utf-8", errors="replace")).hexdigest()[:16]
        cached_bfstm = os.path.join(CACHE_DIR, f"track_{cache_hash}_{target_ch}ch.bfstm")

        if not (os.path.isfile(cached_bfstm) and os.path.getsize(cached_bfstm) > 1024):
            temp_wav = os.path.join(CACHE_DIR, f"temp_{cache_hash}_{target_ch}ch.wav")
            try:
                self._transcode_to_clean_wav(track_path, temp_wav, target_channels=target_ch, target_sample_rate=target_sr)
                subprocess.run([CONVERT_AUDIO_EXE, temp_wav, cached_bfstm], cwd=TOOLBOX_DIR, stdin=subprocess.DEVNULL, check=True)
                self._finalize_bfstm(cached_bfstm, fn)
            except Exception as ex:
                print(f"Failed converting {u_track.get('name')} for {fn}: {ex}")
                return None
            finally:
                if os.path.isfile(temp_wav):
                    try:
                        os.remove(temp_wav)
                    except Exception:
                        pass

        if os.path.isfile(cached_bfstm) and os.path.getsize(cached_bfstm) > 0:
            return {
                "bfstm_path": cached_bfstm,
                "name": u_track["name"],
                "target_filename": fn,
                "target_title": target_track["title"]
            }
        return None

    SHARED_STREAM_PEERS = {
        "StmRsBgmDesertMain.bfstm": "StmRsBgmDesertMainParade.bfstm",
        "StmRsBgmDesertMainParade.bfstm": "StmRsBgmDesertMain.bfstm",
        "StmRsBgmMoon.bfstm": "StmRsBgmMoonParade.bfstm",
        "StmRsBgmMoonParade.bfstm": "StmRsBgmMoon.bfstm",
        "StmDesertWorld_001.bfstm": "StmDesertWorld_010.bfstm",
        "StmDesertWorld_010.bfstm": "StmDesertWorld_001.bfstm",
    }

    def replace_bgm_track(self, track_filename, audio_data_or_path):
        vp = os.path.join(ROMFS_ROOT, "SoundData", "stream", track_filename)
        if os.path.isfile(vp) and bfstm_nx.read_codec(vp) != 2:
            raise RuntimeError(f"{track_filename} uses uncompressed PCM16 and cannot be replaced safely")
        if not self.track_specs.get(track_filename, {}).get("loop", True):
            raise RuntimeError(f"{track_filename} is a non-looping one-shot jingle and cannot be replaced with a looping BGM stream")
        spec = self.track_specs.get(track_filename, {"channels": 2, "sample_rate": 48000})
        target_ch = spec.get("channels", 2)
        target_sr = spec.get("sample_rate", 48000)

        clean_wav = os.path.join(CACHE_DIR, f"temp_{track_filename}.wav")
        self._transcode_to_clean_wav(audio_data_or_path, clean_wav, target_channels=target_ch, target_sample_rate=target_sr)

        temp_bfstm = os.path.join(CACHE_DIR, f"{track_filename}")
        subprocess.run([CONVERT_AUDIO_EXE, clean_wav, temp_bfstm], cwd=TOOLBOX_DIR, stdin=subprocess.DEVNULL, check=True)
        self._finalize_bfstm(temp_bfstm, track_filename)

        # Deploy to Eden LayeredFS
        target_dir = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", "stream")
        os.makedirs(target_dir, exist_ok=True)
        dest_path = os.path.join(target_dir, track_filename)
        shutil.copyfile(temp_bfstm, dest_path)

        # If this track shares its prefetch stream_id with a peer (e.g. DesertMain <-> DesertMainParade), sync the peer too
        peer = self.SHARED_STREAM_PEERS.get(track_filename)
        if peer:
            shutil.copyfile(temp_bfstm, os.path.join(target_dir, peer))

        self._require_kept(self.rebuild_prefetch("bgm"), track_filename)

        # Invalidate / cache mod wav for browser audio preview
        mod_wav_cache = os.path.join(CACHE_DIR, f"mod_{track_filename}.wav")
        shutil.copyfile(clean_wav, mod_wav_cache)
        return dest_path

    def scan_music_directory(self, dir_path):
        """Recursively scans a local folder for compatible music tracks."""
        if not os.path.isdir(dir_path):
            raise FileNotFoundError(f"Directory not found: {dir_path}")

        valid_exts = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
        found = []
        for root, _, files in os.walk(dir_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in valid_exts:
                    full_p = os.path.join(root, f)
                    try:
                        sz_mb = round(os.path.getsize(full_p) / (1024 * 1024), 2)
                        found.append({
                            "name": f,
                            "path": full_p,
                            "size_mb": sz_mb,
                            "ext": ext
                        })
                    except Exception:
                        pass
        return found

    def get_priority_bgm_tracks(self):
        """Returns looping ADPCM BGM tracks ordered chronologically by gameplay prominence (Title, Cap, Cascade, Sand, Metro, etc.)."""
        all_tracks = self.list_bgm_tracks()
        priority_prefixes = [
            "RsBgmTitle",
            "RsBgmHat", "RsBgmCap",
            "RsBgmWaterfall",
            "RsBgmDesert", "StmRsBgmDesert",
            "RsBgmLake", "StmRsBgmLake",
            "RsBgmForest", "StmRsBgmForest",
            "RsBgmCloud",
            "RsBgmClash", "StmRsBgmClash",
            "RsBgmCity", "StmRsBgmCity",
            "RsBgmSnow",
            "RsBgmSea", "StmRsBgmSea",
            "RsBgmLava", "StmRsBgmLava",
            "RsBgmBossRaid",
            "RsBgmKoopa", "StmRsBgmBossKoopa",
            "RsBgmMoon", "StmRsBgmMoon",
            "RsBgmPeachCastle", "RsBgmM1",
            "RsBgmBoss", "StmRsBgmBoss"
        ]

        # Exclude 10-channel 0x20-prefetch streams, non-FSTP streams, and jingles/demos that choke Odyssey's SoundHeap
        unsafe_names = {
            "StmRsBgmDemoWorldMap.bfstm", "StmRsBgmCitySession.bfstm", "StmRsBgmBossHaikai_B.bfstm",
            "RsBgmBeforeGK.nk.48.dspadpcm.bfstm", "RsBgmCityScenario03Clct.nk.48.dspadpcm.bfstm",
            "RsBgmDemoKoopaAppear_Ingame0598.nk.48.dspadpcm.bfstm", "RsBgmDemoKoopaLv2Start.nk.48.dspadpcm.bfstm",
            "RsBgmDemoMeetCapFirstA.fs.48.dspadpcm.bfstm", "RsBgmE3Title.nk.48.dspadpcm.bfstm",
            "RsBgmE3Title2.nk.48.dspadpcm.bfstm", "StmRsBgmBossDragon.bfstm",
            "RsBgmSnowTownJingle.fs.32.dspadpcm.bfstm", "RsBgmShop01Radio_tmp.k.48.dspadpcm.bfstm",
            "RsBgmSeSkyGKZone.sg.48.dspadpcm.bfstm"
        }
        prioritized = []
        used = set()
        for p in priority_prefixes:
            for t in all_tracks:
                fn = t["filename"]
                if fn.startswith(p) and fn not in used and fn not in unsafe_names:
                    if not any(x in fn.lower() for x in ["dummy", "silent", "env", "desertworld", "jingle", "_tmp"]):
                        if self.track_specs.get(fn, {}).get("loop", True):
                            prioritized.append(t)
                            used.add(fn)

        remaining = []
        for t in all_tracks:
            fn = t["filename"]
            if fn not in used and fn not in unsafe_names and not any(x in fn.lower() for x in ["dummy", "silent", "env", "desertworld", "jingle", "_tmp"]):
                if self.track_specs.get(fn, {}).get("loop", True):
                    remaining.append(t)
                    used.add(fn)

        return prioritized + remaining

    def batch_replace_music(self, dir_path=None, file_list=None, shuffle=True, max_tracks=None):
        """Scans a music folder or accepts a file list, converts with channel-matching, and distributes across Odyssey kingdoms."""
        if file_list is not None and len(file_list) > 0:
            user_files = file_list
        elif dir_path:
            user_files = self.scan_music_directory(dir_path)
        else:
            user_files = self.scan_music_directory(os.path.expanduser(r"~\Music"))

        if not user_files:
            return {"success": False, "message": "No supported audio files (.mp3, .wav, .flac, .m4a, .ogg) found in folder. Please browse or drop audio files!"}

        # Filter out massive album mixes (> 25 MB) when normal-length songs are available
        normal_files = [u for u in user_files if u.get("size_mb", 0) <= 25]
        if normal_files:
            user_files = normal_files

        game_tracks = [t for t in self.get_priority_bgm_tracks() if bfstm_nx.read_codec(t["path"]) == 2]
        if not game_tracks:
            return {"success": False, "message": "No Odyssey BGM tracks found to replace"}

        num_dest = len(game_tracks)
        if max_tracks and int(max_tracks) > 0:
            num_dest = min(num_dest, int(max_tracks))
        else:
            num_dest = min(len(game_tracks), 50)

        import random
        tracks_pool = list(user_files)
        if shuffle:
            random.shuffle(tracks_pool)
            # If scanning a huge folder (e.g. 5,000+ tracks), prefer already-cached normal-sized (< 14 MB) 2ch tracks first
            if len(tracks_pool) > num_dest:
                cached_pool, uncached_pool = [], []
                for ut in tracks_pool:
                    tp = ut["path"]
                    mt = os.path.getmtime(tp) if os.path.isfile(tp) else 0
                    sz = os.path.getsize(tp) if os.path.isfile(tp) else 0
                    k2 = hashlib.md5(f"{tp}_{mt}_{sz}_2_48000".encode("utf-8", errors="replace")).hexdigest()[:16]
                    c2 = os.path.join(CACHE_DIR, f"track_{k2}_2ch_48000hz.bfstm")
                    if os.path.isfile(c2) and os.path.getsize(c2) <= 14 * 1024 * 1024:
                        cached_pool.append(ut)
                    else:
                        uncached_pool.append(ut)
                tracks_pool = cached_pool + uncached_pool

        # 1. Map target game tracks to user songs; ensure shared stream_id peers (e.g. DesertMain & DesertMainParade,
        # Moon & MoonParade) receive the exact same user song and are both included!
        by_fn = {t["filename"]: t for t in game_tracks}
        selected_targets = list(game_tracks[:num_dest])
        selected_names = {t["filename"] for t in selected_targets}
        for t in list(selected_targets):
            peer_fn = self.SHARED_STREAM_PEERS.get(t["filename"])
            if peer_fn and peer_fn in by_fn and peer_fn not in selected_names:
                selected_targets.append(by_fn[peer_fn])
                selected_names.add(peer_fn)

        assignments = []
        peer_song_map = {}
        needed_adpcm = set()
        for i, tgt_track in enumerate(selected_targets):
            fn = tgt_track["filename"]
            peer_fn = self.SHARED_STREAM_PEERS.get(fn)
            if peer_fn and peer_fn in peer_song_map:
                u_track = peer_song_map[peer_fn]
            else:
                u_track = tracks_pool[i % len(tracks_pool)]
                peer_song_map[fn] = u_track
            spec = self.track_specs.get(fn, {"channels": 2, "sample_rate": 48000})
            ch = spec.get("channels", 2)
            sr = spec.get("sample_rate", 48000)
            assignments.append((tgt_track, u_track, ch, sr))
            needed_adpcm.add((u_track["path"], u_track["name"], ch, sr))

        # 2. Convert unique ADPCM audio requirements without race conditions
        converted_cache = {}
        def convert_req(item):
            track_path, track_name, ch, sr = item
            mtime = os.path.getmtime(track_path) if os.path.isfile(track_path) else 0
            sz = os.path.getsize(track_path) if os.path.isfile(track_path) else 0
            key = f"{track_path}_{mtime}_{sz}_{ch}_{sr}"
            cache_hash = hashlib.md5(key.encode("utf-8", errors="replace")).hexdigest()[:16]
            cached_bfstm = os.path.join(CACHE_DIR, f"track_{cache_hash}_{ch}ch_{sr}hz.bfstm")

            max_bytes = ch * 7 * 1024 * 1024  # ~200s max per channel pair
            if os.path.isfile(cached_bfstm) and 1024 < os.path.getsize(cached_bfstm) <= max_bytes:
                return ((track_path, ch, sr), cached_bfstm)

            rnd = uuid.uuid4().hex[:8]
            temp_wav = os.path.join(CACHE_DIR, f"temp_{rnd}_{ch}ch.wav")
            try:
                self._transcode_to_clean_wav(track_path, temp_wav, target_channels=ch, target_sample_rate=sr, max_duration=180)
                subprocess.run([CONVERT_AUDIO_EXE, temp_wav, cached_bfstm], cwd=TOOLBOX_DIR, stdin=subprocess.DEVNULL, check=True)
            except Exception as ex:
                print(f"Error converting {track_name} ({ch}ch): {ex}")
                return None
            finally:
                if os.path.isfile(temp_wav):
                    try:
                        os.remove(temp_wav)
                    except Exception:
                        pass

            if os.path.isfile(cached_bfstm) and os.path.getsize(cached_bfstm) > 0:
                return ((track_path, ch, sr), cached_bfstm)
            return None

        with ThreadPoolExecutor(max_workers=4) as executor:
            for res in executor.map(convert_req, list(needed_adpcm)):
                if res is not None:
                    converted_cache[res[0]] = res[1]

        # 3. Clear stale BGM files in LayeredFS and deploy the new batch
        target_dir = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", "stream")
        os.makedirs(target_dir, exist_ok=True)
        for old_fn in os.listdir(target_dir):
            if old_fn.endswith(".bfstm"):
                try:
                    os.remove(os.path.join(target_dir, old_fn))
                except Exception:
                    pass

        replaced = []
        for tgt_track, u_track, ch, sr in assignments:
            fn = tgt_track["filename"]
            dest_file = os.path.join(target_dir, fn)
            try:
                key = (u_track["path"], ch, sr)
                bfstm_p = converted_cache.get(key)
                if not (bfstm_p and os.path.isfile(bfstm_p)):
                    continue
                shutil.copyfile(bfstm_p, dest_file)
                self._finalize_bfstm(dest_file, fn)

                replaced.append({
                    "original": tgt_track["title"],
                    "filename": fn,
                    "replacement": u_track["name"],
                    "channels": ch
                })
            except Exception as e:
                print(f"Error deploying to {fn}: {e}")

        # Rebuild prefetch archive and sync shared stream_id pairs
        pre = self.rebuild_prefetch("bgm")
        dropped_names = set(pre.get("removed", []))
        dropped = [dict(r, reason=dict(pre.get("skipped", [])).get(r["filename"], "unsupported stream type"))
                   for r in replaced if r["filename"] in dropped_names]
        replaced = [r for r in replaced if r["filename"] not in dropped_names]

        return {
            "success": True,
            "replaced_count": len(replaced),
            "dropped_count": len(dropped),
            "dropped": dropped,
            "total_scope": len(selected_targets),
            "unique_songs_used": len({r["replacement"] for r in replaced}),
            "tracks": replaced
        }

    def reset_audio(self):
        """Deletes all modded audio from Eden LayeredFS and clears modded audio preview cache."""
        sound_dir = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData")
        deleted = False
        locked_files = []
        if os.path.isdir(sound_dir):
            for root, dirs, files in os.walk(sound_dir, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        os.remove(fp)
                        deleted = True
                    except Exception:
                        locked_files.append(f)
                for d in dirs:
                    try:
                        os.rmdir(os.path.join(root, d))
                    except Exception:
                        pass
            try:
                shutil.rmtree(sound_dir)
                deleted = True
            except Exception:
                pass
        for f in os.listdir(CACHE_DIR):
            if f.startswith("mod_") and f.endswith(".wav"):
                try:
                    os.remove(os.path.join(CACHE_DIR, f))
                except Exception:
                    pass
        if locked_files:
            return {
                "success": True,
                "deleted": deleted,
                "message": f"Restored vanilla audio (note: {len(locked_files)} file(s) were locked by a running Eden process — close Eden and click Reset Audio again if needed)."
            }
        return {
            "success": True,
            "deleted": deleted,
            "message": "All game audio restored to 100% clean vanilla Switch audio!"
        }


    def _modded_sfx_manifest_path(self):
        return os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", "modded_sfx_manifest.json")

    def _load_modded_sfx_set(self):
        p = self._modded_sfx_manifest_path()
        modded = set()
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    modded.update(json.load(f))
            except Exception:
                pass
        stream_se = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", "streamSe")
        if os.path.isdir(stream_se):
            for fn in os.listdir(stream_se):
                if fn.endswith(".bfstm"):
                    modded.add(fn)
        return modded

    def _record_modded_sfx(self, track_id):
        s = self._load_modded_sfx_set()
        s.add(track_id)
        p = self._modded_sfx_manifest_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(sorted(s), f)

    def list_sfx_tracks(self):
        if not hasattr(self, "_sfx_catalog_cache") or not self._sfx_catalog_cache:
            self._sfx_catalog_cache = bfsar_sfx.build_sfx_catalog(ROMFS_ROOT, CACHE_DIR)
        modded = self._load_modded_sfx_set()
        tracks = []
        for item in self._sfx_catalog_cache:
            t = dict(item)
            wkey = f"{t.get('archive')}:{t.get('fwar_off')}:{t.get('wav_idx')}"
            t["is_modded"] = (t["filename"] in modded) or (wkey in modded)
            tracks.append(t)
        return tracks

    def get_sfx_wav(self, track_filename):
        if track_filename.startswith("fwav:"):
            parts = track_filename.split(":", 4)
            if len(parts) < 4:
                return None
            _, aras_name, fwar_off_s, wav_idx_s = parts[:4]
            fwar_off = int(fwar_off_s)
            wav_idx = int(wav_idx_s)
            mod_arch = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", aras_name)
            van_arch = os.path.join(ROMFS_ROOT, "SoundData", aras_name)
            src_arch = mod_arch if os.path.isfile(mod_arch) else van_arch
            if not os.path.isfile(src_arch):
                return None
            mtime = int(os.path.getmtime(src_arch))
            wav_cache = os.path.join(CACHE_DIR, f"fwav_{aras_name}_{fwar_off}_{wav_idx}_{mtime}.wav")
            if not os.path.isfile(wav_cache):
                fw = bfsar_sfx.read_fwav_from_archive(src_arch, fwar_off, wav_idx)
                bfsar_sfx.decode_fwav_to_wav_file(fw, wav_cache)
            return wav_cache

        modded_path = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", "streamSe", track_filename)
        if os.path.isfile(modded_path):
            mod_wav_cache = os.path.join(CACHE_DIR, f"mod_sfx_{track_filename}.wav")
            if not os.path.isfile(mod_wav_cache) or os.path.getmtime(modded_path) > os.path.getmtime(mod_wav_cache):
                try:
                    subprocess.run([CONVERT_AUDIO_EXE, modded_path, mod_wav_cache], cwd=TOOLBOX_DIR, check=True)
                except Exception:
                    pass
            if os.path.isfile(mod_wav_cache):
                return mod_wav_cache

        stream_dir = os.path.join(ROMFS_ROOT, "SoundData", "streamSe")
        bfstm_path = os.path.join(stream_dir, track_filename)
        if not os.path.isfile(bfstm_path):
            return None

        wav_cache = os.path.join(CACHE_DIR, f"sfx_{track_filename}.wav")
        if not os.path.isfile(wav_cache):
            subprocess.run([CONVERT_AUDIO_EXE, bfstm_path, wav_cache], cwd=TOOLBOX_DIR, check=True)

        return wav_cache

    def replace_sfx_track(self, track_filename, audio_data_or_path):
        if track_filename.startswith("fwav:"):
            parts = track_filename.split(":", 4)
            if len(parts) < 4:
                raise ValueError(f"Invalid FWAV track identifier: {track_filename}")
            _, aras_name, fwar_off_s, wav_idx_s = parts[:4]
            fwar_off = int(fwar_off_s)
            wav_idx = int(wav_idx_s)
            van_arch = os.path.join(ROMFS_ROOT, "SoundData", aras_name)
            if not os.path.isfile(van_arch):
                raise FileNotFoundError(f"Vanilla sound archive not found: {aras_name}")

            vanilla_fwav = bfsar_sfx.read_fwav_from_archive(van_arch, fwar_off, wav_idx)
            ib = int.from_bytes(vanilla_fwav[0x18:0x1C], "little", signed=True) + 8
            codec = vanilla_fwav[ib]
            rate = int.from_bytes(vanilla_fwav[ib + 4:ib + 8], "little")
            ch_cnt = int.from_bytes(vanilla_fwav[ib + 20:ib + 24], "little")

            clean_wav = os.path.join(CACHE_DIR, f"temp_clean_fwav_{wav_idx}.wav")
            self._transcode_to_clean_wav(audio_data_or_path, clean_wav, target_channels=ch_cnt, target_sample_rate=rate)

            new_fwav = bfsar_sfx.encode_wav_to_fwav(clean_wav, vanilla_fwav, CONVERT_AUDIO_EXE, TOOLBOX_DIR, CACHE_DIR)
            dest_arch = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", aras_name)
            bfsar_sfx.patch_archive_fwav(van_arch, dest_arch, fwar_off, wav_idx, new_fwav)

            self._record_modded_sfx(track_filename)
            self._record_modded_sfx(f"{aras_name}:{fwar_off}:{wav_idx}")
            return dest_arch

        # Legacy streamSe/*.bfstm replacement
        vp = os.path.join(ROMFS_ROOT, "SoundData", "streamSe", track_filename)
        if not os.path.isfile(vp):
            raise FileNotFoundError(f"unknown effects stream: {track_filename}")
        with open(vp, "rb") as f:
            vinfo = bfstm_nx._parse(f.read(0x4000))
        if vinfo["codec"] != 2:
            raise RuntimeError(f"{track_filename} is not an ADPCM stream and can't be replaced")

        clean_wav = os.path.join(CACHE_DIR, "temp_clean_sfx.wav")
        self._transcode_to_clean_wav(audio_data_or_path, clean_wav, target_channels=vinfo["channels"],
                                     target_sample_rate=vinfo["rate"])

        temp_bfstm = os.path.join(CACHE_DIR, f"sfx_{track_filename}")
        subprocess.run([CONVERT_AUDIO_EXE, clean_wav, temp_bfstm], cwd=TOOLBOX_DIR, check=True)
        self._finalize_bfstm(temp_bfstm, track_filename, sfx=True)

        # Deploy to Eden LayeredFS streamSe
        target_dir = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData", "streamSe")
        os.makedirs(target_dir, exist_ok=True)
        dest_path = os.path.join(target_dir, track_filename)
        shutil.copyfile(temp_bfstm, dest_path)
        self._require_kept(self.rebuild_prefetch("se"), track_filename)

        mod_wav_cache = os.path.join(CACHE_DIR, f"mod_sfx_{track_filename}.wav")
        shutil.copyfile(clean_wav, mod_wav_cache)
        self._record_modded_sfx(track_filename)
        return dest_path

    def _switch_to_user_desktop(self):
        user32 = ctypes.windll.user32
        DESKTOP_ALL = 0x01FF
        h_desk = user32.OpenDesktopW("Default", 0, False, DESKTOP_ALL)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
        return h_desk

    def _get_windows_for_pid(self, pid):
        self._switch_to_user_desktop()
        user32 = ctypes.windll.user32
        hwnds = []
        def enum_cb(hwnd, extra):
            if user32.IsWindowVisible(hwnd):
                lpdw_proc_id = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw_proc_id))
                if lpdw_proc_id.value == pid:
                    length = user32.GetWindowTextLengthW(hwnd)
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    hwnds.append((hwnd, buff.value))
            return True
        cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(enum_cb)
        user32.EnumWindows(cb, 0)
        return hwnds

    def _bring_window_to_front(self, hwnd, pid=None):
        self._switch_to_user_desktop()
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 1. Unlock foreground lock
        user32.LockSetForegroundWindow(2) # LSFW_UNLOCK
        user32.AllowSetForegroundWindow(-1) # ASFW_ANY

        # 2. Restore if minimized
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9) # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5) # SW_SHOW

        # 3. AttachThreadInput to the current foreground thread
        fore_hwnd = user32.GetForegroundWindow()
        fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()

        attached_fore = False
        attached_target = False
        if fore_thread != 0 and fore_thread != cur_thread:
            attached_fore = user32.AttachThreadInput(cur_thread, fore_thread, True)
        if target_thread != 0 and target_thread != cur_thread:
            attached_target = user32.AttachThreadInput(cur_thread, target_thread, True)

        # 4. Synthesize ALT key press to force Windows to accept SetForegroundWindow
        user32.keybd_event(0x12, 0, 0, 0) # ALT down
        user32.keybd_event(0x12, 0, 2, 0) # ALT up

        # 5. Force window to TOPMOST then NOTOPMOST (bypasses z-order stacking behind browser)
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        time.sleep(0.04)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

        # 6. Bring to top & focus
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)

        if attached_fore:
            user32.AttachThreadInput(cur_thread, fore_thread, False)
        if attached_target:
            user32.AttachThreadInput(cur_thread, target_thread, False)

        # 7. Fallback: Shell activation
        if pid:
            try:
                cmd = f"(New-Object -ComObject WScript.Shell).AppActivate({pid})"
                subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=2)
            except Exception:
                pass

    def _ensure_eden_audio_sink(self):
        """cubeb (output_engine=0) is Eden's fast path. SDL3 (2) makes startup ~3x slower and the audio glitchy, so it is
        only used while Voicemod is running, because cubeb fails with error -1 against its virtual device."""
        qt_ini = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "eden", "config", "qt-config.ini")
        if not os.path.isfile(qt_ini):
            return
        import re
        audio_dev_issue = any((p.info['name'] or '').lower().startswith(('voicemod', 'umc', 'asio')) for p in psutil.process_iter(['name']))
        want = (b"false", b"2") if audio_dev_issue else (b"true", b"0")
        try:
            with open(qt_ini, "r", encoding="utf-8", errors="replace", newline="") as f:
                txt = f.read()
            new_txt = re.sub(r"(\[Audio\]\r?\n(?:[^\[]*?\r?\n)?)output_engine\\default=\w+(\r?\n)output_engine=\d+",
                             lambda m: f"{m.group(1)}output_engine\\default={want[0].decode()}{m.group(2)}output_engine={want[1].decode()}",
                             txt, count=1)
            if new_txt != txt:
                with open(qt_ini, "w", encoding="utf-8", newline="") as f:
                    f.write(new_txt)
        except Exception:
            pass

    def launch_eden(self):
        if not os.path.isfile(EDEN_EXE):
            raise FileNotFoundError("eden.exe not found")

        os.environ["SDL_AUDIODRIVER"] = "directsound"
        self._ensure_eden_audio_sink()
        nsp_path = find_mario_nsp()
        eden_dir = os.path.dirname(EDEN_EXE)

        # 1. Check if Eden is already running
        running_eden_pid = None
        for p in psutil.process_iter(['pid', 'name']):
            try:
                if p.info['name'] and 'eden' in p.info['name'].lower():
                    running_eden_pid = p.info['pid']
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if running_eden_pid:
            # Eden is already running! Force its windows to the front if ready
            hwnds = self._get_windows_for_pid(running_eden_pid)
            if hwnds:
                for h, title in hwnds:
                    self._bring_window_to_front(h, running_eden_pid)
            return True

        # 2. Launch Eden interactively on the user's visible desktop via preconfigured task
        run_cmd = ["schtasks", "/run", "/tn", "SwitchStudio_LaunchEden"]
        res = subprocess.run(run_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            # Fallback to direct bat execution
            bat_path = os.path.join(STUDIO_ROOT, "launch_eden.bat")
            subprocess.Popen([bat_path], cwd=eden_dir, shell=True)

        # 3. Threaded foreground watcher to pop Eden right in front of Chrome
        def watch_and_focus():
            self._switch_to_user_desktop()
            for _ in range(50): # up to 10 seconds
                time.sleep(0.2)
                eden_pids = []
                for p in psutil.process_iter(['pid', 'name']):
                    try:
                        if p.info['name'] and 'eden' in p.info['name'].lower():
                            eden_pids.append(p.info['pid'])
                    except Exception:
                        pass

                found = False
                for pid in eden_pids:
                    hwnds = self._get_windows_for_pid(pid)
                    if hwnds:
                        for h, title in hwnds:
                            self._bring_window_to_front(h, pid)
                        found = True

                if found:
                    for _ in range(6):
                        time.sleep(0.5)
                        for pid in eden_pids:
                            latest_hwnds = self._get_windows_for_pid(pid)
                            for hl, tl in latest_hwnds:
                                self._bring_window_to_front(hl, pid)
                    break

        threading.Thread(target=watch_and_focus, daemon=True).start()
        return True

    # =========================================================================
    # MARIO SIZE & PROPORTIONS (TINY / CHIBI / NORMAL / BOBBLEHEAD / GIANT / TITAN)
    # =========================================================================
    MARIO_SCALE_PRESETS = {
        "tiny": {
            "id": "tiny",
            "label": "Tiny Mario (0.45x)",
            "body_scale": 0.45,
            "head_mult": 1.15,
            "desc": "Pocket-sized Mini-Mushroom Mario!"
        },
        "chibi": {
            "id": "chibi",
            "label": "Kid / Chibi Mario (0.68x)",
            "body_scale": 0.68,
            "head_mult": 1.38,
            "desc": "Child-sized Mario with cute chibi head proportions"
        },
        "normal": {
            "id": "normal",
            "label": "Normal Mario (1.0x)",
            "body_scale": 1.0,
            "head_mult": 1.0,
            "desc": "Standard Super Mario Odyssey proportions"
        },
        "bobblehead": {
            "id": "bobblehead",
            "label": "Big Head Mode (2.0x Head)",
            "body_scale": 1.0,
            "head_mult": 2.0,
            "desc": "Normal body with a giant 2x bobblehead & cap!"
        },
        "giant": {
            "id": "giant",
            "label": "Giant Mario (2.0x)",
            "body_scale": 2.0,
            "head_mult": 1.0,
            "desc": "Mega-Mushroom 2x Giant Mario!"
        },
        "titan": {
            "id": "titan",
            "label": "Titan Mario (3.0x)",
            "body_scale": 3.0,
            "head_mult": 1.0,
            "desc": "Colossal 3x Towering Mario!"
        }
    }

    def get_mario_scale_state(self):
        preset = self.settings.get("mario_scale_preset", "normal")
        bs = float(self.settings.get("mario_body_scale", 1.0))
        hm = float(self.settings.get("mario_head_mult", 1.0))
        return {
            "preset": preset,
            "body_scale": round(bs, 2),
            "head_mult": round(hm, 2),
            "active": self._mario_scale_active(),
            "presets": list(self.MARIO_SCALE_PRESETS.values())
        }

    def apply_mario_scale(self, preset=None, body_scale=None, head_mult=None):
        if preset and preset in self.MARIO_SCALE_PRESETS and body_scale is None and head_mult is None:
            p = self.MARIO_SCALE_PRESETS[preset]
            bs = float(p["body_scale"])
            hm = float(p["head_mult"])
            chosen_preset = preset
        else:
            bs = max(0.25, min(4.0, float(body_scale if body_scale is not None else self.settings.get("mario_body_scale", 1.0))))
            hm = max(0.5, min(3.0, float(head_mult if head_mult is not None else self.settings.get("mario_head_mult", 1.0))))
            chosen_preset = preset or "custom"
            for pid, pinfo in self.MARIO_SCALE_PRESETS.items():
                if abs(pinfo["body_scale"] - bs) < 0.02 and abs(pinfo["head_mult"] - hm) < 0.02:
                    chosen_preset = pid
                    break

        self.settings["mario_scale_preset"] = chosen_preset
        self.settings["mario_body_scale"] = bs
        self.settings["mario_head_mult"] = hm
        self.save_settings()

        # Deploy or restore Mario.szs & MarioColorLuigi.szs
        if not self._mario_scale_active() and not self._slot_is_edited("mario_body"):
            deployed_dir = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "ObjectData")
            for a in SLOT_ARCHIVES.get("mario_body", []):
                fp = os.path.join(deployed_dir, a)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
            msg = "Restored Normal Mario (1.0x) proportions!"
        else:
            self.commit_texture_to_model("mario_body")
            label = self.MARIO_SCALE_PRESETS.get(chosen_preset, {}).get("label", f"Body {bs:.2f}x / Head {hm:.2f}x")
            msg = f"Deployed {label} to Mario.szs & MarioColorLuigi.szs!"

        state = self.get_mario_scale_state()
        state["success"] = True
        state["message"] = msg
        return state

    # =========================================================================
    # COMMUNITY PACKS (GAMEBANANA) BROWSER, INSTALLER & TOGGLER
    # =========================================================================
    CURATED_COMMUNITY_PACKS = [
        {
            "id": "YoshiStarKingdom",
            "gb_id": 284356,
            "name": "Yoshi Star Kingdom (Super Mario Galaxy 2 Remastered)",
            "author": "MasterJ360 & Galaxy Team",
            "category": "3D Kingdom Overhaul",
            "replaces": "Cascade Kingdom (Direct QuickMoon Boot)",
            "size_mb": 100.7,
            "likes": 142,
            "views": 48500,
            "thumb": "thumbs/yoshi_star.jpg",
            "how_to_play": "Just click Launch Eden and press Resume / Start! QuickMoon loads you straight into Super Mario Galaxy 2's Yoshi Star Galaxy (with a separate save at switch/qm-save/remaster-ysk/ so your 100% Odyssey save stays safe!).",
            "description": "Full 3D level geometry & texture port of Super Mario Galaxy 2's Yoshi Star Galaxy into Super Mario Odyssey! Features custom 3D planetoids, Lava & Spiny Planets, Pull Stars, Launch Stars, custom skybox, and 8 Galaxy soundtrack streams."
        },
        {
            "id": "RecreatingEveryTexture",
            "gb_id": 401591,
            "name": "Recreating Every Texture in SMO (Hand-Painted Pack)",
            "author": "Snowy & SMO Community",
            "category": "HD Texture Pack",
            "replaces": "Cap, Cascade, Sand, Metro, Luncheon, Mushroom, Moon & Mario",
            "size_mb": 438.4,
            "likes": 95,
            "views": 29400,
            "thumb": "thumbs/recreating_textures.jpg",
            "how_to_play": "Automatically repaints level & environment textures across almost every kingdom in the game.",
            "description": "Massive community artwork overhaul that repaints the environment, ground, walls, and object textures across Cap, Cascade, Sand, Metro, Luncheon, Mushroom, and Moon Kingdoms."
        },
        {
            "id": "FluffyBluffKingdom",
            "gb_id": 585922,
            "name": "Fluffy Bluff Kingdom (Super Mario Galaxy 2)",
            "author": "Galaxy Modding Team",
            "category": "3D Kingdom Overhaul",
            "replaces": "Cloud Kingdom",
            "size_mb": 16.0,
            "likes": 78,
            "views": 18200,
            "thumb": "thumbs/fluffy_bluff.jpg",
            "how_to_play": "Warp to the Cloud Kingdom on the Odyssey Globe to explore Fluffy Bluff Galaxy!",
            "description": "Transforms the Cloud Kingdom into Super Mario Galaxy 2's Fluffy Bluff Galaxy with custom 3D cloud towers, trees, cosmic platforms, and Galaxy music."
        },
        {
            "id": "WuhuKingdom",
            "gb_id": 701804,
            "name": "Wuhu Kingdom (Wii Sports Resort 3D Island)",
            "author": "Wuhu Team",
            "category": "3D Kingdom Overhaul",
            "replaces": "Cap, Cascade & Sand Kingdoms (Wedge & Wuhu Island)",
            "size_mb": 162.8,
            "likes": 110,
            "views": 31000,
            "thumb": "thumbs/wuhu_kingdom.jpg",
            "how_to_play": "Click Launch Eden and start/resume! Uses a separate save at sd:/smo/WuhuKingdom/save/ so your 100% Odyssey save stays untouched.",
            "description": "Brings the iconic Wuhu Island & Wedge Island from Wii Sports Resort into Super Mario Odyssey with custom Power Moons, volcano, town, and beach resort."
        },
        {
            "id": "KingdomPass",
            "gb_id": 391917,
            "name": "The Kingdom Pass (Custom 3D Stages Expansion)",
            "author": "SMO Stage Builders",
            "category": "3D Kingdom Overhaul",
            "replaces": "Multiple Sub-Areas & Kingdoms",
            "size_mb": 256.4,
            "likes": 89,
            "views": 24100,
            "thumb": "thumbs/kingdom_pass.jpg",
            "how_to_play": "Adds custom 3D challenge stages and moons across multiple kingdoms.",
            "description": "Community expansion pack featuring custom 3D platforming courses, new textures, and custom Power Moons."
        }
    ]

    def _eden_disabled_dir(self):
        d = os.path.join(os.path.dirname(os.path.dirname(EDEN_LOAD_DIR)), "load_disabled", "0100000000010000")
        os.makedirs(d, exist_ok=True)
        return d

    def _community_cache_dir(self):
        d = os.path.join(STUDIO_ROOT, "community_cache")
        os.makedirs(d, exist_ok=True)
        return d

    def _sync_pack_audio_and_exefs(self, pack_id, enabled):
        """Ensures enabling/disabling a community pack with custom music or exefs never freezes Eden or conflicts with ClaraMarioReshaped."""
        active_dir = os.path.join(EDEN_LOAD_DIR, pack_id)
        disabled_dir = os.path.join(self._eden_disabled_dir(), pack_id)
        pack_dir = active_dir if os.path.isdir(active_dir) else disabled_dir
        if not os.path.isdir(pack_dir):
            return

        clara_sd = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData")
        clara_stm = os.path.join(clara_sd, "stream")
        bak_dir = os.path.join(clara_sd, "_pack_backup", pack_id)
        pack_sd = os.path.join(pack_dir, "romfs", "SoundData")
        pack_stm = os.path.join(pack_sd, "stream")

        if os.path.isdir(pack_stm):
            os.makedirs(clara_stm, exist_ok=True)
            os.makedirs(bak_dir, exist_ok=True)
            if enabled:
                for fn in sorted(os.listdir(pack_stm)):
                    if not fn.endswith(".bfstm"):
                        continue
                    src_f = os.path.join(pack_stm, fn)
                    dst_f = os.path.join(clara_stm, fn)
                    bak_f = os.path.join(bak_dir, fn)
                    if os.path.isfile(dst_f) and not os.path.isfile(bak_f):
                        shutil.copy2(dst_f, bak_f)
                    shutil.copy2(src_f, dst_f)
                self.rebuild_prefetch("bgm")
                clara_aras = os.path.join(clara_sd, "BgmResourceStdPrefetch.aras")
                if os.path.isfile(clara_aras):
                    shutil.copy2(clara_aras, os.path.join(pack_sd, "BgmResourceStdPrefetch.aras"))
            else:
                for fn in sorted(os.listdir(pack_stm)):
                    if not fn.endswith(".bfstm"):
                        continue
                    dst_f = os.path.join(clara_stm, fn)
                    bak_f = os.path.join(bak_dir, fn)
                    if os.path.isfile(bak_f):
                        shutil.copy2(bak_f, dst_f)
                        os.remove(bak_f)
                    elif os.path.isfile(dst_f):
                        os.remove(dst_f)
                self.rebuild_prefetch("bgm")

        # Handle standalone LunaKit exefs collision if the pack embeds its own exefs/subsdk9
        any_active_pack_has_exefs = False
        if os.path.isdir(EDEN_LOAD_DIR):
            for dname in os.listdir(EDEN_LOAD_DIR):
                if dname in (self.active_mod_name, "LunaKit"):
                    continue
                if os.path.isdir(os.path.join(EDEN_LOAD_DIR, dname, "exefs")):
                    any_active_pack_has_exefs = True
                    break

        lk_active = os.path.join(EDEN_LOAD_DIR, "LunaKit")
        lk_disabled = os.path.join(self._eden_disabled_dir(), "LunaKit")
        if any_active_pack_has_exefs and os.path.isdir(lk_active):
            if os.path.isdir(lk_disabled):
                shutil.rmtree(lk_disabled)
            shutil.move(lk_active, lk_disabled)
        elif not any_active_pack_has_exefs and os.path.isdir(lk_disabled) and not os.path.isdir(lk_active):
            shutil.move(lk_disabled, lk_active)

    def _normalize_pack_for_v100(self, pack_dir):
        """Patches v1.3.0 BgmDataBase.szs for v1.0.0 safety and normalizes any custom .bfstm files to match vanilla channels & 48kHz."""
        if oead is None:
            return
        # 1. Strip v1.3.0-only PatchBgmBalloon from BgmDataBase.szs so v1.0.0 never crashes
        bgm_db = os.path.join(pack_dir, "romfs", "SoundData", "BgmDataBase.szs")
        if os.path.isfile(bgm_db):
            try:
                with open(bgm_db, "rb") as f:
                    raw = f.read()
                orig_align = raw[8:12]
                decomp = oead.yaz0.decompress(raw)
                sarc = oead.Sarc(decomp)
                writer = oead.SarcWriter.from_sarc(sarc)
                f_info = sarc.get_file("BgmResourceInfoList.byml")
                if f_info is not None:
                    b_info = oead.byml.from_binary(f_info.data)
                    res_list = b_info.get("ResourceNameList", [])
                    new_list = [r for r in res_list if str(r.get("ResourceName", "")) != "PatchBgmBalloon"]
                    if len(new_list) != len(res_list):
                        b_info["ResourceNameList"] = oead.byml.Array(new_list)
                        writer.files["BgmResourceInfoList.byml"] = bytes(oead.byml.to_binary(b_info, big_endian=False))
                        _, sarc_bytes = writer.write()
                        recomp = bytearray(oead.yaz0.compress(sarc_bytes, data_alignment=0x1000, level=9))
                        recomp[8:12] = orig_align
                        with open(bgm_db, "wb") as f:
                            f.write(recomp)
            except Exception as e:
                print(f"Warning normalizing BgmDataBase.szs: {e}")

        # 2. Normalize any .bfstm files in romfs/SoundData/stream/ to match vanilla channel count & sample rate
        pack_stm = os.path.join(pack_dir, "romfs", "SoundData", "stream")
        if os.path.isdir(pack_stm):
            for fn in sorted(os.listdir(pack_stm)):
                if not fn.endswith(".bfstm"):
                    continue
                fp = os.path.join(pack_stm, fn)
                vp = os.path.join(ROMFS_ROOT, "SoundData", "stream", fn)
                if not os.path.isfile(vp):
                    continue
                try:
                    with open(fp, "rb") as f:
                        yinfo = bfstm_nx._parse(f.read(0x4000))
                    with open(vp, "rb") as f:
                        vinfo = bfstm_nx._parse(f.read(0x4000))
                    if yinfo["channels"] != vinfo["channels"] or yinfo["rate"] != vinfo["rate"] or yinfo.get("endian", "<") != "<":
                        tmp_wav = os.path.join(CACHE_DIR, f"pack_tmp_{fn}.wav")
                        clean_wav = os.path.join(CACHE_DIR, f"pack_clean_{fn}.wav")
                        tmp_bfstm = os.path.join(CACHE_DIR, f"pack_out_{fn}")
                        subprocess.run([CONVERT_AUDIO_EXE, fp, tmp_wav], cwd=TOOLBOX_DIR, check=True)
                        self._transcode_to_clean_wav(tmp_wav, clean_wav, target_channels=vinfo["channels"], target_sample_rate=vinfo["rate"])
                        subprocess.run([CONVERT_AUDIO_EXE, clean_wav, tmp_bfstm], cwd=TOOLBOX_DIR, check=True)
                        self._finalize_bfstm(tmp_bfstm, fn, sfx=False)
                        shutil.copy2(tmp_bfstm, fp)
                    else:
                        self._finalize_bfstm(fp, fn, sfx=False)
                except Exception as e:
                    print(f"Warning normalizing {fn}: {e}")

        # 2b. If this is a 3D Kingdom Overhaul pack, move any bundled Mario.szs / MarioFace.szs / MarioHeadTexture.szs
        # aside so they never override the user's custom ClaraMarioReshaped face, outfit, or Tiny/Giant Mario scale.
        if os.path.isdir(os.path.join(pack_dir, "romfs", "StageData")):
            obj_dir = os.path.join(pack_dir, "romfs", "ObjectData")
            skip_dir = os.path.join(pack_dir, "romfs", "_skipped_mario_models")
            protected_mario = {
                "Mario.szs", "MarioHigh.szs", "MarioFace.szs", "MarioHighFace.szs",
                "MarioEye.szs", "MarioHighEye.szs", "MarioHead.szs", "MarioHighHead.szs",
                "MarioHeadTexture.szs", "MarioCap.szs", "MarioHighCap.szs", "MarioCapTexture.szs",
                "MarioUnder.szs", "MarioHandL.szs", "MarioHandR.szs", "MarioHandTexture.szs"
            }
            if os.path.isdir(obj_dir):
                for mfn in protected_mario:
                    mp = os.path.join(obj_dir, mfn)
                    if os.path.isfile(mp):
                        os.makedirs(skip_dir, exist_ok=True)
                        shutil.move(mp, os.path.join(skip_dir, mfn))

        # 2c. Remove incompatible exefs like subsdk4 (requires pm:shell / causes Launching... freeze)
        exefs_dir = os.path.join(pack_dir, "exefs")
        if os.path.isdir(exefs_dir) and os.path.isfile(os.path.join(exefs_dir, "subsdk4")):
            shutil.rmtree(exefs_dir, ignore_errors=True)

        # 2d. Remove non-custom v1.3.0 audio archives that collide with v1.0.0 sound drivers
        sd_dir = os.path.join(pack_dir, "romfs", "SoundData")
        if os.path.isdir(sd_dir):
            for bad_audio in ("SeData.bfsar", "BgmDataBase.szs", "BossForest.aras", "SeResourceStdSystem.aras"):
                bpath = os.path.join(sd_dir, bad_audio)
                if os.path.isfile(bpath):
                    try:
                        os.remove(bpath)
                    except OSError:
                        pass

        # 3. Normalize SystemData/WorldList.szs so v1.3.0 WorldResource.byml & WorldList.byml do not overflow WorldResourceHeap on v1.0.0
        # IMPORTANT: Preserve the mod's own WorldResource.byml (which in mods like WuhuKingdom already prunes Cap/Waterfall/Sand
        # and registers custom 3D island models), while stripping any v1.3.0-only or non-existent files across all Scenario lists.
        wl_mod_path = os.path.join(pack_dir, "romfs", "SystemData", "WorldList.szs")
        wl_van_path = os.path.join(ROMFS_ROOT, "SystemData", "WorldList.szs")
        if os.path.isfile(wl_mod_path) and os.path.isfile(wl_van_path):
            try:
                wl_mod = oead.Sarc(oead.yaz0.decompress(open(wl_mod_path, "rb").read()))
                bm_mod_res = oead.byml.from_binary(wl_mod.get_file("WorldResource.byml").data)
                stage_dir = os.path.join(pack_dir, "romfs", "StageData")
                all_stage_text = ""
                if os.path.isdir(stage_dir):
                    for sfn in os.listdir(stage_dir):
                        if sfn.endswith(".szs"):
                            sc = oead.Sarc(oead.yaz0.decompress(open(os.path.join(stage_dir, sfn), "rb").read()))
                            for sf in sc.get_files():
                                if sf.name.endswith(".byml"):
                                    all_stage_text += " " + str(oead.byml.from_binary(sf.data))
                unused_prefixes = (
                    "ObjectData/Lift2DEx", "ObjectData/WanwanClashEx", "ObjectData/TrexPoppunEx",
                    "ObjectData/CapAppearExGround", "ObjectData/WindBlowEx", "ObjectData/DesSimWaterFall",
                    "ObjectData/DesSimWaterfall", "ObjectData/WaterfallWorldHomeGround",
                    "ObjectData/WaterfallWorldHomeBone", "ObjectData/WaterfallWorldHomeBreak",
                    "ObjectData/WaterfallWorldHomeMiddleView", "ObjectData/WaterfallWorldHomeRock",
                    "ObjectData/WaterfallWorldBreakParts", "ObjectData/WaterfallWorldHomeFloater",
                    "ObjectData/WaterfallWorldHomePlant",
                )
                for item in bm_mod_res:
                    wname = str(item.get("WorldName", ""))
                    for list_key in list(item.keys()):
                        if list_key == "WorldName":
                            continue
                        orig_list = item[list_key]
                        # If the mod author already tailored/pruned this world list (< 450 items), preserve it completely!
                        if len(orig_list) <= 450:
                            continue
                        # Check if this world list is unpruned vanilla (> 500 items) and needs unused Cascade archive pruning
                        prune_waterfall = (wname == "Waterfall" and len(orig_list) > 500)
                        new_res = []
                        for r in orig_list:
                            full_name = str(r["Name"])
                            rel = full_name + "." + str(r["Ext"])
                            rel_os = rel.replace("/", os.sep)
                            # Strip any v1.3.0-only Balloon World or missing archive that exists in neither pack romfs nor vanilla v1.0.0 romfs
                            if not os.path.exists(os.path.join(pack_dir, "romfs", rel_os)) and not os.path.exists(os.path.join(ROMFS_ROOT, rel_os)):
                                continue
                            if prune_waterfall:
                                base_obj = full_name.split("/")[-1]
                                if full_name.startswith(unused_prefixes) and (base_obj not in all_stage_text) and not os.path.exists(os.path.join(pack_dir, "romfs", rel_os)):
                                    continue
                            new_res.append(r)
                        item[list_key] = oead.byml.Array(new_res)

                # Only write out WorldList.szs if any world list was actually modified (> 450 items)
                has_pruned = any(len(item.get("WorldResource", [])) > 450 for item in bm_mod_res)
                if not has_pruned:
                    return

                bm_mod_wl = oead.byml.from_binary(wl_mod.get_file("WorldList.byml").data)
                for item in bm_mod_wl:
                    if "BalloonScenario" in item:
                        del item["BalloonScenario"]
                writer = oead.SarcWriter(endian=oead.Endianness.Little)
                for f in wl_mod.get_files():
                    if f.name == "WorldResource.byml":
                        writer.files[f.name] = oead.byml.to_binary(bm_mod_res, big_endian=False)
                    elif f.name == "WorldList.byml":
                        writer.files[f.name] = oead.byml.to_binary(bm_mod_wl, big_endian=False)
                    else:
                        writer.files[f.name] = bytes(f.data)
                _, raw_sarc = writer.write()
                with open(wl_mod_path, "wb") as out_f:
                    out_f.write(oead.yaz0.compress(raw_sarc, 0, 7))
            except Exception as e:
                print(f"Warning normalizing WorldList.szs: {e}")

    def _metadata_path(self):
        p = os.path.join(STUDIO_ROOT, "switch_studio", "config", "community_metadata.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def _load_community_metadata(self):
        mp = self._metadata_path()
        if os.path.isfile(mp):
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_community_metadata(self, data):
        mp = self._metadata_path()
        try:
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving community metadata: {e}")

    def get_community_packs(self):
        disabled_root = self._eden_disabled_dir()
        packs = []
        seen_ids = set()
        meta_db = self._load_community_metadata()

        for c in self.CURATED_COMMUNITY_PACKS:
            pid = c["id"]
            seen_ids.add(pid)
            active_path = os.path.join(EDEN_LOAD_DIR, pid)
            dis_path = os.path.join(disabled_root, pid)
            is_active = os.path.isdir(active_path)
            is_installed = is_active or os.path.isdir(dis_path)
            item = dict(c)
            # Enrich with real remote metadata if available
            meta = meta_db.get(pid, {})
            if meta:
                if meta.get("thumb"):
                    item["thumb"] = meta["thumb"]
                if meta.get("likes"):
                    item["likes"] = meta["likes"]
                if meta.get("views"):
                    item["views"] = meta["views"]
            item["installed"] = is_installed
            item["enabled"] = is_active
            packs.append(item)

        # Also list any extra folders installed in EDEN_LOAD_DIR or load_disabled
        for root_dir, is_act in ((EDEN_LOAD_DIR, True), (disabled_root, False)):
            if not os.path.isdir(root_dir):
                continue
            for dname in sorted(os.listdir(root_dir)):
                if dname in seen_ids or dname in (self.active_mod_name, "LunaKit", "Cheats"):
                    continue
                full_p = os.path.join(root_dir, dname)
                if not os.path.isdir(full_p):
                    continue
                seen_ids.add(dname)
                meta = meta_db.get(dname, {})
                packs.append({
                    "id": dname,
                    "gb_id": meta.get("gb_id", 0),
                    "name": meta.get("name", dname),
                    "author": meta.get("author", "Installed Community Pack"),
                    "category": meta.get("category", "Custom Mod Pack"),
                    "replaces": "LayeredFS RomFS/ExeFS",
                    "size_mb": 0,
                    "likes": meta.get("likes", 0),
                    "views": meta.get("views", 0),
                    "thumb": meta.get("thumb", ""),
                    "profile_url": meta.get("profile_url", f"https://gamebanana.com/mods/{meta.get('gb_id')}" if meta.get("gb_id") else ""),
                    "how_to_play": "Enabled in Eden LayeredFS load folder.",
                    "description": meta.get("description", f"Local mod pack installed at {dname}."),
                    "installed": True,
                    "enabled": is_act
                })

        return packs

    def search_gamebanana(self, query="", page=1):
        import urllib.request
        import urllib.parse
        q = (query or "").strip()
        url = f"https://gamebanana.com/apiv11/Game/6376/Subfeed?_nPage={int(page)}&_sSort=default"
        if q:
            url += f"&_sName={urllib.parse.quote(q)}"
        req = urllib.request.Request(url, headers={"User-Agent": "SwitchStudio/2.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        installed_map = {p["gb_id"]: p for p in self.get_community_packs() if p.get("gb_id")}
        meta_db = self._load_community_metadata()
        meta_changed = False
        results = []
        for rec in data.get("_aRecords", []):
            if rec.get("_sModelName") != "Mod":
                continue
            gb_id = rec.get("_idRow")
            name = rec.get("_sName", "Untitled Mod")
            sub = rec.get("_aSubmitter", {}).get("_sName", "GameBanana Creator")
            cat = rec.get("_aRootCategory", {}).get("_sName", "Mod")
            likes = rec.get("_nLikeCount", 0)
            views = rec.get("_nViewCount", 0)
            thumb = ""
            media = rec.get("_aPreviewMedia", {}).get("_aImages", [])
            if media:
                img0 = media[0]
                base = img0.get("_sBaseUrl", "")
                f530 = img0.get("_sFile530") or img0.get("_sFile220") or img0.get("_sFile", "")
                if base and f530:
                    thumb = f"{base}/{f530}"
            safe_id = "".join(ch for ch in name if ch.isalnum())[:28] or f"GBMod_{gb_id}"
            if safe_id not in meta_db or not meta_db[safe_id].get("thumb"):
                meta_db[safe_id] = {
                    "gb_id": gb_id,
                    "name": name,
                    "author": sub,
                    "category": cat,
                    "thumb": thumb,
                    "likes": likes,
                    "views": views,
                    "description": f"Community pack '{name}' by {sub}.",
                    "profile_url": rec.get("_sProfileUrl", f"https://gamebanana.com/mods/{gb_id}")
                }
                meta_changed = True
            existing = installed_map.get(gb_id)
            if existing:
                safe_id = existing["id"]
                is_inst = existing["installed"]
                is_en = existing["enabled"]
            else:
                is_en = os.path.isdir(os.path.join(EDEN_LOAD_DIR, safe_id))
                is_inst = is_en or os.path.isdir(os.path.join(self._eden_disabled_dir(), safe_id))

            results.append({
                "id": safe_id,
                "gb_id": gb_id,
                "name": name,
                "author": sub,
                "category": cat,
                "replaces": "Super Mario Odyssey",
                "size_mb": 0,
                "likes": likes,
                "views": views,
                "thumb": thumb,
                "profile_url": rec.get("_sProfileUrl", f"https://gamebanana.com/mods/{gb_id}"),
                "installed": is_inst,
                "enabled": is_en
            })
        if meta_changed:
            self._save_community_metadata(meta_db)
        return results

    def _disable_other_kingdom_packs(self, target_pack_id):
        """Automatically disables any other active community pack so texture packs, WorldList.szs, ShineInfo.szs, and exefs never conflict or overflow RAM."""
        disabled_names = []
        if not os.path.isdir(EDEN_LOAD_DIR):
            return disabled_names
        dis_root = self._eden_disabled_dir()
        for dname in sorted(os.listdir(EDEN_LOAD_DIR)):
            if dname in (target_pack_id, self.active_mod_name, "LunaKit", "Cheats"):
                continue
            src_p = os.path.join(EDEN_LOAD_DIR, dname)
            if not os.path.isdir(src_p):
                continue
            dst_p = os.path.join(dis_root, dname)
            if os.path.isdir(dst_p):
                shutil.rmtree(dst_p)
            shutil.move(src_p, dst_p)
            self._sync_pack_audio_and_exefs(dname, False)
            disabled_names.append(dname)
        return disabled_names

    def get_download_progress(self):
        return getattr(self, "_dl_progress", {"active": False, "pack_id": "", "downloaded_mb": 0.0, "total_mb": 0.0, "percent": 0, "stage": ""})

    def toggle_community_pack(self, pack_id, enabled):
        active_path = os.path.join(EDEN_LOAD_DIR, pack_id)
        dis_path = os.path.join(self._eden_disabled_dir(), pack_id)
        enabled = bool(enabled)

        if enabled:
            if os.path.isdir(dis_path) and not os.path.isdir(active_path):
                shutil.move(dis_path, active_path)
            elif not os.path.isdir(active_path):
                raise FileNotFoundError(f"Pack '{pack_id}' is not installed yet.")
            # Auto-disable all other active community packs so texture packs & 3D kingdoms never collide
            auto_off = self._disable_other_kingdom_packs(pack_id)
            self._sync_pack_audio_and_exefs(pack_id, True)
            extra_note = f" (Auto-disabled {', '.join(auto_off)})" if auto_off else ""
            return {"success": True, "id": pack_id, "enabled": True, "message": f"Enabled '{pack_id}' in Eden!{extra_note}"}
        else:
            if os.path.isdir(active_path):
                if os.path.isdir(dis_path):
                    shutil.rmtree(dis_path)
                shutil.move(active_path, dis_path)
            self._sync_pack_audio_and_exefs(pack_id, False)
            return {"success": True, "id": pack_id, "enabled": False, "message": f"Disabled '{pack_id}' — restored standard kingdom & audio."}

    def uninstall_community_pack(self, pack_id):
        """Cleanly uninstalls and deletes a community pack from Eden's active and disabled folders, removes synced audio/exefs, and purges its downloaded cache archive so the user can cleanly reinstall."""
        active_path = os.path.join(EDEN_LOAD_DIR, pack_id)
        dis_path = os.path.join(self._eden_disabled_dir(), pack_id)

        # 1. Sync pack audio and exefs off before removing files so originals are restored
        try:
            self._sync_pack_audio_and_exefs(pack_id, False)
        except Exception:
            pass

        # 2. Remove active and disabled directory
        if os.path.isdir(active_path):
            shutil.rmtree(active_path, ignore_errors=True)
        if os.path.isdir(dis_path):
            shutil.rmtree(dis_path, ignore_errors=True)

        # 3. Clean any pack backup directory in ClaraMarioReshaped/romfs/SoundData/_pack_backup
        clara_sd = os.path.join(EDEN_LOAD_DIR, self.active_mod_name, "romfs", "SoundData")
        bak_dir = os.path.join(clara_sd, "_pack_backup", pack_id)
        if os.path.isdir(bak_dir):
            shutil.rmtree(bak_dir, ignore_errors=True)

        # 4. Restore LunaKit to active if it was disabled by this pack's exefs
        lk_active = os.path.join(EDEN_LOAD_DIR, "LunaKit")
        lk_disabled = os.path.join(self._eden_disabled_dir(), "LunaKit")
        if os.path.isdir(lk_disabled) and not os.path.isdir(lk_active):
            try:
                shutil.move(lk_disabled, lk_active)
            except Exception:
                pass

        # 5. Clear cached zip / stage files in community_cache so fresh reinstall works
        cache_dir = self._community_cache_dir()
        if os.path.isdir(cache_dir):
            for f in os.listdir(cache_dir):
                fl = f.lower()
                pid_l = pack_id.lower()
                if pid_l in fl or f"_stage_{pack_id}" in f:
                    p = os.path.join(cache_dir, f)
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                    except Exception:
                        pass

        # 6. Clear any sdmc mod saves or cache (e.g. sdmc/smo/{pack_id})
        smo_sdmc = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "eden", "sdmc", "smo", pack_id)
        if os.path.isdir(smo_sdmc):
            shutil.rmtree(smo_sdmc, ignore_errors=True)

        # 7. If it's a custom GameBanana pack (not in CURATED_COMMUNITY_PACKS), remove from metadata DB
        is_curated = any(c["id"] == pack_id for c in self.CURATED_COMMUNITY_PACKS)
        if not is_curated:
            meta_db = self._load_community_metadata()
            if pack_id in meta_db:
                del meta_db[pack_id]
                self._save_community_metadata(meta_db)

        return {
            "success": True,
            "id": pack_id,
            "installed": False,
            "enabled": False,
            "message": f"Successfully uninstalled '{pack_id}' and cleared its cached files."
        }

    def install_community_pack(self, gb_id, pack_id=None):
        import urllib.request
        import zipfile
        import threading
        gb_id = int(gb_id)
        curated = next((c for c in self.CURATED_COMMUNITY_PACKS if c["gb_id"] == gb_id), None)
        if not pack_id:
            pack_id = curated["id"] if curated else f"GBMod_{gb_id}"

        # Prevent duplicate concurrent downloads of the same mod or multiple simultaneous downloads
        if not hasattr(self, "_active_downloads"):
            self._active_downloads = set()
            self._dl_lock = threading.Lock()

        dl_key = str(gb_id)
        with self._dl_lock:
            if dl_key in self._active_downloads or getattr(self, "_dl_progress", {}).get("active"):
                cur_name = getattr(self, "_dl_progress", {}).get("pack_id") or f"Mod #{gb_id}"
                return {
                    "success": False,
                    "error": f"A download is already in progress ({cur_name}). Please wait for it to finish before starting another!"
                }
            self._active_downloads.add(dl_key)

        try:
            # Check if already installed
            active_path = os.path.join(EDEN_LOAD_DIR, pack_id)
            dis_path = os.path.join(self._eden_disabled_dir(), pack_id)
            if os.path.isdir(active_path) or os.path.isdir(dis_path):
                return self.toggle_community_pack(pack_id, True)

            # Fetch download link from GameBanana ProfilePage API
            prof_url = f"https://gamebanana.com/apiv11/Mod/{gb_id}/ProfilePage"
            req = urllib.request.Request(prof_url, headers={"User-Agent": "SwitchStudio/2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                pdata = json.loads(resp.read().decode("utf-8"))

            # Save metadata for this pack so it renders with real name and thumbnail
            meta_db = self._load_community_metadata()
            imgs = pdata.get("_aPreviewMedia", {}).get("_aImages", [])
            m_thumb = ""
            if imgs:
                b = imgs[0].get("_sBaseUrl", "")
                f = imgs[0].get("_sFile530") or imgs[0].get("_sFile220") or imgs[0].get("_sFile", "")
                m_thumb = f"{b}/{f}" if b and f else ""
            meta_db[pack_id] = {
                "gb_id": gb_id,
                "name": pdata.get("_sName") or pack_id,
                "author": pdata.get("_aSubmitter", {}).get("_sName", "GameBanana Creator"),
                "category": pdata.get("_aRootCategory", {}).get("_sName", "Custom Mod"),
                "thumb": m_thumb,
                "likes": pdata.get("_nLikeCount", 0),
                "views": pdata.get("_nViewCount", 0),
                "description": (pdata.get("_sDescription") or f"Community pack '{pack_id}'.")[:120],
                "profile_url": pdata.get("_sProfileUrl", f"https://gamebanana.com/mods/{gb_id}")
            }
            self._save_community_metadata(meta_db)

            files = pdata.get("_aFiles", [])
            if not files:
                raise RuntimeError("No downloadable archive files found on this GameBanana mod page.")

            # Prefer emulator edition or .zip if multiple files exist
            chosen_file = files[0]
            for fobj in files:
                fname = (fobj.get("_sFile") or "").lower()
                desc = (fobj.get("_sDescription") or "").lower()
                if ("emulator" in fname or "emulator" in desc or "yuzu" in desc or "ryujinx" in desc) and fname.endswith(".zip"):
                    chosen_file = fobj
                    break
                if fname.endswith(".zip") and not (chosen_file.get("_sFile") or "").lower().endswith(".zip"):
                    chosen_file = fobj

            dl_url = chosen_file.get("_sDownloadUrl")
            fname = chosen_file.get("_sFile") or f"mod_{gb_id}.zip"
            expected_bytes = int(chosen_file.get("_nFilesize") or 0)
            archive_path = os.path.join(self._community_cache_dir(), fname)

            if not os.path.isfile(archive_path) or (expected_bytes > 0 and os.path.getsize(archive_path) < expected_bytes):
                dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "SwitchStudio/2.0"})
                with urllib.request.urlopen(dl_req, timeout=600) as r, open(archive_path, "wb") as out_f:
                    total_b = expected_bytes or int(r.headers.get("Content-Length") or 0)
                    got_b = 0
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        got_b += len(chunk)
                        pct = int(round((got_b / total_b) * 100)) if total_b > 0 else 0
                        self._dl_progress = {
                            "active": True,
                            "pack_id": pack_id,
                            "downloaded_mb": round(got_b / (1024 * 1024), 1),
                            "total_mb": round(total_b / (1024 * 1024), 1),
                            "percent": min(99, pct),
                            "stage": "downloading"
                        }

            self._dl_progress = {
                "active": True,
                "pack_id": pack_id,
                "downloaded_mb": round(os.path.getsize(archive_path) / (1024 * 1024), 1),
                "total_mb": round(os.path.getsize(archive_path) / (1024 * 1024), 1),
                "percent": 100,
                "stage": "extracting"
            }

            # Extract archive to temporary staging directory
            stage_dir = os.path.join(self._community_cache_dir(), f"_stage_{pack_id}")
            if os.path.isdir(stage_dir):
                shutil.rmtree(stage_dir)
            os.makedirs(stage_dir, exist_ok=True)

            lower_fn = fname.lower()
            if lower_fn.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(stage_dir)
            else:
                seven_z = r"C:\Program Files\7-Zip\7z.exe"
                if os.path.isfile(seven_z):
                    subprocess.run([seven_z, "x", archive_path, f"-o{stage_dir}", "-y"], check=True)
                else:
                    subprocess.run(["tar", "-xf", archive_path, "-C", stage_dir], check=True)

            # Locate romfs/exefs root inside stage_dir
            os.makedirs(active_path, exist_ok=True)
            found_root = None
            for root, dirs, _ in os.walk(stage_dir):
                dlow = {d.lower(): d for d in dirs}
                if "romfs" in dlow or "exefs" in dlow:
                    found_root = root
                    break
                if "objectdata" in dlow or "stagedata" in dlow or "sounddata" in dlow:
                    romfs_dst = os.path.join(active_path, "romfs")
                    os.makedirs(romfs_dst, exist_ok=True)
                    for item in os.listdir(root):
                        shutil.move(os.path.join(root, item), os.path.join(romfs_dst, item))
                    found_root = active_path
                    break

            if found_root and found_root != active_path:
                for item in os.listdir(found_root):
                    dst_item = os.path.join(active_path, item.lower() if item.lower() in ("romfs", "exefs") else item)
                    if os.path.exists(dst_item):
                        if os.path.isdir(dst_item):
                            shutil.rmtree(dst_item)
                        else:
                            os.remove(dst_item)
                    shutil.move(os.path.join(found_root, item), dst_item)

            shutil.rmtree(stage_dir, ignore_errors=True)

            self._dl_progress = {
                "active": True,
                "pack_id": pack_id,
                "downloaded_mb": round(os.path.getsize(archive_path) / (1024 * 1024), 1),
                "total_mb": round(os.path.getsize(archive_path) / (1024 * 1024), 1),
                "percent": 100,
                "stage": "normalizing"
            }

            # Normalize for Switch v1.0.0 & auto-disable other Community Packs
            self._normalize_pack_for_v100(active_path)
            auto_off = self._disable_other_kingdom_packs(pack_id)
            self._sync_pack_audio_and_exefs(pack_id, True)
            extra_note = f" (Auto-disabled {', '.join(auto_off)} so packs don't conflict)" if auto_off else ""

            return {
                "success": True,
                "id": pack_id,
                "gb_id": gb_id,
                "enabled": True,
                "installed": True,
                "message": f"Downloaded, normalized & activated '{pack_id}' in Eden!{extra_note}"
            }
        finally:
            with self._dl_lock:
                self._active_downloads.discard(dl_key)
            self._dl_progress = {"active": False, "pack_id": "", "downloaded_mb": 0.0, "total_mb": 0.0, "percent": 0, "stage": ""}

