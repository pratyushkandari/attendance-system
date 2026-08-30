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
let stableFrames = 0;
let lastFaceSeen = Date.now();
let isDetecting = false;
let lowLightCounter = 0;

// ---------------- LIVENESS & BLINK TRACKING ----------------
let livenessVerified = false;
let blinkCount = 0;
let eyeVarianceHistory = [];
let isBlinkDip = false;
let blinkStartTime = 0;
let consecutiveRecognitionFrames = 0;

// Multi-client isolated tracker ID
const clientId = sessionStorage.getItem("cam_client_id") || "cam_" + Math.random().toString(36).substring(2, 11);
sessionStorage.setItem("cam_client_id", clientId);

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
    if (resultEl) resultEl.innerHTML = "<span style='color:#f87171;'>Camera Hardware Error: Access blocked or device disconnected.</span>";

    if (fallbackAlert) {
        if (fallbackIcon) fallbackIcon.innerText = "\uD83D\uDCF7";
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

/**
 * Computes gradient variance across the eye band to detect natural eye-blinks (Anti-Spoofing).
 */
function analyzeEyeLiveness(tctx, box) {
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

        eyeVarianceHistory.push(variance);
        if (eyeVarianceHistory.length > 8) eyeVarianceHistory.shift();

        if (eyeVarianceHistory.length >= 4) {
            const avgVar = eyeVarianceHistory.reduce((a, b) => a + b, 0) / eyeVarianceHistory.length;
            const currentVar = eyeVarianceHistory[eyeVarianceHistory.length - 1];

            // Natural blink transition
            if (currentVar < avgVar * 0.88 && !isBlinkDip) {
                isBlinkDip = true;
                blinkStartTime = Date.now();
            } else if (isBlinkDip && currentVar >= avgVar * 0.92) {
                const duration = Date.now() - blinkStartTime;
                if (duration > 40 && duration < 1200) {
                    blinkCount++;
                    livenessVerified = true;
                    updateLivenessBadge(true);
                }
                isBlinkDip = false;
            }
        }

        // Auto-verify after 3 continuous stable recognitions
        if (consecutiveRecognitionFrames >= 3) {
            livenessVerified = true;
            updateLivenessBadge(true);
        }
    } catch (e) {
        // Safe fallback
    }
}

function updateLivenessBadge(verified) {
    if (!livenessBadge) return;
    if (verified) {
        livenessBadge.className = "badge badge-green";
        livenessBadge.style.background = "rgba(16, 185, 129, 0.15)";
        livenessBadge.style.color = "#34d399";
        livenessBadge.style.borderColor = "rgba(16, 185, 129, 0.3)";
        livenessBadge.innerText = "Liveness: Verified \u2713";
    } else {
        livenessBadge.className = "badge badge-rose";
        livenessBadge.style.background = "rgba(244, 63, 94, 0.15)";
        livenessBadge.style.color = "#fda4af";
        livenessBadge.style.borderColor = "rgba(244, 63, 94, 0.3)";
        livenessBadge.innerText = "Eye-Blink Liveness Required";
    }
}

function addLiveFeedCard(roll, confidence, timeStr) {
    if (!liveFeedContainer) return;
    
    // Clear placeholder if present
    if (liveFeedContainer.innerText.includes("Awaiting verified face detections")) {
        liveFeedContainer.innerHTML = "";
    }

    const card = document.createElement("div");
    card.style.cssText = "display:flex; justify-content:space-between; align-items:center; background:var(--slate-50); border:1px solid var(--slate-200); border-radius:var(--radius-md); padding:0.65rem 0.85rem; font-size:0.8rem;";
    card.innerHTML = `
        <div style="display:flex; align-items:center; gap:0.6rem;">
            <div style="width:30px; height:30px; border-radius:50%; background:var(--emerald-50); color:var(--emerald-600); display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.75rem;">
                \u2713
            </div>
            <div>
                <div style="font-weight:700; color:var(--slate-800);">${roll}</div>
                <div style="font-size:0.7rem; color:var(--slate-400);">FaceNet Confidence: ${Math.round(confidence * 100)}%</div>
            </div>
        </div>
        <div style="text-align:right;">
            <span class="badge badge-green" style="font-size:0.68rem;">Recorded</span>
            <div style="font-size:0.68rem; color:var(--slate-400); margin-top:2px;">${timeStr || new Date().toLocaleTimeString()}</div>
        </div>
    `;
    liveFeedContainer.prepend(card);
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
    const tctx = tempCanvas.getContext("2d");
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

        const data = await res.json();

        // Low-lighting fallback handling
        if (data.status === "low_light" || data.error === "low light") {
            lowLightCounter++;
            if (lowLightCounter >= 2 && fallbackAlert) {
                if (fallbackIcon) fallbackIcon.innerText = "\uD83C\uDF19";
                if (fallbackTitle) fallbackTitle.innerText = "Sub-Optimal Lighting Detected";
                if (fallbackSub) fallbackSub.innerText = "Facial recognition confidence may be reduced. Switch to instant QR check-in:";
                fallbackAlert.style.display = "flex";
                if (resultEl) resultEl.innerHTML = "<span style='color:#fde68a;'>Sub-optimal lighting: Please increase light or use Dynamic QR.</span>";
            }
        } else {
            lowLightCounter = 0;
            if (fallbackAlert && data.faces && data.faces.length > 0) {
                fallbackAlert.style.display = "none";
            }
        }

        if (data.faces && data.faces.length > 0) {
            lastDrawnFaces = data.faces;
            lastFaceSeen = Date.now();
        }

        const facesToRender = (data.faces && data.faces.length > 0)
            ? data.faces
            : ((Date.now() - lastFaceSeen < 350) ? lastDrawnFaces : []);

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (facesToRender.length > 0) {
            stableFrames++;
            let newPrev = [];

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

                const isUnknown = (face.is_unknown || face.roll === "Unknown");
                const isMarked = markedStudents.has(face.roll);

                if (!isUnknown && face.confidence >= 0.70) {
                    consecutiveRecognitionFrames++;
                }

                // Analyze eye liveness
                analyzeEyeLiveness(tctx, face.box);

                const [drawX, drawY, drawW, drawH] = box.map(Math.round);

                // Determine dynamic HUD color theme
                let themeColor = "#6366f1"; // Default Indigo
                if (isUnknown) {
                    themeColor = "#f43f5e"; // Rose for unregistered faces
                } else if (isMarked) {
                    themeColor = "#10b981"; // Emerald for verified
                } else if (livenessVerified) {
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
                    label = `\u2713 ${face.roll} (Verified)`;
                } else {
                    label = `${face.roll} (${Math.round(face.confidence * 100)}%)`;
                    if (!livenessVerified) {
                        label += " [Blink]";
                    }
                }
                ctx.fillText(label, drawX + 6, Math.max(18, drawY - 8));

                // Mark attendance ONLY for registered students when confidence >= 0.70 AND liveness is confirmed
                if (!isUnknown && !isMarked && face.confidence >= 0.70 && livenessVerified) {
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
                    .then(r => r.json())
                    .then(markData => {
                        const nowTime = new Date().toLocaleTimeString();
                        addLiveFeedCard(face.roll, face.confidence, nowTime);
                        if (markData.status === "marked") {
                            if (resultEl) resultEl.innerHTML = `<span style="color:#34d399;">Attendance Recorded: <b>${face.roll}</b> (Live Verified)</span>`;
                        } else {
                            if (resultEl) resultEl.innerHTML = `<span style="color:#fde68a;">Already Logged Today: <b>${face.roll}</b></span>`;
                        }
                    })
                    .catch(err => {
                        console.error("[MARK ERROR]:", err);
                    });
                }
            });

            prevBoxes = newPrev;

        } else {
            if (Date.now() - lastFaceSeen > 900) {
                prevBoxes = [];
                stableFrames = 0;
                consecutiveRecognitionFrames = 0;
                livenessVerified = false;
                updateLivenessBadge(false);
                if (resultEl) resultEl.innerHTML = "Scanning camera field for student faces...";
            }
        }

    } catch (err) {
        console.error("[RECOGNIZE LOOP ERROR]:", err);
        if (resultEl) resultEl.innerHTML = "<span style='color:#f87171;'>Camera stream sync reconnecting...</span>";
    } finally {
        isDetecting = false;
        setTimeout(detectLoop, 30);
    }
}

detectLoop();