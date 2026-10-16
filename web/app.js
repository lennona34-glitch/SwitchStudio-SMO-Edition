// SWITCH STUDIO - SUPER MARIO ODYSSEY ENGINE CLIENT

// State
let currentSlots = [];
let activeSlotId = "mario_body";
let bgmTracks = [];
let filteredBgmTracks = [];
let activeBgmTrack = null;
let sfxTracks = [];
let filteredSfxTracks = [];
let activeSfxTrack = null;
let autoPlayBgm = localStorage.getItem("ss_autoPlayBgm") === "1";
let autoPlaySfx = localStorage.getItem("ss_autoPlaySfx") === "1";

let uploadedTextureFile = null;
let uploadedBgmFile = null;
let uploadedSfxFile = null;

// Three.js State
let scene, camera, renderer, controls;
let activeMesh = null;
let autoRotate = true;
let isZenMode = false;

// Audio & Recording State
let currentAudioElement = null;
let audioCtx = null;
let mediaRecorder = null;
let recordedChunks = [];
let recordedBlob = null;
let micStream = null;

document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initGlobalAudioPlayer();
    initZenMode();
    loadStatus();
    loadTextures();
    loadBgm();
    initJukeboxScanner();
    loadSfx();
    initTextureControls();
    init3DViewer();
    initMarioScale();
    initCommunityPacks();
    initVoiceMod();
    initEdenLaunchers();
    initSavesAndMods();
    loadSavesAndMods();
});

// ========================================================
// TABS & NAVIGATION
// ========================================================
function initTabs() {
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.dataset.tab;
            switchTab(targetTab);
        });
    });

    // Tool switcher within Textures tab
    document.querySelectorAll(".tool-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            document.querySelectorAll(".tool-pill").forEach(p => p.classList.remove("active"));
            document.querySelectorAll(".tool-pane").forEach(pane => pane.classList.remove("active"));
            pill.classList.add("active");
            const target = document.getElementById("tool-" + pill.dataset.tool);
            if (target) target.classList.add("active");
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.tab === tabId);
    });
    document.querySelectorAll(".tab-pane").forEach(pane => {
        pane.classList.toggle("active", pane.id === "tab-" + tabId);
    });

    if (tabId === "textures" && renderer) {
        onWindowResize();
    } else if (tabId === "community") {
        loadCommunityPacks();
    } else if (tabId === "saves") {
        loadSavesAndMods();
    }
}

// ========================================================
// GLOBAL AUDIO SYNCHRONIZER & NOW PLAYING BAR
// ========================================================
function syncAutoPlayUI() {
    const chkBgm = document.getElementById("checkAutoPlayBgm");
    const chkSfx = document.getElementById("checkAutoPlaySfx");
    const btnGlobalAuto = document.getElementById("btnGlobalAutoNext");
    if (chkBgm) chkBgm.checked = autoPlayBgm;
    if (chkSfx) chkSfx.checked = autoPlaySfx;
    if (btnGlobalAuto) {
        const sfxPlayer = document.getElementById("sfxAudioPlayer");
        const activeAuto = (currentAudioElement === sfxPlayer) ? autoPlaySfx : (autoPlayBgm || autoPlaySfx);
        btnGlobalAuto.style.color = activeAuto ? "var(--accent-cyan)" : "";
        btnGlobalAuto.style.borderColor = activeAuto ? "var(--accent-cyan)" : "";
        btnGlobalAuto.textContent = activeAuto ? "🔁 Auto: ON" : "🔁 Auto";
    }
}

function playAdjacentBgm(step = 1) {
    const list = filteredBgmTracks.length ? filteredBgmTracks : bgmTracks;
    if (!list.length) return;
    let idx = activeBgmTrack ? list.findIndex(t => t.filename === activeBgmTrack.filename) : -1;
    idx = (idx + step + list.length) % list.length;
    playBgmTrack(list[idx]);
}

function playAdjacentSfx(step = 1) {
    const list = filteredSfxTracks.length ? filteredSfxTracks : sfxTracks;
    if (!list.length) return;
    let idx = activeSfxTrack ? list.findIndex(t => t.filename === activeSfxTrack.filename) : -1;
    idx = (idx + step + list.length) % list.length;
    if (idx >= sfxRenderLimit) {
        sfxRenderLimit = idx + 100;
        renderSfxList(list);
    }
    playSfxTrack(list[idx]);
}

function initGlobalAudioPlayer() {
    const bgmPlayer = document.getElementById("bgmAudioPlayer");
    const sfxPlayer = document.getElementById("sfxAudioPlayer");
    const btnPlayPause = document.getElementById("btnGlobalPlayPause");
    const btnStop = document.getElementById("btnGlobalStop");
    const btnPrev = document.getElementById("btnGlobalPrev");
    const btnNext = document.getElementById("btnGlobalNext");
    const btnAutoNext = document.getElementById("btnGlobalAutoNext");
    const pill = document.getElementById("globalAudioPill");

    const chkAutoBgm = document.getElementById("checkAutoPlayBgm");
    const chkAutoSfx = document.getElementById("checkAutoPlaySfx");
    const btnPrevBgm = document.getElementById("btnPrevBgm");
    const btnNextBgm = document.getElementById("btnNextBgm");
    const btnPrevSfx = document.getElementById("btnPrevSfx");
    const btnNextSfx = document.getElementById("btnNextSfx");

    syncAutoPlayUI();

    if (chkAutoBgm) {
        chkAutoBgm.addEventListener("change", (e) => {
            autoPlayBgm = e.target.checked;
            localStorage.setItem("ss_autoPlayBgm", autoPlayBgm ? "1" : "0");
            syncAutoPlayUI();
            showToast(autoPlayBgm ? "🔁 BGM Auto-Play Next: ON" : "BGM Auto-Play Next: OFF");
        });
    }
    if (chkAutoSfx) {
        chkAutoSfx.addEventListener("change", (e) => {
            autoPlaySfx = e.target.checked;
            localStorage.setItem("ss_autoPlaySfx", autoPlaySfx ? "1" : "0");
            syncAutoPlayUI();
            showToast(autoPlaySfx ? "🔁 SFX Auto-Play Next: ON" : "SFX Auto-Play Next: OFF");
        });
    }
    if (btnPrevBgm) btnPrevBgm.addEventListener("click", () => playAdjacentBgm(-1));
    if (btnNextBgm) btnNextBgm.addEventListener("click", () => playAdjacentBgm(1));
    if (btnPrevSfx) btnPrevSfx.addEventListener("click", () => playAdjacentSfx(-1));
    if (btnNextSfx) btnNextSfx.addEventListener("click", () => playAdjacentSfx(1));

    // Hook BGM Player
    bgmPlayer.addEventListener("play", () => {
        if (sfxPlayer && !sfxPlayer.paused) sfxPlayer.pause();
        currentAudioElement = bgmPlayer;
        syncAutoPlayUI();
        updateGlobalAudioState(true, activeBgmTrack ? activeBgmTrack.title : "BGM Track", "MUSIC");
    });
    bgmPlayer.addEventListener("pause", () => {
        if (currentAudioElement === bgmPlayer) updateGlobalAudioState(false);
    });
    bgmPlayer.addEventListener("ended", () => {
        if (currentAudioElement === bgmPlayer) updateGlobalAudioState(false);
        if (autoPlayBgm) playAdjacentBgm(1);
    });

    // Hook SFX Player
    sfxPlayer.addEventListener("play", () => {
        if (bgmPlayer && !bgmPlayer.paused) bgmPlayer.pause();
        currentAudioElement = sfxPlayer;
        syncAutoPlayUI();
        updateGlobalAudioState(true, activeSfxTrack ? activeSfxTrack.title : "Sound Effect", "SFX");
    });
    sfxPlayer.addEventListener("pause", () => {
        if (currentAudioElement === sfxPlayer) updateGlobalAudioState(false);
    });
    sfxPlayer.addEventListener("ended", () => {
        if (currentAudioElement === sfxPlayer) updateGlobalAudioState(false);
        if (autoPlaySfx) playAdjacentSfx(1);
    });

    // Header buttons
    if (btnPrev) {
        btnPrev.addEventListener("click", (e) => {
            e.stopPropagation();
            if (currentAudioElement === sfxPlayer) playAdjacentSfx(-1);
            else playAdjacentBgm(-1);
        });
    }
    if (btnNext) {
        btnNext.addEventListener("click", (e) => {
            e.stopPropagation();
            if (currentAudioElement === sfxPlayer) playAdjacentSfx(1);
            else playAdjacentBgm(1);
        });
    }
    if (btnAutoNext) {
        btnAutoNext.addEventListener("click", (e) => {
            e.stopPropagation();
            const nextState = !(autoPlayBgm && autoPlaySfx);
            autoPlayBgm = nextState;
            autoPlaySfx = nextState;
            localStorage.setItem("ss_autoPlayBgm", nextState ? "1" : "0");
            localStorage.setItem("ss_autoPlaySfx", nextState ? "1" : "0");
            syncAutoPlayUI();
            showToast(nextState ? "🔁 Auto-Play Next enabled for Music & Sound Effects" : "Auto-Play Next disabled");
        });
    }

    btnPlayPause.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!currentAudioElement) {
            // If nothing loaded yet, play first BGM track
            if (bgmTracks.length > 0) playBgmTrack(bgmTracks[0]);
            return;
        }
        if (currentAudioElement.paused) {
            currentAudioElement.play();
        } else {
            currentAudioElement.pause();
        }
    });

    btnStop.addEventListener("click", (e) => {
        e.stopPropagation();
        if (currentAudioElement) {
            currentAudioElement.pause();
            currentAudioElement.currentTime = 0;
            updateGlobalAudioState(false);
        }
    });

    // Clicking header pill navigates to the active audio tab
    pill.addEventListener("click", () => {
        if (currentAudioElement === sfxPlayer) {
            switchTab("sfx");
        } else {
            switchTab("music");
        }
    });
}

function updateGlobalAudioState(isPlaying, title = "", category = "AUDIO") {
    const pill = document.getElementById("globalAudioPill");
    const statusLabel = document.getElementById("globalAudioStatus");
    const titleEl = document.getElementById("globalAudioTitle");
    const playPauseBtn = document.getElementById("btnGlobalPlayPause");
    const zenTrack = document.getElementById("zenTrackName");
    const zenSub = document.getElementById("zenTrackSub");
    const zenPlayPause = document.getElementById("btnZenPlayPause");

    if (isPlaying) {
        pill.classList.add("playing");
        statusLabel.textContent = `PLAYING • ${category}`;
        titleEl.textContent = title;
        playPauseBtn.textContent = "⏸";
        document.title = `▶ ${title} // Switch Studio`;

        if (zenTrack) zenTrack.textContent = title;
        if (zenSub) zenSub.textContent = `Super Mario Odyssey [${category}]`;
        if (zenPlayPause) zenPlayPause.textContent = "⏸";
    } else {
        pill.classList.remove("playing");
        statusLabel.textContent = "IDLE";
        playPauseBtn.textContent = "▶";
        if (zenPlayPause) zenPlayPause.textContent = "▶";
        document.title = "Switch Studio // Super Mario Odyssey Editor";
    }
}

// ========================================================
// ZEN MODE
// ========================================================
// ZEN / MAXIMIZE SCREEN MODE
// ========================================================
function initZenMode() {
    const btnToggle = document.getElementById("btnZenToggle");

    btnToggle.addEventListener("click", () => {
        toggleZenMode(!isZenMode);
    });

    // Keyboard shortcut 'Z' and 'Escape'
    window.addEventListener("keydown", (e) => {
        if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
        if (e.key === "z" || e.key === "Z") {
            toggleZenMode(!isZenMode);
        } else if (e.key === "Escape" && isZenMode) {
            toggleZenMode(false);
        }
    });

    document.addEventListener("fullscreenchange", () => {
        if (!document.fullscreenElement && isZenMode) {
            toggleZenMode(false);
        }
    });
}

function toggleZenMode(enable) {
    isZenMode = enable;
    const btnToggle = document.getElementById("btnZenToggle");

    if (enable) {
        if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
            document.documentElement.requestFullscreen().catch(err => console.log("Fullscreen request:", err));
        }
        document.body.classList.add("zen-maximized");
        if (btnToggle) btnToggle.innerHTML = '<span class="zen-icon">🗗</span> Exit Maximize';
        showToast("⛶ Maximized Screen Mode (Press 'Z' or Esc to restore)");
    } else {
        if (document.fullscreenElement && document.exitFullscreen) {
            document.exitFullscreen().catch(err => console.log("Exit fullscreen:", err));
        }
        document.body.classList.remove("zen-maximized");
        if (btnToggle) btnToggle.innerHTML = '<span class="zen-icon">⛶</span> Maximize Screen';
        showToast("Restored Screen");
    }

    setTimeout(() => {
        if (typeof onWindowResize === "function") onWindowResize();
    }, 150);
}

// ========================================================
// STATUS & EMULATOR INFO
// ========================================================
async function loadStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();
        const pill = document.getElementById("statusPill");
        if (data.eden_available) {
            pill.innerHTML = `<span class="indicator-dot online"></span><span class="status-label">Eden: Online</span>`;
        } else {
            pill.innerHTML = `<span class="indicator-dot" style="background:#ff9800;"></span><span class="status-label">Eden: Standby</span>`;
        }
        const dispName = document.getElementById("dispModName");
        if (dispName) dispName.textContent = data.active_mod;
    } catch (e) {
        console.error("Status check failed", e);
    }
}

// ========================================================
// TAB 1: 3D MODELS & TEXTURES
// ========================================================
async function loadTextures() {
    try {
        const res = await fetch("/api/textures");
        currentSlots = await res.json();
        const list = document.getElementById("slotList");
        list.innerHTML = "";

        currentSlots.forEach(slot => {
            const el = document.createElement("div");
            el.className = `slot-item ${slot.id === activeSlotId ? "active" : ""}`;
            el.dataset.id = slot.id;
            el.innerHTML = `
                <div class="slot-item-title">
                    <span>${slot.title}</span>
                </div>
                <div class="slot-item-desc">${slot.format} • ${slot.width}×${slot.height}</div>
            `;
            el.addEventListener("click", () => selectSlot(slot.id));
            list.appendChild(el);
        });

        document.getElementById("channelCount").textContent = `${currentSlots.length} Components`;
        selectSlot(activeSlotId);
    } catch (e) {
        console.error("Failed to load textures", e);
    }
}

function selectSlot(slotId) {
    activeSlotId = slotId;
    document.querySelectorAll(".slot-item").forEach(item => {
        item.classList.toggle("active", item.dataset.id === slotId);
    });

    const slot = currentSlots.find(s => s.id === slotId);
    if (!slot) return;

    document.getElementById("activeSlotTitle").textContent = slot.title;
    document.getElementById("metaDim").textContent = `${slot.width} × ${slot.height}`;
    document.getElementById("metaFormat").textContent = slot.format;

    // Refresh 2D preview images
    const t = Date.now();
    document.getElementById("imgVanilla").src = `/api/texture/preview?slot=${slotId}&type=orig&t=${t}`;
    document.getElementById("imgModded").src = `/api/texture/preview?slot=${slotId}&type=mod&t=${t}`;

    // Update 3D model texture
    update3DTexture(slotId);
    updateProjectControls();
    drawUVOverlays();
}

function initTextureControls() {
    // 2D / 3D Toggle
    const btn2D = document.getElementById("btnView2D");
    const btn3D = document.getElementById("btnView3D");
    const stage2D = document.getElementById("stage2D");
    const stage3D = document.getElementById("stage3D");

    btn2D.addEventListener("click", () => {
        btn2D.classList.add("active");
        btn3D.classList.remove("active");
        stage2D.style.display = "flex";
        stage3D.style.display = "none";
    });

    btn3D.addEventListener("click", () => {
        btn3D.classList.add("active");
        btn2D.classList.remove("active");
        stage2D.style.display = "none";
        stage3D.style.display = "block";
        onWindowResize();
    });

    // Color Alchemy Sliders
    const sHue = document.getElementById("sliderHue");
    const sSat = document.getElementById("sliderSat");
    const sVal = document.getElementById("sliderVal");
    const cInv = document.getElementById("checkInvert");

    sHue.addEventListener("input", () => document.getElementById("valHue").textContent = `${sHue.value}°`);
    sSat.addEventListener("input", () => document.getElementById("valSat").textContent = `${parseFloat(sSat.value).toFixed(2)}x`);
    sVal.addEventListener("input", () => document.getElementById("valVal").textContent = `${parseFloat(sVal.value).toFixed(2)}x`);

    const liveRecolor = debounce(() => applyRecolor(true), 250);
    [sHue, sSat, sVal].forEach(el => el.addEventListener("input", liveRecolor));
    cInv.addEventListener("change", liveRecolor);

    // Photo Drop Zone
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");

    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.style.borderColor = "var(--neon-blue)"; });
    dropZone.addEventListener("dragleave", () => { dropZone.style.borderColor = ""; });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.style.borderColor = "";
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleUploadedPhoto(e.dataTransfer.files[0]);
        }
    });
    fileInput.addEventListener("change", () => {
        if (fileInput.files && fileInput.files[0]) {
            handleUploadedPhoto(fileInput.files[0]);
        }
    });

    // Sliders for Photo
    const sScale = document.getElementById("sliderScale");
    const sFeather = document.getElementById("sliderFeather");
    const sOpacity = document.getElementById("sliderOpacity");
    sScale.addEventListener("input", () => document.getElementById("valScale").textContent = `${parseFloat(sScale.value).toFixed(2)}x`);
    sFeather.addEventListener("input", () => document.getElementById("valFeather").textContent = `${sFeather.value}px`);
    sOpacity.addEventListener("input", () => document.getElementById("valOpacity").textContent = `${Math.round(sOpacity.value * 100)}%`);

    const liveComposite = debounce(() => { if (uploadedTextureFile) applyComposite(true); }, 250);
    ["sliderScale", "sliderFeather", "sliderOpacity", "sliderOffX", "sliderOffY", "sliderRotate"].forEach(id => {
        document.getElementById(id).addEventListener("input", () => { liveComposite(); drawUVOverlays(); });
    });
    document.getElementById("sliderRotate").addEventListener("input", (e) => {
        document.getElementById("valRotate").textContent = `${e.target.value}°`;
    });
    initUVOverlay();

    // Commit / Swizzle NVN
    document.getElementById("btnCommitSlot").addEventListener("click", async () => {
        showToast("⚙️ Swizzling and deploying every edited texture to Eden...");
        try {
            const res = await fetch("/api/texture/commit_all", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
            const data = await res.json();
            if (data.error) { showToast("Deploy failed: " + data.error); return; }
            if (!data.results.length) { showToast("Nothing to deploy - everything is already original."); return; }
            const ok = data.results.filter(r => r.ok && !r.restored_vanilla).map(r => r.title);
            const back = data.results.filter(r => r.restored_vanilla).map(r => r.title);
            const bad = data.results.filter(r => !r.ok);
            let msg = ok.length ? `⚡ Deployed to Eden: ${ok.join(", ")}.` : "";
            if (back.length) msg += ` ↩️ Back to the original: ${back.join(", ")}.`;
            if (msg) msg += " Restart the game to see it.";
            if (bad.length) msg += ` ⚠️ Failed: ${bad.map(r => r.title + " (" + r.error + ")").join("; ")}`;
            showToast(msg.trim());
        } catch (e) {
            showToast("Commit failed: " + e.message);
        }
    });

    // Presets
    document.getElementById("btnPresetEmerald").addEventListener("click", async () => {
        showToast("🌿 Injecting Emerald Outfit preset...");
        try {
            const res = await fetch("/api/texture/apply_preset", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ preset: "emerald_outlaw" })
            });
            const data = await res.json();
            if (data.success) {
                showToast("🌿 Emerald Outfit deployed!");
                selectSlot(activeSlotId);
            }
        } catch (e) {
            showToast("Preset failed: " + e.message);
        }
    });

    document.getElementById("btnResetSlot").addEventListener("click", async () => {
        try {
            const res = await fetch("/api/texture/reset", { method: "POST", headers: { "Content-Type": "application/json" },
                                                            body: JSON.stringify({ slot: activeSlotId }) });
            const data = await res.json();
            if (!data.success) { showToast("Reset failed: " + data.error); return; }
            showToast("Reset to the original texture" + (data.backup ? " (your edit is kept as " + data.backup.split(/[\\/]/).pop() + ")" : "") +
                      ". Press Swizzle & Deploy to apply it in the game.");
            selectSlot(activeSlotId);
        } catch (e) {
            showToast("Reset failed: " + e.message);
        }
    });

    // Auto-rotate toggle
    document.getElementById("btnToggleRotate").addEventListener("click", (e) => {
        autoRotate = !autoRotate;
        e.target.textContent = `Auto-Spin: ${autoRotate ? "ON" : "OFF"}`;
    });
}

function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

async function applyRecolor(quiet) {
    try {
        const res = await fetch("/api/texture/recolor", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                slot: activeSlotId,
                hue: parseFloat(document.getElementById("sliderHue").value),
                saturation: parseFloat(document.getElementById("sliderSat").value),
                brightness: parseFloat(document.getElementById("sliderVal").value),
                invert: document.getElementById("checkInvert").checked
            })
        });
        const data = await res.json();
        if (data.success) {
            if (!quiet) showToast("✨ Color alchemy preview generated!");
            selectSlot(activeSlotId);
        }
    } catch (e) {
        showToast("Recolor failed: " + e.message);
    }
}

const FACE_OFFSET_UNITS_PER_PX = 0.25;   // must match FACE_OFFSET_UNITS_PER_PX / FACE_CENTRE_Y in core/engine.py
const FACE_CENTRE_Y = 8.0;

function isProjectMode() {
    return activeSlotId === "mario_face";          // portraits are always projected onto the 3D face
}

function updateProjectControls() {
    document.getElementById("rowRotate").style.display = isProjectMode() ? "" : "none";
}

async function applyComposite(quiet) {
    if (!uploadedTextureFile) {
        showToast("Please drop or browse an image first!");
        return;
    }
    const fd = new FormData();
    fd.append("file", uploadedTextureFile);
    fd.append("slot", activeSlotId);
    fd.append("scale", document.getElementById("sliderScale").value);
    fd.append("offset_x", document.getElementById("sliderOffX").value);
    fd.append("offset_y", document.getElementById("sliderOffY").value);
    fd.append("feather", document.getElementById("sliderFeather").value);
    fd.append("opacity", document.getElementById("sliderOpacity").value);
    fd.append("mode", isProjectMode() ? "project" : "flat");
    fd.append("rotation", document.getElementById("sliderRotate").value);
    try {
        const res = await fetch("/api/texture/composite", { method: "POST", body: fd });
        const data = await res.json();
        if (data.success) {
            if (!quiet) showToast("📷 Photo melded to UV mesh!");
            selectSlot(activeSlotId);
        }
    } catch (e) {
        showToast("Meld failed: " + e.message);
    }
}

// ========================================================
// UV MAP OVERLAY (where the real mesh samples the texture) + click-to-place for the photo meld
// ========================================================
let uvOverlayOn = false;
const uvCache = {};

async function getUVLayout(slotId) {
    if (!uvCache[slotId]) {
        const res = await fetch(`/api/model/uv?slot=${slotId}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        uvCache[slotId] = data;
    }
    return uvCache[slotId];
}

function initUVOverlay() {
    document.getElementById("btnUVOverlay").addEventListener("click", () => {
        uvOverlayOn = !uvOverlayOn;
        document.getElementById("btnUVOverlay").classList.toggle("active", uvOverlayOn);
        if (uvOverlayOn) document.getElementById("btnView2D").click();
        drawUVOverlays();
    });

    ["imgVanilla", "imgModded"].forEach(id => {
        document.getElementById(id).addEventListener("load", drawUVOverlays);
    });
    window.addEventListener("resize", () => drawUVOverlays());

    // click on the edited texture's UV map -> centre the portrait there
    document.getElementById("imgModdedUV").addEventListener("click", async (e) => {
        const slot = currentSlots.find(s => s.id === activeSlotId);
        if (!slot) return;
        const r = e.target.getBoundingClientRect();
        const u = (e.clientX - r.left) / r.width, v = (e.clientY - r.top) / r.height;
        const layout = await getUVLayout(activeSlotId);
        const [bcx, bcy] = layout.composite_center;
        if (isProjectMode()) {
            // the photo is projected onto the 3D face, so ask where on the face this texel sits
            const res = await fetch(`/api/model/face_point?u=${u}&v=${v}`);
            if (!res.ok) { showToast("That spot isn't on the front of the face"); return; }
            const pt = await res.json();
            setPlacement(pt.x / FACE_OFFSET_UNITS_PER_PX, -(pt.y - FACE_CENTRE_Y) / FACE_OFFSET_UNITS_PER_PX);
        } else {
            setPlacement((u - bcx) * slot.width, (v - bcy) * slot.height);
        }
        const pill = document.querySelector('.tool-pill[data-tool="composite"]');
        if (pill && !pill.classList.contains("active")) pill.click();
    });

}

function setPlacement(offX, offY) {
    const clamp = (v) => Math.max(-256, Math.min(256, Math.round(v)));
    document.getElementById("sliderOffX").value = clamp(offX);
    document.getElementById("sliderOffY").value = clamp(offY);
    drawUVOverlays();
    if (uploadedTextureFile) applyComposite(true);
}

async function drawUVOverlays() {
    document.getElementById("imgModdedUV").classList.toggle("placeable", uvOverlayOn);
    let layout = null;
    if (uvOverlayOn) {
        try { layout = await getUVLayout(activeSlotId); } catch (e) { console.error(e); }
    }

    for (const id of ["imgVanilla", "imgModded"]) {
        const img = document.getElementById(id), cv = document.getElementById(id + "UV");
        if (!uvOverlayOn || !layout || !img.complete || !img.naturalWidth) { cv.style.display = "none"; continue; }
        cv.style.display = "block";
        const W = img.clientWidth, H = img.clientHeight;
        cv.width = W; cv.height = H; cv.style.width = W + "px"; cv.style.height = H + "px";
        const ctx = cv.getContext("2d");
        ctx.clearRect(0, 0, W, H);
        ctx.strokeStyle = "rgba(0, 255, 200, 0.55)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        const e = layout.edges;
        for (let i = 0; i < e.length; i += 4) {
            // UVs outside 0..1 wrap (the texture repeats): draw each edge in the tile its midpoint falls in
            const su = Math.floor((e[i] + e[i + 2]) / 2), sv = Math.floor((e[i + 1] + e[i + 3]) / 2);
            ctx.moveTo((e[i] - su) * W, (e[i + 1] - sv) * H);
            ctx.lineTo((e[i + 2] - su) * W, (e[i + 3] - sv) * H);
        }
        ctx.stroke();

        // where the photo will land (centre of the portrait) on the edited texture
        const slot = currentSlots.find(s => s.id === activeSlotId);
        if (id === "imgModded" && slot && layout.composite_center && !isProjectMode()) {
            const cx = layout.composite_center[0] + (parseFloat(document.getElementById("sliderOffX").value) || 0) / slot.width;
            const cy = layout.composite_center[1] + (parseFloat(document.getElementById("sliderOffY").value) || 0) / slot.height;
            ctx.strokeStyle = "#ff2a5f"; ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(cx * W - 9, cy * H); ctx.lineTo(cx * W + 9, cy * H);
            ctx.moveTo(cx * W, cy * H - 9); ctx.lineTo(cx * W, cy * H + 9);
            ctx.stroke();
        }
    }
}

// ========================================================
// AUTO-ALIGNED PORTRAIT: find the face, straighten it, crop it to the face outline, and size/position it so the
// eyes land on Mario's eyes. The result is a 512x512 cutout the server projects onto the 3D face with neutral settings.
// Face detection is MediaPipe's FaceLandmarker, run in the browser (library + ~4 MB model fetched on first use).
// ========================================================
const MP_VERSION = "0.10.14";
const MP_MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const EYE_RIGHT = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246];
const EYE_LEFT = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398];
const FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148,
    176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];
// Layout of the aligned image (matches core/engine.py: 512px spans 64 model units, centre = height 8 above the chin line)
const ALIGN = { size: 512, eyeX: 256, eyeY: 184, faceWidth: 416 };

let faceLandmarker = null, faceLandmarkerPromise = null;
let uploadedOriginalFile = null;

function getFaceLandmarker() {
    if (!faceLandmarkerPromise) {
        faceLandmarkerPromise = (async () => {
            const base = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}`;
            const vision = await import(`${base}/vision_bundle.mjs`);
            const files = await vision.FilesetResolver.forVisionTasks(`${base}/wasm`);
            faceLandmarker = await vision.FaceLandmarker.createFromOptions(files, {
                baseOptions: { modelAssetPath: MP_MODEL },
                runningMode: "IMAGE",
                numFaces: 1
            });
            return faceLandmarker;
        })().catch((e) => { console.error("Face detector failed to load", e); faceLandmarkerPromise = null; return null; });
    }
    return faceLandmarkerPromise;
}

async function autoAlignPhoto(file) {
    const bmp = await createImageBitmap(file);
    const lm = await getFaceLandmarker();
    let found = null;
    if (lm) {
        const res = lm.detect(bmp);
        if (res.faceLandmarks && res.faceLandmarks.length) {
            found = res.faceLandmarks[0].map(p => ({ x: p.x * bmp.width, y: p.y * bmp.height, z: p.z * bmp.width }));
        }
    }

    const c = document.createElement("canvas");
    c.width = c.height = ALIGN.size;
    const g = c.getContext("2d");

    if (!found) {
        // no face found: centre the whole picture, fitted to the face area
        const k = Math.min(ALIGN.faceWidth * 1.2 / bmp.width, ALIGN.faceWidth * 1.4 / bmp.height);
        g.drawImage(bmp, ALIGN.size / 2 - bmp.width * k / 2, ALIGN.size / 2 - bmp.height * k / 2, bmp.width * k, bmp.height * k);
        return { canvas: c, found: false };
    }

    // eyes: iris centres if available (478 landmarks), otherwise the eye corners
    const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 });
    let e1 = found.length > 473 ? found[468] : mid(found[33], found[133]);
    let e2 = found.length > 473 ? found[473] : mid(found[362], found[263]);
    if (e1.x > e2.x) [e1, e2] = [e2, e1];
    const eyeMid = mid(e1, e2);
    const angle = Math.atan2(e2.y - e1.y, e2.x - e1.x);              // head tilt in the photo
    const faceW = Math.hypot(found[454].x - found[234].x, found[454].y - found[234].y);
    const k = ALIGN.faceWidth / faceW;

    const place = (ctx) => {
        ctx.translate(ALIGN.eyeX, ALIGN.eyeY);
        ctx.rotate(-angle);
        ctx.scale(k, k);
        ctx.translate(-eyeMid.x, -eyeMid.y);
    };

    // soft face-outline mask
    const m = document.createElement("canvas");
    m.width = m.height = ALIGN.size;
    const mg = m.getContext("2d");
    mg.filter = "blur(5px)";
    mg.fillStyle = "#fff";
    mg.save(); place(mg);
    mg.beginPath();
    FACE_OVAL.forEach((i, n) => n ? mg.lineTo(found[i].x, found[i].y) : mg.moveTo(found[i].x, found[i].y));
    mg.closePath(); mg.fill();
    mg.restore();

    g.save(); place(g); g.drawImage(bmp, 0, 0); g.restore();
    g.globalCompositeOperation = "destination-in";
    g.drawImage(m, 0, 0);

    // Paint out the photo's own eyes with the person's skin tone (sampled from the cheeks): Mario's eyeballs go there.
    {
        let r = 0, gr = 0, b = 0, n = 0;
        [-80, 80].forEach(dx => {
            const px = g.getImageData(ALIGN.eyeX + dx - 20, ALIGN.eyeY + 95, 40, 30).data;
            for (let i = 0; i < px.length; i += 4) { if (px[i + 3] > 200) { r += px[i]; gr += px[i + 1]; b += px[i + 2]; n++; } }
        });
        const skin = n > 200 ? `rgb(${Math.round(r / n)},${Math.round(gr / n)},${Math.round(b / n)})` : "rgb(232,190,165)";
        const h = document.createElement("canvas");
        h.width = h.height = ALIGN.size;
        const hg = h.getContext("2d");
        hg.filter = "blur(8px)";
        hg.fillStyle = skin;
        [EYE_LEFT, EYE_RIGHT].forEach(idx => {
            const pts = idx.map(i => found[i]);
            const cx = pts.reduce((a, p) => a + p.x, 0) / pts.length, cy = pts.reduce((a, p) => a + p.y, 0) / pts.length;
            hg.save(); place(hg);
            hg.beginPath();
            pts.forEach((p, i) => {
                // wider than the eye (including inner tear-duct shadow); below it much taller, to wipe out the under-eye
                // shadow; above it only just past the lid, so the eyebrows are left as photographed
                const above = p.y < cy;
                const x = cx + (p.x - cx) * 1.85, y = cy + (p.y - cy) * (above ? 1.35 : 3.8);
                i ? hg.lineTo(x, y) : hg.moveTo(x, y);
            });
            hg.closePath(); hg.fill();
            hg.restore();
        });
        g.globalCompositeOperation = "source-atop";          // only where the photo is opaque
        g.drawImage(h, 0, 0);
        g.globalCompositeOperation = "source-over";
    }

    // Mario's eyes are closer together than most people's (7.9 units either side of centre = 63px in this layout).
    // Squeeze the middle of the face horizontally so the photo's eyes land exactly on Mario's eyeballs, and leave the
    // outer face (cheeks, jaw) where it is so it still meets the rest of his head. Done in 2px vertical strips.
    const TARGET_EYE = 63, HALF_FACE = ALIGN.faceWidth / 2;
    const halfEyes = Math.hypot(e2.x - e1.x, e2.y - e1.y) / 2 * k;      // half eye distance in this layout
    const srcOffset = (d) => {                                         // dest offset from centre -> source offset
        const a = Math.abs(d);
        let s;
        if (a <= TARGET_EYE) s = a * halfEyes / TARGET_EYE;
        else if (a <= HALF_FACE) s = halfEyes + (a - TARGET_EYE) * (HALF_FACE - halfEyes) / (HALF_FACE - TARGET_EYE);
        else s = a;
        return Math.sign(d) * s;
    };
    const w = document.createElement("canvas");
    w.width = w.height = ALIGN.size;
    const wg = w.getContext("2d");
    const STRIP = 2;
    for (let dx = 0; dx < ALIGN.size; dx += STRIP) {
        const s0 = ALIGN.eyeX + srcOffset(dx - ALIGN.eyeX), s1 = ALIGN.eyeX + srcOffset(dx + STRIP - ALIGN.eyeX);
        if (s1 - s0 > 0.01) wg.drawImage(c, s0, 0, s1 - s0, ALIGN.size, dx, 0, STRIP, ALIGN.size);
    }
    // Depth for reshaping Mario's face: the landmarks in the same layout the texture uses, converted to model units
    // (8px per unit; height 8 at the middle of the layout), depth relative to the eye line, towards the camera positive.
    const fwd = (sx) => {                                            // source offset from centre -> dest offset
        const a = Math.abs(sx);
        let d;
        if (a <= halfEyes) d = a * TARGET_EYE / halfEyes;
        else if (a <= HALF_FACE) d = TARGET_EYE + (a - halfEyes) * (HALF_FACE - TARGET_EYE) / (HALF_FACE - halfEyes);
        else d = a;
        return Math.sign(sx) * d;
    };
    const zEye = (e1.z + e2.z) / 2;
    const toModel = (p) => {
        const dx = p.x - eyeMid.x, dy = p.y - eyeMid.y;
        const rx = dx * Math.cos(angle) + dy * Math.sin(angle), ry = -dx * Math.sin(angle) + dy * Math.cos(angle);
        const px = ALIGN.eyeX + k * rx, py = ALIGN.eyeY + k * ry;
        return [fwd(px - ALIGN.eyeX) / 8, 8 + (ALIGN.size / 2 - py) / 8, -(p.z - zEye) * k / 8];
    };
    const depth = {
        points: found.slice(0, 468).flatMap(p => toModel(p).map(v => Math.round(v * 1000) / 1000)),
        oval: FACE_OVAL.flatMap(i => toModel(found[i]).slice(0, 2).map(v => Math.round(v * 1000) / 1000))
    };
    return { canvas: w, found: true, depth };
}

async function sendFaceDepth(depth) {
    try {
        const res = await fetch("/api/face/depth", { method: "POST", headers: { "Content-Type": "application/json" },
                                                      body: JSON.stringify(depth) });
        const data = await res.json();
        document.getElementById("rowReshape").style.display = data.has_face_depth ? "" : "none";
        reloadSceneForReshape();
    } catch (e) { console.error(e); }
}

function reloadSceneForReshape() {
    Object.keys(sceneCache).forEach(k => delete sceneCache[k]);      // reshaped scenes are built fresh by the server
    if (activeMesh && activeMeshIsReal) loadMesh(document.getElementById("modelMeshSelect").value);
}

// Remove the light and shadow baked into the photo: divide each pixel by the local average brightness (a heavy blur of
// the face, alpha-weighted so the edges don't pull it) and multiply back by the overall average. Fine detail (brows,
// lids, lips) is smaller than the blur, so it stays; broad and medium patches (a lit cheek, nose shadow) even out.
function boxBlur(src, S, r) {
    const tmp = new Float32Array(S * S), out = new Float32Array(S * S), w = 2 * r + 1;
    for (let y = 0; y < S; y++) {                               // horizontal
        let acc = 0;
        for (let x = -r; x <= r; x++) acc += src[y * S + Math.min(S - 1, Math.max(0, x))];
        for (let x = 0; x < S; x++) {
            tmp[y * S + x] = acc / w;
            acc += src[y * S + Math.min(S - 1, x + r + 1)] - src[y * S + Math.max(0, x - r)];
        }
    }
    for (let x = 0; x < S; x++) {                               // vertical
        let acc = 0;
        for (let y = -r; y <= r; y++) acc += tmp[Math.min(S - 1, Math.max(0, y)) * S + x];
        for (let y = 0; y < S; y++) {
            out[y * S + x] = acc / w;
            acc += tmp[Math.min(S - 1, y + r + 1) * S + x] - tmp[Math.max(0, y - r) * S + x];
        }
    }
    return out;
}

function flattenLighting(d, S, strength) {
    if (strength <= 0) return;
    const n = S * S;
    let A = new Float32Array(n), sumA = 0;
    let ch = [new Float32Array(n), new Float32Array(n), new Float32Array(n)];
    const sum = [0, 0, 0];
    for (let i = 0; i < n; i++) {
        const a = d[i * 4 + 3] / 255;
        A[i] = a; sumA += a;
        for (let c = 0; c < 3; c++) { const v = d[i * 4 + c] * a; ch[c][i] = v; sum[c] += v; }
    }
    if (sumA < 1000) return;
    const mean = sum.map(v => v / sumA);
    let A_med = A, ch_med = ch;
    for (let pass = 0; pass < 2; pass++) {
        A_med = boxBlur(A_med, S, 8);
        ch_med = ch_med.map(arr => boxBlur(arr, S, 8));
    }
    for (let pass = 0; pass < 3; pass++) {
        A = boxBlur(A, S, 24);
        ch = ch.map(arr => boxBlur(arr, S, 24));
    }
    // each colour channel is levelled on its own, so patches of colour (a yellow forehead, pink cheeks) even out along
    // with both broad and medium-scale shadows (nose bridge, mouth corners)
    for (let i = 0; i < n; i++) {
        if (d[i * 4 + 3] < 10 || A[i] < 0.05) continue;
        for (let c = 0; c < 3; c++) {
            const broad = ch[c][i] / A[i];
            const med = A_med[i] > 0.05 ? ch_med[c][i] / A_med[i] : broad;
            const local = 0.65 * broad + 0.35 * med;
            const gain = Math.min(1.75, Math.max(0.6, Math.pow(mean[c] / Math.max(local, 1), strength)));
            d[i * 4 + c] = Math.min(255, d[i * 4 + c] * gain);
        }
    }
}

let alignedCanvas = null;       // the aligned portrait before brightness matching
let faceReference = null;

async function getFaceReference() {
    if (!faceReference) faceReference = await (await fetch("/api/model/face_reference")).json();
    return faceReference;
}

// Match the portrait's skin brightness to Mario's (his lighting is built around warm, fairly dark skin) and pull its
// colour part of the way towards his, so the face sits in the same light as the cap and body. adjustPct is the user's
// fine-tune on top (+/-50%).
async function renderAligned(adjustPct) {
    const S = ALIGN.size;
    const out = document.createElement("canvas");
    out.width = out.height = S;
    const ctx = out.getContext("2d");
    ctx.drawImage(alignedCanvas, 0, 0);
    try {
        const ref = await getFaceReference();
        const img = ctx.getImageData(0, 0, S, S), d = img.data;
        flattenLighting(d, S, (parseFloat(document.getElementById("sliderFlat").value) || 0) / 100);
        let r = 0, g = 0, b = 0, n = 0;
        for (let y = 120; y < 380; y++) {                       // the middle of the face, where skin shows
            for (let x = 120; x < 392; x++) {
                const i = (y * S + x) * 4;
                if (d[i + 3] > 200) { r += d[i]; g += d[i + 1]; b += d[i + 2]; n++; }
            }
        }
        if (n > 500 && !ref.error) {
            const m = [r / n, g / n, b / n];
            const lum = 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
            // Mario's albedo is darker than it looks in game (the game lights it up), so aim a little above his texture
            const BRIGHTEN = 1.12;
            const gain = (ref.luminance * BRIGHTEN / lum) * (1 + adjustPct / 100);
            const CHROMA = 0.25;                                // how far towards Mario's skin colour
            const off = [0, 1, 2].map(c => CHROMA * (ref.rgb[c] - m[c] * gain));
            for (let i = 0; i < d.length; i += 4) {
                for (let c = 0; c < 3; c++) d[i + c] = Math.max(0, Math.min(255, d[i + c] * gain + off[c]));
            }
            ctx.putImageData(img, 0, 0);
        }
    } catch (e) { console.error("brightness match skipped", e); }
    return await new Promise(res => out.toBlob(res, "image/png"));
}

async function rerenderAligned() {
    if (!alignedCanvas) return;
    const blob = await renderAligned(parseFloat(document.getElementById("sliderBright").value) || 0);
    uploadedTextureFile = new File([blob], "face_aligned.png", { type: "image/png" });
    await applyComposite(true);
}

function resetPhotoControls() {
    const set = (id, v) => { document.getElementById(id).value = v; };
    set("sliderScale", 1); set("sliderOffX", 0); set("sliderOffY", 0); set("sliderRotate", 0); set("sliderBright", 0);
    set("sliderFlat", 85); document.getElementById("valFlat").textContent = "85%";
    document.getElementById("valBright").textContent = "auto";
    set("sliderFeather", 0); set("sliderOpacity", 1);
    document.getElementById("valScale").textContent = "1.00x";
    document.getElementById("valRotate").textContent = "0°";
    document.getElementById("valFeather").textContent = "0px";
    document.getElementById("valOpacity").textContent = "100%";
}

async function handleUploadedPhoto(file) {
    // A portrait only ever belongs on the face texture, whichever texture happens to be selected
    if (activeSlotId !== "mario_face") {
        selectSlot("mario_face");
        showToast("Portraits go on the face texture - switched to it.");
    }
    uploadedOriginalFile = file;
    document.getElementById("uploadedFileName").textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    const status = document.getElementById("autoStatus");
    status.className = "auto-status";

    if (activeSlotId !== "mario_face") {       // only the face texture gets the automatic alignment
        uploadedTextureFile = file;
        status.textContent = "";
        return;
    }

    status.textContent = "Finding the face...";
    try {
        const { canvas, found, depth } = await autoAlignPhoto(file);
        alignedCanvas = canvas;
        resetPhotoControls();
        const blob = await renderAligned(0);
        uploadedTextureFile = new File([blob], "face_aligned.png", { type: "image/png" });
        await sendFaceDepth(found ? depth : { points: [], oval: [] });
        if (found) {
            status.textContent = "Face found - cropped, straightened and lined up on Mario (eyes on his eyeballs).";
        } else {
            status.className = "auto-status warn";
            status.textContent = "Couldn't find a face (or the detector couldn't load - it needs internet on first use). " +
                                 "The picture was centred instead; use Fine-tune to adjust.";
        }
        await applyComposite(true);
    } catch (e) {
        console.error(e);
        status.className = "auto-status warn";
        status.textContent = "Couldn't process that image: " + e.message;
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    // opening the photo tool selects the face texture too, so what you drop lands where you expect
    document.querySelector('.tool-pill[data-tool="composite"]').addEventListener("click", () => {
        if (activeSlotId !== "mario_face") selectSlot("mario_face");
    });
    try {
        const st = await (await fetch("/api/settings")).json();
        hideFaceParts = !!st.hide_face_parts;
        document.getElementById("checkHideParts").checked = hideFaceParts;
        const pct = Math.round((st.reshape_strength ?? 0) * 100);
        document.getElementById("sliderReshape").value = pct;
        document.getElementById("valReshape").textContent = `${pct}%`;
        document.getElementById("rowReshape").style.display = st.has_face_depth ? "" : "none";
        if (activeMesh && activeMeshIsReal) loadMesh(document.getElementById("modelMeshSelect").value);
    } catch (e) { console.error(e); }
    document.getElementById("checkHideParts").addEventListener("change", async (e) => {
        hideFaceParts = e.target.checked;
        try {
            await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
                                           body: JSON.stringify({ hide_face_parts: hideFaceParts }) });
        } catch (err) { console.error(err); }
        loadMesh(document.getElementById("modelMeshSelect").value);
        showToast(hideFaceParts ? "Moustache & eyebrows removed - press Swizzle & Deploy to apply in game." :
                                  "Moustache & eyebrows kept - press Swizzle & Deploy to apply in game.");
    });
    const saveReshape = debounce(async (v) => {
        try {
            await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
                                           body: JSON.stringify({ reshape_strength: v / 100 }) });
        } catch (err) { console.error(err); }
        reloadSceneForReshape();
    }, 300);
    document.getElementById("sliderReshape").addEventListener("input", (e) => {
        document.getElementById("valReshape").textContent = `${e.target.value}%`;
        saveReshape(parseFloat(e.target.value));
    });
    const liveBright = debounce(rerenderAligned, 250);
    document.getElementById("sliderFlat").addEventListener("input", (e) => {
        document.getElementById("valFlat").textContent = `${e.target.value}%`;
        liveBright();
    });
    document.getElementById("sliderBright").addEventListener("input", (e) => {
        const v = parseInt(e.target.value, 10);
        document.getElementById("valBright").textContent = v === 0 ? "auto" : (v > 0 ? "+" : "") + v + "%";
        liveBright();
    });
    document.getElementById("btnResetAlign").addEventListener("click", () => {
        if (uploadedOriginalFile) handleUploadedPhoto(uploadedOriginalFile);
        else showToast("Drop a portrait first.");
    });
});

// ========================================================
// TAB 2: MUSIC & BGM STUDIO (130 TRACKS)
// ========================================================
async function loadBgm() {
    try {
        const res = await fetch("/api/audio/list");
        bgmTracks = await res.json();
        renderBgmList(bgmTracks);

        // Search & Filter listeners
        const searchInput = document.getElementById("bgmSearch");
        searchInput.addEventListener("input", filterBgm);

        document.querySelectorAll("#bgmFilterPills .pill").forEach(p => {
            p.addEventListener("click", () => {
                document.querySelectorAll("#bgmFilterPills .pill").forEach(x => x.classList.remove("active"));
                p.classList.add("active");
                filterBgm();
            });
        });

        // Dropzone for BGM replace
        initBgmDropzone();
    } catch (e) {
        console.error("Failed to load BGM tracks", e);
    }
}

function renderBgmList(tracks) {
    filteredBgmTracks = tracks;
    const list = document.getElementById("bgmTrackList");
    list.innerHTML = "";

    tracks.forEach(track => {
        const item = document.createElement("div");
        item.className = `track-item ${activeBgmTrack && activeBgmTrack.filename === track.filename ? "active" : ""}`;
        item.dataset.filename = track.filename;

        // Parse Kingdom hint
        let kingdom = "General";
        const f = track.filename;
        if (f.includes("City")) kingdom = "Metro";
        else if (f.includes("Desert")) kingdom = "Sand";
        else if (f.includes("Forest")) kingdom = "Wooded";
        else if (f.includes("Waterfall")) kingdom = "Cascade";
        else if (f.includes("Snow")) kingdom = "Snow";
        else if (f.includes("Sea") || f.includes("Lake")) kingdom = "Seaside";
        else if (f.includes("Moon")) kingdom = "Moon";
        else if (f.includes("Boss")) kingdom = "Boss";

        item.innerHTML = `
            <div class="track-item-info">
                <span class="track-item-title">${track.title}</span>
                <div class="track-item-meta">
                    <span class="track-badge">${kingdom}</span>
                    <span>${track.size_mb} MB</span>
                </div>
            </div>
            <button class="track-play-btn" title="Play Track">▶</button>
        `;

        item.addEventListener("click", () => playBgmTrack(track));
        list.appendChild(item);
    });
}

function filterBgm() {
    const query = document.getElementById("bgmSearch").value.toLowerCase();
    const activePill = document.querySelector("#bgmFilterPills .pill.active");
    const filter = activePill ? activePill.dataset.filter : "all";

    const filtered = bgmTracks.filter(t => {
        const matchesQuery = t.title.toLowerCase().includes(query) || t.filename.toLowerCase().includes(query);
        const matchesFilter = (filter === "all") || t.filename.includes(filter);
        return matchesQuery && matchesFilter;
    });

    renderBgmList(filtered);
}

function playBgmTrack(track) {
    activeBgmTrack = track;
    let activeEl = null;
    document.querySelectorAll("#bgmTrackList .track-item").forEach(it => {
        const isCurrent = it.dataset.filename === track.filename;
        it.classList.toggle("active", isCurrent);
        if (isCurrent) activeEl = it;
    });
    if (activeEl) activeEl.scrollIntoView({ block: "nearest", behavior: "smooth" });

    document.getElementById("bgmActiveTitle").textContent = track.title;
    document.getElementById("bgmActiveFilename").textContent = track.filename;

    const audio = document.getElementById("bgmAudioPlayer");
    audio.src = `/api/audio/play?track=${encodeURIComponent(track.filename)}&t=${Date.now()}`;
    audio.load();
    audio.play().catch(e => console.log("Auto-play blocked", e));
}

function initBgmDropzone() {
    const dropZone = document.getElementById("bgmDropZone");
    const fileInput = document.getElementById("bgmFileInput");
    const btnReplace = document.getElementById("btnReplaceBgm");

    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.style.borderColor = "var(--neon-blue)"; });
    dropZone.addEventListener("dragleave", () => { dropZone.style.borderColor = ""; });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.style.borderColor = "";
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleBgmFile(e.dataTransfer.files[0]);
        }
    });
    fileInput.addEventListener("change", () => {
        if (fileInput.files && fileInput.files[0]) {
            handleBgmFile(fileInput.files[0]);
        }
    });

    btnReplace.addEventListener("click", async () => {
        if (!activeBgmTrack) {
            showToast("Please select a track from the library on the left first.");
            return;
        }
        if (!uploadedBgmFile) {
            showToast("Please drag & drop or browse a music file (MP3/WAV) to replace this track.");
            fileInput.click();
            return;
        }
        btnReplace.disabled = true;
        btnReplace.textContent = "⏳ Transcoding to 48kHz BFSTM...";

        const fd = new FormData();
        fd.append("track", activeBgmTrack.filename);
        fd.append("file", uploadedBgmFile);

        try {
            const res = await fetch("/api/audio/replace", { method: "POST", body: fd });
            const data = await res.json();
            if (data.success) {
                showToast(`🎵 Replaced ${activeBgmTrack.title} in Eden LayeredFS!`);
                playBgmTrack(activeBgmTrack);
            } else {
                showToast("Replace error: " + (data.error || data.message));
            }
        } catch (e) {
            showToast("Failed to replace BGM: " + e.message);
        } finally {
            btnReplace.disabled = false;
            btnReplace.textContent = "⚡ Transcode to BFSTM & Deploy to Eden";
        }
    });
}

function handleBgmFile(file) {
    uploadedBgmFile = file;
    document.getElementById("bgmUploadedName").textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    document.getElementById("btnReplaceBgm").disabled = false;
}

function initJukeboxScanner() {
    const inputDir = document.getElementById("inputMusicDir");
    const btnScan = document.getElementById("btnScanMusicDir");
    const btnPickFolder = document.getElementById("btnPickFolder");
    const btnPickFiles = document.getElementById("btnPickFiles");
    const fileInput = document.getElementById("jukeboxFileInput");
    const folderInput = document.getElementById("jukeboxFolderInput");
    const dropZone = document.getElementById("jukeboxDropZone");
    const badge = document.getElementById("scanResultBadge");
    const btnBatch = document.getElementById("btnBatchShuffleMusic");
    const progressText = document.getElementById("batchProgressText");

    if (!btnScan || !btnBatch) return;

    const btnQuickDownloads = document.getElementById("btnQuickDownloads");
    const btnQuickMusic = document.getElementById("btnQuickMusic");
    const btnQuickConverted = document.getElementById("btnQuickConverted");

    if (btnQuickConverted) {
        btnQuickConverted.addEventListener("click", () => {
            inputDir.value = "C:\\Users\\adria\\Desktop\\Private\\Converted Music";
            queuedFiles = [];
            btnScan.click();
        });
    }

    const handleBatchFiles = async (files) => {
        if (!files || files.length === 0) return;
        queuedFiles = Array.from(files);
        badge.style.display = "block";
        badge.style.color = "var(--accent-cyan)";
        badge.textContent = `🎵 Selected ${queuedFiles.length} music file(s): ${queuedFiles.slice(0, 3).map(f => f.name).join(", ")}${queuedFiles.length > 3 ? "..." : ""}`;
        btnBatch.disabled = false;
        btnBatch.textContent = `🎲 Deploy ${queuedFiles.length} Song(s) across Kingdoms`;
        showToast(`Ready to deploy ${queuedFiles.length} songs!`);
    };

    if (btnPickFolder) {
        btnPickFolder.addEventListener("click", async () => {
            btnPickFolder.disabled = true;
            const origText = btnPickFolder.textContent;
            btnPickFolder.textContent = "⏳ Picking Folder...";
            showToast("Opening Windows folder browser...");
            try {
                const res = await fetch("/api/utils/pick_folder");
                const data = await res.json();
                if (data && data.success && data.path) {
                    inputDir.value = data.path;
                    queuedFiles = [];
                    btnScan.click();
                } else if (data && data.cancelled) {
                    // User closed dialog without selecting
                } else if (folderInput) {
                    // Fallback to browser picker if native dialog unavailable
                    folderInput.click();
                }
            } catch (err) {
                console.warn("Native folder picker failed, using file fallback", err);
                if (folderInput) folderInput.click();
            } finally {
                btnPickFolder.disabled = false;
                btnPickFolder.textContent = origText;
            }
        });
    }

    if (folderInput) {
        folderInput.addEventListener("change", () => {
            if (folderInput.files && folderInput.files.length > 0) {
                handleBatchFiles(folderInput.files);
            }
        });
    }

    if (btnQuickDownloads) {
        btnQuickDownloads.addEventListener("click", () => {
            inputDir.value = "C:\\Downloads";
            queuedFiles = [];
            btnScan.click();
        });
    }

    if (btnQuickMusic) {
        btnQuickMusic.addEventListener("click", () => {
            inputDir.value = "C:\\Users\\adria\\Music";
            queuedFiles = [];
            btnScan.click();
        });
    }

    if (btnPickFiles && fileInput) {
        btnPickFiles.addEventListener("click", () => fileInput.click());
        fileInput.addEventListener("change", () => {
            if (fileInput.files && fileInput.files.length > 0) {
                handleBatchFiles(fileInput.files);
            }
        });
    }

    if (dropZone) {
        dropZone.addEventListener("click", () => {
            if (fileInput) fileInput.click();
        });
        dropZone.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropZone.style.borderColor = "var(--accent-cyan)";
            dropZone.style.background = "rgba(0, 210, 255, 0.1)";
        });
        dropZone.addEventListener("dragleave", () => {
            dropZone.style.borderColor = "rgba(168, 85, 247, 0.4)";
            dropZone.style.background = "rgba(168, 85, 247, 0.05)";
        });
        dropZone.addEventListener("drop", (e) => {
            e.preventDefault();
            dropZone.style.borderColor = "rgba(168, 85, 247, 0.4)";
            dropZone.style.background = "rgba(168, 85, 247, 0.05)";
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                handleBatchFiles(e.dataTransfer.files);
            }
        });
    }

    btnScan.addEventListener("click", async () => {
        const path = inputDir.value.trim();
        if (!path) {
            showToast("Please enter a folder path to scan");
            return;
        }
        btnScan.disabled = true;
        btnScan.textContent = "⏳ Scanning...";
        badge.style.display = "block";
        badge.textContent = `Scanning ${path}...`;

        try {
            const res = await fetch("/api/audio/scan_directory", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path })
            });
            const data = await res.json();
            if (data.success) {
                badge.style.display = "block";
                if (data.count > 0) {
                    badge.style.color = "var(--accent-cyan)";
                    badge.textContent = `✅ Found ${data.count} supported song(s) in folder!`;
                    btnBatch.disabled = false;
                    btnBatch.textContent = `🎲 Shuffle & Deploy to Game (${data.count} songs)`;
                    queuedFiles = []; // Use directory scan
                } else {
                    badge.style.color = "#f87171";
                    badge.textContent = `⚠️ No music files (.mp3, .wav, .flac) found in ${path}. Click "Browse Folder" or drag & drop files!`;
                }
                showToast(`Scanned: ${data.count} audio track(s)`);
            } else {
                badge.style.display = "block";
                badge.style.color = "#f87171";
                badge.textContent = `Error: ${data.error}`;
            }
        } catch (e) {
            badge.style.display = "block";
            badge.style.color = "#f87171";
            badge.textContent = "Failed to scan folder: " + e.message;
        } finally {
            btnScan.disabled = false;
            btnScan.textContent = "🔍 Scan";
        }
    });

    btnBatch.addEventListener("click", async () => {
        btnBatch.disabled = true;
        btnBatch.textContent = "⏳ Transcoding & Deploying...";
        progressText.style.display = "block";
        progressText.style.color = "#a5b4fc";
        progressText.textContent = "⏳ Optimizing and distributing your music across Odyssey kingdoms (usually 10-15 seconds)...";

        const scopeEl = document.getElementById("selectTrackScope");
        const maxTracks = scopeEl ? parseInt(scopeEl.value, 10) : 50;

        try {
            let res, data;
            if (queuedFiles.length > 0) {
                // Multi-file multipart upload
                const fd = new FormData();
                queuedFiles.forEach(f => fd.append("files", f));
                fd.append("max_tracks", maxTracks);
                res = await fetch("/api/audio/upload_batch", {
                    method: "POST",
                    body: fd
                });
                data = await res.json();
            } else {
                // Folder path scan & replace
                let path = inputDir.value.trim();
                if (!path) path = "C:\\Downloads";
                res = await fetch("/api/audio/batch_replace", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path, shuffle: true, max_tracks: maxTracks })
                });
                data = await res.json();
            }

            if (data && data.success) {
                progressText.style.color = "var(--accent-cyan)";
                const droppedNote = data.dropped_count ? ` (${data.dropped_count} skipped: ${data.dropped.map(d => d.original).join(", ")} - not replaceable, left as original)` : "";
                progressText.textContent = `🎉 Deployed ${data.replaced_count} kingdom tracks (using ${data.unique_songs_used || queuedFiles.length} songs)! Title, Sand, Metro, and Cascade Kingdoms updated!${droppedNote}`;
                showToast(`🎉 Shuffled and deployed across ${data.replaced_count} game tracks!${data.dropped_count ? " (" + data.dropped_count + " left original)" : ""}`);
                loadBgm();
            } else {
                const msg = (data && (data.message || data.error)) || "No tracks were replaced. Check audio files.";
                progressText.style.color = "#f87171";
                progressText.textContent = "Deploy error: " + msg;
                showToast("Deploy error: " + msg);
            }
        } catch (e) {
            progressText.style.color = "#f87171";
            progressText.textContent = "Batch deployment error: " + e.message;
            showToast("Deployment error: " + e.message);
        } finally {
            btnBatch.disabled = false;
            btnBatch.textContent = "🎲 Shuffle & Batch Deploy to Game";
        }
    });

    const btnResetAudio = document.getElementById("btnResetAudio");
    if (btnResetAudio) {
        btnResetAudio.addEventListener("click", async () => {
            if (!confirm("Reset all game music and sound effects back to original vanilla Nintendo audio?")) return;
            btnResetAudio.disabled = true;
            btnResetAudio.textContent = "⏳ Resetting...";
            try {
                const res = await fetch("/api/audio/reset", { method: "POST" });
                const data = await res.json();
                if (data.success) {
                    showToast("✅ Audio restored to 100% vanilla!");
                    if (progressText) {
                        progressText.style.display = "block";
                        progressText.style.color = "var(--accent-cyan)";
                        progressText.textContent = "✅ All game music & SFX reset to clean vanilla!";
                    }
                    loadBgm();
                } else {
                    showToast("Reset failed: " + (data.error || "Unknown error"));
                }
            } catch (err) {
                showToast("Error resetting audio: " + err.message);
            } finally {
                btnResetAudio.disabled = false;
                btnResetAudio.textContent = "🔄 Reset Audio (Vanilla)";
            }
        });
    }
}

// ========================================================
// TAB 3: SOUND EFFECTS & VOICE (5,134 FX + VOICEMOD)
// ========================================================
let sfxListenersBound = false;
let sfxRenderLimit = 150;

async function loadSfx() {
    try {
        const res = await fetch("/api/sfx/list");
        sfxTracks = await res.json();
        filterSfx();

        if (!sfxListenersBound) {
            sfxListenersBound = true;
            const sfxSearch = document.getElementById("sfxSearch");
            sfxSearch.addEventListener("input", () => {
                sfxRenderLimit = 150;
                filterSfx();
            });

            document.querySelectorAll("#sfxFilterPills .pill").forEach(p => {
                p.addEventListener("click", () => {
                    document.querySelectorAll("#sfxFilterPills .pill").forEach(x => x.classList.remove("active"));
                    p.classList.add("active");
                    sfxRenderLimit = 150;
                    filterSfx();
                });
            });

            initSfxDropzone();
        }
    } catch (e) {
        console.error("Failed to load SFX tracks", e);
    }
}

function renderSfxList(tracks) {
    filteredSfxTracks = tracks;
    const list = document.getElementById("sfxTrackList");
    list.innerHTML = "";

    const slice = tracks.slice(0, sfxRenderLimit);
    const frag = document.createDocumentFragment();

    slice.forEach(track => {
        const item = document.createElement("div");
        item.className = `track-item ${activeSfxTrack && activeSfxTrack.filename === track.filename ? "active" : ""}`;
        item.dataset.filename = track.filename;

        const durLabel = track.duration > 0 ? `${track.duration}s` : `${track.size_kb || track.size_mb} ${track.size_kb ? "KB" : "MB"}`;
        const rateLabel = track.rate ? `${Math.round(track.rate / 1000)}kHz` : "";
        const modBadge = track.is_modded ? `<span class="track-badge" style="background:rgba(16,185,129,0.2);color:#34d399;border:1px solid rgba(16,185,129,0.4);">✨ MODDED</span>` : "";

        item.innerHTML = `
            <div class="track-item-info">
                <span class="track-item-title">${track.title}</span>
                <div class="track-item-meta">
                    ${modBadge}
                    <span class="track-badge" style="color:var(--joycon-red);">${track.category}</span>
                    <span>${durLabel}</span>
                    ${rateLabel ? `<span style="opacity:0.75;">• ${rateLabel}</span>` : ""}
                    <span style="opacity:0.55;font-family:monospace;font-size:10px;">${track.symbol || ""}</span>
                </div>
            </div>
            <button class="track-play-btn" title="Play SFX">▶</button>
        `;

        item.addEventListener("click", () => playSfxTrack(track));
        frag.appendChild(item);
    });

    if (tracks.length > sfxRenderLimit) {
        const moreBtn = document.createElement("button");
        moreBtn.className = "btn btn-secondary btn-full";
        moreBtn.style.marginTop = "8px";
        moreBtn.textContent = `Show More (${tracks.length - sfxRenderLimit} remaining of ${tracks.length})`;
        moreBtn.addEventListener("click", () => {
            sfxRenderLimit += 250;
            renderSfxList(tracks);
        });
        frag.appendChild(moreBtn);
    } else if (tracks.length === 0) {
        const empty = document.createElement("div");
        empty.style.cssText = "padding:24px;text-align:center;color:var(--text-muted);font-size:13px;";
        empty.textContent = "No matching sound effects found.";
        frag.appendChild(empty);
    }

    list.appendChild(frag);
}

function filterSfx() {
    const query = (document.getElementById("sfxSearch").value || "").toLowerCase().trim();
    const activePill = document.querySelector("#sfxFilterPills .pill.active");
    const filter = activePill ? activePill.dataset.filter : "featured";

    const filtered = sfxTracks.filter(t => {
        const sym = (t.symbol || "").toLowerCase();
        const arch = (t.archive || "").toLowerCase();
        const matchesQuery = !query ||
            t.title.toLowerCase().includes(query) ||
            sym.includes(query) ||
            t.category.toLowerCase().includes(query) ||
            arch.includes(query);
        if (!matchesQuery) return false;

        if (filter === "all") return true;
        if (filter === "modded") return !!t.is_modded;
        if (filter === "featured") {
            return (t.priority !== undefined && t.priority <= 30) || !!t.is_modded;
        }
        return t.category === filter || t.category.includes(filter);
    });

    renderSfxList(filtered);
}

function playSfxTrack(track) {
    activeSfxTrack = track;
    let activeEl = null;
    document.querySelectorAll("#sfxTrackList .track-item").forEach(it => {
        const isCurrent = it.dataset.filename === track.filename;
        it.classList.toggle("active", isCurrent);
        if (isCurrent) activeEl = it;
    });
    if (activeEl) activeEl.scrollIntoView({ block: "nearest", behavior: "smooth" });

    document.getElementById("sfxActiveTitle").textContent = track.title;
    const symInfo = track.symbol ? `${track.symbol} • ${track.archive || "SoundData"}` : track.filename;
    const specInfo = track.rate ? ` (${track.rate}Hz, ${track.channels || 1}ch, ${track.codec === 1 ? "PCM16" : "DSP-ADPCM"})` : "";
    document.getElementById("sfxActiveFilename").textContent = symInfo + specInfo;
    const badgeEl = document.getElementById("sfxActiveBadge");
    if (badgeEl) {
        badgeEl.textContent = `${(track.category || "SFX").toUpperCase()} • ${track.codec === 1 ? "16-BIT PCM" : "NINTENDO DSP-ADPCM"}${track.is_modded ? " • ✨ MODDED" : ""}`;
    }

    const audio = document.getElementById("sfxAudioPlayer");
    audio.src = `/api/sfx/play?track=${encodeURIComponent(track.filename)}&t=${Date.now()}`;
    audio.load();
    audio.play().catch(e => console.log("SFX play blocked", e));
}

function initSfxDropzone() {
    const dropZone = document.getElementById("sfxDropZone");
    const fileInput = document.getElementById("sfxFileInput");
    const btnReplace = document.getElementById("btnReplaceSfx");

    const selectFile = (file) => {
        if (!file) return;
        uploadedSfxFile = file;
        dropZone.querySelector("span").textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        btnReplace.disabled = false;
    };

    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.style.borderColor = "var(--neon-blue)"; });
    dropZone.addEventListener("dragleave", () => { dropZone.style.borderColor = ""; });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.style.borderColor = "";
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            selectFile(e.dataTransfer.files[0]);
        }
    });
    fileInput.addEventListener("change", () => {
        if (fileInput.files && fileInput.files[0]) {
            selectFile(fileInput.files[0]);
        }
    });

    btnReplace.addEventListener("click", async () => {
        if (!activeSfxTrack) {
            showToast("Please select a sound effect from the library on the left first.");
            return;
        }
        if (!uploadedSfxFile) {
            showToast("Please select or drop an audio file first.");
            fileInput.click();
            return;
        }
        btnReplace.disabled = true;
        btnReplace.textContent = "⏳ Deploying...";

        const fd = new FormData();
        fd.append("track", activeSfxTrack.filename);
        fd.append("file", uploadedSfxFile);

        try {
            const res = await fetch("/api/sfx/replace", { method: "POST", body: fd });
            const data = await res.json();
            if (data.success) {
                activeSfxTrack.is_modded = true;
                showToast(`⚡ Replaced '${activeSfxTrack.title}' in Eden LayeredFS!`);
                await loadSfx();
                playSfxTrack(activeSfxTrack);
            } else {
                showToast("Replace error: " + data.error);
            }
        } catch (e) {
            showToast("Failed to replace SFX: " + e.message);
        } finally {
            btnReplace.disabled = false;
            btnReplace.textContent = "⚡ Deploy SFX";
        }
    });
}

// ========================================================
// VOICEMOD & LIVE MICROPHONE RECORDER
// ========================================================
function initVoiceMod() {
    const btnRecord = document.getElementById("btnRecordVoice");
    const btnStop = document.getElementById("btnStopVoice");
    const btnRefreshMics = document.getElementById("btnRefreshMics");
    const audioPreview = document.getElementById("recordedAudioPreview");
    const deployRow = document.getElementById("vmDeployRow");
    const btnDeployVocal = document.getElementById("btnDeployVocal");
    const canvas = document.getElementById("micVisualizer");
    const canvasCtx = canvas.getContext("2d");

    async function populateAudioDevices(requestPermissionFirst = false) {
        if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
        try {
            if (requestPermissionFirst) {
                const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                tempStream.getTracks().forEach(t => t.stop());
            }
            const devices = await navigator.mediaDevices.enumerateDevices();
            const select = document.getElementById("audioDeviceSelect");
            const prevVal = select.value;
            select.innerHTML = '<option value="">Default Microphone / Voicemod Virtual Audio</option>';
            let foundVoicemod = false;
            devices.forEach((d, idx) => {
                if (d.kind === "audioinput") {
                    const opt = document.createElement("option");
                    opt.value = d.deviceId;
                    const isVm = d.label && d.label.toLowerCase().includes("voicemod");
                    opt.textContent = d.label
                        ? (isVm ? `🎙️ [Voicemod] ${d.label}` : d.label)
                        : `Microphone (${idx + 1})`;
                    if (isVm && !foundVoicemod) {
                        opt.selected = true;
                        foundVoicemod = true;
                    } else if (prevVal && d.deviceId === prevVal) {
                        opt.selected = true;
                    }
                    select.appendChild(opt);
                }
            });
            if (requestPermissionFirst) {
                showToast(foundVoicemod ? "🎙️ Voicemod Virtual Audio detected & selected!" : "🎙️ Audio input devices refreshed!");
            }
        } catch (err) {
            console.log("Device enum error", err);
            if (requestPermissionFirst) {
                showToast("Microphone access error: " + err.message);
            }
        }
    }

    populateAudioDevices(false);

    if (btnRefreshMics) {
        btnRefreshMics.addEventListener("click", () => populateAudioDevices(true));
    }

    btnRecord.addEventListener("click", async () => {
        try {
            const deviceId = document.getElementById("audioDeviceSelect").value;
            const constraints = {
                audio: deviceId ? { deviceId: { exact: deviceId } } : true
            };
            micStream = await navigator.mediaDevices.getUserMedia(constraints);
            populateAudioDevices(false);

            // Web Audio Analyser for visualizer
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const source = audioCtx.createMediaStreamSource(micStream);
            const analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);

            drawVisualizer(analyser, canvas, canvasCtx);

            recordedChunks = [];
            mediaRecorder = new MediaRecorder(micStream);
            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) recordedChunks.push(e.data);
            };
            mediaRecorder.onstop = () => {
                recordedBlob = new Blob(recordedChunks, { type: "audio/wav" });
                audioPreview.src = URL.createObjectURL(recordedBlob);
                audioPreview.style.display = "block";
                deployRow.style.display = "flex";
                btnDeployVocal.disabled = false;
            };

            mediaRecorder.start();
            btnRecord.classList.add("recording");
            btnRecord.disabled = true;
            btnStop.disabled = false;
            showToast("🔴 Recording live vocal sound effect...");
        } catch (e) {
            showToast("Microphone access error: " + e.message);
        }
    });

    btnStop.addEventListener("click", () => {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
            micStream.getTracks().forEach(t => t.stop());
            btnRecord.classList.remove("recording");
            btnRecord.disabled = false;
            btnStop.disabled = true;
            showToast("⏹ Recording finished! Preview or click 'Deploy Voice into Game'.");
        }
    });

    btnDeployVocal.addEventListener("click", async () => {
        if (!recordedBlob) {
            showToast("Please click '🔴 Record Clip' to record a voice clip first!");
            return;
        }
        let targetFilename = document.getElementById("voiceTargetSelect").value;
        if (targetFilename === "__active__") {
            if (!activeSfxTrack) {
                showToast("Please select a sound effect in the left panel first, or choose a preset from the Target FX dropdown!");
                return;
            }
            targetFilename = activeSfxTrack.filename;
        }
        btnDeployVocal.disabled = true;
        btnDeployVocal.textContent = "⏳ Transcoding...";

        const fd = new FormData();
        fd.append("track", targetFilename);
        fd.append("file", recordedBlob, "vocal_clip.wav");

        try {
            const res = await fetch("/api/sfx/replace", { method: "POST", body: fd });
            const data = await res.json();
            if (data.success) {
                showToast("🎙️ Vocal clip successfully injected into game!");
                await loadSfx();
                if (activeSfxTrack && activeSfxTrack.filename === targetFilename) {
                    playSfxTrack(activeSfxTrack);
                }
            } else {
                showToast("Deploy failed: " + data.error);
            }
        } catch (e) {
            showToast("Vocal deploy error: " + e.message);
        } finally {
            btnDeployVocal.disabled = false;
            btnDeployVocal.textContent = "⚡ Deploy Voice into Game";
        }
    });
}

function drawVisualizer(analyser, canvas, ctx) {
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function render() {
        requestAnimationFrame(render);
        analyser.getByteFrequencyData(dataArray);

        ctx.fillStyle = "#05070c";
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        const barWidth = (canvas.width / bufferLength) * 2.5;
        let barHeight;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
            barHeight = (dataArray[i] / 255) * canvas.height;
            ctx.fillStyle = `rgb(${dataArray[i] + 50}, 42, 120)`;
            ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
            x += barWidth + 1;
        }
    }
    render();
}

// ========================================================
// THREE.JS 3D VIEWPORT STAGE
// ========================================================
function init3DViewer() {
    const container = document.getElementById("threeCanvasWrap");
    const canvas = document.getElementById("threeCanvas");

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0d121f);

    camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
    camera.position.set(0, 1.2, 3.2);

    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.outputEncoding = THREE.sRGBEncoding;

    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.target.set(0, 0.8, 0);

    // Natural, flattering studio lighting (eliminates cold cyan / bruised magenta shadow tint on skin)
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.92);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xfffaf2, 0.72);
    dirLight.position.set(3, 6, 6);
    scene.add(dirLight);

    const fillLight = new THREE.DirectionalLight(0xdbeafe, 0.35);
    fillLight.position.set(-4, 1, 3);
    scene.add(fillLight);

    // Mesh selection
    document.getElementById("modelMeshSelect").addEventListener("change", (e) => {
        loadMesh(e.target.value);
    });

    document.getElementById("btnToggleModded").addEventListener("click", (e) => {
        showModded3D = !showModded3D;
        e.target.textContent = `Texture: ${showModded3D ? "Edited" : "Original"}`;
        Object.keys(texByName).forEach(applyModelTexture);
    });

    loadMesh(document.getElementById("modelMeshSelect").value);
    window.addEventListener("resize", onWindowResize);
    animate();
}

// ---- real Mario geometry (from the game's BFRES files, built by core/model_view.py) --------------------------
const MODEL_SETS = new Set(["full", "full_nocap", "head", "head_nocap", "face", "body", "cap"]);
const sceneCache = {};
let activeMeshIsReal = false;
let showModded3D = true;
let texByName = {};          // albedo texture name -> { slot, mats[] }
let meshLoadToken = 0;
let hideFaceParts = true;
const modelTexLoader = new THREE.TextureLoader();

async function loadMesh(type) {
    if (!MODEL_SETS.has(type)) { loadPrimitiveMesh(type); return; }
    const token = ++meshLoadToken;
    try {
        let data = sceneCache[type];
        if (!data) {
            showToast("Loading real Mario model (the first load builds it from the game files)...");
            const res = await fetch(`/api/model/scene?set=${type}`);
            if (!(res.headers.get("content-type") || "").includes("json")) {
                throw new Error("the studio server is out of date - restart it (Launch_SpriteSwap_Studio.bat)");
            }
            data = await res.json();
            if (data.error) throw new Error(data.error);
            sceneCache[type] = data;
        }
        if (token !== meshLoadToken) return;
        buildRealModel(data);
    } catch (e) {
        console.error(e);
        showToast("Real model unavailable (" + e.message + ") - showing a stand-in shape");
        loadPrimitiveMesh("character");
    }
}

let currentMarioBodyScale = 1.0;
let currentMarioHeadMult = 1.0;

function apply3DScalePreview() {
    if (!activeMesh || !activeMeshIsReal) return;
    const meshSet = document.getElementById("modelMeshSelect")?.value || "full";
    const isFullBody = (meshSet === "full" || meshSet === "full_nocap" || meshSet === "body");
    const visBody = isFullBody ? Math.pow(currentMarioBodyScale, 0.55) : 1.0;
    activeMesh.scale.setScalar(visBody);
    const headPivot = activeMesh.userData && activeMesh.userData.headPivotGroup;
    if (headPivot && isFullBody) {
        headPivot.scale.setScalar(currentMarioHeadMult);
    } else if (headPivot) {
        headPivot.scale.setScalar(1.0);
    }
}

function buildRealModel(data) {
    if (activeMesh) scene.remove(activeMesh);
    texByName = {};
    activeMeshIsReal = true;

    const inner = new THREE.Group();
    const headRawGroup = new THREE.Group();
    let hasBodyPart = false;
    let hasHeadPart = false;

    data.parts.forEach(part => {
        const isHead = (part.id !== "body");
        if (isHead) hasHeadPart = true; else hasBodyPart = true;
        part.shapes.forEach(sh => {
            // eyelids are posed closed in the bind pose; the game animates them open (and shut for blinks), so leave them out
            if (/^Eyelid/.test(sh.name)) return;
            if (hideFaceParts && /mustache|_brow_/i.test(sh.name)) return;
            const geom = new THREE.BufferGeometry();
            geom.setAttribute("position", new THREE.Float32BufferAttribute(sh.positions, 3));
            geom.setAttribute("normal", new THREE.Float32BufferAttribute(sh.normals, 3));
            geom.setAttribute("uv", new THREE.Float32BufferAttribute(sh.uvs, 2));
            geom.setIndex(sh.indices);
            const mat = new THREE.MeshStandardMaterial({ color: 0x8a93a6, roughness: 0.65, metalness: 0.0, side: THREE.DoubleSide });
            if (sh.albedo === "MarioEyePupil_alb") mat.alphaTest = 0.5;
            const mesh = new THREE.Mesh(geom, mat);
            mesh.userData.shape = sh.name;
            if (isHead) {
                headRawGroup.add(mesh);
            } else {
                inner.add(mesh);
            }
            const entry = texByName[sh.albedo] || (texByName[sh.albedo] = { slot: sh.slot, mats: [] });
            entry.mats.push(mat);
        });
    });

    const headPivotGroup = new THREE.Group();
    if (hasHeadPart) {
        const hbox = new THREE.Box3().setFromObject(headRawGroup);
        const hcenter = hbox.getCenter(new THREE.Vector3());
        // Pivot at the base of the head/neck so Big Head / Chibi scales upward from the collar
        const neckPivot = new THREE.Vector3(hcenter.x, hbox.min.y + (hbox.max.y - hbox.min.y) * 0.12, hcenter.z);
        headPivotGroup.position.copy(neckPivot);
        headRawGroup.position.copy(neckPivot).multiplyScalar(-1);
        headPivotGroup.add(headRawGroup);
        inner.add(headPivotGroup);
    }

    // centre + scale to a fixed height, then frame the camera on it
    const box = new THREE.Box3().setFromObject(inner);
    const size = box.getSize(new THREE.Vector3()), centre = box.getCenter(new THREE.Vector3());
    const k = 2.4 / Math.max(size.y, size.x * 0.75, 1e-3);
    inner.scale.setScalar(k);
    inner.position.copy(centre).multiplyScalar(-k);
    const wrap = new THREE.Group();
    wrap.add(inner);
    wrap.userData.headPivotGroup = headPivotGroup;
    activeMesh = wrap;
    scene.add(wrap);

    const half = Math.max(size.y * k, size.x * k * 0.75) / 2;
    const dist = half / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.3;
    camera.position.set(0, half * 0.12, dist);
    controls.target.set(0, 0, 0);
    controls.update();

    apply3DScalePreview();
    Object.keys(texByName).forEach(applyModelTexture);
}

function applyModelTexture(name) {
    const entry = texByName[name];
    if (!entry) return;
    const useMod = showModded3D && !!entry.slot;
    const url = `/api/model/texture?name=${encodeURIComponent(name)}&type=${useMod ? "mod" : "orig"}&t=${Date.now()}`;
    modelTexLoader.load(url, (tex) => {
        tex.flipY = false;                      // BFRES UVs start at the top-left, like the image
        tex.wrapS = THREE.ClampToEdgeWrapping;  // U is mirrored in 0..1; clamping prevents U=1.0 on the nose from bleeding U=0.0
        tex.wrapT = THREE.RepeatWrapping;
        tex.encoding = THREE.sRGBEncoding;
        tex.anisotropy = 8;
        entry.mats.forEach(m => {
            if (m.map) m.map.dispose();
            m.map = tex;
            m.color.set(0xffffff);
            m.needsUpdate = true;
        });
    });
}

function update3DTexture(slotId) {
    if (!activeMesh) return;
    if (activeMeshIsReal) {
        // every texture on the model that belongs to this editable slot
        Object.keys(texByName).forEach(name => { if (texByName[name].slot === slotId) applyModelTexture(name); });
        return;
    }
    const loader = new THREE.TextureLoader();
    const texPath = `/api/texture/preview?slot=${slotId}&type=mod&t=${Date.now()}`;
    loader.load(texPath, (tex) => {
        activeMesh.traverse(child => {
            if (child.isMesh && child.material) {
                child.material.map = tex;
                child.material.needsUpdate = true;
            }
        });
    });
}

function loadPrimitiveMesh(type) {
    if (activeMesh) scene.remove(activeMesh);
    activeMeshIsReal = false;
    texByName = {};

    const textureLoader = new THREE.TextureLoader();
    const texPath = `/api/texture/preview?slot=${activeSlotId}&type=mod&t=${Date.now()}`;
    const texture = textureLoader.load(texPath);

    let geom;
    if (type === "bust") {
        const group = new THREE.Group();
        // Head
        const headGeom = new THREE.SphereGeometry(0.5, 32, 32);
        const headMat = new THREE.MeshStandardMaterial({ map: texture, roughness: 0.5 });
        const head = new THREE.Mesh(headGeom, headMat);
        head.position.y = 1.0;
        group.add(head);

        // Cap Visor
        const capGeom = new THREE.CylinderGeometry(0.55, 0.55, 0.15, 32);
        const capMat = new THREE.MeshStandardMaterial({ color: 0x00d2ff, roughness: 0.7 });
        const cap = new THREE.Mesh(capGeom, capMat);
        cap.position.set(0, 1.3, 0.1);
        group.add(cap);

        // Shoulders / Bust
        const bustGeom = new THREE.CylinderGeometry(0.4, 0.6, 0.7, 32);
        const bustMat = new THREE.MeshStandardMaterial({ map: texture, roughness: 0.6 });
        const bust = new THREE.Mesh(bustGeom, bustMat);
        bust.position.y = 0.4;
        group.add(bust);

        activeMesh = group;
    } else if (type === "cap") {
        const capGroup = new THREE.Group();
        const domeGeom = new THREE.SphereGeometry(0.7, 32, 16, 0, Math.PI * 2, 0, Math.PI * 0.5);
        const domeMat = new THREE.MeshStandardMaterial({ map: texture, roughness: 0.6 });
        const dome = new THREE.Mesh(domeGeom, domeMat);
        capGroup.add(dome);

        const brimGeom = new THREE.CylinderGeometry(0.85, 0.85, 0.05, 32);
        const brim = new THREE.Mesh(brimGeom, domeMat);
        brim.position.y = 0.05;
        capGroup.add(brim);

        activeMesh = capGroup;
    } else if (type === "sphere") {
        geom = new THREE.SphereGeometry(0.8, 48, 48);
        const mat = new THREE.MeshStandardMaterial({ map: texture, roughness: 0.4 });
        activeMesh = new THREE.Mesh(geom, mat);
        activeMesh.position.y = 0.8;
    } else {
        // Character Figure
        const charGroup = new THREE.Group();
        const bodyGeom = new THREE.CylinderGeometry(0.4, 0.5, 1.0, 32);
        const bodyMat = new THREE.MeshStandardMaterial({ map: texture, roughness: 0.5 });
        const body = new THREE.Mesh(bodyGeom, bodyMat);
        body.position.y = 0.6;
        charGroup.add(body);

        const headGeom = new THREE.SphereGeometry(0.4, 32, 32);
        const head = new THREE.Mesh(headGeom, bodyMat);
        head.position.y = 1.3;
        charGroup.add(head);

        activeMesh = charGroup;
    }

    scene.add(activeMesh);
}

function onWindowResize() {
    if (!renderer || !camera) return;
    const container = isZenMode ? document.getElementById("zenCanvasContainer") : document.getElementById("threeCanvasWrap");
    if (!container) return;
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
}

function animate() {
    requestAnimationFrame(animate);
    if (controls) controls.update();
    if (activeMesh && (autoRotate || isZenMode)) {
        activeMesh.rotation.y += isZenMode ? 0.006 : 0.008;
    }
    if (renderer && scene && camera) {
        renderer.render(scene, camera);
    }
}

// ========================================================
// EDEN EMULATOR LAUNCH
// ========================================================
function initEdenLaunchers() {
    const launchHandler = async () => {
        showToast("🚀 Booting Eden Emulator with Super Mario Odyssey...");
        try {
            const res = await fetch("/api/launch_eden", { method: "POST" });
            const data = await res.json();
            if (data.success) {
                showToast("🎮 Eden Emulator is now running!");
            } else {
                showToast("Launch failed: " + data.error);
            }
        } catch (e) {
            showToast("Launch error: " + e.message);
        }
    };

    document.getElementById("btnLaunchEden").addEventListener("click", launchHandler);
    document.getElementById("btnQuickLaunch").addEventListener("click", launchHandler);
}

// ========================================================
// TOAST NOTIFICATIONS
// ========================================================
function showToast(msg) {
    const toast = document.getElementById("toast");
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => {
        toast.classList.remove("show");
    }, 3500);
}

// ========================================================
// SAVES & MOD MENU ENGINE
// ========================================================
let selectedSaveSlot = 1;

function initSavesAndMods() {
    const btnInject = document.getElementById("btnInject100");
    if (btnInject) {
        btnInject.addEventListener("click", async () => {
            if (!confirm(`Inject 100% Complete Master Save into Slot ${selectedSaveSlot}?\n\n(A safe backup will automatically be created before replacing)`)) {
                return;
            }
            btnInject.disabled = true;
            btnInject.innerHTML = `<span class="btn-icon">⏳</span> Injecting 100% Save...`;
            try {
                const res = await fetch("/api/saves/inject", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ slot: selectedSaveSlot })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(`✨ 100% Master Save Injected into Slot ${selectedSaveSlot}! (999 Moons, All Costumes, Post-Game)`);
                    await loadSavesAndMods();
                } else {
                    showToast(`Injection failed: ${data.error || "Unknown error"}`);
                }
            } catch (err) {
                showToast(`Error: ${err.message}`);
            } finally {
                btnInject.disabled = false;
                btnInject.innerHTML = `<span class="btn-icon">⚡</span> Inject 100% Complete Save`;
            }
        });
    }

    const btnBackup = document.getElementById("btnManualBackup");
    if (btnBackup) {
        btnBackup.addEventListener("click", async () => {
            btnBackup.disabled = true;
            try {
                const res = await fetch("/api/saves/backup", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ label: "user_manual" })
                });
                const data = await res.json();
                if (data.success) {
                    showToast("📦 Save files backed up successfully!");
                    await loadSavesAndMods();
                } else {
                    showToast(`Backup failed: ${data.error}`);
                }
            } catch (err) {
                showToast(`Error: ${err.message}`);
            } finally {
                btnBackup.disabled = false;
            }
        });
    }

    const btnRestore = document.getElementById("btnRestoreBackup");
    if (btnRestore) {
        btnRestore.addEventListener("click", async () => {
            const select = document.getElementById("backupSelect");
            const backupId = select.value;
            if (!backupId) {
                showToast("Please select a backup point from the list first.");
                return;
            }
            if (!confirm(`Restore backup ${backupId}?\nThis will revert your save files to this point.`)) {
                return;
            }
            btnRestore.disabled = true;
            try {
                const res = await fetch("/api/saves/restore", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ backup_id: backupId })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(`🔄 Restored backup ${backupId}!`);
                    await loadSavesAndMods();
                } else {
                    showToast(`Restore failed: ${data.error}`);
                }
            } catch (err) {
                showToast(`Error: ${err.message}`);
            } finally {
                btnRestore.disabled = false;
            }
        });
    }
}

async function loadSavesAndMods() {
    try {
        const res = await fetch("/api/saves");
        const data = await res.json();
        if (data.success && data.status) {
            renderSlotsGrid(data.status.slots || []);
            renderBackupsList(data.backups || []);
        }
    } catch (err) {
        console.error("Error loading saves:", err);
    }
}

function renderSlotsGrid(slots) {
    const grid = document.getElementById("saveSlotsGrid");
    if (!grid) return;
    grid.innerHTML = "";

    slots.forEach(slot => {
        const card = document.createElement("div");
        card.className = "slot-card" + (slot.slot === selectedSaveSlot ? " active" : "");
        card.innerHTML = `
            <div class="slot-card-num">Slot ${slot.slot}</div>
            <div class="slot-card-stage" title="${slot.stage}">${slot.kingdom || "Empty"}</div>
            <div class="slot-card-meta">
                <span class="slot-card-moons">🌕 ${slot.moons}</span>
                <span class="slot-card-coins">💰 ${slot.coins}</span>
            </div>
        `;
        card.addEventListener("click", () => {
            selectedSaveSlot = slot.slot;
            document.querySelectorAll(".slot-card").forEach(c => c.classList.remove("active"));
            card.classList.add("active");
        });
        grid.appendChild(card);
    });
}

function renderBackupsList(backups) {
    const select = document.getElementById("backupSelect");
    if (!select) return;
    select.innerHTML = '<option value="">Select a backup point to restore...</option>';
    backups.forEach(b => {
        const opt = document.createElement("option");
        opt.value = b.id;
        const dateStr = new Date(b.created * 1000).toLocaleString();
        opt.textContent = `${b.id} (${dateStr})`;
        select.appendChild(opt);
    });
}

// ========================================================
// MARIO 3D SIZE & PROPORTIONS (TINY / CHIBI / NORMAL / BIG HEAD / GIANT / TITAN)
// ========================================================
const SCALE_PRESET_VALUES = {
    tiny: { body: 0.45, head: 1.15, label: "Tiny (0.45x)" },
    chibi: { body: 0.68, head: 1.38, label: "Kid / Chibi (0.68x)" },
    normal: { body: 1.0, head: 1.0, label: "Normal (1.0x)" },
    bobblehead: { body: 1.0, head: 2.0, label: "Big Head (2.0x)" },
    giant: { body: 2.0, head: 1.0, label: "Giant (2.0x)" },
    titan: { body: 3.0, head: 1.0, label: "Titan (3.0x)" }
};

function syncMarioScaleUI(state) {
    if (!state) return;
    currentMarioBodyScale = Number(state.body_scale || 1.0);
    currentMarioHeadMult = Number(state.head_mult || 1.0);
    const preset = state.preset || "normal";

    const sliderBody = document.getElementById("sliderBodyScale");
    const sliderHead = document.getElementById("sliderHeadMult");
    const valBody = document.getElementById("valBodyScale");
    const valHead = document.getElementById("valHeadMult");
    const badge1 = document.getElementById("marioScaleBadge");
    const badge2 = document.getElementById("savesMarioScaleBadge");

    if (sliderBody) sliderBody.value = currentMarioBodyScale;
    if (sliderHead) sliderHead.value = currentMarioHeadMult;
    if (valBody) valBody.textContent = `${currentMarioBodyScale.toFixed(2)}x`;
    if (valHead) valHead.textContent = `${currentMarioHeadMult.toFixed(2)}x`;

    const label = (SCALE_PRESET_VALUES[preset] && SCALE_PRESET_VALUES[preset].label)
        || `Custom (${currentMarioBodyScale.toFixed(2)}x / ${currentMarioHeadMult.toFixed(2)}x)`;
    if (badge1) badge1.textContent = label;
    if (badge2) badge2.textContent = `● ${label}`;

    document.querySelectorAll(".btn-scale-preset").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.scalePreset === preset);
    });

    apply3DScalePreview();
}

async function deployMarioScale(payload) {
    const btnDeploy = document.getElementById("btnDeployMarioScale");
    if (btnDeploy) {
        btnDeploy.disabled = true;
        btnDeploy.textContent = "⏳ Deploying Mario Size to Eden...";
    }
    try {
        const res = await fetch("/api/mario/scale", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            syncMarioScaleUI(data);
            showToast(`🍄 ${data.message}`);
        } else {
            showToast(`⚠️ ${data.error || "Could not deploy Mario size"}`);
        }
    } catch (e) {
        showToast("Error applying Mario scale: " + e.message);
    } finally {
        if (btnDeploy) {
            btnDeploy.disabled = false;
            btnDeploy.textContent = "⚡ Apply Size to 3D Preview & Deploy to Game";
        }
    }
}

async function initMarioScale() {
    try {
        const res = await fetch("/api/mario/scale");
        const state = await res.json();
        syncMarioScaleUI(state);
    } catch (e) {
        console.warn("Could not load Mario scale state:", e);
    }

    document.querySelectorAll(".btn-scale-preset").forEach(btn => {
        btn.addEventListener("click", () => {
            const preset = btn.dataset.scalePreset;
            const pval = SCALE_PRESET_VALUES[preset];
            if (pval) {
                currentMarioBodyScale = pval.body;
                currentMarioHeadMult = pval.head;
                syncMarioScaleUI({ preset, body_scale: pval.body, head_mult: pval.head });
            }
            deployMarioScale({ preset });
        });
    });

    const sliderBody = document.getElementById("sliderBodyScale");
    const sliderHead = document.getElementById("sliderHeadMult");
    const onSliderInput = () => {
        currentMarioBodyScale = parseFloat(sliderBody ? sliderBody.value : "1.0");
        currentMarioHeadMult = parseFloat(sliderHead ? sliderHead.value : "1.0");
        const valBody = document.getElementById("valBodyScale");
        const valHead = document.getElementById("valHeadMult");
        if (valBody) valBody.textContent = `${currentMarioBodyScale.toFixed(2)}x`;
        if (valHead) valHead.textContent = `${currentMarioHeadMult.toFixed(2)}x`;
        apply3DScalePreview();
    };
    if (sliderBody) sliderBody.addEventListener("input", onSliderInput);
    if (sliderHead) sliderHead.addEventListener("input", onSliderInput);

    const btnDeploy = document.getElementById("btnDeployMarioScale");
    if (btnDeploy) {
        btnDeploy.addEventListener("click", () => {
            deployMarioScale({
                preset: "custom",
                body_scale: currentMarioBodyScale,
                head_mult: currentMarioHeadMult
            });
        });
    }
}

// ========================================================
// COMMUNITY PACKS (GAMEBANANA BROWSER & 1-CLICK INSTALLER)
// ========================================================
let communityCuratedPacks = [];
let communityLivePacks = [];
let communityViewMode = "curated";

function initCommunityPacks() {
    const btnHeroLaunch = document.getElementById("btnHeroLaunchEden");
    if (btnHeroLaunch) {
        btnHeroLaunch.addEventListener("click", () => {
            document.getElementById("btnLaunchEden")?.click();
        });
    }

    const btnHeroToggleYsk = document.getElementById("btnHeroToggleYsk");
    if (btnHeroToggleYsk) {
        btnHeroToggleYsk.addEventListener("click", async () => {
            const ysk = communityCuratedPacks.find(p => p.id === "YoshiStarKingdom");
            const currentlyEnabled = ysk ? ysk.enabled : true;
            await toggleCommunityPack("YoshiStarKingdom", !currentlyEnabled);
        });
    }

    document.querySelectorAll("#communityViewPills .pill").forEach(pill => {
        pill.addEventListener("click", () => {
            document.querySelectorAll("#communityViewPills .pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            communityViewMode = pill.dataset.view;
            if (communityViewMode === "live" && communityLivePacks.length === 0) {
                searchGameBanana(document.getElementById("gbSearchInput")?.value || "");
            } else {
                renderCommunityGrid();
            }
        });
    });

    const btnSearch = document.getElementById("btnGbSearch");
    const inputSearch = document.getElementById("gbSearchInput");
    if (btnSearch) {
        btnSearch.addEventListener("click", () => {
            document.querySelectorAll("#communityViewPills .pill").forEach(p => {
                p.classList.toggle("active", p.dataset.view === "live");
            });
            communityViewMode = "live";
            searchGameBanana(inputSearch ? inputSearch.value : "");
        });
    }
    if (inputSearch) {
        inputSearch.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                btnSearch?.click();
            }
        });
    }

    loadCommunityPacks();
}

async function loadCommunityPacks() {
    try {
        const res = await fetch("/api/community/list");
        const data = await res.json();
        if (data.success) {
            communityCuratedPacks = data.packs || [];
            updateYskHeroBanner();
            if (communityViewMode === "curated") {
                renderCommunityGrid();
            }
        }
    } catch (e) {
        console.error("Failed to load community packs:", e);
    }
}

function updateYskHeroBanner() {
    const ysk = communityCuratedPacks.find(p => p.id === "YoshiStarKingdom");
    const badge = document.getElementById("yskHeroStatusBadge");
    const btnToggle = document.getElementById("btnHeroToggleYsk");
    if (!ysk) return;
    if (badge) {
        if (ysk.enabled) {
            badge.textContent = "● INSTALLED & ACTIVE IN EDEN";
            badge.style.background = "rgba(16, 185, 129, 0.22)";
            badge.style.color = "#6ee7b7";
            badge.style.borderColor = "rgba(16, 185, 129, 0.5)";
        } else {
            badge.textContent = "○ INSTALLED (CURRENTLY DISABLED)";
            badge.style.background = "rgba(148, 163, 184, 0.2)";
            badge.style.color = "#cbd5e1";
            badge.style.borderColor = "rgba(148, 163, 184, 0.4)";
        }
    }
    if (btnToggle) {
        btnToggle.textContent = ysk.enabled ? "⏸ Disable Pack" : "⚡ Enable Yoshi Star Galaxy";
        btnToggle.className = ysk.enabled ? "btn btn-secondary" : "btn btn-action";
    }
}

async function searchGameBanana(query) {
    const grid = document.getElementById("communityPacksGrid");
    if (grid) {
        grid.innerHTML = `<div style="grid-column:1/-1; padding:32px; text-align:center; color:#93c5fd;">🌐 Querying live GameBanana API (Super Mario Odyssey #6376)...</div>`;
    }
    try {
        const res = await fetch(`/api/community/search?q=${encodeURIComponent(query || "")}`);
        const data = await res.json();
        if (data.success) {
            communityLivePacks = data.results || [];
            renderCommunityGrid();
        } else {
            if (grid) grid.innerHTML = `<div style="grid-column:1/-1; padding:24px; color:#f87171;">GameBanana search error: ${data.error}</div>`;
        }
    } catch (e) {
        if (grid) grid.innerHTML = `<div style="grid-column:1/-1; padding:24px; color:#f87171;">Failed to reach GameBanana: ${e.message}</div>`;
    }
}

function renderCommunityGrid() {
    const grid = document.getElementById("communityPacksGrid");
    const badge = document.getElementById("communityCountBadge");
    if (!grid) return;

    const list = communityViewMode === "curated" ? communityCuratedPacks : communityLivePacks;
    if (badge) {
        badge.textContent = `${list.length} ${communityViewMode === "curated" ? "Featured" : "Live Results"}`;
    }
    grid.innerHTML = "";

    if (list.length === 0) {
        grid.innerHTML = `<div style="grid-column:1/-1; padding:28px; text-align:center; color:var(--text-muted);">No matching mod packs found. Try searching for "Galaxy", "Texture", "Kingdom", or "Luigi".</div>`;
        return;
    }

    list.forEach(pack => {
        const card = document.createElement("div");
        card.className = `community-pack-card ${pack.enabled ? "pack-active" : ""}`;
        const thumbUrl = pack.thumb || "thumbs/yoshi_star.jpg";
        const statusChip = pack.enabled
            ? `<span class="pack-status-chip active">● ACTIVE IN EDEN</span>`
            : (pack.installed ? `<span class="pack-status-chip installed">INSTALLED (OFF)</span>` : `<span class="pack-status-chip">GAMEBANANA #${pack.gb_id}</span>`);

        const sizeInfo = pack.size_mb ? `<span>📦 ${pack.size_mb} MB</span>` : "";
        const likesInfo = pack.likes ? `<span>❤️ ${pack.likes}</span>` : "";
        const viewsInfo = pack.views ? `<span>👁️ ${pack.views.toLocaleString()}</span>` : "";

        let actionBtnHtml = "";
        if (pack.installed) {
            actionBtnHtml = `
                <button class="btn ${pack.enabled ? "btn-secondary" : "btn-action"} btn-sm btn-pack-toggle" data-id="${pack.id}" data-enable="${!pack.enabled}">
                    ${pack.enabled ? "⏸ Disable Pack" : "⚡ Enable in Eden"}
                </button>
            `;
        } else {
            actionBtnHtml = `
                <button class="btn btn-action btn-sm btn-pack-install" data-gbid="${pack.gb_id}" data-id="${pack.id}">
                    ⬇️ 1-Click Download &amp; Activate
                </button>
            `;
        }

        card.innerHTML = `
            <div class="pack-thumb-wrap">
                <img src="${thumbUrl}" alt="${pack.name}" loading="lazy" onerror="this.onerror=null;this.src='thumbs/yoshi_star.jpg';">
                <span class="pack-cat-tag">${pack.category || "Mod Pack"}</span>
                ${statusChip}
            </div>
            <div class="pack-body">
                <h4>${pack.name}</h4>
                <div class="pack-meta-row">
                    <span>👤 ${pack.author}</span>
                    ${sizeInfo}
                    ${likesInfo}
                    ${viewsInfo}
                </div>
                ${pack.description ? `<p class="pack-desc">${pack.description}</p>` : ""}
                ${pack.how_to_play ? `<div class="pack-howto"><strong>🎮 In-Game:</strong> ${pack.how_to_play}</div>` : ""}
                <div class="pack-actions-row">
                    ${actionBtnHtml}
                    ${pack.gb_id ? `<a href="https://gamebanana.com/mods/${pack.gb_id}" target="_blank" class="btn btn-outline btn-sm" style="text-decoration:none;">🔗 Page</a>` : ""}
                </div>
            </div>
        `;

        const btnToggle = card.querySelector(".btn-pack-toggle");
        if (btnToggle) {
            btnToggle.addEventListener("click", async () => {
                btnToggle.disabled = true;
                btnToggle.textContent = "⏳ Updating...";
                await toggleCommunityPack(btnToggle.dataset.id, btnToggle.dataset.enable === "true");
            });
        }

        const btnInstall = card.querySelector(".btn-pack-install");
        if (btnInstall) {
            btnInstall.addEventListener("click", async () => {
                btnInstall.disabled = true;
                btnInstall.textContent = "⏳ Downloading & Normalizing...";
                await installCommunityPack(btnInstall.dataset.gbid, btnInstall.dataset.id, btnInstall);
            });
        }

        grid.appendChild(card);
    });
}

async function toggleCommunityPack(packId, enable) {
    try {
        const res = await fetch("/api/community/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: packId, enabled: enable })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`🌟 ${data.message}`);
            await loadCommunityPacks();
            if (communityViewMode === "live") {
                communityLivePacks.forEach(p => {
                    if (p.id === packId) p.enabled = enable;
                });
                renderCommunityGrid();
            }
        } else {
            showToast(`⚠️ ${data.error || "Could not toggle pack"}`);
            await loadCommunityPacks();
        }
    } catch (e) {
        showToast("Error toggling pack: " + e.message);
    }
}

async function installCommunityPack(gbId, packId, btnEl) {
    showToast(`⬇️ Downloading GameBanana Mod #${gbId} and normalizing for Switch v1.0.0...`);
    try {
        const res = await fetch("/api/community/install", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ gb_id: Number(gbId), id: packId })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`🎉 ${data.message}`);
            await loadCommunityPacks();
            if (communityViewMode === "live") {
                communityLivePacks.forEach(p => {
                    if (String(p.gb_id) === String(gbId)) {
                        p.installed = true;
                        p.enabled = true;
                    }
                });
                renderCommunityGrid();
            }
        } else {
            showToast(`⚠️ Install failed: ${data.error}`);
            if (btnEl) {
                btnEl.disabled = false;
                btnEl.textContent = "⬇️ 1-Click Download & Activate";
            }
        }
    } catch (e) {
        showToast("Download error: " + e.message);
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.textContent = "⬇️ 1-Click Download & Activate";
        }
    }
}


