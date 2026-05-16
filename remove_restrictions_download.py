#!/usr/bin/env python3
"""
Script para remover restrições da pasta download
Remove restrições de leitura, escrita e execução e altera proprietário
"""

import os
import stat
import subprocess


def remove_restrictions(path):
    """
    Remove todas as restrições usando comandos do sistema
    """
    if not os.path.exists(path):
        print(f"Erro: O caminho '{path}' não existe.")
        return False

    if not os.path.isdir(path):
        print(f"Erro: '{path}' não é um diretório.")
        return False

    try:
        print("=" * 60)
        print("REMOVENDO RESTRIÇÕES")
        print("=" * 60)

        # Obter usuário atual
        current_user = os.getenv("USER") or os.getenv("USERNAME")
        print(f"Usuário: {current_user}")
        print(f"Diretório: {path}")
        print()

        # Verificar se o caminho existe
        if not os.path.exists(path):
            print(f"✗ Erro: O caminho '{path}' não existe.")
            return False

        # Verificar propriedades atuais
        print("Propriedades ATUAIS:")
        subprocess.run(["ls", "-la", path])
        print()

        # COMANDO 1: Mudar proprietário (mais importante para remover cadeados)
        print("1. Alterando proprietário...")
        result = subprocess.run(
            ["sudo", "chown", "-R", current_user + ":" + current_user, path],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("   ✓ Proprietário alterado com sucesso")
        else:
            print(f"   ⚠ Erro: {result.stderr}")

        # COMANDO 2: Definir permissões totais
        print("2. Alterando permissões...")
        result = subprocess.run(
            ["sudo", "chmod", "-R", "777", path],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("   ✓ Permissões alteradas com sucesso")
        else:
            print(f"   ⚠ Erro: {result.stderr}")

        print()
        print("Propriedades APÓS alterações:")
        subprocess.run(["ls", "-la", path])
        print()

        print(f"✓ Processo concluído!")
        print(f"  Se ainda houver problemas, talvez outro aplicativo (como Soulseek)")
        print(f"  esteja usando os arquivos. Tente fechá-lo e executar novamente.")
        return True

    except Exception as e:
        print(f"Erro durante o processo: {e}")
        return False


if __name__ == "__main__":
    # Caminho da pasta download
    download_path = "/home/savio/slskd/downloads"

    success = remove_restrictions(download_path)

    if not success:
        print("\nDICA: Execute o script com sudo se as permissões forem negadas:")
        print("      sudo python3 remove_restrictions_download.py")