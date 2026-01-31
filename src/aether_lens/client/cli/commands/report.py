import os
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import click


@click.group()
def report():
    """Manage and view Aether Lens test reports."""
    pass


@report.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True))
@click.option("--allure", is_flag=True, help="Open the real-time Allure dashboard.")
def open(target_dir, allure):
    """Open test reports in your browser."""
    if allure:
        url = "http://localhost:5050"
        click.echo(f"Opening Allure Dashboard: {url}")
        click.echo(
            "(Make sure you have run: kubectl port-forward svc/allure-dashboard 5050:5050)"
        )
        webbrowser.open(url)
        return

    report_path = Path(target_dir) / ".aether" / "report.html"
    if not report_path.exists():
        click.secho(f"Error: Report not found at {report_path}", fg="red")
        click.echo("Run 'aether-lens run' first to generate a report.")
        return

    abs_path = report_path.absolute()
    click.echo(f"Opening report: {abs_path}")
    webbrowser.open(f"file://{abs_path}")


@report.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True))
@click.option("--port", default=43210, help="Port to serve the report on.")
def serve(target_dir, port):
    """Serve the report directory via HTTP."""
    report_dir = Path(target_dir) / ".aether"
    if not report_dir.exists():
        click.secho(f"Error: .aether directory not found in {target_dir}", fg="red")
        return

    os.chdir(report_dir)
    server_address = ("", port)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)

    click.secho("Aether Lens Conformance UI serving at:", fg="blue", bold=True)
    click.secho(f"http://localhost:{port}/report.html", fg="cyan", underline=True)
    click.echo("\nPress Ctrl+C to stop.")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopping server...")
        httpd.server_close()


@report.command()
def dashboard():
    """Show instructions for accessing the real-time Allure dashboard."""
    click.secho("\n--- Allure Real-time Dashboard ---", fg="blue", bold=True)
    click.echo("The dashboard is managed by Allure Docker Service in Kubernetes.")
    click.echo("\n1. If not already deployed:")
    click.echo("   kubectl apply -f allure-dashboard.yaml")
    click.echo("\n2. To access locally:")
    click.secho("   kubectl port-forward svc/allure-dashboard 5050:5050", fg="green")
    click.echo("\n3. Open in your browser:")
    click.secho("   http://localhost:5050", fg="cyan", underline=True)
    click.echo("\nThe dashboard will automatically refresh every 3 seconds.")
