const video = document.getElementById("video");
const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");
const resultEl = document.getElementById("result");
const livenessBadge = document.getElementById("livenessBadge");

let markedStudents = new Set();
let prevBoxes = [];
let stableFrames = 0;
let lastFaceSeen = Date.now();
let isDetecting = false;

// ---------------- LIVENESS & BLINK TRACKING ----------------
let livenessVerified = false;
let blinkCount = 0;
let eyeVarianceHistory = [];
let isBlinkDip = false;
let blinkStartTime = 0;

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
    resultEl.innerHTML = "❌ Camera access denied. Please allow permissions.";
});

function smoothBox(prev, curr) {
    if (!prev) return curr;
    const alpha = 0.70;
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
        // Eye band is approximately in the upper 20% to 45% region of the face
        const eyeY = Math.max(0, Math.round(y + h * 0.20));
        const eyeH = Math.max(10, Math.round(h * 0.25));
        const eyeX = Math.max(0, Math.round(x + w * 0.15));
        const eyeW = Math.max(10, Math.round(w * 0.70));

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

        if (eyeVarianceHistory.length >= 5) {
            const avgVar = eyeVarianceHistory.reduce((a, b) => a + b, 0) / eyeVarianceHistory.length;
            const currentVar = eyeVarianceHistory[eyeVarianceHistory.length - 1];

            // Blink transition: sharp dip in contrast variance
            if (currentVar < avgVar * 0.75 && !isBlinkDip) {
                isBlinkDip = true;
                blinkStartTime = Date.now();
            } else if (isBlinkDip && currentVar >= avgVar * 0.85) {
                const duration = Date.now() - blinkStartTime;
                if (duration > 80 && duration < 600) {
                    blinkCount++;
                    livenessVerified = true;
                    updateLivenessBadge(true);
                }
                isBlinkDip = false;
            }
        }
    } catch (e) {
        // Fallback for canvas boundaries
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
        setTimeout(detectLoop, 200);
        return;
    }

    isDetecting = true;

    canvas.width = video.clientWidth;
    canvas.height = video.clientHeight;

    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = video.videoWidth;
    tempCanvas.height = video.videoHeight;
    const tctx = tempCanvas.getContext("2d");
    tctx.drawImage(video, 0, 0);

    const image = tempCanvas.toDataURL("image/jpeg", 0.85);

    try {
        const res = await fetch("/recognize_with_box", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                image: image,
                client_id: clientId
            })
        });

        const data = await res.json();
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (data.faces && data.faces.length > 0) {
            stableFrames++;
            lastFaceSeen = Date.now();

            let newPrev = [];

            data.faces.forEach((face, i) => {
                let box = smoothBox(prevBoxes[i], face.box);
                newPrev.push(box);

                // Run eye liveness check on detected face
                analyzeEyeLiveness(tctx, face.box);

                const [x, y, w, h] = box;
                const scaleX = video.clientWidth / video.videoWidth;
                const scaleY = video.clientHeight / video.videoHeight;

                const drawX = Math.round(x * scaleX);
                const drawY = Math.round(y * scaleY);
                const drawW = Math.round(w * scaleX);
                const drawH = Math.round(h * scaleY);

                const isMarked = markedStudents.has(face.roll);

                // Styling
                ctx.strokeStyle = isMarked ? "#eab308" : (livenessVerified ? "#16a34a" : "#3b82f6");
                ctx.lineWidth = 3;
                ctx.strokeRect(drawX, drawY, drawW, drawH);

                // Label badge
                ctx.fillStyle = isMarked ? "#eab308" : (livenessVerified ? "#16a34a" : "#3b82f6");
                ctx.fillRect(drawX, Math.max(0, drawY - 26), Math.max(140, drawW), 26);

                ctx.fillStyle = "#ffffff";
                ctx.font = "bold 13px sans-serif";
                let label = isMarked ? `✓ ${face.roll} (Marked)` : `${face.roll} (${Math.round(face.confidence * 100)}%)`;
                if (!isMarked && !livenessVerified) {
                    label += " [Blink to verify]";
                }
                ctx.fillText(label, drawX + 6, Math.max(18, drawY - 8));

                // Mark attendance only when confidence >= 0.70 AND liveness is confirmed
                if (!isMarked && face.confidence >= 0.70 && livenessVerified) {
                    markedStudents.add(face.roll);

                    fetch("/mark_attendance", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            roll: face.roll,
                            method: "Face"
                        })
                    })
                    .then(r => r.json())
                    .then(markData => {
                        if (markData.status === "marked") {
                            resultEl.innerHTML = `✅ <b>Attendance Marked</b><br>🎓 Student: <b>${face.roll}</b> (Live Verified)`;
                        } else {
                            resultEl.innerHTML = `⚠️ <b>Already Marked Today</b><br>🎓 Student: <b>${face.roll}</b>`;
                        }
                    })
                    .catch(err => {
                        console.error("[MARK ERROR]:", err);
                    });
                }
            });

            prevBoxes = newPrev;

        } else {
            // Debounced empty state
            if (Date.now() - lastFaceSeen > 1200) {
                prevBoxes = [];
                stableFrames = 0;
                livenessVerified = false;
                updateLivenessBadge(false);
                resultEl.innerHTML = "🔍 Scanning for registered students...";
            }
        }

    } catch (err) {
        console.error("[RECOGNIZE LOOP ERROR]:", err);
    } finally {
        isDetecting = false;
        setTimeout(detectLoop, 250);
    }
}

detectLoop();