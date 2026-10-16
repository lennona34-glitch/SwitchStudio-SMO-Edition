"""Real Mario geometry for the studio viewer.

Models are exported once from the game's BFRES files by toolbox/ExportModel.exe (positions, normals, UVs, triangles,
bone transforms, albedo textures), cached under cache/models/<version>/, and assembled the way the game does it:
face / eyes / hair+cap attach to the body skeleton's `Head` joint using InitPartsFixInfo*.byml from Mario.szs.
"""
import json
import math
import os
import subprocess
import threading

import numpy as np
import oead

CACHE_VERSION = "v1"

# viewer sets -> parts (part id, source archive, attach-info file inside Mario.szs, shapes to hide)
PARTS = {
    "body": dict(szs="Mario.szs", attach=None, hide=[]),
    "face": dict(szs="MarioFace.szs", attach="InitPartsFixInfoFace.byml", hide=[]),
    "eye": dict(szs="MarioEye.szs", attach="InitPartsFixInfoEye.byml", hide=[]),
    "head_cap": dict(szs="MarioHead.szs", attach="InitPartsFixInfoHead.byml", hide=["Hair__HairMT"]),
    "head_hair": dict(szs="MarioHead.szs", attach="InitPartsFixInfoHead.byml", hide=["Cap__CapMT", "CapHair__HairMT"]),
    "cap": dict(szs="MarioCap.szs", attach=None, hide=[]),
}
SETS = {
    "full": ["body", "face", "eye", "head_cap"],
    "full_nocap": ["body", "face", "eye", "head_hair"],
    "head": ["face", "eye", "head_cap"],
    "head_nocap": ["face", "eye", "head_hair"],
    "body": ["body"],
    "face": ["face", "eye"],
    "cap": ["cap"],
}
# archives that only supply textures
TEXTURE_ONLY = ["MarioHeadTexture.szs"]


class ModelView:
    def __init__(self, object_data_dir, toolbox_dir, texconv, cache_dir, texture_slots):
        self.obj = object_data_dir
        self.tb = toolbox_dir
        self.texconv = texconv
        self.root = os.path.join(cache_dir, "models", CACHE_VERSION)
        os.makedirs(self.root, exist_ok=True)
        # texture name -> slot id, for the textures the studio lets the user edit
        self.slot_by_texture = {info["texture"]: sid for sid, info in texture_slots.items()}
        self._export_cache = {}
        self._lock = threading.RLock()     # the server is multi-threaded; exports and the texture index must not race
        self.face_reshape = None      # set by the server; reshapes the face mesh to match a photo
        self.reshape_strength = 0.0
        self._tex_index = {}

    # ---------------------------------------------------------------- export ---------------------------------
    def _export(self, szs):
        with self._lock:
            return self._export_locked(szs)

    def _export_locked(self, szs):
        if szs in self._export_cache:
            return self._export_cache[szs]
        out = os.path.join(self.root, os.path.splitext(szs)[0])
        model_json = os.path.join(out, "model.json")
        if not os.path.isfile(model_json):
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(self.obj, szs), "rb") as f:
                sarc = oead.Sarc(bytes(oead.yaz0.decompress(f.read())))
            bfres = next((x for x in sarc.get_files() if x.name.endswith(".bfres")), None)
            if bfres is None:
                raise RuntimeError(f"no BFRES in {szs}")
            src = os.path.join(out, "src.bfres")
            with open(src, "wb") as f:
                f.write(bytes(bfres.data))
            r = subprocess.run([os.path.join(self.tb, "ExportModel.exe"), src, out, "-1"], cwd=self.tb,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if r.returncode != 0 or not os.path.isfile(model_json):
                raise RuntimeError(f"ExportModel failed for {szs}: {r.stderr[-300:]}")
            for fn in os.listdir(out):
                if fn.lower().endswith(".dds"):
                    subprocess.run([self.texconv, "-ft", "png", "-y", "-o", out, os.path.join(out, fn)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.remove(src)
        with open(model_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._export_cache[szs] = (data, out)
        return data, out

    def _all_archives(self):
        return sorted({p["szs"] for p in PARTS.values()} | set(TEXTURE_ONLY))

    def vanilla_texture_png(self, name):
        """Path of the vanilla albedo PNG for a texture name, searching every exported archive."""
        with self._lock:
            if not self._tex_index:
                index = {}
                for szs in self._all_archives():
                    try:
                        _, out = self._export(szs)
                    except Exception:
                        continue
                    for fn in os.listdir(out):
                        if fn.lower().endswith(".png"):
                            index.setdefault(os.path.splitext(fn)[0], os.path.join(out, fn))
                self._tex_index = index          # published only once complete
            return self._tex_index.get(name)

    # ---------------------------------------------------------------- assembly -------------------------------
    @staticmethod
    def _euler_zyx(rx, ry, rz):
        def Rx(a): c, s = math.cos(a), math.sin(a); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
        def Ry(a): c, s = math.cos(a), math.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        def Rz(a): c, s = math.cos(a), math.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        return Rz(rz) @ Ry(ry) @ Rx(rx)

    def _attach_matrix(self, attach_file):
        """4x4 matrix placing a part on its joint of the body skeleton, per the game's InitPartsFixInfo byml."""
        with open(os.path.join(self.obj, "Mario.szs"), "rb") as f:
            sarc = oead.Sarc(bytes(oead.yaz0.decompress(f.read())))
        info = next(x for x in sarc.get_files() if x.name == attach_file)
        y = oead.byml.from_binary(bytes(info.data))
        joint = y["JointName"]
        rot = y.get("LocalRotate", {"X": 0.0, "Y": 0.0, "Z": 0.0})
        body, _ = self._export("Mario.szs")
        bone = next(b for b in body["models"][0]["bones"] if b["name"] == joint)
        H = np.array(bone["world"], dtype=float).reshape(4, 4)
        R = self._euler_zyx(*(math.radians(float(rot[a])) for a in ("X", "Y", "Z")))
        M = H.copy()
        M[:3, :3] = H[:3, :3] @ R
        return M

    def _part_shapes(self, part_id):
        spec = PARTS[part_id]
        data, _ = self._export(spec["szs"])
        shapes = [s for s in data["models"][0]["shapes"] if s["name"] not in spec["hide"] and s["indices"]]
        M = self._attach_matrix(spec["attach"]) if spec["attach"] else None
        out = []
        for s in shapes:
            P = np.array(s["positions"], dtype=float).reshape(-1, 3)
            N = np.array(s["normals"], dtype=float).reshape(-1, 3)
            if part_id == "face" and s["name"].startswith("mario_tooth_up"):
                P[:, 2] += 0.6
            if (part_id == "face" and s["name"].startswith("face__FaceMT") and self.face_reshape is not None
                    and self.face_reshape.has_depth() and self.reshape_strength > 0):
                tris = np.array(s["indices"], dtype=np.int64).reshape(-1, 3)
                P, N, _ = self.face_reshape.reshape_shape(P, N, tris, self.reshape_strength)
            if M is not None:
                P = (M[:3, :3] @ P.T).T + M[:3, 3]
                N = (M[:3, :3] @ N.T).T
            out.append(dict(name=s["name"], albedo=s["albedo"], slot=self.slot_by_texture.get(s["albedo"]),
                            positions=np.round(P, 3).ravel().tolist(), normals=np.round(N, 3).ravel().tolist(),
                            uvs=s["uvs"], indices=s["indices"]))
        return out

    def scene(self, set_name="full"):
        if set_name not in SETS:
            raise KeyError(set_name)
        reshaping = (self.face_reshape is not None and self.face_reshape.has_depth() and self.reshape_strength > 0
                     and "face" in SETS[set_name])
        cache = os.path.join(self.root, f"scene_{set_name}.json")
        if not reshaping and os.path.isfile(cache):
            with open(cache, "r", encoding="utf-8") as f:
                return json.load(f)
        parts = []
        lo = np.array([1e9] * 3); hi = np.array([-1e9] * 3)
        for pid in SETS[set_name]:
            shapes = self._part_shapes(pid)
            for s in shapes:
                P = np.array(s["positions"]).reshape(-1, 3)
                lo = np.minimum(lo, P.min(axis=0)); hi = np.maximum(hi, P.max(axis=0))
            parts.append(dict(id=pid, shapes=shapes))
        scene = dict(set=set_name, parts=parts, bounds=dict(min=lo.tolist(), max=hi.tolist()))
        if not reshaping:
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(scene, f, separators=(",", ":"))
        return scene

    # ---------------------------------------------------------------- UV layout ------------------------------
    def uv_layout(self, texture_name):
        """Unique UV edges (flat [u0,v0,u1,v1,...]) of every mesh shape that samples `texture_name` as its albedo,
        plus per-shape UV bounds. Lets the 2D editor show where the model actually uses the texture."""
        edges = []
        regions = []
        for szs in sorted({p["szs"] for p in PARTS.values()}):
            data, _ = self._export(szs)
            for model in data["models"]:
                for s in model["shapes"]:
                    if s["albedo"] != texture_name or not s["indices"]:
                        continue
                    uv = s["uvs"]
                    idx = s["indices"]
                    seen = set()
                    for t in range(0, len(idx) - 2, 3):
                        a, b, c = idx[t], idx[t + 1], idx[t + 2]
                        for e0, e1 in ((a, b), (b, c), (c, a)):
                            k = (e0, e1) if e0 < e1 else (e1, e0)
                            if k in seen:
                                continue
                            seen.add(k)
                            edges.extend([round(uv[2 * e0], 4), round(uv[2 * e0 + 1], 4),
                                          round(uv[2 * e1], 4), round(uv[2 * e1 + 1], 4)])
                    us, vs = uv[0::2], uv[1::2]
                    regions.append(dict(shape=s["name"], u=[min(us), max(us)], v=[min(vs), max(vs)]))
        return dict(texture=texture_name, edges=edges, regions=regions)

    def face_front_uv_center(self):
        """UV centre of the front of the face mesh (nose, cheeks, forehead): where a portrait belongs on MarioFace_alb."""
        data, _ = self._export("MarioFace.szs")
        for s in data["models"][0]["shapes"]:
            if s["name"].startswith("face__FaceMT"):
                P = np.array(s["positions"]).reshape(-1, 3)
                UV = np.array(s["uvs"]).reshape(-1, 2)
                m = (P[:, 2] > 22.0) & (UV[:, 0] >= 0) & (UV[:, 0] <= 1) & (UV[:, 1] >= 0) & (UV[:, 1] <= 1)
                if m.any():
                    c = UV[m].mean(axis=0)
                    return float(c[0]), float(c[1])
        return None

    def face_geometry(self):
        """Raw (model-space) positions, normals, UVs and triangle indices of the front-of-face shape, for projecting a photo."""
        data, _ = self._export("MarioFace.szs")
        for sh in data["models"][0]["shapes"]:
            if sh["name"].startswith("face__FaceMT"):
                return (np.array(sh["positions"], dtype=np.float32).reshape(-1, 3),
                        np.array(sh["normals"], dtype=np.float32).reshape(-1, 3),
                        np.array(sh["uvs"], dtype=np.float32).reshape(-1, 2),
                        np.array(sh["indices"], dtype=np.int64).reshape(-1, 3))
        raise RuntimeError("face shape not found")
