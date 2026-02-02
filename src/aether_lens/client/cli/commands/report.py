import click
from dependency_injector.wiring import Provide, inject

from aether_lens.core.containers import Container


@click.group()
def report():
    """Manage and view Aether Lens test reports."""
    pass


@report.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True))
@click.option("--allure", is_flag=True, help="Open the real-time Allure dashboard.")
@inject
def open(
    target_dir,
    allure,
    report_service: Container.report_service = Provide[Container.report_service],
):
    """Open test reports in your browser."""
    if allure:
        url = report_service.open_report(use_allure=True)
        click.echo(f"Opening Allure Dashboard: {url}")
        click.echo(
            "(Make sure you have run: kubectl port-forward svc/allure-dashboard 5050:5050)"
        )
        return

    path = report_service.open_report(target_dir=target_dir)
    if not path:
        click.secho(f"Error: Report not found in {target_dir}/.aether", fg="red")
        click.echo("Run 'aether-lens run' first to generate a report.")
        return

    click.echo(f"Opening report: {path}")


@report.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True))
@click.option("--port", default=43210, help="Port to serve the report on.")
@inject
def serve(
    target_dir,
    port,
    report_service: Container.report_service = Provide[Container.report_service],
):
    """Serve the report directory via HTTP."""

    try:
        httpd = report_service.serve_report(target_dir=target_dir, port=port)

        click.secho("Aether Lens Conformance UI serving at:", fg="blue", bold=True)
        click.secho(f"http://localhost:{port}/report.html", fg="cyan", underline=True)
        click.echo("\nPress Ctrl+C to stop.")

        report_service.start_serving(httpd)

    except Exception as e:
        click.secho(f"Error: {e}", fg="red")


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
