// Helpers shared by the admin pages (loaded from base.html before page scripts).

/**
 * Map a box measured in camera-frame pixels onto the displayed <video> element.
 * The video uses `object-fit: cover` inside a 4:3 frame, so a frame with another
 * aspect ratio (16:9 webcams, portrait phones) is scaled to fill the element and
 * centred, with the overflow cropped. Boxes must go through the same transform or
 * they drift away from the faces.
 */
function frameBoxToElement(box, frameWidth, frameHeight, element) {
    const scale = Math.max(element.clientWidth / frameWidth, element.clientHeight / frameHeight);
    const offsetX = (element.clientWidth - frameWidth * scale) / 2;
    const offsetY = (element.clientHeight - frameHeight * scale) / 2;
    const [x, y, w, h] = box;
    return [x * scale + offsetX, y * scale + offsetY, w * scale, h * scale];
}

/** Ask for confirmation, then delete every attendance record. */
async function purgeAttendanceRecords(button, onCleared) {
    if (!confirm("Are you sure you want to permanently purge all attendance records? This action cannot be undone.")) {
        return;
    }

    if (button) button.disabled = true;
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
        alert(data.message || "All attendance records cleared.");
        if (onCleared) onCleared();
    } catch (err) {
        console.error("[CLEAR RECORDS ERROR]:", err);
        alert("Failed to clear attendance records.");
    } finally {
        if (button) button.disabled = false;
    }
}
