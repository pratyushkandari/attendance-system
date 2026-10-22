window.onload = async () => {
    const roll = sessionStorage.getItem("qr_roll");
    const token = sessionStorage.getItem("qr_token");

    if (!roll || !token) {
        alert("Session expired or missing security token. Please scan the QR code again.");
        window.location.href = "/qr_mobile";
        return;
    }

    try {
        // The live QR token authorises this lookup (see /get_student)
        const res = await fetch("/get_student/" + encodeURIComponent(roll), {
            headers: { "X-QR-Token": token }
        });
        const data = await res.json();

        if (res.status === 401) {
            alert(data.error || "QR code expired. Please rescan the classroom QR code.");
            window.location.href = "/qr_mobile";
            return;
        }

        if (data.error) {
            alert("Student record not found.");
            window.location.href = "/qr_mobile";
            return;
        }

        document.getElementById("name").innerText = `${data.first_name} ${data.last_name}`;
        document.getElementById("dept").innerText = `${data.department} • Year ${data.year}`;

    } catch (err) {
        console.error("[GET STUDENT ERROR]:", err);
        alert("Network error fetching student info.");
        window.location.href = "/qr_mobile";
    }
};

async function confirmAttendance() {
    const roll = sessionStorage.getItem("qr_roll");
    const token = sessionStorage.getItem("qr_token");
    const btn = document.getElementById("confirmBtn");

    if (!roll || !token) {
        alert("Session expired. Please scan QR again.");
        window.location.href = "/qr_mobile";
        return;
    }

    if (btn) btn.disabled = true;

    try {
        const res = await fetch("/mark_attendance", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                roll: roll,
                method: "QR",
                qr_token: token
            })
        });

        const data = await res.json();

        if (data.status === "marked" || data.status === "already marked today") {
            sessionStorage.removeItem("qr_roll");
            sessionStorage.removeItem("qr_token");
            // Lets the result page say whether this was a new or an existing record
            sessionStorage.setItem("qr_result_status", data.status);
            window.location.href = "/qr_result";
        } else {
            alert(data.message || "Failed to mark attendance.");
            if (btn) btn.disabled = false;
        }

    } catch (err) {
        console.error("[CONFIRM ATTENDANCE ERROR]:", err);
        alert("Failed to connect to server. Please try again.");
        if (btn) btn.disabled = false;
    }
}
