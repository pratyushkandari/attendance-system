async function loadDashboard() {
    try {
        const res = await fetch("/dashboard_data");
        if (res.status === 401) {
            window.location.href = "/";
            return;
        }

        const data = await res.json();
        const today = new Date();

        const todayEl = document.getElementById("todayDate");
        if (todayEl) {
            todayEl.innerText = today.toLocaleDateString("en-GB", { 
                weekday: 'long', 
                year: 'numeric', 
                month: 'long', 
                day: 'numeric' 
            });
        }

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
    }
}

async function confirmClearModal() {
    if (!confirm("Are you sure you want to permanently clear all attendance records? This action cannot be undone.")) {
        return;
    }

    try {
        const res = await fetch("/clear_records", { method: "POST" });
        const data = await res.json();
        alert(data.message || "Attendance records successfully cleared.");
        loadDashboard();
    } catch (err) {
        console.error("[CLEAR ERROR]:", err);
        alert("Failed to clear attendance records.");
    }
}

loadDashboard();