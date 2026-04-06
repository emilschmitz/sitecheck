from fastmcp import FastMCP
import subprocess

mcp = FastMCP("Bash Server")

@mcp.tool()
async def execute_command(command: str) -> str:
    """
    Executes a bash command in a subprocess and returns stdout, stderr, and the return code.
    Use this to perform OSINT tasks, file manipulations, or run scripts.
    """
    try:
        # We run this in a shell-like environment for maximum flexibility
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
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds."
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    # Standard stdio by default, but can be switched to SSE in docker-compose
    mcp.run()
