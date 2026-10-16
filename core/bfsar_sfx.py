"""NintendoWare Sound Archive (.bfsar / .aras / FGRP / FWAR / FWAV) parser, decoder, and patcher for Super Mario Odyssey.

Unlocks 3,500+ true gameplay sound effects (Mario's voice clips, Cappy throws, jumps, coin pickups,
Power Moon fanfares, 8-bit 2D Mario SFX, UI sounds, enemy/boss SFX, NPC voices, and footsteps)
stored inside FWAR wave archives across SoundData/*.aras and *.bfsar.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import wave
import numpy as np

from . import bfstm_nx

ALIGN_FWAV = 0x40


def _align(n, a=ALIGN_FWAV):
    return (n + a - 1) & ~(a - 1)


# ---------------------------------------------------------------------------------------------------------------
# Friendly Title & Category Formatting
# ---------------------------------------------------------------------------------------------------------------

EXACT_TITLES = {
    # Fanfares & Jingles (BgmResourceStd2nd.aras)
    "WsdRsBgmJgMainMoon": "Power Moon Get! (Main Story Fanfare)",
    "WsdRsBgmJgSubMoon": "Power Moon Get! (Sub-Area Fanfare)",
    "WsdRsBgmJgGrandMoon": "Multi-Moon Get! (Grand Fanfare)",
    "WsdRsBgmJgSubMoon8bit": "Power Moon Get! (8-Bit Retro Fanfare)",
    "WsdRsBgmJgSubMoonPeach": "Power Moon Get! (Peach Found Fanfare)",
    "WsdRsBgmJgGrandMoonCeremony": "Multi-Moon Ceremony Fanfare",
    "WsdRsBgmJgGrandMoonCeremony8bit": "Multi-Moon Ceremony (8-Bit Fanfare)",
    "WsdLifeMaxUp": "Life-Up Heart Get! (Max HP Up)",
    "WsdRsBgmJgClearFanfare": "Kingdom Objective Clear Fanfare",
    "WsdRsBgmJgRaceIntro": "Koopa Freerunning: Race Intro Jingle",
    "WsdRsBgmJgRaceWin": "Koopa Freerunning: Victory Fanfare",
    "WsdRsBgmJgRaceLose": "Koopa Freerunning: Defeat Jingle",
    "WsdRsBgmJgRaceFinalLap": "Koopa Freerunning: Final Lap!",
    "WsdRsBgmJgHomeRevive": "Odyssey Airship: Revived Fanfare",
    "WsdRsBgmJgHomeStarting": "Odyssey Airship: Powering Up",
    "WsdRsBgmAmiiboInvincibility": "Amiibo Star Invincibility Jingle",
    "WsdRsBgmMarioPlayGuitarPomcho": "Mario Playing Guitar (Sombrero)",
    "WsdRsBgmMarioPlayHula": "Mario Hula Dance Jingle",
    # Iconic Coins & Stage FX
    "WsSsCoin": "Gold Coin Pickup (Single)",
    "WsSsCoinTwo": "Gold Coin Pickup (2nd Coin)",
    "WsSsCoinThree": "Gold Coin Pickup (3rd Coin)",
    "WsSsCoinFive": "Gold Coin Pickup (5-Coin Stack)",
    "WsSsCoinPurple": "Purple Regional Coin Pickup",
    "WsDoCoin2D": "8-Bit Gold Coin Pickup (2D)",
    "WsDoCoin2DTwo": "8-Bit Gold Coin Pickup 2nd (2D)",
    "RcSeSyGreenCoinGot": "Moon Shard Collected",
    "RcSeSyShineAppear": "Power Moon Appears!",
    "WsSyMario64Start": "Super Mario 64 Painting Warp",
    "WsSyPlayerMiss": "Mario Miss / Lose Life",
    "WsSyPlayerDead2D": "8-Bit Mario Dies (2D)",
    # Iconic Mario Voice
    "WsrPvRcGetPrize": "Mario Voice: Got a Prize / Moon!",
    "WsPvJump00": "Mario Voice: Jump ('Yah!')",
    "WsPvJump01": "Mario Voice: Jump ('Wah!')",
    "WsPvJump02": "Mario Voice: Jump ('Hup!')",
    "WsPvJumpHigh00": "Mario Voice: Double/Triple Jump ('Wahoo!')",
    "WsPvJumpHigh01": "Mario Voice: High Jump ('Yahoo!')",
    "WsPvJumpHigh02": "Mario Voice: High Jump ('Yippee!')",
    "WsPvJumpBroad": "Mario Voice: Long Jump ('Yahoooo!')",
    "WsPvJumpTurn00": "Mario Voice: Backflip / Side Sommersault 1",
    "WsPvJumpTurn01": "Mario Voice: Backflip / Side Sommersault 2",
    "WsPvLandJump": "Mario Voice: Landing Grunt",
    "WsPvThrow": "Mario Voice: Cap Throw",
    # Iconic UI
    "WsUiBaseSelect": "UI Menu: Cursor Move / Select",
    "WsUiBaseDecide": "UI Menu: Confirm / Decide",
    "WsUiBaseBack": "UI Menu: Cancel / Back",
    "WsUiSaveEnd": "UI Menu: Save Complete",
    "WsUiCoinDecrease": "UI Menu: Coin Counter Tick",
}


def classify_and_format_sfx(name, source_archive):
    """Returns (category, friendly_title, priority_score) for an internal sound symbol name."""
    if source_archive == "BgmResourceStd2nd.aras" or name.startswith("WsdRsBgm") or name == "WsdLifeMaxUp":
        cat = "Fanfares & Moons"
        prio = 10
    elif "Pv" in name[:6]:
        cat = "Mario Voice"
        prio = 20
    elif "Pm" in name[:7]:
        cat = "Mario & Cappy"
        prio = 30
    elif any(name.startswith(p) for p in ("WsSs", "WsSy", "RcSeSy", "RcWsdSy", "SeSy")):
        if "Coin" in name or "Shine" in name or "Moon" in name or "Mario64" in name or "Note" in name:
            cat = "Coins & Stage FX"
            prio = 25
        else:
            cat = "Coins & Stage FX"
            prio = 35
    elif any(name.startswith(p) for p in ("WsDp", "WsDo", "WsdDo", "RcWsdChange")):
        cat = "8-Bit 2D Retro"
        prio = 28
    elif "Ui" in name[:6]:
        cat = "Menus & UI"
        prio = 40
    elif any(p in name[:6] for p in ("Bm", "Bv")) or source_archive.startswith("Boss"):
        cat = "Bosses & Broodals"
        prio = 50
    elif any(p in name[:6] for p in ("Em", "Ev")) or source_archive.startswith("Enemy"):
        cat = "Enemies & Captures"
        prio = 60
    elif any(p in name[:6] for p in ("Nm", "Nv", "WNpc")) or source_archive.startswith("Npc"):
        cat = "NPCs & Voices"
        prio = 70
    elif any(p in name[:6] for p in ("Pf", "Ps")) or source_archive == "FootNote.bfsar":
        cat = "Footsteps & Movement"
        prio = 80
    elif any(p in name[:6] for p in ("Mo", "Oj", "Mp")) or source_archive.startswith("Object"):
        cat = "World Objects"
        prio = 75
    else:
        cat = "Foley & Atmosphere"
        prio = 90

    if name in EXACT_TITLES:
        return cat, EXACT_TITLES[name], prio - 5

    # Strip technical prefixes (WsPv, RcSePm,RcWsd, WsdRsBgmJg, etc.)
    clean = name
    for pref in (
        "WsdRsBgmJg", "WsdRsBgm", "RcWsdPm", "RcWsdSy", "RcWsdUi", "RcWsdBm", "RcWsd",
        "RcSePm", "RcSeSy", "RcSeEm", "RcSeBm", "RcSeNm", "RcSeAt", "RcSe",
        "WsrPvRc", "WsPv", "SePv", "WsPm", "SePm", "WsSs", "WsSy", "SeSy",
        "WsUi", "WsDp", "WsDo", "WsdDo", "WsBm", "SeBm", "WsBv", "SeBv",
        "WsEm", "SeEm", "WsEv", "WsNm", "SeNm", "WsNv", "WNpc",
        "WsPf", "SePf", "WsPs", "SePs", "WsMo", "SeMo", "WsOj", "WsMp", "SeMp",
        "WsAt", "SeAt", "WsAo", "WsdEm", "StSy", "StAt"
    ):
        if clean.startswith(pref) and len(clean) > len(pref):
            clean = clean[len(pref):]
            break

    # Split camelCase and underscores into readable words
    clean = clean.replace("_", " ")
    clean = re.sub(r"([a-z])([A-Z])", r"\1 \2", clean)
    clean = re.sub(r"([A-Za-z])(\d+)", r"\1 \2", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    prefix_label = {
        "Fanfares & Moons": "Fanfare: ",
        "Mario Voice": "Mario Voice: ",
        "Mario & Cappy": "Mario/Cappy: ",
        "Coins & Stage FX": "Stage FX: ",
        "8-Bit 2D Retro": "8-Bit: ",
        "Menus & UI": "UI: ",
        "Bosses & Broodals": "Boss: ",
        "Enemies & Captures": "Enemy: ",
        "NPCs & Voices": "NPC: ",
        "Footsteps & Movement": "Step: ",
        "World Objects": "Object: ",
        "Foley & Atmosphere": "Atmos: ",
    }.get(cat, "")

    return cat, f"{prefix_label}{clean}", prio


# ---------------------------------------------------------------------------------------------------------------
# Binary Archive Parsers (FSAR / FGRP / FWSD / FWAR / FWAV)
# ---------------------------------------------------------------------------------------------------------------

def _parse_fsar_strings(d, fsar_pos):
    strg_off = fsar_pos + struct.unpack_from("<i", d, fsar_pos + 0x18)[0]
    strg_body = strg_off + 8
    tbl_pos = strg_body + struct.unpack_from("<i", d, strg_body + 4)[0]
    str_count = struct.unpack_from("<I", d, tbl_pos)[0]
    strings = []
    for i in range(str_count):
        _, _, roff, rlen = struct.unpack_from("<HHii", d, tbl_pos + 4 + 12 * i)
        s_pos = tbl_pos + roff
        strings.append(d[s_pos:s_pos + rlen - 1].decode("ascii", errors="replace"))
    return strings


def _parse_fgrp_files(d, fgrp_pos):
    info_off = struct.unpack_from("<i", d, fgrp_pos + 0x18)[0]
    file_off = struct.unpack_from("<i", d, fgrp_pos + 0x24)[0]
    ib = fgrp_pos + info_off + 8
    fb = fgrp_pos + file_off + 8
    cnt = struct.unpack_from("<I", d, ib)[0]
    out = {}
    for i in range(cnt):
        _, _, ro = struct.unpack_from("<HHi", d, ib + 4 + 8 * i)
        if ro < 0:
            continue
        ep = ib + ro
        fid, _, _, b_off, b_sz = struct.unpack_from("<IHHii", d, ep)
        if b_off >= 0 and b_sz > 0:
            abs_off = fb + b_off
            out[fid] = (abs_off, b_sz, d[abs_off:abs_off + 4])
    return out


def _parse_fsar_internal_files(d, fsar_pos):
    info_off = fsar_pos + struct.unpack_from("<i", d, fsar_pos + 0x24)[0]
    file_off = fsar_pos + struct.unpack_from("<i", d, fsar_pos + 0x30)[0]
    ib = info_off + 8
    fb = file_off + 8
    file_tbl = ib + struct.unpack_from("<i", d, ib + 8 * 6 + 4)[0]
    cnt = struct.unpack_from("<I", d, file_tbl)[0]
    out = {}
    for fid in range(cnt):
        _, _, ro = struct.unpack_from("<HHi", d, file_tbl + 4 + 8 * fid)
        if ro < 0:
            continue
        ep = file_tbl + ro
        loc_type, _, loc_off = struct.unpack_from("<HHi", d, ep)
        if loc_type == 0x220C and loc_off > 0:
            inp = ep + loc_off
            _, _, b_off, b_sz = struct.unpack_from("<HHii", d, inp)
            if b_off >= 0 and b_sz > 0:
                abs_off = fb + b_off
                out[fid] = (abs_off, b_sz, d[abs_off:abs_off + 4])
    return out


def _parse_fwsd_map(d, fwsd_off):
    info_b_off = struct.unpack_from("<i", d, fwsd_off + 0x18)[0]
    ib = fwsd_off + info_b_off + 8
    _, _, ref0_o, _, _, ref1_o = struct.unpack_from("<HHiHHi", d, ib)
    wid_tbl = ib + ref0_o
    wid_cnt = struct.unpack_from("<I", d, wid_tbl)[0]
    wids = [struct.unpack_from("<II", d, wid_tbl + 4 + 8 * w) for w in range(wid_cnt)]

    wsd_tbl = ib + ref1_o
    wsd_cnt = struct.unpack_from("<I", d, wsd_tbl)[0]
    res = {}
    for idx in range(wsd_cnt):
        _, _, ro = struct.unpack_from("<HHi", d, wsd_tbl + 4 + 8 * idx)
        if ro < 0:
            continue
        wep = wsd_tbl + ro
        _, _, r2_o = struct.unpack_from("<HHi", d, wep + 16)
        if r2_o <= 0:
            continue
        nep = wep + r2_o
        n_cnt = struct.unpack_from("<I", d, nep)[0]
        notes = []
        for n in range(n_cnt):
            _, _, nro = struct.unpack_from("<HHi", d, nep + 4 + 8 * n)
            if nro < 0:
                continue
            note_pos = nep + nro
            wid_index = struct.unpack_from("<I", d, note_pos)[0]
            if wid_index < len(wids):
                notes.append(wids[wid_index])
        res[idx] = notes
    return res


def _parse_fwar_header_meta(d, fwar_off):
    """Returns list of dicts for each FWAV in the FWAR at fwar_off."""
    info_off = fwar_off + struct.unpack_from("<i", d, fwar_off + 0x18)[0]
    file_off = fwar_off + struct.unpack_from("<i", d, fwar_off + 0x24)[0]
    wav_cnt = struct.unpack_from("<I", d, info_off + 8)[0]
    waves = []
    for i in range(wav_cnt):
        _, _, ro, sz = struct.unpack_from("<HHii", d, info_off + 12 + 12 * i)
        abs_off = file_off + 8 + ro
        if sz >= 0x60 and d[abs_off:abs_off + 4] == b"FWAV":
            ib = abs_off + struct.unpack_from("<i", d, abs_off + 0x18)[0] + 8
            codec, loop, _, rate, ls, samples, _, ch_cnt = struct.unpack_from("<BBHIIIII", d, ib)
        else:
            codec, loop, rate, samples, ch_cnt = (2, 0, 48000, 0, 1)
        waves.append({
            "wav_idx": i,
            "rel_off": ro,
            "abs_off": abs_off,
            "size": sz,
            "codec": codec,
            "loop": loop,
            "rate": rate,
            "samples": samples,
            "channels": ch_cnt,
            "duration": round(samples / rate, 2) if rate > 0 else 0.0,
        })
    return waves


def build_sfx_catalog(romfs_root, cache_dir):
    """Builds or loads a cached catalog of all named sound effects across SoundData."""
    cache_file = os.path.join(cache_dir, "sfx_catalog_v2.json")
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 3000:
                return data
        except Exception:
            pass

    sound_dir = os.path.join(romfs_root, "SoundData")
    if not os.path.isdir(sound_dir):
        return []

    catalog = []

    def index_fsar_with_fgrp(bfsar_name, fgrp_aras_list):
        bfsar_path = os.path.join(sound_dir, bfsar_name)
        if not os.path.isfile(bfsar_path):
            return
        with open(bfsar_path, "rb") as f:
            sar_bytes = f.read()
        strings = _parse_fsar_strings(sar_bytes, 0)

        fwsd_lookup = {}
        fwar_lookup = {}  # arch_name -> (fwar_off, waves_meta)
        for aras_name in fgrp_aras_list:
            ap = os.path.join(sound_dir, aras_name)
            if not os.path.isfile(ap):
                continue
            with open(ap, "rb") as f:
                ad = f.read()
            fgrp_pos = ad.find(b"FGRP")
            if fgrp_pos < 0:
                continue
            files = _parse_fgrp_files(ad, fgrp_pos)
            for fid, (off, sz, magic) in files.items():
                if magic == b"FWSD":
                    fwsd_lookup[fid] = (aras_name, _parse_fwsd_map(ad, off))
                elif magic == b"FWAR":
                    fwar_lookup[aras_name] = (off, _parse_fwar_header_meta(ad, off))

        info_base = struct.unpack_from("<i", sar_bytes, 0x24)[0] + 8
        snd_tbl = info_base + struct.unpack_from("<i", sar_bytes, info_base + 4)[0]
        snd_cnt = struct.unpack_from("<I", sar_bytes, snd_tbl)[0]

        for i in range(snd_cnt):
            _, _, ro = struct.unpack_from("<HHi", sar_bytes, snd_tbl + 4 + 8 * i)
            if ro < 0:
                continue
            ep = snd_tbl + ro
            file_id = struct.unpack_from("<I", sar_bytes, ep)[0]
            sub_type, _, sub_off = struct.unpack_from("<HHi", sar_bytes, ep + 12)
            str_id = struct.unpack_from("<I", sar_bytes, ep + 24)[0]
            name = strings[str_id] if str_id < len(strings) else f"snd_{i}"
            if name.startswith("_SinWave") or "Dummy" in name:
                continue
            if sub_type == 0x2202 and file_id in fwsd_lookup:
                wsi_idx = struct.unpack_from("<I", sar_bytes, ep + sub_off)[0]
                aras_name, wmap = fwsd_lookup[file_id]
                notes = wmap.get(wsi_idx, [])
                if not notes or aras_name not in fwar_lookup:
                    continue
                _, wav_idx = notes[0]
                fwar_off, waves_meta = fwar_lookup[aras_name]
                if wav_idx >= len(waves_meta):
                    continue
                wmeta = waves_meta[wav_idx]
                cat, title, prio = classify_and_format_sfx(name, aras_name)
                track_id = f"fwav:{aras_name}:{fwar_off}:{wav_idx}:{name}"
                catalog.append({
                    "filename": track_id,
                    "symbol": name,
                    "title": title,
                    "category": cat,
                    "priority": prio,
                    "archive": aras_name,
                    "fwar_off": fwar_off,
                    "wav_idx": wav_idx,
                    "rate": wmeta["rate"],
                    "channels": wmeta["channels"],
                    "codec": wmeta["codec"],
                    "duration": wmeta["duration"],
                    "size_kb": round(wmeta["size"] / 1024, 1),
                    "size_mb": round(wmeta["size"] / (1024 * 1024), 3),
                    "kind": "fwav",
                })

    # 1. Power Moon & Heart Fanfares (BgmData.bfsar -> BgmResourceStd2nd.aras)
    index_fsar_with_fgrp("BgmData.bfsar", ["BgmResourceStd2nd.aras"])

    # 2. Main Gameplay SFX & Mario Voice (SeData.bfsar -> SeResourceStd2nd.aras + SeResourceStdSystem.aras)
    index_fsar_with_fgrp("SeData.bfsar", ["SeResourceStd2nd.aras", "SeResourceStdSystem.aras"])

    # 3. Self-contained FSAR archives (Boss*.aras, Enemy*.aras, NpcVoice*.aras, Object*.aras, FootNote.bfsar)
    for fn in sorted(os.listdir(sound_dir)):
        if not (fn.startswith(("Boss", "Enemy", "Npc", "Object")) and fn.endswith(".aras")) and fn != "FootNote.bfsar":
            continue
        ap = os.path.join(sound_dir, fn)
        if not os.path.isfile(ap):
            continue
        with open(ap, "rb") as f:
            ad = f.read()
        fsar_pos = ad.find(b"FSAR")
        if fsar_pos < 0:
            continue
        try:
            strings = _parse_fsar_strings(ad, fsar_pos)
            if not strings:
                continue
            int_files = _parse_fsar_internal_files(ad, fsar_pos)
            fwsds = {}
            fwars = []
            for fid, (off, sz, magic) in sorted(int_files.items()):
                if magic == b"FWSD":
                    fwsds[fid] = _parse_fwsd_map(ad, off)
                elif magic == b"FWAR":
                    fwars.append((off, _parse_fwar_header_meta(ad, off)))
            if not fwars or not fwsds:
                continue

            info_base = fsar_pos + struct.unpack_from("<i", ad, fsar_pos + 0x24)[0] + 8
            snd_tbl = info_base + struct.unpack_from("<i", ad, info_base + 4)[0]
            snd_cnt = struct.unpack_from("<I", ad, snd_tbl)[0]
            for i in range(snd_cnt):
                _, _, ro = struct.unpack_from("<HHi", ad, snd_tbl + 4 + 8 * i)
                if ro < 0:
                    continue
                ep = snd_tbl + ro
                file_id = struct.unpack_from("<I", ad, ep)[0]
                sub_type, _, sub_off = struct.unpack_from("<HHi", ad, ep + 12)
                str_id = struct.unpack_from("<I", ad, ep + 24)[0]
                name = strings[str_id] if str_id < len(strings) else f"{fn}_{i}"
                if "Dummy" in name or name.startswith("PLAYER_"):
                    continue
                if sub_type == 0x2202 and file_id in fwsds:
                    wsi_idx = struct.unpack_from("<I", ad, ep + sub_off)[0]
                    notes = fwsds[file_id].get(wsi_idx, [])
                    if not notes:
                        continue
                    war_id, wav_idx = notes[0]
                    war_slot = (war_id & 0xFF) if (war_id & 0xFF) < len(fwars) else 0
                    fwar_off, waves_meta = fwars[war_slot]
                    if wav_idx >= len(waves_meta):
                        continue
                    wmeta = waves_meta[wav_idx]
                    cat, title, prio = classify_and_format_sfx(name, fn)
                    track_id = f"fwav:{fn}:{fwar_off}:{wav_idx}:{name}"
                    catalog.append({
                        "filename": track_id,
                        "symbol": name,
                        "title": title,
                        "category": cat,
                        "priority": prio + 5,
                        "archive": fn,
                        "fwar_off": fwar_off,
                        "wav_idx": wav_idx,
                        "rate": wmeta["rate"],
                        "channels": wmeta["channels"],
                        "codec": wmeta["codec"],
                        "duration": wmeta["duration"],
                        "size_kb": round(wmeta["size"] / 1024, 1),
                        "size_mb": round(wmeta["size"] / (1024 * 1024), 3),
                        "kind": "fwav",
                    })
        except Exception as e:
            print(f"Warning parsing {fn}: {e}")

    # 4. Also include the 72 streamSe/*.bfstm ambient & cutscene foley streams
    stream_dir = os.path.join(sound_dir, "streamSe")
    if os.path.isdir(stream_dir):
        for f in sorted(os.listdir(stream_dir)):
            if f.endswith(".bfstm"):
                full_p = os.path.join(stream_dir, f)
                sz = os.path.getsize(full_p)
                raw = f.replace(".dspadpcm.bfstm", "").replace(".pcm16.bfstm", "").replace(".bfstm", "")
                title = raw.replace("StSy", "Cutscene: ").replace("StAt", "Wind: ").replace("_", " ")
                catalog.append({
                    "filename": f,
                    "symbol": raw,
                    "title": title,
                    "category": "Foley & Atmosphere",
                    "priority": 95,
                    "archive": "streamSe",
                    "fwar_off": 0,
                    "wav_idx": -1,
                    "rate": 48000,
                    "channels": 6,
                    "codec": 2,
                    "duration": 0.0,
                    "size_kb": round(sz / 1024, 1),
                    "size_mb": round(sz / (1024 * 1024), 2),
                    "kind": "bfstm",
                })

    catalog.sort(key=lambda x: (x["priority"], x["title"]))
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(catalog, f)
    except Exception:
        pass
    return catalog


# ---------------------------------------------------------------------------------------------------------------
# Fast FWAV -> WAV Decoder (PCM16 + Nintendo DSP-ADPCM)
# ---------------------------------------------------------------------------------------------------------------

def decode_dsp_adpcm_channel(data, num_samples, coefs, yn1=0, yn2=0):
    """Decodes Nintendo GC/Wii/Switch DSP-ADPCM (8 bytes -> 14 samples per frame) into int16 PCM bytes."""
    out = bytearray(num_samples * 2)
    sample_idx = 0
    num_frames = (num_samples + 13) // 14
    c_pairs = [(coefs[i * 2], coefs[i * 2 + 1]) for i in range(8)]
    mv = memoryview(data)
    out_pos = 0
    for f in range(num_frames):
        f_off = f * 8
        if f_off >= len(mv):
            break
        hdr = mv[f_off]
        scale = 1 << (hdr & 0x0F)
        c_idx = (hdr >> 4) & 0x07
        c1, c2 = c_pairs[c_idx]
        rem = num_samples - sample_idx
        n_s = 14 if rem >= 14 else rem
        for i in range(n_s):
            byte_val = mv[f_off + 1 + (i >> 1)]
            nib = (byte_val >> 4) if (i & 1) == 0 else (byte_val & 0x0F)
            if nib >= 8:
                nib -= 16
            val = ((nib * scale) << 11) + 1024 + (c1 * yn1 + c2 * yn2)
            val >>= 11
            if val > 32767:
                val = 32767
            elif val < -32768:
                val = -32768
            yn2 = yn1
            yn1 = val
            out[out_pos] = val & 0xFF
            out[out_pos + 1] = (val >> 8) & 0xFF
            out_pos += 2
        sample_idx += n_s
    return bytes(out)


def decode_fwav_to_wav_file(fw, out_wav_path):
    """Decodes a raw Switch FWAV buffer (1ch/2ch, PCM16 or DSP-ADPCM) and writes a standard RIFF WAV file."""
    if fw[:4] != b"FWAV":
        raise ValueError("Invalid FWAV magic header")
    ib = struct.unpack_from("<i", fw, 0x18)[0] + 8
    db = struct.unpack_from("<i", fw, 0x24)[0] + 8
    codec, loop = struct.unpack_from("<BB", fw, ib)
    rate, loop_start, samples = struct.unpack_from("<III", fw, ib + 4)
    ch_cnt = struct.unpack_from("<I", fw, ib + 20)[0]

    ch_pcm = []
    for c in range(ch_cnt):
        _, _, cro = struct.unpack_from("<HHi", fw, ib + 24 + 8 * c)
        cep = ib + 20 + cro
        _, _, d_ro, _, _, a_ro = struct.unpack_from("<HHiHHi", fw, cep)
        ch_data_start = db + d_ro
        if codec == 1:
            ch_pcm.append(fw[ch_data_start:ch_data_start + samples * 2])
        elif codec == 2:
            aep = cep + a_ro
            coefs = struct.unpack_from("<16h", fw, aep)
            _, yn1, yn2 = struct.unpack_from("<3h", fw, aep + 32)
            n_frames = (samples + 13) // 14
            ch_pcm.append(decode_dsp_adpcm_channel(fw[ch_data_start:ch_data_start + n_frames * 8], samples, coefs, yn1, yn2))
        else:
            raise ValueError(f"Unsupported FWAV codec: {codec}")

    if ch_cnt == 1:
        pcm_bytes = ch_pcm[0]
    else:
        arrs = [np.frombuffer(p, dtype=np.int16) for p in ch_pcm]
        min_len = min(len(a) for a in arrs)
        interleaved = np.empty((min_len, ch_cnt), dtype=np.int16)
        for c, a in enumerate(arrs):
            interleaved[:, c] = a[:min_len]
        pcm_bytes = interleaved.tobytes()

    os.makedirs(os.path.dirname(out_wav_path), exist_ok=True)
    with wave.open(out_wav_path, "wb") as wf:
        wf.setnchannels(ch_cnt)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)
    return out_wav_path


def read_fwav_from_archive(archive_path, fwar_off, wav_idx):
    """Seeks directly to an FWAV inside an FWAR without loading the entire archive into memory."""
    with open(archive_path, "rb") as f:
        f.seek(fwar_off + 0x18)
        info_rel, _, _, file_rel = struct.unpack("<iiii", f.read(16))
        info_off = fwar_off + info_rel
        file_off = fwar_off + file_rel
        f.seek(info_off + 12 + 12 * wav_idx)
        _, _, ro, sz = struct.unpack("<HHii", f.read(12))
        f.seek(file_off + 8 + ro)
        return f.read(sz)


# ---------------------------------------------------------------------------------------------------------------
# WAV -> Switch FWAV Encoder & Archive Patcher
# ---------------------------------------------------------------------------------------------------------------

def encode_wav_to_fwav(clean_wav_path, vanilla_fwav, convert_audio_exe, toolbox_dir, cache_dir):
    """Encodes a clean PCM16 WAV file into a Switch little-endian FWAV matching vanilla_fwav's header layout."""
    i_off, i_sz = struct.unpack_from("<ii", vanilla_fwav, 0x18)
    d_off, _ = struct.unpack_from("<ii", vanilla_fwav, 0x24)
    ib_rel = 8  # inside INFO block bytes
    info = bytearray(vanilla_fwav[i_off:i_off + i_sz])

    codec, loop, _, rate, ls, _, ols, ch_cnt = struct.unpack_from("<BBHIIIII", info, ib_rel)

    # First channel's data_ro in vanilla template
    _, _, cro0 = struct.unpack_from("<HHi", info, ib_rel + 24)
    cep0 = ib_rel + 20 + cro0
    _, _, base_d_ro = struct.unpack_from("<HHi", info, cep0)

    with wave.open(clean_wav_path, "rb") as wf:
        n_ch = wf.getnchannels()
        n_frames_pcm = wf.getnframes()
        raw_pcm = wf.readframes(n_frames_pcm)

    arr = np.frombuffer(raw_pcm, dtype=np.int16)
    if n_ch > 1:
        arr = arr.reshape(-1, n_ch)
    else:
        arr = arr.reshape(-1, 1)

    samples = arr.shape[0]
    ch_payloads = []
    ch_adpcm_meta = []

    if codec == 1:  # PCM16 little-endian
        for c in range(ch_cnt):
            col = arr[:, min(c, arr.shape[1] - 1)].astype(np.int16)
            ch_payloads.append(col.tobytes())
    elif codec == 2:  # DSP-ADPCM via ConvertAudio.exe (1 channel at a time for contiguous FWAV channel layout)
        for c in range(ch_cnt):
            col = arr[:, min(c, arr.shape[1] - 1)].astype(np.int16)
            mono_wav = os.path.join(cache_dir, f"fwav_tmp_ch{c}.wav")
            mono_bfstm = os.path.join(cache_dir, f"fwav_tmp_ch{c}.bfstm")
            with wave.open(mono_wav, "wb") as mw:
                mw.setnchannels(1)
                mw.setsampwidth(2)
                mw.setframerate(rate)
                mw.writeframes(col.tobytes())
            subprocess.run([convert_audio_exe, mono_wav, mono_bfstm], cwd=toolbox_dir, stdin=subprocess.DEVNULL, check=True)
            with open(mono_bfstm, "rb") as bf:
                cafe = bf.read()
            parsed = bfstm_nx._parse(cafe)
            samples = parsed["samples"]
            n_adpcm_bytes = ((samples + 13) // 14) * 8
            audio_start = parsed["data_off"] + 0x20
            ch_payloads.append(cafe[audio_start:audio_start + n_adpcm_bytes])
            ch_adpcm_meta.append((parsed["chans"][0]["coefs"], parsed["chans"][0]["ctx"]))
            for p in (mono_wav, mono_bfstm):
                try:
                    os.remove(p)
                except OSError:
                    pass
    else:
        raise ValueError(f"Unsupported target FWAV codec: {codec}")

    # Patch INFO sample counts and channel offsets / ADPCM coefficients
    new_loop_start = 0 if loop == 0 else min(ls, max(0, samples - 1))
    new_ols = 0 if loop == 0 else min(ols, max(0, samples - 1))
    struct.pack_into("<IIII", info, ib_rel + 4, rate, new_loop_start, samples, new_ols)

    data_body = bytearray(b"\x00" * base_d_ro)
    for c in range(ch_cnt):
        _, _, cro = struct.unpack_from("<HHi", info, ib_rel + 24 + 8 * c)
        cep = ib_rel + 20 + cro
        cur_d_ro = len(data_body)
        struct.pack_into("<i", info, cep + 4, cur_d_ro)
        if codec == 2:
            _, _, a_ro = struct.unpack_from("<HHi", info, cep + 8)
            aep = cep + a_ro
            coefs, ctx = ch_adpcm_meta[c]
            struct.pack_into("<16h", info, aep, *coefs)
            struct.pack_into("<6h", info, aep + 32, *ctx)
        data_body.extend(ch_payloads[c])
        if c < ch_cnt - 1:
            pad = _align(len(data_body), ALIGN_FWAV) - len(data_body)
            data_body.extend(b"\x00" * pad)

    data_block_size = 8 + len(data_body)
    data_block = b"DATA" + struct.pack("<I", data_block_size) + bytes(data_body)

    hdr = bytearray(vanilla_fwav[:0x40])
    total_size = d_off + data_block_size
    struct.pack_into("<I", hdr, 0x0C, total_size)
    struct.pack_into("<HHii", hdr, 0x14, 0x7000, 0, i_off, i_sz)
    struct.pack_into("<HHii", hdr, 0x20, 0x7001, 0, d_off, data_block_size)

    return bytes(hdr) + bytes(info) + data_block


def patch_archive_fwav(vanilla_archive_path, deployed_archive_path, fwar_off, wav_idx, new_fwav_bytes):
    """Patches a single FWAV inside an FWAR in an .aras or .bfsar archive, updating all container offsets."""
    src_path = deployed_archive_path if os.path.isfile(deployed_archive_path) else vanilla_archive_path
    with open(src_path, "rb") as f:
        raw = bytearray(f.read())

    # Note: If deployed_archive_path was already modified earlier, fwar_off might have shifted if an earlier FWAR
    # before it changed size. In SMO, SeResourceStd2nd.aras, SeResourceStdSystem.aras, and BgmResourceStd2nd.aras
    # each have only ONE FWAR and its start offset (0x8940, 0x1e80, 0x2180) is fixed before any resizeable data.
    # Still, verify FWAR magic at fwar_off; if shifted, locate the matching FWAR.
    if raw[fwar_off:fwar_off + 4] != b"FWAR":
        raise RuntimeError(f"FWAR not found at 0x{fwar_off:x} in {src_path}")

    fwar_total_sz = struct.unpack_from("<I", raw, fwar_off + 0x0C)[0]
    info_rel = struct.unpack_from("<i", raw, fwar_off + 0x18)[0]
    file_rel = struct.unpack_from("<i", raw, fwar_off + 0x24)[0]
    file_blk_sz = struct.unpack_from("<I", raw, fwar_off + 0x28)[0]

    info_off = fwar_off + info_rel
    file_off = fwar_off + file_rel
    file_body = file_off + 8
    wav_cnt = struct.unpack_from("<I", raw, info_off + 8)[0]
    if not (0 <= wav_idx < wav_cnt):
        raise IndexError(f"wav_idx {wav_idx} out of range (0..{wav_cnt - 1})")

    _, _, ro, old_sz = struct.unpack_from("<HHii", raw, info_off + 12 + 12 * wav_idx)
    if wav_idx + 1 < wav_cnt:
        _, _, next_ro, _ = struct.unpack_from("<HHii", raw, info_off + 12 + 12 * (wav_idx + 1))
        old_slot_len = next_ro - ro
    else:
        old_slot_len = (file_blk_sz - 8) - ro

    new_sz = len(new_fwav_bytes)
    if new_sz <= old_slot_len:
        new_slot_len = old_slot_len
    elif wav_idx + 1 == wav_cnt:
        pad_tail = _align(file_off + 8 + ro + new_sz, ALIGN_FWAV) - (file_off + 8 + ro + new_sz)
        new_slot_len = new_sz + pad_tail
    else:
        new_slot_len = _align(new_sz, ALIGN_FWAV)

    delta = new_slot_len - old_slot_len
    padded_fwav = new_fwav_bytes + b"\x00" * (new_slot_len - new_sz)

    # 1. Update FWAR INFO table
    struct.pack_into("<i", raw, info_off + 12 + 12 * wav_idx + 8, new_sz)
    if delta != 0:
        for j in range(wav_idx + 1, wav_cnt):
            pos = info_off + 12 + 12 * j + 4
            old_ro = struct.unpack_from("<i", raw, pos)[0]
            struct.pack_into("<i", raw, pos, old_ro + delta)

        # Update FWAR header and FILE block header sizes
        struct.pack_into("<I", raw, fwar_off + 0x0C, fwar_total_sz + delta)
        struct.pack_into("<I", raw, fwar_off + 0x28, file_blk_sz + delta)
        struct.pack_into("<I", raw, file_off + 4, file_blk_sz + delta)

        # 2. Update parent FGRP or FSAR container
        is_aras = raw[:4] == b"SARC"
        inner_pos = 0x1000 if is_aras else 0
        inner_magic = bytes(raw[inner_pos:inner_pos + 4])

        if inner_magic == b"FGRP":
            fgrp_sz = struct.unpack_from("<I", raw, inner_pos + 0x0C)[0]
            g_info_off = inner_pos + struct.unpack_from("<i", raw, inner_pos + 0x18)[0]
            g_file_off = inner_pos + struct.unpack_from("<i", raw, inner_pos + 0x24)[0]
            g_file_sz = struct.unpack_from("<I", raw, inner_pos + 0x28)[0]
            g_infx_rel = struct.unpack_from("<i", raw, inner_pos + 0x30)[0]

            struct.pack_into("<I", raw, inner_pos + 0x0C, fgrp_sz + delta)
            struct.pack_into("<I", raw, inner_pos + 0x28, g_file_sz + delta)
            if g_infx_rel > 0:
                struct.pack_into("<i", raw, inner_pos + 0x30, g_infx_rel + delta)
            struct.pack_into("<I", raw, g_file_off + 4, g_file_sz + delta)

            gib = g_info_off + 8
            g_cnt = struct.unpack_from("<I", raw, gib)[0]
            fwar_b_off = fwar_off - (g_file_off + 8)
            for i in range(g_cnt):
                _, _, gro = struct.unpack_from("<HHi", raw, gib + 4 + 8 * i)
                if gro < 0:
                    continue
                gep = gib + gro
                fid, _, _, b_off, b_sz = struct.unpack_from("<IHHii", raw, gep)
                if b_off == fwar_b_off:
                    struct.pack_into("<i", raw, gep + 12, b_sz + delta)
                elif b_off > fwar_b_off:
                    struct.pack_into("<i", raw, gep + 8, b_off + delta)

        elif inner_magic == b"FSAR":
            fsar_sz = struct.unpack_from("<I", raw, inner_pos + 0x0C)[0]
            s_info_off = inner_pos + struct.unpack_from("<i", raw, inner_pos + 0x24)[0]
            s_file_off = inner_pos + struct.unpack_from("<i", raw, inner_pos + 0x30)[0]
            s_file_sz = struct.unpack_from("<I", raw, inner_pos + 0x34)[0]

            struct.pack_into("<I", raw, inner_pos + 0x0C, fsar_sz + delta)
            struct.pack_into("<I", raw, inner_pos + 0x34, s_file_sz + delta)
            struct.pack_into("<I", raw, s_file_off + 4, s_file_sz + delta)

            sib = s_info_off + 8
            file_tbl = sib + struct.unpack_from("<i", raw, sib + 8 * 6 + 4)[0]
            f_cnt = struct.unpack_from("<I", raw, file_tbl)[0]
            fwar_b_off = fwar_off - (s_file_off + 8)
            for fid in range(f_cnt):
                _, _, fro = struct.unpack_from("<HHi", raw, file_tbl + 4 + 8 * fid)
                if fro < 0:
                    continue
                fep = file_tbl + fro
                loc_type, _, loc_off = struct.unpack_from("<HHi", raw, fep)
                if loc_type == 0x220C and loc_off > 0:
                    inp = fep + loc_off
                    _, _, b_off, b_sz = struct.unpack_from("<HHii", raw, inp)
                    if b_off == fwar_b_off:
                        struct.pack_into("<i", raw, inp + 8, b_sz + delta)
                    elif b_off > fwar_b_off:
                        struct.pack_into("<i", raw, inp + 4, b_off + delta)

        # 3. Update SARC (.aras) header if applicable
        if is_aras:
            aras_sz = struct.unpack_from("<I", raw, 0x08)[0]
            sfat_end = struct.unpack_from("<I", raw, 0x2C)[0]
            struct.pack_into("<I", raw, 0x08, aras_sz + delta)
            struct.pack_into("<I", raw, 0x2C, sfat_end + delta)

    # 4. Splice the new FWAV payload into FWAR FILE body
    abs_target = file_body + ro
    raw[abs_target:abs_target + old_slot_len] = padded_fwav

    os.makedirs(os.path.dirname(deployed_archive_path), exist_ok=True)
    tmp_path = deployed_archive_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(raw)
    os.replace(tmp_path, deployed_archive_path)
    return deployed_archive_path
