#!/usr/bin/env python3
"""Start the Personal Assistant server.

Usage:
  python run.py                        # default port 8000
  python run.py --port 8080
  ANTHROPIC_API_KEY=sk-… python run.py
  OPENAI_API_KEY=sk-… python run.py
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app.main import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    import uvicorn
    app = create_app()
    print(f"\nPersonal Assistant")
    print(f"   Open: http://localhost:{args.port}")
    print(f"   Calendar feed: http://localhost:{args.port}/calendar.ics\n")
    uvicorn.run(app, host=args.host, port=args.port)
