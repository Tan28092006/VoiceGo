document.addEventListener("DOMContentLoaded", () => {
    const voiceSearch = document.querySelector(".voice-search");
    if (!voiceSearch) return;

    voiceSearch.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            window.location.href = voiceSearch.getAttribute("href");
        }
    });
});
