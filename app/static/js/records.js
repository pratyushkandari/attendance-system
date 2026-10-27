const FACE_BADGE = `<span class="badge badge-blue"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path><circle cx="12" cy="12" r="3"></circle></svg> Face Biometrics</span>`;
const QR_BADGE = `<span class="badge badge-green"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg> Dynamic QR</span>`;

function renderMessageRow(table, title, detail, isError) {
    table.innerHTML = `
        <tr>
            <td colspan="3" style="text-align:center; padding:3rem 1rem; color:var(--slate-500);">
                <div class="msg-title" style="font-size:1.1rem; font-weight:700; color:${isError ? "var(--rose-600)" : "var(--slate-700)"}; margin-bottom:0.35rem;"></div>
                <div class="msg-detail" style="font-size:0.8rem;"></div>
            </td>
        </tr>`;
    table.querySelector(".msg-title").textContent = title;
    table.querySelector(".msg-detail").textContent = detail;
}

async function loadRecords() {
    const table = document.getElementById("table");
    if (!table) return;

    try {
        const res = await fetch("/records");
        if (res.status === 401) {
            window.location.href = "/";
            return;
        }
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        table.innerHTML = "";

        if (typeof data === "object" && !Array.isArray(data)) {
            // Keys are ISO dates (YYYY-MM-DD), so a string sort is a chronological sort
            const sortedDates = Object.keys(data).sort().reverse();

            if (sortedDates.length === 0) {
                renderMessageRow(
                    table,
                    "No Verification Records Found",
                    "Attendance events marked via Biometric Face or Dynamic QR will appear here.",
                    false
                );
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
                    <th scope="col" style="width:40%;">Student Roll ID</th>
                    <th scope="col" style="width:30%;">Verification Channel</th>
                    <th scope="col" style="width:30%;">Recorded Timestamp</th>
                `;
                table.appendChild(headerRow);

                // Times are zero-padded HH:MM:SS strings, so compare them as text
                // (parsing "YYYY-MM-DD HH:MM:SS" with Date is not portable across browsers).
                const sortedRecords = [...data[date]].sort((a, b) => b.time.localeCompare(a.time));

                sortedRecords.forEach(r => {
                    const row = document.createElement("tr");
                    row.innerHTML = `
                        <td><span class="roll-cell" style="font-family:var(--font-mono); font-weight:700; color:var(--slate-900);"></span></td>
                        <td>${r.method === "Face" ? FACE_BADGE : QR_BADGE}</td>
                        <td><span class="time-cell" style="font-family:var(--font-mono); font-size:0.8rem; color:var(--slate-600);"></span></td>
                    `;
                    // Server values are inserted as text, never as HTML
                    row.querySelector(".roll-cell").textContent = r.roll;
                    row.querySelector(".time-cell").textContent = r.time;
                    table.appendChild(row);
                });
            });
        }

    } catch (err) {
        console.error("[LOAD RECORDS ERROR]:", err);
        renderMessageRow(
            table,
            "Unable to Load Records",
            "The attendance ledger could not be retrieved. Please refresh the page or try again shortly.",
            true
        );
    }
}

function formatDate(dateStr) {
    // Parse YYYY-MM-DD as a *local* date; new Date("YYYY-MM-DD") is UTC midnight and
    // shows the previous day in timezones behind UTC.
    const [year, month, day] = dateStr.split("-").map(Number);
    const d = new Date(year, month - 1, day);
    return d.toLocaleDateString("en-GB", {
        weekday: "short",
        day: "2-digit",
        month: "long",
        year: "numeric"
    });
}

loadRecords();
