const video = document.getElementById("video");
const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");
const resultEl = document.getElementById("result");
const livenessBadge = document.getElementById("livenessBadge");
const fallbackAlert = document.getElementById("fallbackAlert");
const fallbackIcon = document.getElementById("fallbackIcon");
const fallbackTitle = document.getElementById("fallbackTitle");
const fallbackSub = document.getElementById("fallbackSub");
const liveFeedContainer = document.getElementById("liveFeedContainer");

let markedStudents = new Set();
let prevBoxes = [];
let lastFaceSeen = Date.now();
let isDetecting = false;
let lowLightCounter = 0;

// ---------------- LIVENESS & BLINK TRACKING ----------------
// Liveness is tracked separately for every recognised student (keyed by roll), so a
// blink from one person can never verify a different face (e.g. a photo held up next
// to them). A face is "live" only after its own eye-band variance dips and recovers
// like a natural blink. There is no time-based bypass.
const LIVENESS_STATE_TTL_MS = 1500;
const livenessByRoll = new Map();

// Multi-client isolated tracker ID
const clientId = sessionStorage.getItem("cam_client_id") || "cam_" + Math.random().toString(36).substring(2, 11);
sessionStorage.setItem("cam_client_id", clientId);

function setResult(text, color) {
    if (!resultEl) return;
    resultEl.textContent = text;
    resultEl.style.color = color || "var(--slate-200)";
}

// ---------------- WEBCAM INITIALIZATION & ERROR HANDLING ----------------
navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }
})
.then(stream => {
    video.srcObject = stream;
    video.onloadedmetadata = () => {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
    };
})
.catch(err => {
    console.error("[WEBCAM HARDWARE ERROR]:", err);
    setResult("Camera Hardware Error: Access blocked or device disconnected.", "#f87171");

    if (fallbackAlert) {
        if (fallbackIcon) fallbackIcon.innerText = "📷";
        if (fallbackTitle) fallbackTitle.innerText = "Camera Device Unavailable";
        if (fallbackSub) fallbackSub.innerText = "Webcam is disconnected or blocked. You can take attendance with Dynamic QR instead:";
        fallbackAlert.style.display = "flex";
    }
});

/**
 * Fast dynamic bounding box smoothing:
 * Snaps instantly during rapid head movements (zero lag)
 * Applies subtle smoothing only when nearly stationary.
 */
function smoothBox(prev, curr) {
    if (!prev) return curr;
    const dx = Math.abs(curr[0] - prev[0]);
    const dy = Math.abs(curr[1] - prev[1]);

    // Rapid movement: snap immediately with zero lag
    if (dx > 18 || dy > 18) {
        return curr;
    }

    // Subtle smoothing when holding still
    const alpha = 0.35;
    return [
        prev[0] + (curr[0] - prev[0]) * alpha,
        prev[1] + (curr[1] - prev[1]) * alpha,
        prev[2] + (curr[2] - prev[2]) * alpha,
        prev[3] + (curr[3] - prev[3]) * alpha,
    ];
}

function getLivenessState(roll) {
    let state = livenessByRoll.get(roll);
    if (!state) {
        state = { history: [], isDip: false, dipStart: 0, verified: false, lastSeen: 0 };
        livenessByRoll.set(roll, state);
    }
    state.lastSeen = Date.now();
    return state;
}

/** Forget faces that left the frame so a returning (or substituted) face must blink again. */
function pruneLivenessStates() {
    const now = Date.now();
    for (const [roll, state] of livenessByRoll) {
        if (now - state.lastSeen > LIVENESS_STATE_TTL_MS) livenessByRoll.delete(roll);
    }
}

/**
 * Computes grey-level variance across the eye band of one face to detect a natural
 * eye-blink (anti-spoofing). A blink is a variance dip below 88% of the rolling mean
 * that recovers above 92% within 40-1200 ms. `box` must come from the same frame that
 * was drawn into `tctx`.
 */
function analyzeEyeLiveness(tctx, box, state) {
    try {
        const [x, y, w, h] = box;
        const eyeY = Math.max(0, Math.round(y + h * 0.18));
        const eyeH = Math.max(10, Math.round(h * 0.28));
        const eyeX = Math.max(0, Math.round(x + w * 0.12));
        const eyeW = Math.max(10, Math.round(w * 0.76));

        const imgData = tctx.getImageData(eyeX, eyeY, eyeW, eyeH);
        const data = imgData.data;

        let sum = 0;
        let sumSq = 0;
        const count = data.length / 4;

        for (let i = 0; i < data.length; i += 4) {
            const gray = (data[i] * 0.299 + data[i+1] * 0.587 + data[i+2] * 0.114);
            sum += gray;
            sumSq += gray * gray;
        }

        const mean = sum / count;
        const variance = (sumSq / count) - (mean * mean);

        state.history.push(variance);
        if (state.history.length > 8) state.history.shift();

        if (state.history.length >= 4) {
            const avgVar = state.history.reduce((a, b) => a + b, 0) / state.history.length;
            const currentVar = state.history[state.history.length - 1];

            // Natural blink transition
            if (currentVar < avgVar * 0.88 && !state.isDip) {
                state.isDip = true;
                state.dipStart = Date.now();
            } else if (state.isDip && currentVar >= avgVar * 0.92) {
                const duration = Date.now() - state.dipStart;
                if (duration > 40 && duration < 1200) {
                    state.verified = true;
                }
                state.isDip = false;
            }
        }
    } catch (e) {
        // getImageData can fail for boxes outside the canvas; skip this sample
    }
}

function updateLivenessBadge(verified) {
    if (!livenessBadge) return;
    if (verified) {
        livenessBadge.className = "badge badge-green";
        livenessBadge.style.background = "rgba(16, 185, 129, 0.15)";
        livenessBadge.style.color = "#34d399";
        livenessBadge.style.borderColor = "rgba(16, 185, 129, 0.3)";
        livenessBadge.innerText = "Liveness: Verified ✓";
    } else {
        livenessBadge.className = "badge badge-rose";
        livenessBadge.style.background = "rgba(244, 63, 94, 0.15)";
        livenessBadge.style.color = "#fda4af";
        livenessBadge.style.borderColor = "rgba(244, 63, 94, 0.3)";
        livenessBadge.innerText = "Eye-Blink Liveness Required";
    }
}

/**
 * Prepend a card to the session feed.
 * `status` is "marked" (new record) or "already" (record existed earlier today).
 */
function addLiveFeedCard(roll, confidence, timeStr, status) {
    if (!liveFeedContainer) return;

    // Clear placeholder if present
    if (liveFeedContainer.innerText.includes("Awaiting verified face detections")) {
        liveFeedContainer.innerHTML = "";
    }

    const isNew = status === "marked";
    const card = document.createElement("div");
    card.style.cssText = "display:flex; justify-content:space-between; align-items:center; background:var(--slate-50); border:1px solid var(--slate-200); border-radius:var(--radius-md); padding:0.65rem 0.85rem; font-size:0.8rem;";
    card.innerHTML = `
        <div style="display:flex; align-items:center; gap:0.6rem;">
            <div style="width:30px; height:30px; border-radius:50%; background:var(--emerald-50); color:var(--emerald-600); display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.75rem;">
                ✓
            </div>
            <div>
                <div class="feed-roll" style="font-weight:700; color:var(--slate-800);"></div>
                <div style="font-size:0.7rem; color:var(--slate-400);">FaceNet Confidence: ${Math.round(confidence * 100)}%</div>
            </div>
        </div>
        <div style="text-align:right;">
            <span class="badge ${isNew ? "badge-green" : "badge-amber"}" style="font-size:0.68rem;">${isNew ? "Recorded" : "Already Logged"}</span>
            <div class="feed-time" style="font-size:0.68rem; color:var(--slate-400); margin-top:2px;"></div>
        </div>
    `;
    card.querySelector(".feed-roll").textContent = roll;
    card.querySelector(".feed-time").textContent = timeStr || new Date().toLocaleTimeString();
    liveFeedContainer.prepend(card);
}

/** Submit a Face attendance record once a recognised face has proven liveness. */
function markFaceAttendance(face) {
    markedStudents.add(face.roll);

    fetch("/mark_attendance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
            roll: face.roll,
            method: "Face"
        })
    })
    .then(async r => {
        if (r.status === 401) {
            window.location.href = "/";
            return;
        }
        const markData = await r.json();
        const nowTime = new Date().toLocaleTimeString();
        if (markData.status === "marked") {
            addLiveFeedCard(face.roll, face.confidence, nowTime, "marked");
            setResult(`Attendance Recorded: ${face.roll} (Live Verified)`, "#34d399");
        } else if (markData.status === "already marked today") {
            addLiveFeedCard(face.roll, face.confidence, nowTime, "already");
            setResult(`Already Logged Today: ${face.roll}`, "#fde68a");
        } else {
            // Not recorded: allow a retry on a later frame
            markedStudents.delete(face.roll);
            setResult(`Could not record ${face.roll}: ${markData.message || "server error"}`, "#f87171");
        }
    })
    .catch(err => {
        console.error("[MARK ERROR]:", err);
        markedStudents.delete(face.roll);
        setResult(`Network error while recording ${face.roll}. Retrying...`, "#f87171");
    });
}

let lastDrawnFaces = [];

async function detectLoop() {
    if (isDetecting || video.videoWidth === 0) {
        setTimeout(detectLoop, 50);
        return;
    }

    isDetecting = true;

    if (canvas.width !== video.clientWidth || canvas.height !== video.clientHeight) {
        canvas.width = video.clientWidth;
        canvas.height = video.clientHeight;
    }

    const targetWidth = 380;
    const scaleFactor = targetWidth / video.videoWidth;
    const targetHeight = Math.round(video.videoHeight * scaleFactor);

    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = targetWidth;
    tempCanvas.height = targetHeight;
    const tctx = tempCanvas.getContext("2d", { willReadFrequently: true });
    tctx.drawImage(video, 0, 0, targetWidth, targetHeight);

    const image = tempCanvas.toDataURL("image/jpeg", 0.60);

    try {
        const res = await fetch("/recognize_with_box", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({
                image: image,
                client_id: clientId
            })
        });

        if (res.status === 401) {
            window.location.href = "/";
            return;
        }

        const data = await res.json();

        // Low-lighting fallback handling
        if (data.status === "low_light" || data.error === "low light") {
            lowLightCounter++;
            if (lowLightCounter >= 2 && fallbackAlert) {
                if (fallbackIcon) fallbackIcon.innerText = "🌙";
                if (fallbackTitle) fallbackTitle.innerText = "Sub-Optimal Lighting Detected";
                if (fallbackSub) fallbackSub.innerText = "Facial recognition confidence may be reduced. Switch to instant QR check-in:";
                fallbackAlert.style.display = "flex";
                setResult("Sub-optimal lighting: Please increase light or use Dynamic QR.", "#fde68a");
            }
        } else {
            lowLightCounter = 0;
            if (fallbackAlert && data.faces && data.faces.length > 0) {
                fallbackAlert.style.display = "none";
            }
        }

        const hasFreshFaces = Boolean(data.faces && data.faces.length > 0);
        if (hasFreshFaces) {
            lastDrawnFaces = data.faces;
            lastFaceSeen = Date.now();
        }

        // Briefly keep drawing the last boxes to avoid flicker between frames
        const facesToRender = hasFreshFaces
            ? data.faces
            : ((Date.now() - lastFaceSeen < 350) ? lastDrawnFaces : []);

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (facesToRender.length > 0) {
            let newPrev = [];
            let anyKnownFace = false;
            let allKnownFacesLive = true;

            facesToRender.forEach((face, i) => {
                const coordScaleX = video.clientWidth / targetWidth;
                const coordScaleY = video.clientHeight / targetHeight;

                const [rawX, rawY, rawW, rawH] = face.box;
                const scaledBox = [
                    rawX * coordScaleX,
                    rawY * coordScaleY,
                    rawW * coordScaleX,
                    rawH * coordScaleY
                ];

                let box = smoothBox(prevBoxes[i], scaledBox);
                newPrev.push(box);

                // The server applies FACE_MATCH_THRESHOLD and flags non-matches as unknown
                const isUnknown = (face.is_unknown || face.roll === "Unknown");
                const isMarked = markedStudents.has(face.roll);

                let isLive = false;
                if (!isUnknown) {
                    anyKnownFace = true;
                    const state = getLivenessState(face.roll);
                    // Only sample liveness on boxes computed for *this* frame; reused
                    // boxes from an earlier frame would measure the wrong pixels.
                    if (hasFreshFaces) {
                        analyzeEyeLiveness(tctx, face.box, state);
                    }
                    isLive = state.verified;
                    if (!isLive) allKnownFacesLive = false;
                }

                const [drawX, drawY, drawW, drawH] = box.map(Math.round);

                // Determine dynamic HUD color theme
                let themeColor = "#6366f1"; // Default Indigo
                if (isUnknown) {
                    themeColor = "#f43f5e"; // Rose for unregistered faces
                } else if (isMarked) {
                    themeColor = "#10b981"; // Emerald for verified
                } else if (isLive) {
                    themeColor = "#06b6d4"; // Cyan for live verified
                }

                // Render dynamic HUD bounding box
                ctx.strokeStyle = themeColor;
                ctx.lineWidth = 2.5;
                ctx.strokeRect(drawX, drawY, drawW, drawH);

                // Label badge
                ctx.fillStyle = themeColor;
                ctx.fillRect(drawX, Math.max(0, drawY - 26), Math.max(160, drawW), 26);

                ctx.fillStyle = "#ffffff";
                ctx.font = "bold 12px 'Plus Jakarta Sans', sans-serif";
                let label = "";
                if (isUnknown) {
                    label = `Unregistered Face (${Math.round(face.confidence * 100)}%)`;
                } else if (isMarked) {
                    label = `✓ ${face.roll} (Verified)`;
                } else {
                    label = `${face.roll} (${Math.round(face.confidence * 100)}%)`;
                    if (!isLive) {
                        label += " [Blink]";
                    }
                }
                ctx.fillText(label, drawX + 6, Math.max(18, drawY - 8));

                // Mark attendance ONLY for recognised students whose own blink was seen
                if (!isUnknown && !isMarked && isLive) {
                    markFaceAttendance(face);
                }
            });

            prevBoxes = newPrev;
            updateLivenessBadge(anyKnownFace && allKnownFacesLive);
            pruneLivenessStates();

        } else {
            pruneLivenessStates();
            if (Date.now() - lastFaceSeen > 900) {
                prevBoxes = [];
                livenessByRoll.clear();
                updateLivenessBadge(false);
                setResult("Scanning camera field for student faces...");
            }
        }

    } catch (err) {
        console.error("[RECOGNIZE LOOP ERROR]:", err);
        setResult("Camera stream sync reconnecting...", "#f87171");
    } finally {
        isDetecting = false;
        setTimeout(detectLoop, 30);
    }
}

detectLoop();
