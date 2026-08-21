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
    "Sample 1/5: Look straight at the camera.",
    "Sample 2/5: Tilt head slightly up.",
    "Sample 3/5: Look slightly to your left.",
    "Sample 4/5: Look slightly to your right.",
    "Sample 5/5: Neutral expression or slight smile."
];

// 1. Check if roll number exists
if (!roll) {
    statusEl.innerHTML = "⚠️ No student roll found. Please register student first.";
    startBtn.disabled = true;
    setTimeout(() => {
        window.location.href = "/register_page";
    }, 2000);
} else {
    rollDisplay.innerText = "🎓 Enrolling: " + roll;
    statusEl.innerText = "Camera ready. Click 'Start Capture' to begin face enrollment.";
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
    statusEl.innerText = "❌ Unable to access camera. Please allow camera permissions.";
});

// 3. Start Capture Flow
startBtn.addEventListener("click", async () => {
    if (isCapturing) return;
    isCapturing = true;
    startBtn.disabled = true;
    collectedEmbeddings = [];

    await runEnrollmentLoop();
});

async function captureSingleFrame() {
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = video.videoWidth || 640;
    tempCanvas.height = video.videoHeight || 480;
    const tctx = tempCanvas.getContext("2d");
    tctx.drawImage(video, 0, 0, tempCanvas.width, tempCanvas.height);
    return tempCanvas.toDataURL("image/jpeg", 0.9);
}

function drawFaceBox(box) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!box) return;

    const [x, y, w, h] = box;
    ctx.strokeStyle = "#22c55e"; // Green box
    ctx.lineWidth = 3;
    ctx.strokeRect(x, y, w, h);

    ctx.fillStyle = "#22c55e";
    ctx.font = "bold 16px sans-serif";
    ctx.fillText(`Sample ${collectedEmbeddings.length + 1}/${REQUIRED_SAMPLES}`, x, Math.max(20, y - 8));
}

async function runEnrollmentLoop() {
    let sampleIndex = 0;
    let failedAttempts = 0;

    while (sampleIndex < REQUIRED_SAMPLES && failedAttempts < 15) {
        statusEl.innerText = INSTRUCTIONS[sampleIndex] || "Capturing face sample...";

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
                sampleIndex++;
                failedAttempts = 0;
            } else {
                failedAttempts++;
                statusEl.innerText = `⚠️ ${data.error || "No face detected"}. Re-centering...`;
            }

        } catch (err) {
            console.error("[FRAME CAPTURE ERROR]:", err);
            failedAttempts++;
        }
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (collectedEmbeddings.length < REQUIRED_SAMPLES) {
        statusEl.innerHTML = "❌ Failed to capture sufficient face angles. Please try again.";
        startBtn.disabled = false;
        isCapturing = false;
        return;
    }

    // Submit embeddings to backend
    statusEl.innerHTML = "💾 Generating biometric centroid profile...";

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
            statusEl.innerHTML = `✅ <b>Success!</b> Face profile created for <b>${roll}</b>.<br>Redirecting to Dashboard...`;
            localStorage.removeItem("roll");
            setTimeout(() => {
                window.location.href = "/dashboard";
            }, 2000);
        } else {
            statusEl.innerHTML = `❌ Error saving face: ${saveData.error || "Unknown error"}`;
            startBtn.disabled = false;
            isCapturing = false;
        }

    } catch (err) {
        console.error("[SAVE ERROR]:", err);
        statusEl.innerHTML = "❌ Network error while saving face profile.";
        startBtn.disabled = false;
        isCapturing = false;
    }
}