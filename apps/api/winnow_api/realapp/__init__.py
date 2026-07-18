"""Real-mode HTTP surface — the self-hosted dashboard's API.

Deliberately does not import the demo module graph (session middleware,
seeder, fixtures), mirroring the discipline the demo side keeps: neither
mode pulls the other's code into memory. Shapes are intentionally close
to the demo's so the dashboard can talk to either with only an endpoint
prefix change.
"""

from winnow_api.realapp.routes import router

__all__ = ["router"]
