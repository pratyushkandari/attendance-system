async function loadDashboard() {
    try {
        const res = await fetch("/dashboard_data");
        if (res.status === 401) {
            window.location.href = "/";
            return;
        }

        const data = await res.json();
        const today = new Date();

        document.getElementById("todayDate").innerText =
            "📅 " + today.toLocaleDateString("en-GB", { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

        document.getElementById("students").innerText = data.total_students ?? 0;
        document.getElementById("present").innerText = data.present ?? 0;
        document.getElementById("absent").innerText = data.absent ?? 0;

    } catch (err) {
        console.error("[DASHBOARD LOAD ERROR]:", err);
    }
}

async function clearRecords() {
    if (!confirm("⚠️ Are you sure you want to permanently clear all attendance records?")) {
        return;
    }

    try {
        const res = await fetch("/clear_records", { method: "POST" });
        const data = await res.json();
        alert(data.message || "Records Cleared.");
        loadDashboard();
    } catch (err) {
        console.error("[CLEAR ERROR]:", err);
        alert("Failed to clear records.");
    }
}

loadDashboard();