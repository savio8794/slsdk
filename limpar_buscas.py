#!/usr/bin/env python3
"""Deleta todas as buscas antigas do slskd para limpar a fila."""
import requests, json

SLSKD_URL  = "http://localhost:5030"
SLSKD_USER = "slskd"
SLSKD_PASS = "slskd"

s = requests.Session()
r = s.post(f"{SLSKD_URL}/api/v0/session",
           json={"username": SLSKD_USER, "password": SLSKD_PASS}, timeout=10)
s.headers["Authorization"] = f"Bearer {r.json()['token']}"

# Lista todas as buscas
r = s.get(f"{SLSKD_URL}/api/v0/searches", timeout=10)
buscas = r.json() if r.status_code == 200 else []
print(f"Buscas encontradas: {len(buscas)}")

for b in buscas:
    sid   = b.get("id")
    texto = b.get("searchText", "?")
    state = b.get("state", "?")
    r = s.delete(f"{SLSKD_URL}/api/v0/searches/{sid}", timeout=10)
    print(f"  [{r.status_code}] Deletada: '{texto}' (state={state})")

print(f"\nFila limpa! {len(buscas)} busca(s) removidas.")
