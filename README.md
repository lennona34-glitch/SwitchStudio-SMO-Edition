# 🎮 Switch Studio // Super Mario Odyssey RomFS & 3D Modding Suite

An all-in-one visual modding studio for **Super Mario Odyssey** (`0100000000010000`) built for the **Eden Nintendo Switch Emulator**.

Switch Studio lets you customize Mario's 3D head & face from a real photo, scale Mario from **Tiny (0.45x)** or **Kid/Chibi (0.68x)** up to **Titan (3.0x)**, browse and 1-click install **GameBanana Community Kingdom & Texture Packs** (including *Super Mario Galaxy 2*'s **Yoshi Star Galaxy**), swap any of the **130 Background Music (`BFSTM`)** streams, record custom **Voicemod / Foley SFX (`BFSAR` / `ARAS`)** across **5,134 sound effects**, and inject a **100% Completed Game Save (999 Power Moons)**.

---

## ⚡ Emulator Compatibility (Eden Emulator)

This project is built and tested specifically against **Eden Emulator**:

- **Recommended Build:** **Eden Development Build — `master-67bada77f8-master` (`Eden-Windows-67bada77f8-msvc-amd64`, Oct 08 2026)**
  - **Runtime:** Qt `6.11.1` | Switch Firmware `21.2.0`
  - **Official Website:** [https://eden-emu.dev](https://eden-emu.dev)
  - **Official Git Repository:** [https://git.eden-emu.dev/eden-emu/eden](https://git.eden-emu.dev/eden-emu/eden)
  - **Exact Commit (`67bada77f8`):** [https://git.eden-emu.dev/eden-emu/eden/commit/67bada77f8](https://git.eden-emu.dev/eden-emu/eden/commit/67bada77f8)
  - **Official Releases / Nightly Builds:** [https://git.eden-emu.dev/eden-emu/eden/releases](https://git.eden-emu.dev/eden-emu/eden/releases) | [https://github.com/Eden-CI/Nightly/releases](https://github.com/Eden-CI/Nightly/releases)

### Recommended Eden Settings for Modded Kingdoms
- **Memory Layout Mode:** `6GB` (`Core.memory_layout_mode: Memory_6Gb`) — required for large custom 3D kingdoms and high-resolution texture packs.
- **Graphics Backend:** `Vulkan` (`Renderer.resolution_setup: Res2X`, `Renderer.accelerate_astc: Gpu`)
- **Base Game Version:** *Super Mario Odyssey* `v1.0.0` (`0100000000010000`). Switch Studio automatically normalizes `v1.3.0` community mods (such as `BgmDataBase.szs` and `WorldList.szs`) so they run natively on `v1.0.0` without crashes.

---

## ✨ Key Features

### 1. 🧑🎨 3D Textures, Face-Meld & Mario Sizer (`#tab-textures`)
- **Interactive Three.js 3D Preview:** Real-time orbit/zoom viewport inspecting `Mario.bfres`, `MarioHead.bfres`, `MarioFace.bfres`, and `MarioCap.bfres` with live UV texture updates.
- **Seamless 3D Face-Meld & Mesh Reshaper:**
  - Automatically reshapes Mario's 3D facial geometry (`MarioFace.szs` / `MarioHighFace.szs`) into a smooth, child-proportioned portrait surface and hides vanilla mustache/sideburn/hair card strips.
  - Uses Poisson-style seamless frequency-separated skin blending and zero-seam cheek boundary feathering so custom portrait photos blend naturally into Mario's head mesh.
  - Generates matching **Custom Iris & Eye Textures** (`MarioEye.szs` / `MarioHighEye.szs`) and a **Custom Cap Emblem**.
- **🍄 Mario 3D Size & Proportions (`InitPartsFixInfo.byml`):**
  - **1-Click Presets:** `🐜 Tiny (0.45x)`, `🧒 Kid / Chibi (0.68x)`, `🍄 Normal (1.0x)`, `🎈 Big Head (2.0x)`, `🦖 Giant (2.0x)`, and `🏔️ Titan (3.0x)`.
  - **Granular Sliders:** Independent **Full Body Scale (`0.25x` – `4.00x`)**, **Head Ratio (`0.40x` – `3.00x`)**, and **Cap Ratio (`0.40x` – `3.00x`)**.
  - **Zero-Shift SARC Repacker:** Patches `InitPartsFixInfo.byml` in-place inside `Mario.szs`, `MarioHigh.szs`, `MarioHead.szs`, and `MarioCap.szs` while preserving the strict `0x2000` (4096-byte) GPU memory pool alignment required by `nn::g3d::ResFile`.

### 2. 🌟 Community Packs — GameBanana Browser (`#tab-community`)
- **Featured 1-Click Pack — *Yoshi Star Kingdom (Super Mario Galaxy 2)*:**
  - Full custom 3D kingdom port of *Super Mario Galaxy 2*'s **Yoshi Star Galaxy** replacing the **Cascade Kingdom (`WaterfallWorldHomeStage`)** with custom planets, Launch Stars, Sling Stars, Lumas, Yoshi capture missions, and 26 Power Moons.
- **Automatic Odyssey `v1.0.0` Normalization & Heap Optimizer:**
  - Converts all custom `.bfstm` music tracks to `48,000 Hz` Little-Endian Switch DSP-ADPCM matching vanilla channel counts and updates `BgmResourceStdPrefetch.aras` so custom stage music boots with zero slowdown.
  - Strips `v1.3.0`-only `PatchBgmBalloon` and `BalloonScenario` entries and prunes unused vanilla Cascade Kingdom sub-stage archives (`153+ MB` freed in `WorldResourceHeap`) so respawning after losing a life never causes a black screen.
- **Live GameBanana Search:** Search, download, install, and toggle any *Super Mario Odyssey* level, texture, or skin mod directly from GameBanana's API.

### 3. 🎵 Background Music Jukebox (`#tab-bgm`)
- **All 130 Odyssey Streams (`SoundData/stream/*.bfstm`):** Audition any original track in the browser and drag-and-drop `.mp3`, `.wav`, or `.ogg` replacements.
- **Hardware-Verified DSP-ADPCM Encoder (`core/bfstm_nx.py`):** Automatically matches multi-channel track layouts (2ch, 4ch, 6ch, 8ch), patches loop points, and synchronizes the 16 KB prefetch buffer inside `BgmResourceStdPrefetch.aras`.

### 4. 🎙️ Sound Effects & Voicemod Booth (`#tab-sfx`)
- **5,134 Sound Effects (`SoundData/*.aras` + `OdysseyAudio.bfsar`):** Browse by archive (Mario Voice, Cappy, UI, Enemies, Physics) and audition any clip instantly.
- **Built-in WebAudio Voicemod Studio:** Record directly from your microphone with real-time waveform visualization and DSP effects (**Chipmunk / Toad**, **Bowser Monster**, **Mecha Brobot**, **Cave Echo**, **Bitcrush 64**, **Megaphone**) and inject directly into the Switch `.aras` archives.

### 5. 💾 Save Data & Cheat Manager (`core/save_manager.py`)
- **1-Click 100% Save Game (`File1.bin`):** Unlocks all Kingdoms, all outfits, and 999 Power Moons while automatically backing up your existing save files.
- **Respawn-Safe Odyssey `v1.0.0` Cheats (`3CA12DFAAF9C82DA.txt`):** Includes conditional Infinite Health (`HP > 0` check so pit deaths respawn cleanly), 9999 Gold Coins, and All Regional Purple Coins.

---

## 🚀 Quick Start

### 1. Prerequisites
- **Windows 10 / 11 (64-bit)**
- **Python 3.11 or 3.12**
- **Eden Emulator (`master-67bada77f8-master`)** installed at `~/Desktop/Switch Emu/eden.exe` (or set via `EDEN_EXE`)
- **Extracted Super Mario Odyssey `v1.0.0` RomFS** in `../odyssey_romfs` (or set via `ODYSSEY_ROMFS_DIR`)

### 2. Install Python Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Launch Switch Studio
Double-click **`start_studio.bat`** or run:
```powershell
python -X utf8 server.py
```
Then open **[http://localhost:5050](http://localhost:5050)** in your browser.

---

## 📁 Project Structure

```text
switch_studio/
├── server.py               # HTTP API & static asset server (port 5050)
├── start_studio.bat        # One-click Windows launcher
├── requirements.txt        # Python dependencies (oead, Pillow, numpy, scipy, psutil)
├── track_specs.json        # Exact channel & sample-rate metadata for all 130 BGM streams
├── core/
│   ├── engine.py           # RomFS SARC/Yaz0 packer, BNTX injector, Mario Sizer & GameBanana installer
│   ├── face_reshape.py     # 3D facial mesh vertex reshaper & UV projector
│   ├── model_view.py       # BFRES -> OBJ/MTL 3D geometry & texture extractor for Three.js
│   ├── bfstm_nx.py         # Switch BFSTM v4.0 header patcher & ARAS prefetch synchronizer
│   ├── bfsar_sfx.py        # BFSAR / ARAS sound effect parser, extractor & injector
│   └── save_manager.py     # Super Mario Odyssey save file (File1.bin) & backup manager
├── tools/                  # C# source code for Switch Toolbox CLI helpers (BNTX, BFRES, VGAudio)
└── web/
    ├── index.html          # Studio UI layout (3D Viewport, Community Packs, BGM, SFX, Save Modal)
    ├── app.js              # Three.js renderer, WebAudio Voicemod DSP & API client
    └── style.css           # Switch dark-mode neon UI theme
```

---

## ⚖️ License & Disclaimer

This repository contains **no copyrighted Nintendo game assets, ROMs, keys, or firmware**. You must provide your own legally dumped *Super Mario Odyssey* RomFS (`odyssey_romfs/`) to use this tool.
