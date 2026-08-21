async function loadRecords() {
    try {
        const res = await fetch("/records");
        if (res.status === 401) {
            window.location.href = "/";
            return;
        }

        const data = await res.json();
        const table = document.getElementById("table");

        if (!table) return;
        table.innerHTML = "";

        if (typeof data === "object" && !Array.isArray(data)) {
            const sortedDates = Object.keys(data).sort((a, b) => new Date(b) - new Date(a));

            if (sortedDates.length === 0) {
                table.innerHTML = `<tr><td colspan="3" style="color:#64748b; padding:20px;">No attendance records found.</td></tr>`;
                return;
            }

            sortedDates.forEach(date => {
                const dateRow = document.createElement("tr");
                dateRow.innerHTML = `
                    <td colspan="3" style="padding-top:18px; font-weight:bold; color:#1e3a8a; background:#f1f5f9; text-align:left; padding-left:14px;">
                        📅 ${formatDate(date)}
                    </td>
                `;
                table.appendChild(dateRow);

                const headerRow = document.createElement("tr");
                headerRow.innerHTML = `
                    <th>Roll Number</th>
                    <th>Method</th>
                    <th>Time</th>
                `;
                table.appendChild(headerRow);

                const sortedRecords = data[date].sort((a, b) => {
                    return new Date(`${date} ${b.time}`) - new Date(`${date} ${a.time}`);
                });

                sortedRecords.forEach(r => {
                    const row = document.createElement("tr");
                    const methodBadge = r.method === "Face" 
                        ? `<span style="background:#dbeafe; color:#1e40af; padding:3px 8px; border-radius:6px; font-weight:600; font-size:12px;">👤 Face</span>`
                        : `<span style="background:#dcfce7; color:#166534; padding:3px 8px; border-radius:6px; font-weight:600; font-size:12px;">📱 QR</span>`;

                    row.innerHTML = `
                        <td><b>${r.roll}</b></td>
                        <td>${methodBadge}</td>
                        <td>${r.time}</td>
                    `;
                    table.appendChild(row);
                });
            });
        }

    } catch (err) {
        console.error("[LOAD RECORDS ERROR]:", err);
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
        loadRecords();
    } catch (err) {
        console.error("[CLEAR RECORDS ERROR]:", err);
        alert("Failed to clear records.");
    }
}

function formatDate(dateStr) {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "long",
        year: "numeric"
    });
}

loadRecords();