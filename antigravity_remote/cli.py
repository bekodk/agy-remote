import argparse
import asyncio
import sys

import qrcode
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import AppConfig
from .server import RemoteServer


console = Console()


def print_terminal_banner(config: AppConfig) -> None:
    qr = qrcode.QRCode(version=1, box_size=1, border=1)
    url = config.qr_url if config.require_pin else config.base_url
    qr.add_data(url)
    qr.make(fit=True)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column(style="white")
    table.add_row("📱 Telefon Adresi (IP):", f"[bold green]{config.base_url}[/bold green]")
    table.add_row("🔑 Güvenlik PIN Kodu:", f"[bold yellow]{config.pin_code}[/bold yellow]" if config.require_pin else "[dim]Devre Dışı[/dim]")
    table.add_row("🧠 Brain Dizini:", str(config.brain_dir))

    console.print(
        Panel(
            table,
            title="[bold magenta]🚀 Antigravity Remote (PC <-> Telefon Köprüsü)[/bold magenta]",
            subtitle="Aynı Wi-Fi ağındaki telefonunuzdan yukarıdaki IP adresine girin veya QR kodu okutun",
            border_style="bright_blue",
        )
    )
    qr.print_ascii(invert=True)


async def run_cli_server(config: AppConfig) -> None:
    config.prepare_https()
    print_terminal_banner(config)

    def on_log(msg: str) -> None:
        console.print(f"[cyan]{msg}[/cyan]")

    server = RemoteServer(config, on_log=on_log)
    await server.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Antigravity Remote — PC'de açık olan Antigravity ile telefondan mesajlaşma aracı"
    )
    parser.add_argument("--cli", action="store_true", help="Masaüstü arayüzü (GUI) yerine terminal (CLI) modunda başlatır")
    parser.add_argument("--port", type=int, default=None, help="Sunucu portu (varsayılan: 8765)")
    parser.add_argument("--no-pin", action="store_true", help="PIN kodu korumasını devre dışı bırakır")
    args = parser.parse_args()

    config = AppConfig()
    if args.port:
        config.port = args.port
    if args.no_pin:
        config.require_pin = False

    if args.cli:
        try:
            asyncio.run(run_cli_server(config))
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        try:
            from .gui import run_gui
            run_gui(config)
        except ImportError:
            console.print("[yellow]PyQt6 bulunamadı, CLI modunda başlatılıyor...[/yellow]")
            asyncio.run(run_cli_server(config))
