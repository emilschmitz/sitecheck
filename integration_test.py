# /// script
# dependencies = [
#   "httpx",
#   "python-on-whales",
#   "rich",
# ]
# ///
import asyncio
import json
import time
import httpx
import argparse
import sys
import re
from python_on_whales import docker
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt


A2A_URL = "http://localhost:8000/"
console = Console()

def strip_ansi(text):
    ansi_escape = re.compile(r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def wait_for_port(port, timeout=60.0):
    start_time = time.perf_counter()
    while time.perf_counter() - start_time < timeout:
        try:
            with httpx.Client() as client:
                if client.get(f"http://localhost:{port}/docs").status_code == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False

async def chat(prompt_text=None, debug=False):
    if not prompt_text:
        console.print("\n[bold blue]Sitecheck A2A Test Client[/bold blue]")
    
    while True:
        if prompt_text:
            task_text = prompt_text
        else:
            task_text = Prompt.ask("\n[bold green]Prompt[/bold green]")
        
        if task_text.lower() in ["exit", "quit", "q"]:
            break

        with Live(Panel("...", title="[bold blue]A2A Agent SSE Stream[/bold blue]", border_style="blue"), console=console, refresh_per_second=10) as live:
            try:
                async with httpx.AsyncClient(timeout=600) as client:
                    async with client.stream("POST", A2A_URL, json={
                        "jsonrpc": "2.0",
                        "method": "message/stream",
                        "params": {
                            "message": {
                                "role": "user",
                                "parts": [{"kind": "text", "text": task_text}],
                                "message_id": f"msg-{int(time.time())}"
                            }
                        },
                        "id": 1
                    }) as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                raw_json = line[6:]
                                if debug:
                                    console.log(f"[dim]DEBUG: {raw_json}[/dim]")
                                
                                data = json.loads(raw_json)
                                content = None
                                
                                # The A2A server wraps the event in 'result' for the stream response
                                payload = data.get("result", data.get("params", {}))

                                # Handle standard message parts
                                if "message" in payload:
                                    parts = payload["message"].get("parts", [])
                                    if parts:
                                        last_part = parts[-1]
                                        if isinstance(last_part, dict):
                                            content = last_part.get("text")
                                        elif hasattr(last_part, "text"):
                                            content = last_part.text
                                
                                # Handle status updates (TaskStatusUpdateEvent)
                                elif "status" in payload:
                                    status_msg = payload["status"].get("message", {})
                                    parts = status_msg.get("parts", [])
                                    if parts:
                                        last_part = parts[-1]
                                        if isinstance(last_part, dict):
                                            content = last_part.get("text")
                                        elif hasattr(last_part, "text"):
                                            content = last_part.text
                                
                                # Direct message if not wrapped in 'message'
                                elif "parts" in payload:
                                    parts = payload.get("parts", [])
                                    if parts:
                                        last_part = parts[-1]
                                        if isinstance(last_part, dict):
                                            content = last_part.get("text")
                                        elif hasattr(last_part, "text"):
                                            content = last_part.text

                                if content:
                                    # Strip carriage returns and ANSI codes as the Live panel 
                                    # handles the 'in-place' update and styling.
                                    clean_content = strip_ansi(content.replace("\r", ""))
                                    if clean_content.strip():
                                        live.update(Panel(Markdown(clean_content), title="[bold blue]A2A Agent SSE Stream[/bold blue]", border_style="blue"))
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
        
        if prompt_text:
            break

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, help="Run a single prompt non-interactively")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging of raw server responses")
    parser.add_argument("--no-docker", action="store_true", help="Do not attempt to start docker containers")
    args = parser.parse_args()

    if not args.no_docker and not wait_for_port(8000, timeout=2):
        console.print("[yellow]Services not found. Starting Docker containers...[/yellow]")
        docker.compose.up(detach=True, build=True)
        if not wait_for_port(8000):
            console.print("[red]Timeout waiting for services.[/red]")
            exit(1)

    try:
        asyncio.run(chat(prompt_text=args.prompt, debug=args.debug))
    except KeyboardInterrupt:
        pass
    finally:
        if not args.prompt and not args.no_docker and docker.compose.ps():
            if Prompt.ask("\nShut down containers?", choices=["y", "n"], default="n") == "y":
                docker.compose.down()
