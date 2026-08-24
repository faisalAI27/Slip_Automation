"""Mobile-first visual layer for the Streamlit interface."""

APP_CSS = r"""
<style>
:root {
    --ink: #123f4d;
    --body-ink: #365963;
    --muted-ink: #526a73;
    --primary: #087f9b;
    --success: #087a55;
    --surface: #ffffff;
    --soft: #ecfeff;
    --border: #b8e7ec;
    --danger: #b42318;
}

html {
    font-size: 16px;
    overscroll-behavior-y: contain;
}

html, body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 50% -8rem, rgba(34, 211, 238, 0.14), transparent 28rem),
        #f8fcfd;
    color: var(--body-ink);
    overflow-x: hidden;
}

[data-testid="stHeader"], footer, #MainMenu {
    display: none;
}

.block-container {
    max-width: 680px;
    padding: max(1.25rem, env(safe-area-inset-top)) 1rem
        max(2.25rem, env(safe-area-inset-bottom));
}

h1 {
    color: var(--ink);
    font-size: clamp(2rem, 10.5vw, 3.35rem) !important;
    font-weight: 750 !important;
    letter-spacing: -.045em !important;
    line-height: 1.08 !important;
    margin: .15rem 0 .25rem !important;
}

h2, h3 {
    color: var(--ink);
    letter-spacing: -.02em;
    line-height: 1.25;
}

h2 {
    font-size: clamp(1.25rem, 5vw, 1.55rem) !important;
    margin-top: 1.5rem !important;
}

p, label, [data-testid="stCaptionContainer"] {
    line-height: 1.6;
}

[data-testid="stCaptionContainer"] {
    color: var(--muted-ink);
    font-size: .9rem;
}

[data-testid="stBadge"] {
    margin-bottom: .2rem;
}

[data-testid="stSegmentedControl"] {
    margin: .35rem 0 .65rem;
    width: 100%;
}

[data-testid="stSegmentedControl"] > div {
    width: 100%;
}

[data-testid="stSegmentedControl"] button {
    min-height: 3rem;
    touch-action: manipulation;
}

[data-testid="stFileUploader"] {
    background: rgba(255, 255, 255, .9);
    border: 1px solid var(--border);
    border-radius: 16px;
    margin-top: .5rem;
    padding: .35rem .7rem .7rem;
}

[data-testid="stFileUploaderDropzone"] {
    background: #f5fdfe;
    border-color: #78c9d4;
    border-radius: 12px;
    min-height: 7.25rem;
}

[data-testid="stCameraInput"] {
    margin-top: .5rem;
}

[data-testid="stCameraInput"] video,
[data-testid="stCameraInput"] img {
    border-radius: 14px;
    max-height: 58vh;
    object-fit: contain;
}

.stButton > button,
.stDownloadButton > button {
    cursor: pointer;
    font-size: 1rem;
    font-weight: 700;
    min-height: 3.25rem;
    border-radius: 12px;
    touch-action: manipulation;
    transition: background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    box-shadow: 0 7px 20px rgba(22, 78, 99, .12);
}

.stButton > button:focus-visible,
.stDownloadButton > button:focus-visible {
    outline: 3px solid rgba(8, 145, 178, .36);
    outline-offset: 2px;
}

[data-testid="stImage"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    box-shadow: 0 12px 34px rgba(22, 78, 99, .08);
    margin: .5rem 0 .25rem;
    padding: .55rem;
}

[data-testid="stImage"] img {
    border-radius: 11px;
    max-height: 56vh;
    object-fit: contain;
}

.progress-shell,
.result-shell {
    background: rgba(255, 255, 255, .96);
    border: 1px solid var(--border);
    border-radius: 18px;
    box-shadow: 0 16px 40px rgba(22, 78, 99, .09);
    padding: 1.2rem;
}

.progress-title,
.result-title {
    color: var(--ink);
    font-size: clamp(1.45rem, 6vw, 1.9rem);
    font-weight: 750;
    letter-spacing: -.025em;
    line-height: 1.2;
    margin: 0 0 .45rem;
}

.progress-intro,
.result-copy {
    color: var(--muted-ink);
    line-height: 1.6;
    margin: 0 0 1.2rem;
}

.progress-list {
    display: grid;
    gap: .5rem;
}

.progress-row {
    align-items: center;
    border-radius: 12px;
    color: #667b82;
    display: grid;
    font-size: .97rem;
    font-weight: 600;
    gap: .7rem;
    grid-template-columns: 1.65rem minmax(0, 1fr);
    min-height: 3rem;
    padding: .45rem .55rem;
}

.progress-row.current { background: var(--soft); color: #0b6579; }
.progress-row.done { color: var(--success); }
.progress-row.error { background: #fff1f0; color: var(--danger); }

.progress-marker {
    align-items: center;
    border: 2px solid #aebfc4;
    border-radius: 50%;
    display: flex;
    font-size: .78rem;
    height: 1.4rem;
    justify-content: center;
    width: 1.4rem;
}

.done .progress-marker {
    background: var(--success);
    border-color: var(--success);
    color: white;
}

.current .progress-marker { border-color: var(--primary); color: var(--primary); }
.error .progress-marker { border-color: var(--danger); color: var(--danger); }

.result-shell {
    border-top: 5px solid var(--success);
    margin-bottom: .75rem;
}

.result-eyebrow {
    color: var(--success);
    font-size: .78rem;
    font-weight: 800;
    letter-spacing: .08em;
    margin-bottom: .5rem;
    text-transform: uppercase;
}

.demo-badge {
    background: #fff7e6;
    border: 1px solid #e3c47e;
    border-radius: 10px;
    color: #684b16;
    font-size: .9rem;
    line-height: 1.55;
    margin-top: .8rem;
    padding: .75rem .85rem;
}

.footer-note {
    color: #657c83;
    font-size: .82rem;
    line-height: 1.5;
    margin: 2rem auto 0;
    max-width: 28rem;
    text-align: center;
}

@media (min-width: 641px) {
    .block-container {
        padding-left: 1.5rem;
        padding-right: 1.5rem;
        padding-top: 3rem;
    }

    .progress-shell,
    .result-shell {
        border-radius: 22px;
        padding: 2rem;
    }
}

@media (max-width: 380px) {
    .block-container {
        padding-left: .8rem;
        padding-right: .8rem;
    }

    [data-testid="stSegmentedControl"] button {
        font-size: .9rem;
        padding-left: .45rem;
        padding-right: .45rem;
    }
}

@media (orientation: landscape) and (max-height: 520px) {
    .block-container { padding-top: .8rem; }
    [data-testid="stCameraInput"] video { max-height: 66vh; }
}

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        scroll-behavior: auto !important;
        transition-duration: .01ms !important;
    }
}
</style>
"""
