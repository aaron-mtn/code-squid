"""Code Squid's intentional specialization point for Core Agent behavior."""

from squid_core.agent import Agent

# Keep this product-owned name even while behavior is identical; future coding
# completion policy belongs here rather than in the reusable Core Agent.
CodingAgent = Agent

__all__ = ["CodingAgent"]
