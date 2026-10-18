"""Convert VGAudio's Wii U (Cafe, big-endian) BFSTM output into a Nintendo Switch (NX, little-endian) BFSTM.

VGAudio 2.2.1 can't target the Switch, so we keep it as the DSP-ADPCM *encoder* and rebuild the container here.
A vanilla game file with the same channel count is used as the layout template: its header, INFO block
(track info, ref tables, region info sizes) are kept and only the audio-dependent fields are replaced:

  stream info    codec/loop/channels/sample rate/loop start/sample count/block geometry/seek geometry
                 + the three Switch-only trailing words (original loop start, original loop end, file id)
  channel info   per-channel DSP-ADPCM coefficients, start/loop contexts
  SEEK block     (hist1, hist2) per block per channel (VGAudio already emits these little-endian)
  DATA block     interleaved ADPCM blocks, copied verbatim (ADPCM bytes are endian-neutral)
"""
import os
import struct
import zlib

ALIGN = 0x20


def _align(n, a=ALIGN):
    return (n + a - 1) & ~(a - 1)


class BfstmError(Exception):
    pass


def _blocks(d, e):
    count = struct.unpack_from(e + "H", d, 0x10)[0]
    refs = [struct.unpack_from(e + "HHii", d, 0x14 + 12 * i) for i in range(count)]
    by_type = {t: (off, size) for t, _, off, size in refs}
    return by_type


def _endian(d):
    if d[:4] != b"FSTM":
        raise BfstmError("not an FSTM file")
    return "<" if d[4:6] == b"\xff\xfe" else ">"


def is_big_endian_bfstm(path):
    try:
        with open(path, "rb") as f:
            h = f.read(6)
        return h[:4] == b"FSTM" and h[4:6] == b"\xfe\xff"
    except OSError:
        return False


def _parse(d):
    """Returns dict with the fields we need from an FSTM file of either endianness."""
    e = _endian(d)
    blk = _blocks(d, e)
    info_off, info_size = blk[0x4000]
    seek_off, seek_size = blk.get(0x4001, (0, 0))
    data_off, data_size = blk[0x4002]

    body = info_off + 8
    stream_ref = struct.unpack_from(e + "HHi", d, body)
    track_ref = struct.unpack_from(e + "HHi", d, body + 8)
    chan_ref = struct.unpack_from(e + "HHi", d, body + 16)
    s = body + stream_ref[2]

    codec, loop, channels, regions = struct.unpack_from("4B", d, s)
    (rate, loop_start, samples, block_count, block_size, block_samples,
     last_size, last_samples, last_padded, seek_info_size, seek_interval) = struct.unpack_from(e + "11I", d, s + 4)

    table = body + chan_ref[2]
    n = struct.unpack_from(e + "I", d, table)[0]
    chans = []
    for c in range(n):
        rec = table + struct.unpack_from(e + "i", d, table + 4 + 8 * c + 4)[0]
        dsp_rel = struct.unpack_from(e + "i", d, rec + 4)[0]
        if codec == 2 and dsp_rel >= 0:
            dsp = rec + dsp_rel
            coefs = struct.unpack_from(e + "16h", d, dsp)
            ps, h1, h2, lps, lh1, lh2 = struct.unpack_from(e + "6h", d, dsp + 32)
            chans.append(dict(rec=rec, dsp=dsp, coefs=coefs, ctx=(ps, h1, h2, lps, lh1, lh2)))
        else:
            chans.append(dict(rec=rec, dsp=None, coefs=(), ctx=()))

    return dict(e=e, info_off=info_off, info_size=info_size, seek_off=seek_off, seek_size=seek_size,
                data_off=data_off, data_size=data_size, stream_start=s, track_ref=track_ref,
                codec=codec, loop=loop, channels=channels, regions=regions, rate=rate, loop_start=loop_start,
                samples=samples, block_count=block_count, block_size=block_size, block_samples=block_samples,
                last_size=last_size, last_samples=last_samples, last_padded=last_padded,
                seek_info_size=seek_info_size, seek_interval=seek_interval, chans=chans, chan_table_off=table)


def convert_wav_to_nx_pcm16_bytes(wav_path, template, file_id=None):
    """Build a little-endian Switch PCM16 (codec=1) BFSTM directly from a 16-bit PCM WAV file and vanilla template."""
    import wave
    import numpy as np

    tpl = _parse(template)
    if tpl["e"] != "<" or tpl["codec"] != 1:
        raise BfstmError("template is not a little-endian Switch PCM16 BFSTM")

    with wave.open(wav_path, "rb") as wf:
        n = wf.getnchannels()
        rate = wf.getframerate()
        samples = wf.getnframes()
        raw_bytes = wf.readframes(samples)

    if n != tpl["channels"]:
        raise BfstmError("channel mismatch for PCM16: wav %d vs template %d" % (n, tpl["channels"]))

    pcm = np.frombuffer(raw_bytes, dtype="<i2").reshape(-1, n)
    block_samples = 4096
    block_size = 8192
    # Ensure at least 6 blocks so the 5-block prefetch is strictly shorter than the stream
    min_samples = 6 * block_samples
    if pcm.shape[0] < min_samples:
        reps = (min_samples // max(1, pcm.shape[0])) + 1
        pcm = np.tile(pcm, (reps, 1))
    samples = int(pcm.shape[0])

    rem = samples % block_samples
    if rem == 0:
        block_count = samples // block_samples
        last_samples = block_samples
        last_size = block_size
        last_padded = block_size
    else:
        block_count = samples // block_samples + 1
        last_samples = rem
        last_size = rem * 2
        last_padded = _align(last_size, 0x20)

    B = block_count - 1
    if B > 0:
        first_part = np.ascontiguousarray(pcm[:B * block_samples].reshape(B, block_samples, n).transpose(0, 2, 1)).tobytes()
    else:
        first_part = b""
    last_arr = np.zeros((n, last_padded // 2), dtype="<i2")
    last_arr[:, :last_samples] = pcm[B * block_samples:].T
    audio = first_part + last_arr.tobytes()

    info = bytearray(template[tpl["info_off"]: tpl["info_off"] + tpl["info_size"]])
    s = tpl["stream_start"] - tpl["info_off"]
    loop_flag = tpl["loop"]
    loop_start = 0
    info[s + 1] = loop_flag
    struct.pack_into("<11I", info, s + 4, rate, loop_start, samples, block_count,
                     block_size, block_samples, last_size, last_samples,
                     last_padded, 4, block_samples)
    if file_id is None:
        file_id = zlib.crc32(audio[:0x10000]) & 0xFFFFFFFF
    struct.pack_into("<3I", info, s + 0x44, loop_start, samples, file_id)

    info_size = len(info)
    struct.pack_into("<I", info, 4, info_size)
    data_block_size = 0x20 + len(audio)
    data_hdr = b"DATA" + struct.pack("<I", data_block_size) + b"\0" * 0x18

    hdr = bytearray(template[:0x40])
    info_at = 0x40
    data_at = info_at + info_size
    total = data_at + data_block_size
    struct.pack_into("<I", hdr, 0x0C, total)
    struct.pack_into("<HHii", hdr, 0x14, 0x4000, 0, info_at, info_size)
    struct.pack_into("<HHii", hdr, 0x20, 0x4002, 0, data_at, data_block_size)

    out = bytes(hdr) + bytes(info) + data_hdr + audio
    if len(out) != total:
        raise BfstmError("PCM16 internal size mismatch (%d != %d)" % (len(out), total))
    return out


def write_pcm16_bfstm_from_wav(wav_path, out_bfstm_path, vanilla_template_path):
    """Write a Switch PCM16 BFSTM at `out_bfstm_path` using `vanilla_template_path` as template."""
    with open(vanilla_template_path, "rb") as f:
        template = f.read(0x4000)
    file_id = read_stream_id(vanilla_template_path)
    out = convert_wav_to_nx_pcm16_bytes(wav_path, template, file_id)
    tmp = out_bfstm_path + ".pcm_tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, out_bfstm_path)
    return out_bfstm_path


def convert_cafe_to_nx_bytes(cafe, template, file_id=None):
    src = _parse(cafe)
    tpl = _parse(template)
    if src["e"] != ">":
        raise BfstmError("source is not a big-endian (Cafe) BFSTM")
    if tpl["e"] != "<":
        raise BfstmError("template is not a little-endian Switch BFSTM")
    if src["codec"] != 2 or tpl["codec"] != 2:
        raise BfstmError("only DSP-ADPCM streams are supported (src codec %d, template codec %d)"
                         % (src["codec"], tpl["codec"]))
    if src["channels"] != tpl["channels"] or len(src["chans"]) != len(tpl["chans"]):
        raise BfstmError("channel mismatch: source %d vs template %d" % (src["channels"], tpl["channels"]))
    if src["regions"] != 0 or tpl["regions"] != 0:
        raise BfstmError("region info is not supported")

    n = src["channels"]

    # ---- audio + seek payloads -------------------------------------------------------------------------
    audio_start = src["data_off"] + 0x20
    audio = cafe[audio_start: src["data_off"] + src["data_size"]]
    full = (src["block_count"] - 1) * n * src["block_size"] + n * src["last_padded"]
    if len(audio) < full:
        raise BfstmError("DATA block shorter than the stream geometry (%d < %d)" % (len(audio), full))
    audio = audio[:full]

    seek_len = src["block_count"] * n * 4
    seek_payload = cafe[src["seek_off"] + 0x10: src["seek_off"] + 0x10 + seek_len]
    if len(seek_payload) != seek_len:
        raise BfstmError("SEEK block shorter than expected")
    if src["seek_info_size"] != 4 or src["seek_interval"] != src["block_samples"]:
        raise BfstmError("unexpected seek geometry")

    # ---- INFO: patch the template ------------------------------------------------------------------------
    info = bytearray(template[tpl["info_off"]: tpl["info_off"] + tpl["info_size"]])
    rel = lambda a: a - tpl["info_off"]  # noqa: E731  absolute file offset -> offset inside the INFO bytes

    s = rel(tpl["stream_start"])
    info[s + 1] = src["loop"]
    struct.pack_into("<11I", info, s + 4, src["rate"], src["loop_start"], src["samples"], src["block_count"],
                     src["block_size"], src["block_samples"], src["last_size"], src["last_samples"],
                     src["last_padded"], 4, src["block_samples"])
    # Switch-only trailing words: original loop start / end, plus an id (not interpreted by us; any value works)
    if file_id is None:
        file_id = zlib.crc32(audio[:0x10000]) & 0xFFFFFFFF
    struct.pack_into("<3I", info, s + 0x44, src["loop_start"], src["samples"], file_id)

    for c in range(n):
        d = rel(tpl["chans"][c]["dsp"])
        struct.pack_into("<16h", info, d, *src["chans"][c]["coefs"])
        struct.pack_into("<6h", info, d + 32, *src["chans"][c]["ctx"])

    # ---- assemble ----------------------------------------------------------------------------------------
    info_size = len(info)
    seek_block_size = _align(0x10 + len(seek_payload))
    seek_block = bytearray(b"SEEK" + struct.pack("<I", seek_block_size) + b"\0" * 8 + seek_payload)
    seek_block += b"\0" * (seek_block_size - len(seek_block))
    data_block_size = 0x20 + len(audio)
    data_hdr = b"DATA" + struct.pack("<I", data_block_size) + b"\0" * 0x18

    hdr = bytearray(template[:0x40])
    info_at = 0x40
    seek_at = info_at + info_size
    data_at = seek_at + seek_block_size
    total = data_at + data_block_size
    struct.pack_into("<I", hdr, 0x0C, total)
    struct.pack_into("<HHii", hdr, 0x14, 0x4000, 0, info_at, info_size)
    struct.pack_into("<HHii", hdr, 0x20, 0x4001, 0, seek_at, seek_block_size)
    struct.pack_into("<HHii", hdr, 0x2C, 0x4002, 0, data_at, data_block_size)

    # keep the INFO block-size header word consistent
    struct.pack_into("<I", info, 4, info_size)

    out = bytes(hdr) + bytes(info) + bytes(seek_block) + data_hdr + audio
    if len(out) != total:
        raise BfstmError("internal size mismatch (%d != %d)" % (len(out), total))
    return out


def find_template(romfs_dir, preferred_name, channels):
    """Pick a vanilla Switch BFSTM with this channel count and DSP-ADPCM codec (preferring the target's own file)."""
    def usable(path):
        try:
            with open(path, "rb") as f:
                head = f.read(0x1000)
            if head[:4] != b"FSTM" or head[4:6] != b"\xff\xfe":
                return False
            with open(path, "rb") as f:
                t = _parse(f.read(0x4000))
            return t["codec"] == 2 and t["channels"] == channels and t["regions"] == 0
        except Exception:
            return False

    if preferred_name:
        p = os.path.join(romfs_dir, preferred_name)
        if os.path.isfile(p) and usable(p):
            return p
    for name in sorted(os.listdir(romfs_dir)):
        if name.endswith(".bfstm"):
            p = os.path.join(romfs_dir, name)
            if usable(p):
                return p
    raise BfstmError("no vanilla ADPCM template with %d channels in %s" % (channels, romfs_dir))


ID_OFFSET = 0x44 + 8  # stream-info start + this = the per-file id word (Switch-only trailing word #3)


def read_stream_id(path):
    """The id word of a Switch BFSTM (any codec). The prefetch archive and sound archive refer to streams by it."""
    with open(path, "rb") as f:
        d = f.read(0x4000)
    return struct.unpack_from("<I", d, _parse(d)["stream_start"] + ID_OFFSET)[0]


def read_codec(path):
    with open(path, "rb") as f:
        d = f.read(0x4000)
    return _parse(d)["codec"]


def convert_file_in_place(path, romfs_dir, target_name):
    """Convert a Cafe BFSTM at `path` to Switch format in place. Returns True if converted, False if already NX."""
    with open(path, "rb") as f:
        cafe = f.read()
    if _endian(cafe) != ">":
        return False
    src = _parse(cafe)
    tpl_path = find_template(romfs_dir, target_name, src["channels"])
    with open(tpl_path, "rb") as f:
        template = f.read(0x4000)  # header + INFO are all that's needed (INFO is < 0x4000 even for 10 channels)
    vanilla = os.path.join(romfs_dir, target_name) if target_name else ""
    file_id = read_stream_id(vanilla) if os.path.isfile(vanilla) else None
    out = convert_cafe_to_nx_bytes(cafe, template, file_id)
    tmp = path + ".nx_tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, path)
    return True


# ---------------------------------------------------------------------------------------------------------------
# Prefetch archive (BgmResourceStdPrefetch.aras)
#
# SMO starts each BGM from a "prefetch" copy (FSTP) stored in a group file: an exact copy of the stream's INFO block
# (including the id word) plus the first few blocks of audio. Playback begins from that copy and then continues
# inside the .bfstm. So when a stream is replaced, its prefetch entry has to be rebuilt from the replacement audio,
# otherwise the game plays a snippet of the original and then fails to continue.
# ---------------------------------------------------------------------------------------------------------------

def _fstp_entries(g):
    """id -> dict(off, info_off, info_size, pdat_off, pdat_size, channels, block_size, ref_pos) for every FSTP in g."""
    out = {}
    pos = 0
    while True:
        m = g.find(b"FSTP", pos)
        if m < 0:
            break
        pos = m + 4
        try:
            if g[m + 4:m + 6] != bytes((0xFF, 0xFE)):
                continue
            refs = {t: (o, sz) for t, _, o, sz in
                    (struct.unpack_from("<HHii", g, m + 0x14 + 12 * i) for i in range(struct.unpack_from("<H", g, m + 0x10)[0]))}
            info_off, info_size = refs[0x4000]
            pdat_off, pdat_size = refs[0x4004]
            body = m + info_off + 8
            st = body + struct.unpack_from("<i", g, m + info_off + 12)[0]
            codec, loop, ch, regions = struct.unpack_from("4B", g, st)
            block_size = struct.unpack_from("<I", g, st + 0x14)[0]
            fid = struct.unpack_from("<I", g, st + ID_OFFSET)[0]
            out[fid] = dict(off=m, info_off=m + info_off, info_size=info_size, pdat_off=m + pdat_off,
                            pdat_size=pdat_size, codec=codec, channels=ch, block_size=block_size, stream_start=st)
        except Exception:
            continue
    return out


def rebuild_prefetch_archive(vanilla_aras, vanilla_stream_dir, deployed_stream_dir, out_aras):
    """Regenerate the prefetch archive so every deployed replacement stream has a matching prefetch entry.

    Also syncs each deployed stream's id word with its vanilla target. Returns a report dict.
    """
    import shutil
    with open(vanilla_aras, "rb") as f:
        raw = bytearray(f.read())
    base = raw.find(b"FGRP")
    if base < 0:
        raise BfstmError("FGRP not found in " + vanilla_aras)
    entries = _fstp_entries(bytes(raw))
    rep = dict(rebuilt=[], no_prefetch=[], skipped=[], ids_fixed=[])
    claimed = {}

    for name in sorted(os.listdir(deployed_stream_dir)):
        if not name.endswith(".bfstm"):
            continue
        dpath = os.path.join(deployed_stream_dir, name)
        vpath = os.path.join(vanilla_stream_dir, name)
        if not os.path.isfile(vpath):
            rep["skipped"].append((name, "no vanilla counterpart"))
            continue
        with open(dpath, "rb") as f:
            d = bytearray(f.read())
        if _endian(d) != "<":
            rep["skipped"].append((name, "still big-endian"))
            continue
        vid = read_stream_id(vpath)
        if vid in claimed:
            # Two vanilla streams share the same prefetch stream_id (e.g. StmRsBgmDesertMain & StmRsBgmDesertMainParade,
            # StmRsBgmMoon & StmRsBgmMoonParade). Sync this second file with the first so both match the shared FSTP!
            first_path = os.path.join(deployed_stream_dir, claimed[vid])
            if os.path.isfile(first_path):
                shutil.copyfile(first_path, dpath)
                rep["rebuilt"].append(name)
            continue
        dp = _parse(bytes(d[:0x4000]))
        if dp.get("chan_table_off", 0) - dp["stream_start"] >= 80:
            id_pos = dp["stream_start"] + ID_OFFSET
            if struct.unpack_from("<I", d, id_pos)[0] != vid:
                struct.pack_into("<I", d, id_pos, vid)
                with open(dpath + ".id_tmp", "wb") as f:
                    f.write(d)
                os.replace(dpath + ".id_tmp", dpath)
                rep["ids_fixed"].append(name)

        e = entries.get(vid)
        if e is None:
            rep["no_prefetch"].append(name)
            claimed[vid] = name
            continue
        if e["codec"] != 2 or dp["codec"] != 2:
            rep["skipped"].append((name, "non-ADPCM codec (prefetch %d, stream %d)" % (e["codec"], dp["codec"])))
            continue
        if e["info_size"] != dp["info_size"] or e["channels"] != dp["channels"] or e["block_size"] != dp["block_size"]:
            rep["skipped"].append((name, "layout mismatch"))
            continue
        pdat_audio_size = struct.unpack_from("<I", raw, e["pdat_off"] + 0x10)[0]
        need = e["pdat_size"] - 0x40
        audio_start = dp["data_off"] + 0x20
        if need < 1 or pdat_audio_size != need or len(d) - audio_start < need:
            rep["skipped"].append((name, "non-standard prefetch header or stream shorter than prefetch (%d)" % need))
            continue

        # INFO: our stream's INFO, but keep the prefetch's own sample-data ref offset
        info = bytearray(d[dp["info_off"]:dp["info_off"] + dp["info_size"]])
        ref_pos = (e["stream_start"] - e["info_off"]) + 0x30 + 4  # sample-data ref offset field, inside INFO
        info[ref_pos:ref_pos + 4] = raw[e["info_off"] + ref_pos: e["info_off"] + ref_pos + 4]
        raw[e["info_off"]:e["info_off"] + e["info_size"]] = info
        # PDAT audio = first `need` bytes of our stream's DATA payload
        raw[e["pdat_off"] + 0x40: e["pdat_off"] + 0x40 + need] = d[audio_start: audio_start + need]
        claimed[vid] = name
        rep["rebuilt"].append(name)

    os.makedirs(os.path.dirname(out_aras), exist_ok=True)
    tmp = out_aras + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, out_aras)
    return rep
