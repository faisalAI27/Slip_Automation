"""Small, maintainable visual layer for the Streamlit interface."""

APP_CSS = r"""
<style>
:root {
    --ink: #164e63;
    --muted-ink: #526a73;
    --primary: #087f9b;
    --primary-dark: #08657a;
    --success: #087a55;
    --surface: #ffffff;
    --soft: #ecfeff;
    --border: #b8e7ec;
    --danger: #b42318;
}

html, body, [class*="st-"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 50% -10%, rgba(34, 211, 238, 0.13), transparent 31rem),
        #f8fcfd;
    color: var(--ink);
}

[data-testid="stHeader"], footer, #MainMenu {
    visibility: hidden;
}

.block-container {
    max-width: 720px;
    padding-top: 3.5rem;
    padding-bottom: 3rem;
}

.app-kicker {
    width: fit-content;
    margin: 0 auto 1.15rem;
    padding: .42rem .72rem;
    border-radius: 999px;
    background: #dff8fa;
    color: #09657a;
    font-size: .78rem;
    font-weight: 700;
    letter-spacing: .07em;
    text-transform: uppercase;
}

.app-title {
    color: #123f4d;
    font-size: clamp(2.15rem, 7vw, 3.45rem);
    font-weight: 750;
    letter-spacing: -.045em;
    line-height: 1.04;
    margin: 0;
    text-align: center;
}

.app-subtitle {
    color: var(--muted-ink);
    font-size: clamp(1rem, 3.6vw, 1.16rem);
    line-height: 1.6;
    margin: 1rem auto 2.25rem;
    max-width: 34rem;
    text-align: center;
}

.section-label {
    color: #244f5c;
    font-size: 1rem;
    font-weight: 700;
    margin: .25rem 0 .65rem;
}

[data-testid="stFileUploader"] {
    background: rgba(255,255,255,.86);
    border: 1px solid var(--border);
    border-radius: 18px;
    padding: .4rem .8rem .8rem;
}

[data-testid="stFileUploaderDropzone"] {
    min-height: 8rem;
    background: #f5fdfe;
    border-color: #8fd5de;
    border-radius: 14px;
}

[data-testid="stCameraInput"] > div {
    border-radius: 16px;
}

.stButton > button, .stDownloadButton > button {
    cursor: pointer;
    min-height: 3.25rem;
    border-radius: 12px;
    font-size: 1rem;
    font-weight: 700;
    transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease;
    touch-action: manipulation;
}

.stButton > button:hover, .stDownloadButton > button:hover {
    transform: translateY(-1px);
}

.stButton > button:focus-visible, .stDownloadButton > button:focus-visible {
    outline: 3px solid rgba(8, 145, 178, .34);
    outline-offset: 2px;
}

[data-testid="stImage"] {
    margin: .75rem 0 .7rem;
    padding: .8rem;
    border: 1px solid var(--border);
    border-radius: 18px;
    background: var(--surface);
    box-shadow: 0 12px 36px rgba(22, 78, 99, .08);
}

[data-testid="stImage"] img {
    border-radius: 12px;
    max-height: 34rem;
    object-fit: contain;
}

.privacy-note {
    color: var(--muted-ink);
    font-size: .83rem;
    line-height: 1.5;
    margin: .65rem 0 1rem;
    text-align: center;
}

.progress-shell, .result-shell {
    background: rgba(255,255,255,.94);
    border: 1px solid var(--border);
    border-radius: 22px;
    box-shadow: 0 18px 48px rgba(22, 78, 99, .09);
    padding: clamp(1.35rem, 5vw, 2rem);
}

.progress-title, .result-title {
    color: #123f4d;
    font-size: clamp(1.45rem, 5vw, 1.9rem);
    font-weight: 750;
    letter-spacing: -.02em;
    margin: 0 0 .45rem;
}

.progress-intro, .result-copy {
    color: var(--muted-ink);
    line-height: 1.55;
    margin: 0 0 1.35rem;
}

.progress-list { display: grid; gap: .55rem; }
.progress-row {
    align-items: center;
    border-radius: 12px;
    color: #718187;
    display: grid;
    font-weight: 600;
    gap: .75rem;
    grid-template-columns: 1.7rem 1fr;
    min-height: 3rem;
    padding: .45rem .6rem;
}
.progress-row.current { background: var(--soft); color: #0b6579; }
.progress-row.done { color: var(--success); }
.progress-row.error { background: #fff1f0; color: var(--danger); }
.progress-marker {
    align-items: center;
    border: 2px solid #bdd0d5;
    border-radius: 50%;
    display: flex;
    font-size: .78rem;
    height: 1.45rem;
    justify-content: center;
    width: 1.45rem;
}
.done .progress-marker { background: var(--success); border-color: var(--success); color: white; }
.current .progress-marker { border-color: var(--primary); color: var(--primary); }
.error .progress-marker { border-color: var(--danger); color: var(--danger); }

.demo-badge {
    background: #fff7e6;
    border: 1px solid #f0d39a;
    border-radius: 10px;
    color: #76561c;
    font-size: .86rem;
    line-height: 1.45;
    margin: .85rem 0 1.25rem;
    padding: .75rem .85rem;
}

.result-shell { border-top: 5px solid var(--success); }
.result-eyebrow {
    color: var(--success);
    font-size: .78rem;
    font-weight: 800;
    letter-spacing: .08em;
    margin-bottom: .5rem;
    text-transform: uppercase;
}

.footer-note {
    color: #73868c;
    font-size: .78rem;
    margin-top: 2.2rem;
    text-align: center;
}

@media (max-width: 640px) {
    .block-container { padding: 2rem 1rem 2.5rem; }
    .app-subtitle { margin-bottom: 1.65rem; }
    .progress-shell, .result-shell { border-radius: 18px; padding: 1.2rem; }
}

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        scroll-behavior: auto !important;
        transition-duration: .01ms !important;
    }
}
</style>
"""
