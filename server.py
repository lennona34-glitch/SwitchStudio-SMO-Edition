import os
import sys
import json
import mimetypes
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.engine import SwitchEngine, ROMFS_ROOT, TOOLBOX_DIR, TEXCONV, CACHE_DIR, TEXTURE_SLOTS
from core.model_view import ModelView
from core.face_reshape import FaceReshape
from core.save_manager import SaveManager

engine = SwitchEngine()
save_manager = SaveManager()
model_view = ModelView(os.path.join(ROMFS_ROOT, "ObjectData"), TOOLBOX_DIR, TEXCONV, CACHE_DIR, TEXTURE_SLOTS)
engine.model_view = model_view
face_reshape = FaceReshape(model_view, CACHE_DIR)
engine.face_reshape = face_reshape
model_view.face_reshape = face_reshape
model_view.reshape_strength = float(engine.settings.get("reshape_strength", 0.0))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

def pick_windows_folder():
    """Opens a native Windows Folder Browser dialog."""
    ps_cmd = (
        "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
        "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$f.Description = 'Select Music Folder (.mp3, .wav, .flac, etc.)'; "
        "$f.ShowNewFolderButton = $false; "
        "$top = New-Object System.Windows.Forms.Form; "
        "$top.TopMost = $true; "
        "if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { "
        "  Write-Output $f.SelectedPath "
        "}"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if res.returncode == 0:
            p = res.stdout.strip()
            if p and os.path.isdir(p):
                return p
    except Exception as e:
        print(f"Error picking folder: {e}")
    return None

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class StudioRequestHandler(BaseHTTPRequestHandler):
    def send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file_response(self, file_path, content_type=None):
        if not os.path.isfile(file_path):
            self.send_error(404, "File not found")
            return
        if not content_type:
            content_type, _ = mimetypes.guess_type(file_path)
            if not content_type:
                content_type = "application/octet-stream"
                
        length = os.path.getsize(file_path)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            with open(file_path, "rb") as f:
                shutil_copy(f, self.wfile)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # API Routes
        if path == "/api/status":
            self.send_json(engine.get_status())
            return
        elif path == "/api/textures":
            self.send_json(engine.get_texture_slots())
            return
        elif path == "/api/texture/preview":
            slot = query.get("slot", [None])[0]
            req_type = query.get("type", ["orig"])[0]
            is_mod = (req_type == "mod")
            img_path = engine.get_texture_png(slot, modded=is_mod)
            if img_path and os.path.isfile(img_path):
                self.send_file_response(img_path, "image/png")
            else:
                self.send_error(404, "Texture preview not available")
            return
        elif path == "/api/settings":
            self.send_json(dict(engine.settings, has_face_depth=face_reshape.has_depth()))
            return
        elif path == "/api/model/scene":
            try:
                self.send_json(model_view.scene(query.get("set", ["full"])[0]))
            except KeyError:
                self.send_json({"error": "unknown model set"}, code=404)
            except Exception as e:
                self.send_json({"error": str(e)}, code=500)
            return
        elif path == "/api/model/texture":
            name = query.get("name", [""])[0]
            as_mod = query.get("type", ["mod"])[0] == "mod"
            slot = model_view.slot_by_texture.get(name)
            img_path = engine.get_texture_png(slot, modded=as_mod) if slot else model_view.vanilla_texture_png(name)
            if img_path and os.path.isfile(img_path):
                self.send_file_response(img_path, "image/png")
            else:
                self.send_error(404, "Texture not available")
            return
        elif path == "/api/model/face_reference":
            try:
                self.send_json(engine.face_reference_color())
            except Exception as e:
                self.send_json({"error": str(e)}, code=500)
            return
        elif path == "/api/model/face_point":
            try:
                pt = engine.face_point_at_uv(float(query.get("u", ["0"])[0]), float(query.get("v", ["0"])[0]))
                self.send_json({"x": pt[0], "y": pt[1]} if pt else {"error": "not on the front of the face"},
                               code=200 if pt else 404)
            except Exception as e:
                self.send_json({"error": str(e)}, code=500)
            return
        elif path == "/api/model/uv":
            slot = query.get("slot", [None])[0]
            if slot not in TEXTURE_SLOTS:
                self.send_json({"error": "unknown slot"}, code=404)
                return
            try:
                data = model_view.uv_layout(TEXTURE_SLOTS[slot]["texture"])
                data["composite_center"] = list(engine.composite_base_center(slot))
                if slot == "mario_face":
                    c = model_view.face_front_uv_center()
                    data["suggested_center"] = list(c) if c else None
                self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)}, code=500)
            return
        elif path == "/api/audio/list":
            self.send_json(engine.list_bgm_tracks())
            return
        elif path == "/api/audio/play":
            track = query.get("track", [None])[0]
            if not track:
                self.send_error(400, "Missing track parameter")
                return
            try:
                wav_path = engine.get_track_wav(track)
                if wav_path and os.path.isfile(wav_path):
                    self.send_file_response(wav_path, "audio/wav")
                else:
                    self.send_error(404, "Audio file not found")
            except Exception as e:
                self.send_json({"error": str(e)}, code=500)
            return
        elif path == "/api/sfx/list":
            self.send_json(engine.list_sfx_tracks())
            return
        elif path == "/api/sfx/play":
            track = query.get("track", [None])[0]
            if not track:
                self.send_error(400, "Missing track parameter")
                return
            try:
                wav_path = engine.get_sfx_wav(track)
                if wav_path and os.path.isfile(wav_path):
                    self.send_file_response(wav_path, "audio/wav")
                else:
                    self.send_error(404, "SFX audio file not found")
            except Exception as e:
                self.send_json({"error": str(e)}, code=500)
            return

        elif path == "/api/utils/pick_folder":
            try:
                selected_dir = pick_windows_folder()
                if selected_dir:
                    self.send_json({"success": True, "path": selected_dir})
                else:
                    self.send_json({"success": False, "cancelled": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/saves":
            try:
                status = save_manager.get_save_status()
                backups = save_manager.list_backups()
                self.send_json({"success": True, "status": status, "backups": backups})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/mods":
            try:
                lunakit_exefs = r"C:\Users\adria\AppData\Roaming\eden\load\0100000000010000\LunaKit\exefs\subsdk9"
                ysk_exefs = r"C:\Users\adria\AppData\Roaming\eden\load\0100000000010000\YoshiStarKingdom\exefs\subsdk9"
                cheats_file = r"C:\Users\adria\AppData\Roaming\eden\load\0100000000010000\Cheats\cheats\3CA12DFAAF9C82DA.txt"
                self.send_json({
                    "success": True,
                    "lunakit": {
                        "installed": os.path.isfile(lunakit_exefs) or os.path.isfile(ysk_exefs),
                        "version": "v1.4.3",
                        "menu_hotkey": "ZR + R + L",
                        "controller_hotkey": "ZR + R + ZL",
                        "hide_hotkey": "Left Stick Click (L3)",
                        "mouse_supported": True
                    },
                    "cheats": {
                        "installed": os.path.isfile(cheats_file),
                        "file": cheats_file,
                        "codes": [
                            "Infinite Health (Always 3/6 HP)",
                            "9999 Gold Coins",
                            "Max Purple Coins (All Kingdoms)",
                            "Thrown Cappy 999,999 times",
                            "Jumped 999,999 times",
                            "Instant Respawn on L3 Click"
                        ]
                    }
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/mario/scale":
            try:
                self.send_json(engine.get_mario_scale_state())
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/community/list":
            try:
                self.send_json({"success": True, "packs": engine.get_community_packs()})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/community/search":
            try:
                q = query.get("q", [""])[0]
                page = int(query.get("page", ["1"])[0])
                results = engine.search_gamebanana(query=q, page=page)
                self.send_json({"success": True, "results": results})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/community/progress":
            self.send_json(engine.get_download_progress())
            return

        # Static Assets
        if path == "/" or path == "":
            file_path = os.path.join(STATIC_DIR, "index.html")
        else:
            rel = path.lstrip("/")
            file_path = os.path.join(STATIC_DIR, rel)

        if os.path.isfile(file_path):
            self.send_file_response(file_path)
        else:
            self.send_error(404, "Static file not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""

        if path == "/api/texture/recolor":
            req = json.loads(body.decode("utf-8"))
            slot = req.get("slot")
            hue = float(req.get("hue", 0))
            sat = float(req.get("saturation", 1.0))
            val = float(req.get("brightness", 1.0))
            inv = bool(req.get("invert", False))
            res = engine.apply_color_transform(slot, hue_shift=hue, sat_mult=sat, val_mult=val, invert=inv)
            self.send_json({"success": res is not None, "slot": slot})
            return

        elif path == "/api/texture/composite":
            # Handles multipart or json base64
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" in content_type:
                # Parse boundary
                boundary = content_type.split("boundary=")[1].encode("utf-8")
                parts = body.split(b"--" + boundary)
                fields = {}
                file_bytes = None
                for part in parts:
                    if b"Content-Disposition" in part:
                        headers_blob, part_body = part.split(b"\r\n\r\n", 1)
                        part_body = part_body.rstrip(b"\r\n")
                        headers_str = headers_blob.decode("latin1")
                        if 'name="file"' in headers_str:
                            file_bytes = part_body
                        elif 'name="slot"' in headers_str:
                            fields["slot"] = part_body.decode("utf-8")
                        elif 'name="scale"' in headers_str:
                            fields["scale"] = float(part_body.decode("utf-8"))
                        elif 'name="offset_x"' in headers_str:
                            fields["offset_x"] = float(part_body.decode("utf-8"))
                        elif 'name="offset_y"' in headers_str:
                            fields["offset_y"] = float(part_body.decode("utf-8"))
                        elif 'name="feather"' in headers_str:
                            fields["feather"] = int(float(part_body.decode("utf-8")))
                        elif 'name="opacity"' in headers_str:
                            fields["opacity"] = float(part_body.decode("utf-8"))
                        elif 'name="rotation"' in headers_str:
                            fields["rotation"] = float(part_body.decode("utf-8"))
                        elif 'name="mode"' in headers_str:
                            fields["mode"] = part_body.decode("utf-8")

                slot = fields.get("slot")
                if slot == "mario_face" and file_bytes and fields.get("mode") == "project":
                    res = engine.apply_projected_face(
                        slot,
                        file_bytes,
                        scale=fields.get("scale", 1.0),
                        offset_x=fields.get("offset_x", 0),
                        offset_y=fields.get("offset_y", 0),
                        rotation=fields.get("rotation", 0.0),
                        feather=fields.get("feather", 8),
                        opacity=fields.get("opacity", 1.0)
                    )
                    self.send_json({"success": res is not None, "slot": slot})
                    return
                elif slot and file_bytes:
                    res = engine.apply_composite_face(
                        slot,
                        file_bytes,
                        scale=fields.get("scale", 1.0),
                        offset_x=fields.get("offset_x", 0),
                        offset_y=fields.get("offset_y", 0),
                        feather=fields.get("feather", 8),
                        opacity=fields.get("opacity", 1.0)
                    )
                    self.send_json({"success": res is not None, "slot": slot})
                    return
                else:
                    self.send_json({"error": "Missing slot or image data"}, code=400)
                    return
            else:
                self.send_json({"error": "Unsupported Content-Type"}, code=400)
                return

        elif path == "/api/texture/commit":
            req = json.loads(body.decode("utf-8"))
            slot = req.get("slot")
            try:
                engine.commit_texture_to_model(slot)
                self.send_json({"success": True, "message": f"Injected into BFRES and repacked into SZS successfully for {slot}"})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/settings":
            try:
                req = json.loads(body.decode("utf-8"))
                for k, v in req.items():
                    engine.set_setting(k, v)
                model_view.reshape_strength = float(engine.settings.get("reshape_strength", 0.0))
                self.send_json(dict(engine.settings, has_face_depth=face_reshape.has_depth()))
            except KeyError as e:
                self.send_json({"error": f"unknown setting {e}"}, code=400)
            return

        elif path == "/api/face/depth":
            try:
                req = json.loads(body.decode("utf-8"))
                face_reshape.set_depth(req.get("points", []), req.get("oval", []))
                self.send_json({"has_face_depth": face_reshape.has_depth()})
            except Exception as e:
                self.send_json({"error": str(e)}, code=400)
            return

        elif path == "/api/texture/reset":
            try:
                req = json.loads(body.decode("utf-8"))
                saved = engine.reset_slot(req.get("slot"))
                self.send_json({"success": True, "backup": saved})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=400)
            return

        elif path == "/api/texture/commit_all":
            try:
                results = engine.commit_all_edited()
                self.send_json({"success": bool(results) and all(r["ok"] for r in results), "results": results})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/texture/apply_preset":
            req = json.loads(body.decode("utf-8"))
            preset = req.get("preset")
            
            if preset == "emerald_outlaw":
                # Recolor body & cap
                engine.apply_color_transform("mario_body", hue_shift=120, sat_mult=1.3, val_mult=0.9)
                engine.apply_color_transform("mario_cap", hue_shift=120, sat_mult=1.3, val_mult=0.9)
                engine.commit_texture_to_model("mario_body")
                engine.commit_texture_to_model("mario_cap")
                self.send_json({"success": True, "preset": preset, "message": "Emerald Outlaw Preset deployed to models!"})
                return

            self.send_json({"error": f"Unknown preset: {preset}"}, code=400)
            return

        elif path == "/api/audio/scan_directory":
            req = json.loads(body.decode("utf-8")) if body else {}
            folder_path = req.get("path", "").strip()
            if not folder_path:
                # Default to user's Music directory
                folder_path = os.path.expanduser(r"~\Music")
            try:
                tracks = engine.scan_music_directory(folder_path)
                self.send_json({"success": True, "path": folder_path, "count": len(tracks), "tracks": tracks})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/audio/batch_replace":
            req = json.loads(body.decode("utf-8")) if body else {}
            folder_path = req.get("path", "").strip()
            shuffle = bool(req.get("shuffle", True))
            max_tracks = req.get("max_tracks", None)
            if max_tracks is not None:
                max_tracks = int(max_tracks)
            if not folder_path:
                folder_path = os.path.expanduser(r"~\Music")
            try:
                res = engine.batch_replace_music(dir_path=folder_path, shuffle=shuffle, max_tracks=max_tracks)
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/audio/reset":
            try:
                res = engine.reset_audio()
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/audio/upload_batch":
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" in content_type:
                raw_b = content_type.split("boundary=")[1].strip('"\'; ')
                boundary = raw_b.encode("utf-8")
                parts = body.split(b"--" + boundary)
                uploaded_files = []
                upload_dir = os.path.join(CACHE_DIR, "jukebox_uploads")
                os.makedirs(upload_dir, exist_ok=True)
                
                max_tracks = 50
                for idx, part in enumerate(parts):
                    if b'name="max_tracks"' in part:
                        try:
                            _, val = part.split(b"\r\n\r\n", 1)
                            max_tracks = int(val.strip())
                        except Exception:
                            pass
                    elif b"Content-Disposition" in part and b'filename="' in part:
                        try:
                            headers_blob, part_body = part.split(b"\r\n\r\n", 1)
                            part_body = part_body.rstrip(b"\r\n")
                            headers_str = headers_blob.decode("latin1")
                            import re
                            fn_match = re.search(r'filename="([^"]+)"', headers_str)
                            fname = fn_match.group(1) if fn_match else f"upload_{idx}.mp3"
                            save_path = os.path.join(upload_dir, fname)
                            with open(save_path, "wb") as f_out:
                                f_out.write(part_body)
                            uploaded_files.append({
                                "name": fname,
                                "path": save_path,
                                "size_mb": round(len(part_body) / (1024 * 1024), 2)
                            })
                        except Exception as p_err:
                            print(f"Error parsing part {idx}: {p_err}")

                if uploaded_files:
                    try:
                        res = engine.batch_replace_music(file_list=uploaded_files, shuffle=True, max_tracks=max_tracks)
                        self.send_json(res)
                    except Exception as e:
                        self.send_json({"success": False, "error": str(e)}, code=500)
                else:
                    self.send_json({"success": False, "message": "No valid audio files found in upload"}, code=400)
            return

        elif path == "/api/audio/replace":
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" in content_type:
                boundary = content_type.split("boundary=")[1].encode("utf-8")
                parts = body.split(b"--" + boundary)
                track_name = None
                file_bytes = None
                for part in parts:
                    if b"Content-Disposition" in part:
                        headers_blob, part_body = part.split(b"\r\n\r\n", 1)
                        part_body = part_body.rstrip(b"\r\n")
                        headers_str = headers_blob.decode("latin1")
                        if 'name="track"' in headers_str:
                            track_name = part_body.decode("utf-8")
                        elif 'name="file"' in headers_str:
                            file_bytes = part_body
                if track_name and file_bytes:
                    try:
                        dest = engine.replace_bgm_track(track_name, file_bytes)
                        self.send_json({"success": True, "message": f"Replaced {track_name} and deployed to Eden!", "path": dest})
                    except Exception as e:
                        self.send_json({"success": False, "error": str(e)}, code=500)
                else:
                    self.send_json({"error": "Missing track name or audio file"}, code=400)
            return

        elif path == "/api/sfx/replace":
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" in content_type:
                boundary = content_type.split("boundary=")[1].encode("utf-8")
                parts = body.split(b"--" + boundary)
                track_name = None
                file_bytes = None
                for part in parts:
                    if b"Content-Disposition" in part:
                        headers_blob, part_body = part.split(b"\r\n\r\n", 1)
                        part_body = part_body.rstrip(b"\r\n")
                        headers_str = headers_blob.decode("latin1")
                        if 'name="track"' in headers_str:
                            track_name = part_body.decode("utf-8")
                        elif 'name="file"' in headers_str:
                            file_bytes = part_body
                if track_name and file_bytes:
                    try:
                        dest = engine.replace_sfx_track(track_name, file_bytes)
                        self.send_json({"success": True, "message": f"Replaced SFX {track_name} and deployed to Eden!", "path": dest})
                    except Exception as e:
                        self.send_json({"success": False, "error": str(e)}, code=500)
                else:
                    self.send_json({"error": "Missing track name or audio file"}, code=400)
            return

        elif path == "/api/launch_eden":
            try:
                engine.launch_eden()
                self.send_json({"success": True, "message": "Eden Emulator launched with Super Mario Odyssey!"})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/saves/inject":
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
                slot = int(req.get("slot", 1))
                res = save_manager.inject_100_percent(slot=slot)
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/saves/backup":
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
                label = req.get("label", "manual")
                bp = save_manager.backup_saves(label=label)
                self.send_json({"success": True, "backup_path": bp})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/saves/restore":
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
                backup_id = req.get("backup_id")
                if not backup_id:
                    self.send_json({"success": False, "error": "Missing backup_id"}, code=400)
                    return
                ok = save_manager.restore_backup(backup_id)
                self.send_json({"success": ok, "message": f"Restored backup {backup_id}!"})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/saves/delete":
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
                slot = req.get("slot", 1)
                res = save_manager.delete_save(slot=slot)
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/mario/scale":
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
                res = engine.apply_mario_scale(
                    preset=req.get("preset"),
                    body_scale=req.get("body_scale"),
                    head_mult=req.get("head_mult")
                )
                self.send_json(res)
            except PermissionError:
                self.send_json({"success": False, "error": "Eden has Mario.szs open — close Eden briefly to apply the new Mario size, then relaunch!"}, code=500)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/community/toggle":
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
                pack_id = req.get("id")
                enabled = bool(req.get("enabled", True))
                res = engine.toggle_community_pack(pack_id, enabled)
                self.send_json(res)
            except PermissionError:
                self.send_json({"success": False, "error": "Eden is currently running and locking this pack's files — close Eden first, toggle the pack, then click Launch in Eden!"}, code=500)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/community/install":
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
                gb_id = req.get("gb_id")
                pack_id = req.get("id")
                res = engine.install_community_pack(gb_id, pack_id=pack_id)
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        elif path == "/api/community/uninstall":
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
                pack_id = req.get("id")
                if not pack_id:
                    raise ValueError("No pack id specified")
                res = engine.uninstall_community_pack(pack_id)
                self.send_json(res)
            except PermissionError:
                self.send_json({"success": False, "error": "Eden is currently running and locking this pack's files — close Eden first before uninstalling!"}, code=500)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
            return

        self.send_error(404, "Unknown API POST endpoint")

def shutil_copy(f_src, f_dst):
    buf_size = 64 * 1024
    while True:
        buf = f_src.read(buf_size)
        if not buf:
            break
        f_dst.write(buf)

def start_server(port=5050):
    server_address = ("127.0.0.1", port)
    httpd = ThreadedHTTPServer(server_address, StudioRequestHandler)
    print(f"==================================================")
    print(f"  SWITCH STUDIO // SUPER MARIO ODYSSEY EDITOR    ")
    print(f"  Active on: http://localhost:{port}              ")
    print(f"==================================================")
    httpd.serve_forever()

if __name__ == "__main__":
    port = 5050
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    start_server(port)
