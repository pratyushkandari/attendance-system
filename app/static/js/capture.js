const video = document.getElementById("video");
const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");

const rollDisplay = document.getElementById("rollDisplay");
const statusEl = document.getElementById("status");
const startBtn = document.getElementById("startBtn");

let roll = localStorage.getItem("roll");
let collectedEmbeddings = [];
let isCapturing = false;

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
    if (statusEl) statusEl.innerHTML = "<span style='color:#f87171;'>No active enrollment roll found. Redirecting to student form...</span>";
    if (startBtn) startBtn.disabled = true;
    setTimeout(() => {
        window.location.href = "/register_page";
    }, 1800);
} else {
    if (rollDisplay) rollDisplay.innerText = "Roll ID: " + roll;
    if (statusEl) statusEl.innerText = "Camera initialized. Click 'Begin 5-Angle Face Capture' when ready.";
}

// 2. Start webcam
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
    if (statusEl) statusEl.innerHTML = "<span style='color:#f87171;'>Camera hardware blocked or unavailable. Please check system permissions.</span>";
});

// 3. Start Capture Flow
if (startBtn) {
    startBtn.addEventListener("click", async () => {
        if (isCapturing) return;
        isCapturing = true;
        startBtn.disabled = true;
        startBtn.innerText = "Capturing Face Embeddings...";
        collectedEmbeddings = [];

        await runEnrollmentLoop();
    });
}

async function captureSingleFrame() {
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = video.videoWidth || 640;
    tempCanvas.height = video.videoHeight || 480;
    const tctx = tempCanvas.getContext("2d");
    tctx.drawImage(video, 0, 0, tempCanvas.width, tempCanvas.height);
    return tempCanvas.toDataURL("image/jpeg", 0.9);
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
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!box) return;

    const [x, y, w, h] = box;
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
        statusEl.innerText = INSTRUCTIONS[sampleIndex] || "Capturing vector sample...";

        // Small delay between shots
        await new Promise(r => setTimeout(r, 650));

        const imageBase64 = await captureSingleFrame();

        try {
            const res = await fetch("/capture_face", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: imageBase64 })
            });

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
                statusEl.innerText = `Re-aligning: ${data.error || "No face detected in reticle"}...`;
            }

        } catch (err) {
            console.error("[FRAME CAPTURE ERROR]:", err);
            failedAttempts++;
        }
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (collectedEmbeddings.length < REQUIRED_SAMPLES) {
        statusEl.innerHTML = "<span style='color:#f87171;'>Failed to collect sufficient facial angles. Please retry enrollment.</span>";
        startBtn.disabled = false;
        startBtn.innerText = "Retry 5-Angle Face Capture";
        isCapturing = false;
        return;
    }

    // Submit embeddings to backend
    statusEl.innerHTML = "<span style='color:#60a5fa;'>Synthesizing 512-D centroid vector profile...</span>";

    try {
        const saveRes = await fetch("/save_face_data", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                roll: roll,
                embeddings: collectedEmbeddings
            })
        });

        const saveData = await saveRes.json();

        if (saveData.status === "saved") {
            statusEl.innerHTML = `<span style='color:#34d399;'><b>Enrollment Complete!</b> Biometric profile synthesized for <b>${roll}</b>. Redirecting...</span>`;
            localStorage.removeItem("roll");
            setTimeout(() => {
                window.location.href = "/dashboard";
            }, 1800);
        } else {
            statusEl.innerHTML = `<span style='color:#f87171;'>Profile storage error: ${saveData.error || "Unknown"}</span>`;
            startBtn.disabled = false;
            startBtn.innerText = "Retry Save";
            isCapturing = false;
        }

    } catch (err) {
        console.error("[SAVE ERROR]:", err);
        statusEl.innerHTML = "<span style='color:#f87171;'>Network error persisting biometric vectors.</span>";
        startBtn.disabled = false;
        startBtn.innerText = "Retry Save";
        isCapturing = false;
    }
}