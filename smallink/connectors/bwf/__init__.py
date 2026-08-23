"""BWF Studio connector — embedded short-video production workbench.

Unlike MineM (which is an external CLI-driven app), BWF is embedded directly
inside the Smallink process. Its FastAPI router is mounted at startup and its
data lives under the Smallink state directory.
"""

from .pipeline import BWFPipeline
from .store import BWFStore
from .router import bwf_router, init_bwf

__all__ = ["BWFPipeline", "BWFStore", "bwf_router", "init_bwf"]
