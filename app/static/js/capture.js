const video = document.getElementById("video");
const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");

const rollDisplay = document.getElementById("rollDisplay");
const statusEl = document.getElementById("status");
const startBtn = document.getElementById("startBtn");

let roll = localStorage.getItem("roll");
let collectedEmbeddings = [];
let isCapturing = false;
let cameraReady = false;
// True when all samples were captured but saving them failed: a retry only re-sends them
let savePending = false;

/** Show a coloured status line; text is inserted as text, never as HTML. */
function setStatus(text, color) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.style.color = color || "var(--slate-300)";
}

const REQUIRED_SAMPLES = 5;
const INSTRUCTIONS = [
    "Sample 1/5: Look directly forward into the camera reticle.",
    "Sample 2/5: Tilt your head slightly upward.",
    "Sample 3/5: Turn head slightly to your left (15 degrees).",
    "Sample 4/5: Turn head slightly to your right (15 degrees).",
    "Sample 5/5: Neutral relaxed expression or slight smile."
];

// 1. Check if roll number exists
if (!roll) {
    setStatus("No active enrollment roll found. Redirecting to student form...", "#f87171");
    if (startBtn) startBtn.disabled = true;
    setTimeout(() => {
        window.location.href = "/register_page";
    }, 1800);
} else {
    if (rollDisplay) rollDisplay.innerText = "Roll ID: " + roll;
    setStatus("Camera initialized. Click 'Begin 5-Angle Face Capture' when ready.");
}

// 2. Start webcam
navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }
})
.then(stream => {
    video.srcObject = stream;
    video.onloadedmetadata = () => {
        cameraReady = true;
    };
})
.catch(err => {
    console.error("[WEBCAM ERROR]:", err);
    setStatus("Camera hardware blocked or unavailable. Please check system permissions.", "#f87171");
    // Without a camera every "sample" would be a blank frame, so block the capture flow
    if (startBtn) startBtn.disabled = true;
});

// 3. Start Capture Flow
if (startBtn) {
    startBtn.addEventListener("click", async () => {
        if (isCapturing || !roll) return;
        if (!cameraReady) {
            setStatus("Camera is still starting. Please wait a moment and try again.", "#fde68a");
            return;
        }
        isCapturing = true;
        startBtn.disabled = true;

        if (savePending) {
            startBtn.innerText = "Saving Face Profile...";
            await saveFaceProfile();
            return;
        }

        startBtn.innerText = "Capturing Face Embeddings...";
        collectedEmbeddings = [];
        resetSampleBadges();

        await runEnrollmentLoop();
    });
}

function finishWithRetry(label) {
    startBtn.disabled = false;
    startBtn.innerText = label;
    isCapturing = false;
}

async function captureSingleFrame() {
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = video.videoWidth || 640;
    tempCanvas.height = video.videoHeight || 480;
    const tctx = tempCanvas.getContext("2d");
    tctx.drawImage(video, 0, 0, tempCanvas.width, tempCanvas.height);
    return tempCanvas.toDataURL("image/jpeg", 0.9);
}

// The sample tiles are styled inline; remember the initial look so a retry can restore it
const initialBadgeStyles = new Map();
document.querySelectorAll("[id^=sampleStep], [id^=sampleStatus]").forEach(el => {
    initialBadgeStyles.set(el, el.style.cssText);
});

function resetSampleBadges() {
    initialBadgeStyles.forEach((cssText, el) => {
        el.style.cssText = cssText;
        if (el.id.startsWith("sampleStatus")) el.innerText = "Pending";
    });
}

function updateSampleStepBadge(index, isSuccess) {
    const stepEl = document.getElementById(`sampleStep${index + 1}`);
    const statusEl = document.getElementById(`sampleStatus${index + 1}`);
    if (stepEl && statusEl) {
        if (isSuccess) {
            stepEl.style.background = "rgba(16, 185, 129, 0.2)";
            stepEl.style.borderColor = "rgba(16, 185, 129, 0.5)";
            stepEl.style.color = "#34d399";
            statusEl.innerText = "Captured \u2713";
            statusEl.style.color = "#34d399";
        } else {
            stepEl.style.background = "rgba(244, 63, 94, 0.2)";
            stepEl.style.borderColor = "rgba(244, 63, 94, 0.5)";
            statusEl.innerText = "Retrying...";
            statusEl.style.color = "#f87171";
        }
    }
}

function drawFaceBox(box) {
    // Draw in on-screen pixels; the box is in camera-frame pixels (see captureSingleFrame)
    canvas.width = video.clientWidth;
    canvas.height = video.clientHeight;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!box) return;

    const [x, y, w, h] = frameBoxToElement(box, video.videoWidth, video.videoHeight, video);
    ctx.strokeStyle = "#10b981"; // Emerald green
    ctx.lineWidth = 3;
    ctx.strokeRect(x, y, w, h);

    ctx.fillStyle = "#10b981";
    ctx.font = "bold 14px sans-serif";
    ctx.fillText(`Vector Captured: ${collectedEmbeddings.length}/${REQUIRED_SAMPLES}`, x, Math.max(20, y - 8));
}

async function runEnrollmentLoop() {
    let sampleIndex = 0;
    let failedAttempts = 0;

    while (sampleIndex < REQUIRED_SAMPLES && failedAttempts < 15) {
        setStatus(INSTRUCTIONS[sampleIndex] || "Capturing vector sample...");

        // Small delay between shots
        await new Promise(r => setTimeout(r, 650));

        const imageBase64 = await captureSingleFrame();

        try {
            const res = await fetch("/capture_face", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: imageBase64 })
            });

            if (res.status === 401) {
                window.location.href = "/";
                return;
            }

            const data = await res.json();

            if (data.status === "success" && data.embedding) {
                collectedEmbeddings.push(data.embedding);
                drawFaceBox(data.box);
                updateSampleStepBadge(sampleIndex, true);
                sampleIndex++;
                failedAttempts = 0;
            } else {
                failedAttempts++;
                updateSampleStepBadge(sampleIndex, false);
                setStatus(`Re-aligning: ${data.error || "No face detected in reticle"}...`, "#fde68a");
            }

        } catch (err) {
            console.error("[FRAME CAPTURE ERROR]:", err);
            failedAttempts++;
        }
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (collectedEmbeddings.length < REQUIRED_SAMPLES) {
        setStatus("Failed to collect sufficient facial angles. Please retry enrollment.", "#f87171");
        finishWithRetry("Retry 5-Angle Face Capture");
        return;
    }

    await saveFaceProfile();
}

/** Send the collected samples; on failure keep them so "Retry Save" does not re-capture. */
async function saveFaceProfile() {
    setStatus("Synthesizing 512-D centroid vector profile...", "#60a5fa");

    try {
        const saveRes = await fetch("/save_face_data", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                roll: roll,
                embeddings: collectedEmbeddings
            })
        });

        if (saveRes.status === 401) {
            window.location.href = "/";
            return;
        }

        const saveData = await saveRes.json();

        if (saveData.status === "saved") {
            savePending = false;
            setStatus(`Enrollment Complete! Biometric profile synthesized for ${roll}. Redirecting...`, "#34d399");
            localStorage.removeItem("roll");
            setTimeout(() => {
                window.location.href = "/dashboard";
            }, 1800);
        } else {
            savePending = true;
            setStatus(`Profile storage error: ${saveData.error || "Unknown"}`, "#f87171");
            finishWithRetry("Retry Save");
        }

    } catch (err) {
        console.error("[SAVE ERROR]:", err);
        savePending = true;
        setStatus("Network error persisting biometric vectors.", "#f87171");
        finishWithRetry("Retry Save");
    }
}
