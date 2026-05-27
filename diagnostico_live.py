#!/usr/bin/env python3
"""
Faz polling DURANTE a busca (não espera 25s antes).
Testa /responses a cada 2s enquanto state=InProgress.
"""
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
print("Polling a cada 2s por 60s...\n")

inicio = time.time()
max_files_vistos = 0

while time.time() - inicio < 60:
    elapsed = time.time() - inicio

    # Objeto principal
    r1 = s.get(f"{SLSKD_URL}/api/v0/searches/{sid}", timeout=10)
    d  = r1.json() if r1.status_code == 200 else {}
    file_count = d.get("fileCount", 0)
    resp_count = d.get("responseCount", 0)
    state      = d.get("state", "?")
    is_done    = d.get("isComplete", False)

    # Endpoint /responses
    r2 = s.get(f"{SLSKD_URL}/api/v0/searches/{sid}/responses", timeout=10)
    lista = r2.json() if r2.status_code == 200 else []
    total_arqs = sum(len(p.get("files", [])) for p in lista)

    if total_arqs != max_files_vistos or elapsed < 3:
        print(f"[{elapsed:5.1f}s] state={state:<12} fileCount={file_count:4} "
              f"responseCount={resp_count:4} | /responses: {len(lista)} peers, {total_arqs} arqs")
        if total_arqs > max_files_vistos:
            max_files_vistos = total_arqs
            # Mostra exemplo do primeiro arquivo encontrado
            for peer in lista:
                arqs = peer.get("files", [])
                if arqs:
                    print(f"  → Exemplo: {json.dumps(arqs[0], indent=6)}")
                    break

    if is_done or state in ("Completed", "TimedOut"):
        print(f"\nBusca encerrada pelo slskd. Max arquivos vistos: {max_files_vistos}")
        break

    time.sleep(2)

s.delete(f"{SLSKD_URL}/api/v0/searches/{sid}", timeout=10)
print("Busca deletada. FIM.")
