document.getElementById("registerBtn").addEventListener("click", register);

async function register() {
    const msg = document.getElementById("msg");
    const registerBtn = document.getElementById("registerBtn");

    const first = document.getElementById("first").value.trim();
    const last = document.getElementById("last").value.trim();
    const department = document.getElementById("department").value.trim();
    const year = document.getElementById("year").value.trim();
    const email = document.getElementById("email").value.trim();

    if (!first || !last || !department || !year || !email) {
        msg.innerHTML = `
            <div class="alert-box alert-rose">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                <span>Please complete all required fields before proceeding.</span>
            </div>`;
        return;
    }

    if (!email.includes("@") || !email.includes(".")) {
        msg.innerHTML = `
            <div class="alert-box alert-rose">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                <span>Please enter a valid institutional email address.</span>
            </div>`;
        return;
    }

    msg.innerHTML = `
        <div class="alert-box alert-amber">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
            <span>Creating student profile and allocating unique Roll ID...</span>
        </div>`;
    registerBtn.disabled = true;
    const origText = registerBtn.innerHTML;
    registerBtn.innerText = "Allocating Identity...";

    try {
        const res = await fetch("/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                first_name: first,
                last_name: last,
                department: department,
                year: year,
                email: email
            })
        });

        const result = await res.json();

        if (!res.ok) {
            msg.innerHTML = `
                <div class="alert-box alert-rose">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    <span>${result.error || "Enrollment rejected by server."}</span>
                </div>`;
            registerBtn.disabled = false;
            registerBtn.innerHTML = origText;
            return;
        }

        if (result.roll) {
            localStorage.setItem("roll", result.roll);
            msg.innerHTML = `
                <div class="alert-box alert-emerald">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                    <span>Student registered! Assigned Roll ID: <b>${result.roll}</b>. Redirecting to biometric capture...</span>
                </div>`;

            setTimeout(() => {
                window.location.href = "/capture";
            }, 1100);
        } else {
            msg.innerHTML = `
                <div class="alert-box alert-rose">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    <span>Unexpected server response format.</span>
                </div>`;
            registerBtn.disabled = false;
            registerBtn.innerHTML = origText;
        }

    } catch (err) {
        console.error("[REGISTER ERROR]:", err);
        msg.innerHTML = `
            <div class="alert-box alert-rose">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                <span>Network error communicating with server.</span>
            </div>`;
        registerBtn.disabled = false;
        registerBtn.innerHTML = origText;
    }
}