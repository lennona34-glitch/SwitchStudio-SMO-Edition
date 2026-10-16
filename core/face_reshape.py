"""Reshape Mario's face towards the depth profile of a photographed face.

The browser's face detector gives roughly 3D landmarks. They are converted to Mario's model space (see the client code:
x/y in model units on the same layout the photo texture uses, depth relative to the eye line, towards the camera =
positive) and stored here. Mario's front-of-face vertices are then moved in depth (z only) part of the way towards the
photo's surface:

    delta_z = strength * weight(x, y) * (photo_surface(x, y) - mario_z)

weight tapers to 0 at the edge of the face outline (so the face still joins the head) and around the eye sockets and
mouth (so the eyeballs, teeth and tongue, which are separate meshes, still fit). Normals are recomputed for the affected
vertices. Everything depends only on position, so the same function reshapes the gameplay face and the cutscene face.
"""
import json
import os

import numpy as np
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import Delaunay

EYE_CENTRES = ((7.9, 17.1), (-7.9, 17.1))      # Mario's eyes in model units (pupil meshes span x 2.2..13.6, y 9..25)
EYE_RADII = (7.0, 9.5)
NOSE_CENTRE = (0.0, 8.5)                       # Mario's protruding 3D nose bulb (x -9.5..9.5, y 0..17, z 27..43)
NOSE_RADII = (9.5, 8.5)
MOUTH_CENTRE = (0.0, -4.0)                     # teeth span y -10.6..1.3, tongue -7.3..-2.5
MOUTH_RADII = (14.0, 8.0)
EDGE_FALLOFF = 16.0                            # model units over which the effect fades in from the face outline
MAX_DELTA = 8.0                                # clamp on the raw per-vertex offset (model units)
GAIN = 2.0                                     # strength 100% applies this multiple of the smoothed offset
SMOOTH_PASSES = 2                              # neighbour-averaging passes over the offset field


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _ellipse_clear(x, y, centre, radii, ramp=(1.0, 1.6)):
    """0 inside the ellipse, rising smoothly to 1 outside it."""
    r = np.sqrt(((x - centre[0]) / radii[0]) ** 2 + ((y - centre[1]) / radii[1]) ** 2)
    return _smoothstep((r - ramp[0]) / (ramp[1] - ramp[0]))


def _dist_to_polygon(pts, poly):
    """Distance from each point to the polygon's boundary."""
    a = poly
    b = np.roll(poly, -1, axis=0)
    ab = b - a
    best = np.full(len(pts), np.inf)
    for i in range(len(a)):
        ap = pts - a[i]
        t = np.clip((ap @ ab[i]) / max(float(ab[i] @ ab[i]), 1e-12), 0.0, 1.0)
        d = np.linalg.norm(ap - t[:, None] * ab[i], axis=1)
        best = np.minimum(best, d)
    return best


def _vertex_normals(P, tris):
    n = np.zeros_like(P)
    v0, v1, v2 = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)                      # area-weighted face normals
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    n[np.abs(P[:, 0]) < 0.05, 0] = 0.0                   # keep X=0 centerline normal seam-free
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.maximum(ln, 1e-12)


def pack_normal(n):
    """3 floats -> the low 30 bits of a 10_10_10_2 SNorm value."""
    q = np.clip(np.round(n * 511.0), -511, 511).astype(np.int64) & 0x3FF
    return int(q[0] | (q[1] << 10) | (q[2] << 20))


class FaceReshape:
    def __init__(self, model_view, cache_dir):
        self.mv = model_view
        self.path = os.path.join(cache_dir, "face_depth.json")
        self.points = None       # (N,3) model-space x, y, depth
        self.oval = None         # (M,2) face outline in model space
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.set_depth(d["points"], d["oval"], save=False)
        except (OSError, ValueError, KeyError):
            pass

    # ---------------------------------------------------------------- state ---------------------------------------
    def has_depth(self):
        return self.points is not None and len(self.points) > 20

    def signature(self):
        if not self.has_depth():
            return ""
        return "%d:%.3f" % (len(self.points), float(np.round(self.points[:, 2].sum(), 3)))

    def set_depth(self, flat_points, flat_oval, save=True):
        pts = np.asarray(flat_points, dtype=np.float64).reshape(-1, 3) if len(flat_points) else None
        self.points = pts
        self.oval = np.asarray(flat_oval, dtype=np.float64).reshape(-1, 2) if pts is not None else None
        if save:
            if pts is None:
                try:
                    os.remove(self.path)
                except OSError:
                    pass
            else:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump({"points": np.round(pts, 3).ravel().tolist(), "oval": np.round(self.oval, 3).ravel().tolist()}, f)
        self._interp = None

    # ---------------------------------------------------------------- field ---------------------------------------
    def _photo_depth(self, xy):
        if getattr(self, "_interp", None) is None:
            self._interp = LinearNDInterpolator(self.points[:, :2], self.points[:, 2])
        return self._interp(xy)

    @staticmethod
    def _smooth(dz, tris, weight):
        """Average each vertex's offset with its mesh neighbours so the landmark noise doesn't ripple the surface.
        Vertices with zero weight (outline, eye sockets, mouth) stay exactly where they are."""
        n = len(dz)
        a = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2], tris[:, 1], tris[:, 2], tris[:, 0]])
        b = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0], tris[:, 0], tris[:, 1], tris[:, 2]])
        cnt = np.bincount(a, minlength=n).astype(float)
        free = weight > 1e-6
        out = dz.copy()
        for _ in range(SMOOTH_PASSES):
            nb = np.bincount(a, weights=out[b], minlength=n) / np.maximum(cnt, 1.0)
            out = np.where(free, 0.4 * out + 0.6 * nb, out)
        return out

    def deltas(self, P, N, strength, tris=None):
        """Per-vertex z offsets (N,) for a face shape's positions P and normals N."""
        dz = np.zeros(len(P))
        if not self.has_depth() or strength <= 0:
            return dz
        xy = P[:, :2]
        inside = Delaunay(self.oval).find_simplex(xy) >= 0
        front = N[:, 2] > 0.1
        D = self._photo_depth(xy)
        ok = inside & front & ~np.isnan(D)
        if not ok.any():
            return dz
        dist = _dist_to_polygon(xy, self.oval)
        # calibrate: near the outline the reshaped surface must meet Mario's, so offset the photo's depth to match
        ring = ok & (dist > 1.5) & (dist < 8.0)
        sel = ring if ring.sum() >= 10 else ok
        c = float(np.median(P[sel, 2] - D[sel]))
        target = c + D
        w = _smoothstep(dist / EDGE_FALLOFF)
        w = w * _ellipse_clear(xy[:, 0], xy[:, 1], EYE_CENTRES[0], EYE_RADII)
        w = w * _ellipse_clear(xy[:, 0], xy[:, 1], EYE_CENTRES[1], EYE_RADII)
        w = w * _ellipse_clear(xy[:, 0], xy[:, 1], NOSE_CENTRE, NOSE_RADII)
        w = w * _ellipse_clear(xy[:, 0], xy[:, 1], MOUTH_CENTRE, MOUTH_RADII)
        raw = np.clip(target[ok] - P[ok, 2], -MAX_DELTA, MAX_DELTA)
        dz[ok] = w[ok] * raw
        if tris is not None:
            dz = self._smooth(dz, tris, w)
        return strength * GAIN * dz

    def reshape_shape(self, P, N, tris, strength):
        """Returns (new_positions, new_normals, changed_vertex_mask)."""
        dz = self.deltas(P, N, strength, tris)
        changed = np.abs(dz) > 1e-4
        if not changed.any():
            return P, N, changed
        P2 = P.copy()
        P2[:, 2] += dz
        old_n = _vertex_normals(P, tris)
        new_n = _vertex_normals(P2, tris)
        # vertices touching a changed one also get new normals so shading stays smooth across the boundary
        touched = changed.copy()
        for k in range(3):
            tri_changed = changed[tris].any(axis=1)
            touched[tris[tri_changed, k]] = True
        N2 = N.copy()
        v = N[touched] + (new_n[touched] - old_n[touched])
        N2[touched] = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
        return P2, N2, touched

    # ---------------------------------------------------------------- face shapes ---------------------------------
    def face_shape(self, szs):
        """(P, N, tris) of the face__FaceMT shape of a face archive, raw model space."""
        data, _ = self.mv._export(szs)
        for sh in data["models"][0]["shapes"]:
            if sh["name"].startswith("face__FaceMT"):
                return (np.array(sh["positions"], dtype=np.float64).reshape(-1, 3),
                        np.array(sh["normals"], dtype=np.float64).reshape(-1, 3),
                        np.array(sh["indices"], dtype=np.int64).reshape(-1, 3))
        raise RuntimeError("face shape not found in " + szs)

    def patch_text(self, szs, strength):
        """Input for toolbox/PatchVertices.exe: rewrite the changed vertices of this archive's face shape."""
        P, N, tris = self.face_shape(szs)
        P2, N2, touched = self.reshape_shape(P, N, tris, strength)
        moved = np.abs(P2[:, 2] - P[:, 2]) > 1e-4
        lines = ["face__FaceMT"]
        for i in np.nonzero(touched | moved)[0]:
            packed = pack_normal(N2[i]) if touched[i] else -1
            lines.append("%d %.5f %.5f %.5f %d" % (i, P2[i, 0], P2[i, 1], P2[i, 2], packed))
        return "\n".join(lines) + "\n", int(moved.sum())
