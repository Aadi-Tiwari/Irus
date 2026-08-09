# Gate A subject

A small but structurally real FastAPI application: routers split across modules,
mounted through an intermediate `api_router`, a Pydantic request and response
model, and a frontend that calls the endpoint.

It exists because the repositories we tried first could not serve as a control.
`fastapi/full-stack-fastapi-template` at commit `66f444a` does not parse under
Python 3 (`except InvalidTokenError, ValidationError:` in
`backend/app/api/deps.py`), and Netflix/dispatch needs a database to import.

**Stated limitation:** this app was written by us, not found in the wild. What
the experiment measures, though, is a property of Python and FastAPI rather than
of whose code it is: whether a partially-edited tree still imports.
