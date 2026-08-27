"""Compatibility launcher for the WebAuto v3 control plane and dashboard."""

from __future__ import annotations

import argparse

from webauto.application.control_api import create_app
from webauto.application.settings import RuntimeConfigStore
from webauto.bootstrap import get_application_service, get_butler_service
from webauto.config import RuntimeSettings

service = get_application_service()
settings_store = RuntimeConfigStore(RuntimeSettings.from_env().runtime_dir)
butler = get_butler_service(settings_store)
app = create_app(service, settings_store=settings_store, butler=butler)


def main() -> None:
    parser = argparse.ArgumentParser(description="WebAuto v3 control plane")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7860, type=int)
    args = parser.parse_args()
    import uvicorn

    token_path = settings_store.authorizer.token_path.resolve()
    settings_store.authorizer.token()
    print(f"WebAuto setup: http://{args.host}:{args.port}/setup")
    print(f"Setup token file: {token_path}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
