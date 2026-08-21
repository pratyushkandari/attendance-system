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
        msg.innerHTML = "<span style='color:#dc2626;'>⚠️ Please fill in all required fields.</span>";
        return;
    }

    // Basic email format check
    if (!email.includes("@") || !email.includes(".")) {
        msg.innerHTML = "<span style='color:#dc2626;'>⚠️ Please enter a valid email address.</span>";
        return;
    }

    msg.innerHTML = "<span style='color:#2563eb;'>⏳ Creating student profile...</span>";
    registerBtn.disabled = true;

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
            msg.innerHTML = `<span style='color:#dc2626;'>❌ ${result.error || "Registration failed."}</span>`;
            registerBtn.disabled = false;
            return;
        }

        if (result.roll) {
            localStorage.setItem("roll", result.roll);
            msg.innerHTML = `<span style='color:#16a34a;'>✅ Registered! Assigned Roll: <b>${result.roll}</b><br>Redirecting to Face Enrollment...</span>`;

            setTimeout(() => {
                window.location.href = "/capture";
            }, 1200);
        } else {
            msg.innerHTML = "<span style='color:#dc2626;'>❌ Unexpected response from server.</span>";
            registerBtn.disabled = false;
        }

    } catch (err) {
        console.error("[REGISTER ERROR]:", err);
        msg.innerHTML = "<span style='color:#dc2626;'>❌ Network error. Please try again.</span>";
        registerBtn.disabled = false;
    }
}