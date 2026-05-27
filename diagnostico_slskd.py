#!/usr/bin/env python3
"""
Diagnóstico da API do slskd
Rode: python3 diagnostico_slskd.py
"""
import json, time, requests

SLSKD_URL    = "http://localhost:5030"
SLSKD_USER   = "slskd"
SLSKD_SENHA  = "slskd"
TERMO_BUSCA  = "Alok Hear Me Now"

s = requests.Session()

# 1. Autenticar
print("=== 1. AUTENTICAÇÃO ===")
r = s.post(f"{SLSKD_URL}/api/v0/session",
           json={"username": SLSKD_USER, "password": SLSKD_SENHA}, timeout=10)
print(f"Status: {r.status_code}")
token = r.json().get("token") if r.status_code == 200 else None
if not token:
    print("FALHA na autenticação:", r.text)
    exit(1)
s.headers["Authorization"] = f"Bearer {token}"
print("Token OK")

# 2. Criar busca
print(f"\n=== 2. CRIANDO BUSCA: '{TERMO_BUSCA}' ===")
r = s.post(f"{SLSKD_URL}/api/v0/searches",
           json={"searchText": TERMO_BUSCA}, timeout=10)
print(f"Status: {r.status_code}")
print("Resposta JSON:", json.dumps(r.json(), indent=2))
search_id = r.json().get("id")
if not search_id:
    print("ERRO: sem search_id")
    exit(1)
print(f"search_id = {search_id}")

# 3. Testar ambos os endpoints
print(f"\n=== 3. TESTANDO ENDPOINTS (aguarda 5s) ===")
time.sleep(5)

for endpoint in [
    f"/api/v0/searches/{search_id}",
    f"/api/v0/searches/{search_id}/responses",
]:
    r = s.get(f"{SLSKD_URL}{endpoint}", timeout=10)
    print(f"\nGET {endpoint}")
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            total = sum(len(x.get("files",[])) for x in data)
            print(f"  Tipo: lista com {len(data)} peers, {total} arquivos")
            if data:
                print(f"  Primeiro peer keys: {list(data[0].keys())}")
        elif isinstance(data, dict):
            print(f"  Tipo: dict, keys={list(data.keys())}")
            print(f"  isComplete: {data.get('isComplete')}")
            print(f"  state: {data.get('state')}")
            resps = data.get("responses") or []
            total = sum(len(p.get("files",[]))for p in resps)
            print(f"  responses: {len(resps)} peers, {total} arquivos")
    else:
        print(f"  Body: {r.text[:200]}")

# 4. Polling por 30s
print(f"\n=== 4. POLLING POR 30s NO ENDPOINT PRINCIPAL ===")
inicio = time.time()
endpoint = f"/api/v0/searches/{search_id}"
ultimo = -1
while time.time() - inicio < 30:
    r = s.get(f"{SLSKD_URL}{endpoint}", timeout=10)
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, dict):
            resps = data.get("responses") or []
            total = sum(len(p.get("files",[]))for p in resps)
            state = data.get("state","?")
            done  = data.get("isComplete", False)
            if total != ultimo:
                print(f"  [{time.time()-inicio:.0f}s] {total} arquivos | state={state} | done={done}")
                ultimo = total
            if done:
                print("  → isComplete=True, encerrando poll")
                break
        elif isinstance(data, list):
            total = sum(len(x.get("files",[]))for x in data)
            if total != ultimo:
                print(f"  [{time.time()-inicio:.0f}s] {total} arquivos (lista)")
                ultimo = total
    time.sleep(2)

print("\n=== FIM DO DIAGNÓSTICO ===")
