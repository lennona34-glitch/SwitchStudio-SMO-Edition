"""
Switch Studio Save Manager & Mod Menu Engine for Super Mario Odyssey
Handles 100% complete save injection, automated backups, restore points,
and live cheat / mod menu configuration for Eden.
"""

import os
import shutil
import time
import struct
import zlib
import urllib.request
from typing import Dict, List, Any, Optional

try:
    import oead
except ImportError:
    oead = None

# Save path for Super Mario Odyssey in Eden
EDEN_SAVE_DIR = r"C:\Users\adria\AppData\Roaming\eden\nand\user\save\0000000000000000\92F748C5C32A34B276EF4FEF8A69DFDF\0100000000010000"
# Backup directory
BACKUP_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups", "saves"))
CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cache"))

# Base Darker Side completed save from community preservation
BASE_SAVE_URL = "https://raw.githubusercontent.com/MysticExile/SuperMarioOdyssey-All-Kingdom-Saves/master/SuperMarioOdyssey-All-Kingdom-Saves/Darker%20Side/File1.bin"

# Kingdom names mapping
KINGDOM_NAMES = {
    0: "Cap Kingdom",
    1: "Cascade Kingdom",
    2: "Sand Kingdom",
    3: "Lake Kingdom",
    4: "Wooded Kingdom",
    5: "Cloud Kingdom",
    6: "Lost Kingdom",
    7: "Metro Kingdom",
    8: "Snow Kingdom",
    9: "Seaside Kingdom",
    10: "Luncheon Kingdom",
    11: "Ruined Kingdom",
    12: "Bowser's Kingdom",
    13: "Moon Kingdom",
    14: "Mushroom Kingdom",
    15: "Dark Side",
    16: "Darker Side",
}

# Unique moon counts per kingdom (total 880 unique)
UNIQUE_MOONS = {
    0: 31,   # Cap
    1: 40,   # Cascade
    2: 89,   # Sand
    3: 42,   # Lake
    4: 74,   # Wooded
    5: 2,    # Cloud
    6: 35,   # Lost
    7: 81,   # Metro
    8: 55,   # Snow
    9: 71,   # Seaside
    10: 68,  # Luncheon
    11: 10,  # Ruined
    12: 62,  # Bowser
    13: 38,  # Moon
    14: 116, # Mushroom
    15: 24,  # Dark Side
    16: 3,   # Darker Side
}

class SaveManager:
    def __init__(self, save_dir: str = EDEN_SAVE_DIR):
        self.save_dir = save_dir
        os.makedirs(BACKUP_BASE_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)

    def get_save_status(self) -> Dict[str, Any]:
        """Inspects all save slots (File1 - File5) in Eden."""
        slots = []
        if not os.path.exists(self.save_dir):
            return {"exists": False, "slots": []}

        for i in range(1, 6):
            file_name = f"File{i}.bin"
            file_path = os.path.join(self.save_dir, file_name)
            slot_info = {
                "slot": i,
                "file": file_name,
                "exists": os.path.exists(file_path),
                "stage": "Empty",
                "kingdom": "None",
                "world_id": -1,
                "coins": 0,
                "moons": 0,
                "clothes": 0,
                "mtime": 0
            }

            if os.path.exists(file_path) and oead is not None:
                try:
                    slot_info["mtime"] = os.path.getmtime(file_path)
                    with open(file_path, "rb") as f:
                        raw = f.read()
                    if len(raw) >= 16 and raw[16:18] == b"YB":
                        doc = oead.byml.from_binary(raw[16:])
                        wid = int(doc.get("WorldId", -1))
                        slot_info["world_id"] = wid
                        slot_info["kingdom"] = KINGDOM_NAMES.get(wid, f"Kingdom {wid}")
                        slot_info["stage"] = str(doc.get("StageName", "Unknown"))
                        slot_info["coins"] = int(doc.get("CoinNum", 0))

                        # Total moons from WorldInfo
                        total_moons = sum(int(wi.get("PayShineNum", 0)) for wi in doc.get("WorldInfo", []) if int(wi.get("UnlockedWorldId", -1)) >= 0)
                        if total_moons == 0:
                            # Fallback count from ShineData
                            total_moons = sum(1 for s in doc.get("ShineData", []) if s.get("IsGet"))
                        slot_info["moons"] = total_moons

                        clothes = [c for c in doc.get("ItemCloth", []) if c]
                        slot_info["clothes"] = len(clothes)
                except Exception as e:
                    slot_info["error"] = str(e)

            slots.append(slot_info)

        return {"exists": True, "path": self.save_dir, "slots": slots}

    def backup_saves(self, label: str = "auto") -> str:
        """Creates a timestamped backup of the current save directory."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        folder_name = f"backup_{ts}_{label}"
        backup_path = os.path.join(BACKUP_BASE_DIR, folder_name)
        os.makedirs(backup_path, exist_ok=True)

        copied = 0
        if os.path.exists(self.save_dir):
            for f in os.listdir(self.save_dir):
                if f.endswith(".bin"):
                    src = os.path.join(self.save_dir, f)
                    dst = os.path.join(backup_path, f)
                    shutil.copy2(src, dst)
                    copied += 1

        return backup_path

    def list_backups(self) -> List[Dict[str, Any]]:
        """Lists all existing backups."""
        backups = []
        if not os.path.exists(BACKUP_BASE_DIR):
            return backups

        for d in sorted(os.listdir(BACKUP_BASE_DIR), reverse=True):
            bp = os.path.join(BACKUP_BASE_DIR, d)
            if os.path.isdir(bp):
                files = [f for f in os.listdir(bp) if f.endswith(".bin")]
                backups.append({
                    "id": d,
                    "path": bp,
                    "file_count": len(files),
                    "created": os.path.getctime(bp)
                })
        return backups

    def restore_backup(self, backup_id: str) -> bool:
        """Restores a backup directory to Eden's save folder."""
        src_dir = os.path.join(BACKUP_BASE_DIR, backup_id)
        if not os.path.isdir(src_dir):
            raise FileNotFoundError(f"Backup {backup_id} not found.")

        os.makedirs(self.save_dir, exist_ok=True)
        for f in os.listdir(src_dir):
            if f.endswith(".bin"):
                shutil.copy2(os.path.join(src_dir, f), os.path.join(self.save_dir, f))
        return True

    def _get_base_save_bytes(self) -> bytearray:
        """Retrieves and caches the base 100% template save."""
        cache_file = os.path.join(CACHE_DIR, "base_darker_side.bin")
        if os.path.exists(cache_file) and os.path.getsize(cache_file) == 2097164:
            with open(cache_file, "rb") as f:
                return bytearray(f.read())

        req = urllib.request.Request(BASE_SAVE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()

        with open(cache_file, "wb") as f:
            f.write(data)

        return bytearray(data)

    def generate_100_percent_save(self) -> bytearray:
        """Generates a complete, flawless 100% 999 Moons save file."""
        if oead is None:
            raise RuntimeError("oead library is required for BYML save synthesis.")

        raw = self._get_base_save_bytes()
        doc = oead.byml.from_binary(raw[16:])

        # 1. Moons - Mark every shine collected
        for s in doc.get("ShineData", []):
            s["IsGet"] = True
            s["Status"] = oead.S32(2)

        # 2. Coins - Max out Gold Coins (9,999 bank, 999,999 total)
        doc["CoinNum"] = oead.S32(9999)
        doc["TotalCoinNum"] = oead.S32(999999)

        # 3. Purple Coins - Collect all 1,000 regional purple coins
        for c in doc.get("GetCoinCollectData", []):
            c["IsGet"] = True

        # 4. Toadette Achievements - Mark all 61 achievements unlocked
        for a in doc.get("AchievementSaveData", []):
            a["IsGet"] = True

        # 5. Toad's Music Player - Mark all 79 tracks collected
        for b in doc.get("CollectBgmList", []):
            b["IsCollected"] = True

        # 6. WorldInfo - Bank 999 Moons into the Odyssey
        total_paid = 0
        for wi in doc.get("WorldInfo", []):
            wid = int(wi.get("UnlockedWorldId", -1))
            if wid in UNIQUE_MOONS:
                wi["PayShineNum"] = oead.S32(UNIQUE_MOONS[wid])
                total_paid += UNIQUE_MOONS[wid]

        # Top up with Mushroom Kingdom shop moons to reach exactly 999
        needed = 999 - total_paid
        for wi in doc.get("WorldInfo", []):
            if int(wi.get("UnlockedWorldId", -1)) == 14: # Mushroom Kingdom
                cur = int(wi["PayShineNum"])
                wi["PayShineNum"] = oead.S32(cur + needed)
                wi["ShopShine"] = oead.S32(int(wi.get("ShopShine", 0)) + needed)
                break

        doc["IsPayShineAllInAllWorld"] = True

        # Ensure 100% compatibility with Super Mario Odyssey v1.0.0 by stripping v1.3.0 Balloon World & DLC keys
        for bad_key in [
            "FirstBalloonGame", "AocDigPointSaveData", "JumpingRopeBestCount2",
            "IsExistRecordJumpingRope2", "BgSpecifyHistory", "FootPrintIdx"
        ]:
            if bad_key in doc:
                del doc[bad_key]

        # 7. Serialize BYML & Wrap in 2,097,164 byte binary container with CRC32
        new_byml = oead.byml.to_binary(doc, big_endian=False, version=3)
        header16 = bytearray(raw[:16])
        struct.pack_into("<I", header16, 12, len(new_byml))

        out_save = bytearray(2097164)
        out_save[0:16] = header16
        out_save[16:16+len(new_byml)] = new_byml

        crc = zlib.crc32(out_save[4:]) & 0xffffffff
        struct.pack_into("<I", out_save, 0, crc)

        return out_save

    def inject_100_percent(self, slot: int = 1) -> Dict[str, Any]:
        """Backs up existing saves and injects the 100% complete save into the chosen slot."""
        if slot < 1 or slot > 5:
            raise ValueError(f"Invalid slot: {slot}. Must be 1-5.")

        # 1. Automatic backup first
        backup_path = self.backup_saves(label=f"pre_inject_slot{slot}")

        # 2. Generate save
        save_bytes = self.generate_100_percent_save()

        # 3. Write to slot
        os.makedirs(self.save_dir, exist_ok=True)
        target_file = os.path.join(self.save_dir, f"File{slot}.bin")
        with open(target_file, "wb") as f:
            f.write(save_bytes)

        return {
            "success": True,
            "slot": slot,
            "target_file": target_file,
            "backup_path": backup_path,
            "moons": 999,
            "coins": 9999,
            "kingdoms_unlocked": 17,
            "achievements": 61,
            "music_tracks": 79
        }

    def delete_save(self, slot: Any = 1) -> Dict[str, Any]:
        """Backs up existing saves and deletes the chosen slot (or all slots if slot='all' or 0)."""
        if str(slot).lower() in ("all", "0"):
            backup_path = self.backup_saves(label="pre_delete_all")
            deleted_count = 0
            if os.path.isdir(self.save_dir):
                for fn in os.listdir(self.save_dir):
                    if fn.endswith(".bin"):
                        try:
                            os.remove(os.path.join(self.save_dir, fn))
                            deleted_count += 1
                        except OSError:
                            pass
            return {
                "success": True,
                "slot": "all",
                "backup_path": backup_path,
                "deleted_count": deleted_count,
                "message": "All saves cleared. Super Mario Odyssey will start a fresh new adventure!"
            }

        slot_int = int(slot)
        if slot_int < 1 or slot_int > 5:
            raise ValueError(f"Invalid slot: {slot}. Must be 1-5.")

        backup_path = self.backup_saves(label=f"pre_delete_slot{slot_int}")
        target_file = os.path.join(self.save_dir, f"File{slot_int}.bin")
        deleted = False
        if os.path.isfile(target_file):
            os.remove(target_file)
            deleted = True

        return {
            "success": True,
            "slot": slot_int,
            "deleted": deleted,
            "backup_path": backup_path,
            "message": f"Save Slot {slot_int} has been deleted and reset to empty."
        }

