"""Remote services package.

This package provides a framework for creating remote services that can be
called by the phone-stream server via HTTP POST with JSON payloads.

Each service should:
1. Inherit from RemoteService base class
2. Implement the process() method
3. Be runnable as a standalone HTTP server

Example usage:
    from remotes.remote_generic import RemoteService

    class MyService(RemoteService):
        def process(self, data: dict) -> dict:
            # Your processing logic here
            return {"response": "Hello!"}

    if __name__ == "__main__":
        MyService.run(host="0.0.0.0", port=8000)
"""
