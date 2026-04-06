import subprocess

async def execute_bash_command(command: str) -> str:
    """Run any terminal command via bash locally."""
    try:
        process = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=60
        )
        output = []
        if process.stdout:
            output.append(f"### STDOUT\n{process.stdout}")
        if process.stderr:
            output.append(f"### STDERR\n{process.stderr}")
        output.append(f"### Return Code: {process.returncode}")
        return "\n\n".join(output)
    except Exception as e:
        return f"Error: {str(e)}"
