"""Render a real local variable font in an installed Chromium browser, preserving evidence."""

import argparse
import hashlib
import html
import json
import platform
import subprocess
import sys
import uuid
from html.parser import HTMLParser
from pathlib import Path

from fontTools.ttLib import TTFont


class Body(HTMLParser):
    attributes = {}

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.attributes = dict(attrs)


def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lines = [
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "abcdefghijklmnopqrstuvwxyz",
        "0123456789 € & @ # %",
        "KAYAK MINIMUM WAVY",
        "minimum kayak",
        "Créez sans limites.",
        "Votre infrastructure.",
        "Vos règles.",
    ]
    with TTFont(args.font) as font:
        missing = sorted({ord(c) for text in lines for c in text if ord(c) not in font.getBestCmap()})
        if missing:
            raise ValueError(f"Proof text contains unavailable codepoints: {missing}")
        font.flavor = "woff2"
        font.save(output / "proof.woff2")
    cards = []
    for label, weight, width in [
        ("Semibold", 600, 100),
        ("Bold", 800, 100),
        ("Semibold Extended", 600, 125),
        ("Extended", 800, 125),
    ]:
        content = "".join(
            f'<p class="{"alphabet" if i < 3 else "words"}">{html.escape(text)}</p>'
            for i, text in enumerate(lines)
        )
        cards.append(
            f'<section><header>{label} · {weight} / {width}</header><div class="sample" style="font-variation-settings: &quot;wght&quot; {weight}, &quot;wdth&quot; {width}"><h2>UniSlaw</h2>{content}</div></section>'
        )
    source = (
        """<!doctype html><html lang="fr"><meta charset="utf-8"><title>UniSlaw — épreuves navigateur</title><style>
@font-face{font-family:Proof;src:url(proof.woff2) format('woff2');font-weight:600 800;font-stretch:100% 125%;font-display:block}
*{box-sizing:border-box}body{margin:0;padding:38px;background:#f4f5f6;color:#080a0c;font-family:Arial,sans-serif}h1{font-size:23px;margin:0 0 12px}aside{font-size:14px;color:#4b5560;margin-bottom:26px}main{display:grid;grid-template-columns:1fr 1fr;gap:22px}section{background:white;border:1px solid #d6dbe0;padding:28px;overflow:visible}header{font-size:15px;color:#52606c;border-bottom:1px solid #ddd;padding-bottom:18px}.sample{font-family:Proof;font-synthesis:none;font-kerning:normal}h2{font-size:82px;line-height:1.15;margin:30px 0 24px}p{margin:14px 0;line-height:1.3}.alphabet{font-size:28px;letter-spacing:.005em}.words{font-size:46px}
</style><body><h1>UniSlaw · épreuves du fichier variable dans le navigateur</h1><aside>Quatre masters · glyphes et mots · export d’épreuve, sans attestation de livraison</aside><main>"""
        + "".join(cards)
        + """</main><script>
document.fonts.load('48px Proof').then(async faces=>{await document.fonts.ready;document.body.dataset.fontReady=String(faces.length>0);document.body.dataset.userAgent=navigator.userAgent;document.body.dataset.overflow=String([...document.querySelectorAll('.sample')].some(e=>e.scrollWidth>e.clientWidth+1))}).catch(e=>document.body.dataset.fontReady='false');
</script></body></html>"""
    )
    page = output / "specimen.html"
    page.write_text(source, encoding="utf-8")
    browser = args.browser.resolve()
    profile = output / ("browser-profile-" + uuid.uuid4().hex[:8])
    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--allow-file-access-from-files",
        "--hide-scrollbars",
        "--virtual-time-budget=3000",
        "--window-size=1600,1750",
        f"--user-data-dir={profile}",
        f"--screenshot={output / 'specimen.png'}",
        "--dump-dom",
        page.as_uri(),
    ]
    process = subprocess.run(
        command,
        capture_output=True,
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    dom = process.stdout.decode("utf-8", errors="replace")
    (output / "browser.log").write_bytes(process.stderr)
    (output / "rendered.html").write_text(dom, encoding="utf-8")
    body = Body()
    body.feed(dom)
    report = {
        "font_sha256": hashlib.sha256(args.font.read_bytes()).hexdigest(),
        "host": platform.platform(),
        "browser": str(browser),
        "exit_code": process.returncode,
        "font_loaded": body.attributes.get("data-font-ready") == "true",
        "user_agent": body.attributes.get("data-user-agent"),
        "horizontal_overflow": body.attributes.get("data-overflow"),
        "image": str(output / "specimen.png"),
        "artistic_approval": False,
    }
    report["checks_passed"] = (
        process.returncode == 0
        and report["font_loaded"]
        and report["horizontal_overflow"] == "false"
        and (output / "specimen.png").is_file()
    )
    (output / "browser-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["checks_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path)
    parser.add_argument("--output", type=Path, default=Path("test-output/browser-proof"))
    parser.add_argument(
        "--browser", type=Path, default=Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    )
    sys.exit(main(parser.parse_args()))
