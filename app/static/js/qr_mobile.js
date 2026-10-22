window.onload = () => {
    const rollInput = document.getElementById("roll");
    const msg = document.getElementById("msg");

    // Extract token from URL query params
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get("token");

    if (token) {
        sessionStorage.setItem("qr_token", token);
        // Drop the token from the address bar so it is not kept in history or shared
        window.history.replaceState(null, "", window.location.pathname);
    } else if (!sessionStorage.getItem("qr_token")) {
        msg.innerHTML = "⚠️ <b>Invalid Session:</b> Missing security token.<br>Please scan the live classroom QR code.";
    }

    if (rollInput) {
        rollInput.focus();
        rollInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                verify();
            }
        });
    }
};

let isVerifying = false;

async function verify() {
    if (isVerifying) return;

    const rollInput = document.getElementById("roll");
    const msg = document.getElementById("msg");
    const btn = document.getElementById("verifyBtn");
    // Rolls are stored upper-case (e.g. 2026CSE001); the input only *displays* upper-case
    const roll = rollInput.value.trim().toUpperCase();
    const token = sessionStorage.getItem("qr_token");

    if (!roll) {
        msg.innerText = "⚠️ Please enter your roll number.";
        return;
    }

    if (!token) {
        msg.innerText = "❌ Security token missing. Please rescan the QR code.";
        return;
    }

    isVerifying = true;
    if (btn) btn.disabled = true;
    msg.innerText = "Verifying security token and student record...";

    try {
        // Step 1: Validate dynamic token
        const tokenRes = await fetch("/verify_qr_token", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token: token })
        });
        const tokenData = await tokenRes.json();

        if (!tokenData.valid) {
            msg.innerText = `❌ ${tokenData.error || "QR token expired. Please rescan."}`;
            return;
        }

        // Step 2: Verify student exists (the live QR token authorises the lookup)
        const res = await fetch("/verify_student", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ roll: roll, token: token })
        });
        const data = await res.json();

        if (data.success) {
            sessionStorage.setItem("qr_roll", data.roll || roll);
            window.location.href = "/qr_verify";
        } else if (res.status === 401) {
            msg.innerText = `❌ ${data.message || "QR code expired. Please rescan."}`;
        } else {
            msg.innerText = "❌ Student roll number not found.";
        }

    } catch (err) {
        console.error("[QR VERIFY ERROR]:", err);
        msg.innerText = "⚠️ Network error. Please try again.";
    } finally {
        isVerifying = false;
        if (btn) btn.disabled = false;
    }
}
