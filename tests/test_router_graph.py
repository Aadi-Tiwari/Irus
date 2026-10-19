from pathlib import Path

from irus.scan import ScanCache, scan


def write(root, name, source):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_existing_nested_router_fixture_matches_its_client():
    root = Path(__file__).resolve().parents[1] / "fixtures" / "gate-a-app"
    checked = scan(root)
    assert "POST /api/checkout" in {p.seam for p in checked.producers}
    assert not [f for f in checked.findings if f.kind == "endpoint_not_found"]


def test_router_and_model_names_are_scoped_to_their_module(tmp_path):
    for name, field in [("orders", "email"), ("payments", "amount")]:
        write(tmp_path, f"app/{name}.py", f'''from fastapi import APIRouter
from pydantic import BaseModel
router = APIRouter()
class Body(BaseModel):
    {field}: str
@router.post("/submit")
def submit(payload: Body): return {{}}
''')
    write(tmp_path, "app/main.py", '''from fastapi import FastAPI, APIRouter
from .orders import router as orders
from . import payments
app = FastAPI()
api = APIRouter(prefix="/v1")
api.include_router(orders, prefix="/orders")
api.include_router(payments.router, prefix="/payments")
app.include_router(api, prefix="/api")
''')
    checked = scan(tmp_path)
    assert {p.path: p.field_names() for p in checked.producers} == {
        "/api/v1/orders/submit": {"email"}, "/api/v1/payments/submit": {"amount"},
    }
    assert all(p.mounted for p in checked.producers)


def test_multiple_mounts_and_changed_prefix_refresh_cached_routes(tmp_path):
    write(tmp_path, "routes.py", '''from fastapi import APIRouter
router = APIRouter(prefix="/users")
@router.get("/{id}")
def user(id: str): return {}
''')
    app = '''from fastapi import FastAPI
from routes import router
app = FastAPI()
app.include_router(router, prefix="/v1")
app.include_router(router, prefix="/v2")
'''
    write(tmp_path, "main.py", app)
    cache = ScanCache()
    assert {p.path for p in scan(tmp_path, cache).producers} == {"/v1/users/{}", "/v2/users/{}"}
    write(tmp_path, "main.py", app.replace("/v2", "/v3"))
    assert {p.path for p in scan(tmp_path, cache).producers} == {"/v1/users/{}", "/v3/users/{}"}


def test_module_qualified_models_resolve_request_and_response(tmp_path):
    write(tmp_path, "schemas.py", '''from pydantic import BaseModel
class Body(BaseModel):
    email: str
class Reply(BaseModel):
    receipt: str
''')
    write(tmp_path, "main.py", '''from fastapi import FastAPI
import schemas
app = FastAPI()
@app.post("/checkout", response_model=schemas.Reply)
def checkout(body: schemas.Body): return {}
''')
    producer, = scan(tmp_path).producers
    assert producer.encoding == "json"
    assert producer.field_names() == {"email"}
    assert {field.name for field in producer.response_fields} == {"receipt"}
    (tmp_path / "schemas.py").unlink()
    assert scan(tmp_path).producers[0].encoding == "unknown"


def test_dynamic_prefix_is_unverified_instead_of_a_false_contract(tmp_path):
    write(tmp_path, "main.py", '''from fastapi import FastAPI, APIRouter
app = FastAPI()
router = APIRouter(prefix=settings.PREFIX)
@router.post("/checkout")
def checkout(): return {}
app.include_router(router)
''')
    write(tmp_path, "client.ts", 'fetch("/checkout", {method: "POST", body: JSON.stringify({email: "x"})});')
    checked = scan(tmp_path)
    assert any(f.kind == "unresolved_route" for f in checked.findings)
    assert not checked.high
