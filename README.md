SLSKD AUTO
Guia Completo de Instalacao e Uso

Versao com suporte a 3 modos de organizacao de pasta
Modo 1  →  Raiz (flat): salva tudo diretamente na pasta de downloads
Modo 2  →  Pasta unica: agrupa por "Artista - Musica/"
Modo 3  →  Artista/Musica: subpastas hierarquicas

Arquivo: gui_server.py  +  gui.html  (versoes corrigidas)

Maio 2026

1. Visao Geral do Sistema
O sistema SLSKD AUTO e composto por 4 arquivos Python/HTML que trabalham juntos para baixar musicas automaticamente via Soulseek e organiza-las em pastas.

Arquivo
Funcao
gui_server.py
Servidor Flask: API, logica de download, organizacao de pastas
gui.html
Interface web: controles, configuracoes, log em tempo real
organizar_mp3.py
Organiza arquivos ja baixados por artista/album/genero (uso manual)
orquestrador.py
Pipeline completo: Rekordbox → download → qualidade → organiza


2. Pre-requisitos
2.1 Python e bibliotecas
Python 3.10 ou superior (recomendado 3.11+). Instale as dependencias com:

pip install flask flask-cors openpyxl requests mutagen

2.2 slskd rodando localmente
O slskd precisa estar em execucao e acessivel em http://localhost:5030. Voce pode baixa-lo em:
    • https://github.com/slskd/slskd/releases
    • Configure usuario e senha em appsettings.yml (padrao: slskd / slskd)

IMPORTANTE: Pasta de downloads do slskd
No slskd, va em Settings > Options > Directories e anote qual e a
pasta de downloads configurada (ex: /home/usuario/slskd/downloads).

Os caminhos que o gui_server.py envia sao RELATIVOS a essa pasta.
Voce nao precisa alterar nada no slskd — so precisa saber onde ele salva.


3. Como Rodar
3.1 Iniciar o servidor
Abra um terminal na pasta onde estao os arquivos e execute:

python3 gui_server.py

Por padrao o servidor sobe na porta 8080. Para usar outra porta:
python3 gui_server.py --port 9090

3.2 Abrir a interface
Com o servidor rodando, abra o arquivo gui.html diretamente no navegador:

    • Windows: clique duas vezes em gui.html
    • Mac/Linux: abra o terminal e execute:  open gui.html  ou  xdg-open gui.html
    • Ou acesse http://localhost:8080 se o servidor estiver servindo o arquivo

Dica: servidor na porta certa
A constante API dentro do gui.html aponta para http://localhost:8081/api.
Se voce rodar na 8080, certifique-se que o gui.html aponte para a porta correta.
Para checar, abra gui.html em um editor de texto e procure:  const API = '...'


4. Modos de Organizacao de Pasta (Funcionalidade Corrigida)
Esta foi a principal correcao desta versao. Antes, o sistema criava subpastas mesmo no modo Flat porque o localFilename enviado ao slskd nao estava sendo montado corretamente. Agora os 3 modos funcionam como esperado.

Modo 1: Raiz (flat)
Todos os arquivos sao salvos diretamente na pasta de downloads do slskd, sem nenhuma subpasta.

Campo
Valor
Selecao
Botao "Raiz (flat)" na interface
Nome da pasta
Opcional. Se preenchido, cria UMA pasta e coloca tudo dentro dela
Estrutura (sem nome)
downloads/musica.flac
Estrutura (com nome)
downloads/MinhaColecao/musica.flac

Modo 2: Pasta Unica
Cria uma pasta por musica com o padrao "Artista - Musica" e coloca o arquivo dentro.

Campo
Valor
Selecao
Botao "Pasta unica" na interface
Nome da pasta
Opcional. Se preenchido, vira o prefixo do caminho
Estrutura (sem nome)
downloads/Queen - Bohemian Rhapsody/bohemian.flac
Estrutura (com nome)
downloads/Rock/Queen - Bohemian Rhapsody/bohemian.flac

Modo 3: Artista/Musica
Cria uma hierarquia de pastas: Artista > Musica > arquivo. Ideal para colecoes organizadas.

Campo
Valor
Selecao
Botao "Artista/Musica" na interface
Nome da pasta
Opcional. Se preenchido, vira o prefixo do caminho
Estrutura (sem nome)
downloads/Queen/Bohemian Rhapsody/bohemian.flac
Estrutura (com nome)
downloads/Classicos/Queen/Bohemian Rhapsody/bohemian.flac

Por que as subpastas apareciam antes mesmo no modo Flat?
O slskd usa o campo localFilename para definir onde salvar o arquivo DENTRO
da sua pasta de downloads configurada. Na versao anterior, a logica que montava
esse caminho estava correta no papel, mas o campo era ignorado porque o payload
era enviado como lista de objetos e o slskd criava subpastas espelhando a
estrutura do arquivo remoto.

A correcao garante que localFilename seja montado antes do envio e contenha
exatamente o caminho relativo correto para cada modo.


5. Campo "Nome da Pasta" (Novo)
Logo abaixo dos botoes de modo, agora aparece um campo de texto chamado "Nome da pasta". Ele funciona como um prefixo opcional para todos os downloads desta sessao.

    • Deixe vazio para salvar na raiz da pasta de downloads do slskd
    • Preencha com qualquer nome (ex: Rock, 2024, Favoritas) para agrupar os downloads
    • O campo aceita qualquer texto; caracteres especiais sao removidos automaticamente
    • Uma previa do caminho e exibida em tempo real abaixo do campo

Exemplos de previa exibida na interface:

→ MinhaColecao/musica.flac              (modo Flat com pasta)
→ Rock/Queen - Bohemian Rhapsody/b.flac (modo Pasta unica com pasta)
→ musica.flac                           (modo Flat sem pasta)


6. Como Substituir os Arquivos
Os dois arquivos modificados sao gui_server.py e gui.html. Siga os passos abaixo:

Passo 1 — Parar o servidor atual
Se o gui_server.py estiver rodando, pare-o com Ctrl+C no terminal.

Passo 2 — Fazer backup (recomendado)
cp gui_server.py gui_server_backup.py
cp gui.html gui_backup.html

Passo 3 — Copiar os novos arquivos
Substitua os arquivos antigos pelos novos que foram gerados (gui_server.py e gui.html). Coloque-os na mesma pasta onde estavam os originais.

Passo 4 — Iniciar o servidor novamente
python3 gui_server.py

Passo 5 — Limpar cache do navegador
Abra o gui.html no navegador e pressione Ctrl+Shift+R (Windows/Linux) ou Cmd+Shift+R (Mac) para forcar o recarregamento sem cache. Isso garante que o JavaScript novo seja carregado.


7. Configuracoes do slskd
Para o sistema funcionar corretamente, o slskd precisa estar configurado com:

Configuracao
Valor recomendado
URL
http://localhost:5030
Usuario
slskd  (ou o que voce definiu)
Senha
slskd  (ou a sua senha)
Shared files
Configure pelo menos uma pasta compartilhada
Downloads dir
Anote o caminho completo (ex: /home/user/slskd/downloads)

Para alterar URL, usuario ou senha, edite as constantes no inicio do gui_server.py:

SLSKD_URL     = "http://localhost:5030"
SLSKD_USUARIO = "slskd"
SLSKD_SENHA   = "slskd"


8. Resolucao de Problemas
Problema
Solucao
Ainda cria subpastas no modo Flat
Certifique-se que substituiu AMBOS os arquivos (gui_server.py e gui.html). Limpe o cache do navegador (Ctrl+Shift+R).
Erro de conexao com slskd
Verifique se o slskd esta rodando em http://localhost:5030. Confirme usuario e senha no gui_server.py.
Flask nao encontrado
Execute: pip install flask flask-cors
Excel nao carrega
Verifique se o caminho esta correto e se as colunas existem na planilha.
Download enfileirado mas arquivo nao aparece
Verifique a pasta de downloads do slskd. O arquivo pode estar com nome diferente do esperado.
Campo 'Nome da pasta' nao aparece
Certifique-se que substituiu o gui.html novo. Limpe o cache do navegador.


9. Fluxo de Uso Completo
    1. Inicie o slskd e confirme que esta acessivel em http://localhost:5030
    2. Inicie o servidor: python3 gui_server.py
    3. Abra o gui.html no navegador
    4. Preencha o caminho do Excel e clique em "Carregar Excel"
    5. Em Configuracoes, ajuste formatos, bitrate e modo de organizacao
    6. (Opcional) Preencha o campo "Nome da pasta" para agrupar os downloads
    7. Clique em "Start" e acompanhe pelo log e pela tabela
    8. Ao terminar, exporte a lista de nao encontrados se necessario
