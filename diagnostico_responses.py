#!/usr/bin/env python3
"""Confirma qual endpoint retorna os arquivos de fato."""
import json, time, requests

SLSKD_URL  = "http://localhost:5030"
SLSKD_USER = "slskd"
SLSKD_PASS = "slskd"
TERMO      = "Alok Hear Me Now"

s = requests.Session()
r = s.post(f"{SLSKD_URL}/api/v0/session",
           json={"username": SLSKD_USER, "password": SLSKD_PASS}, timeout=10)
s.headers["Authorization"] = f"Bearer {r.json()['token']}"

r = s.post(f"{SLSKD_URL}/api/v0/searches", json={"searchText": TERMO}, timeout=10)
sid = r.json()["id"]
print(f"search_id: {sid}")
print("Aguardando 25s para acumular resultados...")
time.sleep(25)

# Testa /searches/{id}
r1 = s.get(f"{SLSKD_URL}/api/v0/searches/{sid}", timeout=10)
d  = r1.json()
print(f"\nGET /searches/{sid}")
print(f"  fileCount={d.get('fileCount')} responseCount={d.get('responseCount')}")
print(f"  responses (embutido) = {len(d.get('responses') or [])} peers")

# Testa /searches/{id}/responses
r2 = s.get(f"{SLSKD_URL}/api/v0/searches/{sid}/responses", timeout=10)
lista = r2.json() if r2.status_code == 200 else []
total = sum(len(p.get("files", [])) for p in lista)
print(f"\nGET /searches/{sid}/responses")
print(f"  {len(lista)} peers | {total} arquivos")
if lista:
    print(f"  Exemplo peer keys: {list(lista[0].keys())}")
    arquivos = lista[0].get("files", [])
    if arquivos:
        print(f"  Exemplo arquivo keys: {list(arquivos[0].keys())}")
        print(f"  Primeiro arquivo: {json.dumps(arquivos[0], indent=4)}")

s.delete(f"{SLSKD_URL}/api/v0/searches/{sid}", timeout=10)
print("\nOK")
