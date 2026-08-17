"""PyInstaller entry shim for the Smallink server sidecar.

`smallink/server/run.py` uses package-relative imports (`from ..config import ...`), so it
cannot be frozen as the `__main__` script directly — relative imports fail when a module runs
as `__main__`. This shim imports the package absolutely and delegates, which is exactly what the
`smallink-server` console script does.
"""

from smallink.server.run import main

if __name__ == "__main__":
    main()
