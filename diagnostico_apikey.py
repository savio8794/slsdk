#!/usr/bin/env python3
"""
Testa autenticação via API Key (X-API-Key) vs token Bearer.
"""
import json, time, requests

SLSKD_URL  = "http://localhost:5030"
SLSKD_USER = "slskd"
SLSKD_PASS = "slskd"
API_KEY    = "slskd123456"   # ← ajuste se necessário
TERMO      = "Alok Hear Me Now"

def testar_busca(label, headers):
    print(f"\n=== TESTANDO: {label} ===")
    s = requests.Session()
    s.headers.update(headers)

    r = s.post(f"{SLSKD_URL}/api/v0/searches",
               json={"searchText": TERMO}, timeout=10)
    print(f"POST /searches → {r.status_code}")
    if r.status_code not in (200, 201):
        print(f"  Erro: {r.text[:200]}")
        return

    sid = r.json().get("id")
    print(f"  search_id: {sid}")

    print("  Aguardando 20s...")
    time.sleep(20)

    r2 = s.get(f"{SLSKD_URL}/api/v0/searches/{sid}", timeout=10)
    if r2.status_code == 200:
        d = r2.json()
        resps = d.get("responses") or []
        total = sum(len(p.get("files",[])) for p in resps)
        print(f"  state={d.get('state')} | isComplete={d.get('isComplete')} | arquivos={total} | fileCount={d.get('fileCount')} | responseCount={d.get('responseCount')}")
    else:
        print(f"  GET status: {r2.status_code}")

    # Deleta
    s.delete(f"{SLSKD_URL}/api/v0/searches/{sid}", timeout=10)

# Teste 1: Bearer token (método atual)
s = requests.Session()
r = s.post(f"{SLSKD_URL}/api/v0/session",
           json={"username": SLSKD_USER, "password": SLSKD_PASS}, timeout=10)
token = r.json().get("token")
testar_busca("Bearer Token (método atual)", {"Authorization": f"Bearer {token}"})

# Teste 2: X-API-Key
testar_busca("X-API-Key header", {"X-API-Key": API_KEY})

# Teste 3: sem autenticação
testar_busca("Sem autenticação", {})

print("\n=== FIM ===")
