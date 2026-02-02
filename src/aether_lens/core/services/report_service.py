import webbrowser
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


class ReportService:
    def get_report_path(self, target_dir="."):
        return Path(target_dir) / ".aether" / "report.html"

    def open_report(self, target_dir=".", use_allure=False):
        if use_allure:
            url = "http://localhost:5050"
            webbrowser.open(url)
            return url

        report_path = self.get_report_path(target_dir)
        if not report_path.exists():
            return None

        abs_path = report_path.absolute()
        webbrowser.open(f"file://{abs_path}")
        return str(abs_path)

    def serve_report(self, target_dir=".", port=43210):
        report_dir = Path(target_dir) / ".aether"
        if not report_dir.exists():
            raise FileNotFoundError(f".aether directory not found in {target_dir}")

        handler = partial(SimpleHTTPRequestHandler, directory=str(report_dir))
        server_address = ("", port)
        httpd = HTTPServer(server_address, handler)

        return httpd

    def start_serving(self, httpd, use_allure=False):
        try:
            if use_allure:
                self.open_report(use_allure=True)
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.server_close()
