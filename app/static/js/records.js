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
                table.innerHTML = `
                    <tr>
                        <td colspan="3" style="text-align:center; padding:3rem 1rem; color:var(--slate-400);">
                            <div style="font-size:1.1rem; font-weight:700; color:var(--slate-700); margin-bottom:0.35rem;">No Verification Records Found</div>
                            <div style="font-size:0.8rem;">Attendance events marked via Biometric Face or Dynamic QR will appear here.</div>
                        </td>
                    </tr>`;
                return;
            }

            sortedDates.forEach(date => {
                const dateRow = document.createElement("tr");
                dateRow.className = "date-divider-row";
                dateRow.innerHTML = `
                    <td colspan="3">
                        <div style="display:flex; align-items:center; gap:0.5rem;">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                                <line x1="16" y1="2" x2="16" y2="6"></line>
                                <line x1="8" y1="2" x2="8" y2="6"></line>
                                <line x1="3" y1="10" x2="21" y2="10"></line>
                            </svg>
                            <span>${formatDate(date)}</span>
                            <span class="badge badge-slate" style="font-size:0.65rem; margin-left:auto;">${data[date].length} ${data[date].length === 1 ? 'Record' : 'Records'}</span>
                        </div>
                    </td>
                `;
                table.appendChild(dateRow);

                const headerRow = document.createElement("tr");
                headerRow.innerHTML = `
                    <th style="width:40%;">Student Roll ID</th>
                    <th style="width:30%;">Verification Channel</th>
                    <th style="width:30%;">Recorded Timestamp</th>
                `;
                table.appendChild(headerRow);

                const sortedRecords = data[date].sort((a, b) => {
                    return new Date(`${date} ${b.time}`) - new Date(`${date} ${a.time}`);
                });

                sortedRecords.forEach(r => {
                    const row = document.createElement("tr");
                    const methodBadge = r.method === "Face" 
                        ? `<span class="badge badge-blue"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path><circle cx="12" cy="12" r="3"></circle></svg> Face Biometrics</span>`
                        : `<span class="badge badge-green"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg> Dynamic QR</span>`;

                    row.innerHTML = `
                        <td><span style="font-family:var(--font-mono); font-weight:700; color:var(--slate-900);">${r.roll}</span></td>
                        <td>${methodBadge}</td>
                        <td><span style="font-family:var(--font-mono); font-size:0.8rem; color:var(--slate-600);">${r.time}</span></td>
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
    if (!confirm("Are you sure you want to permanently purge all attendance logs? This action is recorded in audit logs.")) {
        return;
    }

    try {
        const res = await fetch("/clear_records", { method: "POST" });
        const data = await res.json();
        alert(data.message || "All attendance records purged.");
        loadRecords();
    } catch (err) {
        console.error("[CLEAR RECORDS ERROR]:", err);
        alert("Failed to clear records.");
    }
}

function formatDate(dateStr) {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-GB", {
        weekday: "short",
        day: "2-digit",
        month: "long",
        year: "numeric"
    });
}

loadRecords();