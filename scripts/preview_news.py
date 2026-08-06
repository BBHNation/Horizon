"""Serve the latest generated news digest with the GitHub Pages theme assets."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import markdown


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "docs"
NEWS_DIR = PROJECT_ROOT / "data" / "news"


def latest_report() -> Path:
    reports = sorted(NEWS_DIR.glob("news-digest-*.md"))
    if not reports:
        raise FileNotFoundError("No generated report found under data/news")
    return reports[-1]


def render_page(report_path: Path) -> bytes:
    body = markdown.markdown(
        report_path.read_text(encoding="utf-8"),
        extensions=["extra", "sane_lists"],
    )
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#4338a3">
  <title>Horizon 综合新闻本地预览</title>
  <link rel="stylesheet" href="/assets/css/horizon.css?v=preview">
  <script src="/assets/js/horizon.js?v=preview" defer></script>
</head>
<body>
  <header class="page-header" role="banner">
    <h1 class="project-name">Horizon 综合决策雷达</h1>
    <p class="project-tagline">用多源新闻理解变化，再发现值得验证的创业机会</p>
  </header>
  <main class="main-content" id="content" role="main">
    {body}
  </main>
  <footer class="site-footer">
    <span>本地预览 · {report_path.name}</span>
  </footer>
</body>
</html>"""
    return page.encode("utf-8")


class PreviewHandler(SimpleHTTPRequestHandler):
    report_path: Path

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DOCS_DIR), **kwargs)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] in {"/", "/index.html", "/report"}:
            payload = render_page(self.report_path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview the latest Horizon news report")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    PreviewHandler.report_path = args.report or latest_report()
    server = ThreadingHTTPServer((args.host, args.port), PreviewHandler)
    print(f"Horizon preview: http://{args.host}:{args.port}", flush=True)
    print(f"Report: {PreviewHandler.report_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
