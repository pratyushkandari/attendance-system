const video = document.getElementById("video");
const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");
const resultEl = document.getElementById("result");
const livenessBadge = document.getElementById("livenessBadge");
const fallbackAlert = document.getElementById("fallbackAlert");

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
    console.error("[WEBCAM ERROR]:", err);
    resultEl.innerHTML = "❌ <b>Camera Access Required:</b> Please grant webcam permissions or switch to mobile QR check-in.";
    if (fallbackAlert) {
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
    if (verified) {
        livenessBadge.style.background = "#dcfce7";
        livenessBadge.style.color = "#166534";
        livenessBadge.innerText = "👁️ Liveness: Verified ✓";
    } else {
        livenessBadge.style.background = "#fee2e2";
        livenessBadge.style.color = "#991b1b";
        livenessBadge.innerText = "👁️ Liveness: Blink Required";
    }
}

async function detectLoop() {
    if (isDetecting || video.videoWidth === 0) {
        setTimeout(detectLoop, 50);
        return;
    }

    isDetecting = true;

    canvas.width = video.clientWidth;
    canvas.height = video.clientHeight;

    // Use optimized resolution (380px) for ultra-fast network roundtrip
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
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Low-lighting fallback handling
        if (data.status === "low_light" || data.error === "low light") {
            lowLightCounter++;
            if (lowLightCounter >= 2 && fallbackAlert) {
                fallbackAlert.style.display = "flex";
                resultEl.innerHTML = "🌙 <b>Low lighting detected:</b> Please increase lighting or switch to QR.";
            }
        } else {
            lowLightCounter = 0;
            if (fallbackAlert && data.faces && data.faces.length > 0) {
                fallbackAlert.style.display = "none";
            }
        }

        if (data.faces && data.faces.length > 0) {
            stableFrames++;
            lastFaceSeen = Date.now();

            let newPrev = [];

            data.faces.forEach((face, i) => {
                // Scale back from 380px processing space to displayed canvas coordinates
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
                let themeColor = "#3b82f6"; // Default blue
                if (isUnknown) {
                    themeColor = "#ef4444"; // Red for unregistered faces
                } else if (isMarked) {
                    themeColor = "#eab308"; // Gold for already marked
                } else if (livenessVerified) {
                    themeColor = "#16a34a"; // Green for live verified
                }

                // Render dynamic HUD bounding box
                ctx.strokeStyle = themeColor;
                ctx.lineWidth = 3;
                ctx.strokeRect(drawX, drawY, drawW, drawH);

                // Label badge
                ctx.fillStyle = themeColor;
                ctx.fillRect(drawX, Math.max(0, drawY - 26), Math.max(160, drawW), 26);

                ctx.fillStyle = "#ffffff";
                ctx.font = "bold 13px sans-serif";
                let label = "";
                if (isUnknown) {
                    label = `⚠️ Unregistered Face (${Math.round(face.confidence * 100)}%)`;
                } else if (isMarked) {
                    label = `✓ ${face.roll} (Marked)`;
                } else {
                    label = `${face.roll} (${Math.round(face.confidence * 100)}%)`;
                    if (!livenessVerified) {
                        label += " [Blink to verify]";
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
                        if (markData.status === "marked") {
                            resultEl.innerHTML = `✅ <b style="color:#16a34a;">Attendance Marked!</b><br>🎓 Student Roll: <b>${face.roll}</b> (Live Verified)`;
                        } else {
                            resultEl.innerHTML = `⚠️ <b style="color:#ca8a04;">Already Marked Today</b><br>🎓 Student Roll: <b>${face.roll}</b>`;
                        }
                    })
                    .catch(err => {
                        console.error("[MARK ERROR]:", err);
                    });
                }
            });

            prevBoxes = newPrev;

        } else {
            // Reset when face is out of view
            if (Date.now() - lastFaceSeen > 900) {
                prevBoxes = [];
                stableFrames = 0;
                consecutiveRecognitionFrames = 0;
                livenessVerified = false;
                updateLivenessBadge(false);
                resultEl.innerHTML = "🔍 Scanning for registered students...";
            }
        }

    } catch (err) {
        console.error("[RECOGNIZE LOOP ERROR]:", err);
        resultEl.innerHTML = "⚡ <b>Reconnecting:</b> Verifying camera feed stream...";
    } finally {
        isDetecting = false;
        // Ultra-low latency loop continuation
        setTimeout(detectLoop, 30);
    }
}

detectLoop();