async function loadDashboard() {
    const todayEl = document.getElementById("todayDate");
    if (todayEl) {
        todayEl.innerText = new Date().toLocaleDateString("en-GB", {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    }

    try {
        const res = await fetch("/dashboard_data");
        if (res.status === 401) {
            window.location.href = "/";
            return;
        }
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();

        const total = data.total_students ?? 0;
        const present = data.present ?? 0;
        const absent = data.absent ?? 0;

        const studentsEl = document.getElementById("students");
        if (studentsEl) studentsEl.innerText = total;

        const presentEl = document.getElementById("present");
        if (presentEl) presentEl.innerText = present;

        const absentEl = document.getElementById("absent");
        if (absentEl) absentEl.innerText = absent;

        const rateEl = document.getElementById("attendanceRate");
        if (rateEl) {
            const percentage = total > 0 ? Math.round((present / total) * 100) : 0;
            rateEl.innerText = `${percentage}% Verified`;
        }

    } catch (err) {
        console.error("[DASHBOARD LOAD ERROR]:", err);
        // Leave the "--" placeholders and say why, instead of showing stale or zero counts
        const rateEl = document.getElementById("attendanceRate");
        if (rateEl) rateEl.innerText = "Stats unavailable";
    }
}

async function confirmClearModal() {
    if (!confirm("Are you sure you want to permanently clear all attendance records? This action cannot be undone.")) {
        return;
    }

    try {
        const res = await fetch("/clear_records", { method: "POST" });
        if (res.status === 401) {
            window.location.href = "/";
            return;
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            alert(data.error || "Failed to clear attendance records.");
            return;
        }
        alert(data.message || "Attendance records successfully cleared.");
        loadDashboard();
    } catch (err) {
        console.error("[CLEAR ERROR]:", err);
        alert("Failed to clear attendance records.");
    }
}

loadDashboard();
