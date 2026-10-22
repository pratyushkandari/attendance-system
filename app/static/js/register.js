// Submitting the form (button click or Enter in any field) runs the enrollment request
document.getElementById("enrollForm").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!document.getElementById("registerBtn").disabled) register();
});

const ALERT_ICONS = {
    rose: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>',
    amber: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
    emerald: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
};

/**
 * Render a status alert in the #msg area. The message is inserted as text so
 * server-provided values (error messages, roll IDs) can never inject markup.
 */
function showAlert(kind, text) {
    const msg = document.getElementById("msg");
    msg.innerHTML = `<div class="alert-box alert-${kind}" role="${kind === "rose" ? "alert" : "status"}">${ALERT_ICONS[kind]}<span></span></div>`;
    msg.querySelector("span").textContent = text;
}

async function register() {
    const registerBtn = document.getElementById("registerBtn");

    const first = document.getElementById("first").value.trim();
    const last = document.getElementById("last").value.trim();
    const department = document.getElementById("department").value.trim();
    const year = document.getElementById("year").value.trim();
    const email = document.getElementById("email").value.trim();

    if (!first || !last || !department || !year || !email) {
        showAlert("rose", "Please complete all required fields before proceeding.");
        return;
    }

    if (!email.includes("@") || !email.includes(".")) {
        showAlert("rose", "Please enter a valid institutional email address.");
        return;
    }

    showAlert("amber", "Creating student profile and allocating unique Roll ID...");
    registerBtn.disabled = true;
    const origText = registerBtn.innerHTML;
    registerBtn.innerText = "Allocating Identity...";

    const resetButton = () => {
        registerBtn.disabled = false;
        registerBtn.innerHTML = origText;
    };

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

        if (res.status === 401) {
            window.location.href = "/";
            return;
        }

        const result = await res.json();

        if (!res.ok) {
            showAlert("rose", result.error || "Enrollment rejected by server.");
            resetButton();
            return;
        }

        if (result.roll) {
            // The capture page reads the roll from localStorage to know whom to enroll
            localStorage.setItem("roll", result.roll);
            showAlert("emerald", `Student registered! Assigned Roll ID: ${result.roll}. Redirecting to biometric capture...`);

            setTimeout(() => {
                window.location.href = "/capture";
            }, 1100);
        } else {
            showAlert("rose", "Unexpected server response format.");
            resetButton();
        }

    } catch (err) {
        console.error("[REGISTER ERROR]:", err);
        showAlert("rose", "Network error communicating with server.");
        resetButton();
    }
}
