import uvicorn
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from a2a_agent.agent import SiteCheckAgentExecutor

def create_app():
    # A2A Metadata
    agent_card = AgentCard(
        protocol_version="2024-11-05",
        name="SiteCheckSubagent",
        description="OSINT real estate due diligence specialist.",
        capabilities=AgentCapabilities(),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="site-audit",
                name="site_audit",
                description="Audits physical property conditions from unstructured text.",
            )
        ],
    )

    # Setup Executor & Handlers
    executor = SiteCheckAgentExecutor()
    handler = DefaultRequestHandler(
        agent_executor=executor, 
        task_store=InMemoryTaskStore()
    )

    # Build FastAPI App
    a2a_app = A2AFastAPIApplication(agent_card=agent_card, http_handler=handler)
    return a2a_app.build()

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
