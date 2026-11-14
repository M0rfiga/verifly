# <h1 style="color: #107ACF">Verifly</h1>

<p>Nosso projeto do segundo período - TOP 1</p>

### ! Atenção !

- O arquivo de estilo variables.css irá conter cores e fontes que iremos utilizar em todo o projeto;
- Todos os arquivos de .html devem conter o link do arquivo variable.css para que haja padronização;
- Sigam o primeiro arquivo de template adicionado e nao foquem em mexer no menu;

#### <p style="color: #FE731F; font-style: italic">Caso tenham qualquer dúvida quanto ao projeto, questionem no grupo.</p>

## Estrutura do projeto

```text
VeriFLY/
├── app.py                   # Entrada do servidor Flask
├── python_modules/
│   ├── web.py               # Aplicação Flask e rotas
│   ├── authentication.py    # Contas e sessões
│   ├── create_user.py       # Comando de cadastro da equipe
│   ├── firebase_db.py       # Conexão com o Firebase
│   ├── comparator.py        # Comparação dos voos
│   ├── flight_search.py     # Adaptador dos buscadores
│   ├── local_worker.py      # Execução local da fila
│   ├── menu_services.py     # Pesquisa e notificações
│   ├── reservation_history.py
│   ├── verification_queue.py
│   └── search_scripts/      # Buscadores por companhia
├── static/                  # CSS, JavaScript e imagens
├── templates/               # Páginas e componentes HTML
├── tests/                   # Testes automatizados
├── start_worker.ps1         # Atalho do worker local
└── requirements*.txt        # Dependências do servidor e da máquina local
```

Execute os comandos abaixo na raiz do projeto. O servidor continua iniciando
com `python app.py`, e a entrada de publicação continua sendo `app:app`.
Os comandos administrativos agora são executados como módulos, com
`python -m python_modules.create_user` e `python -m python_modules.local_worker`,
conforme os exemplos das próximas seções. `start_worker.ps1` ajusta a pasta de
execução automaticamente, inclusive quando chamado de outro diretório.

## Buscas executadas na máquina local

O painel continua hospedado. O botão **Verificar voos agora** grava solicitações
na coleção `verificacoes` do mesmo Firestore usado pelas reservas e retorna HTTP
202. O servidor não importa nem executa o Playwright. Um worker nesta máquina
consulta a fila, abre o navegador, executa os buscadores de Azul/GOL e publica os
resultados no Firestore. O painel atualiza os dados automaticamente a cada cinco
segundos. LATAM continua sem buscador implementado.

### Servidor do painel

Instale `requirements.txt`, mantenha `FIREBASE_SERVICE_ACCOUNT_JSON` configurada
com a credencial do Firebase e publique este código pelo processo de deploy do
projeto. O servidor precisa ter acesso às coleções `reservas` e `verificacoes`.
Não execute `python_modules.local_worker` no servidor. O Playwright e seus navegadores são
necessários apenas na máquina local.

### Máquina local (PowerShell)

Na pasta do projeto, execute uma vez:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Em cada terminal onde for iniciar o worker, configure o caminho da sua chave
Firebase e execute:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = (Resolve-Path '.\verifly-56717-firebase-adminsdk-fbsvc-3f1251030a.json').Path
.\.venv\Scripts\python.exe -m python_modules.local_worker
```

Com a chave já presente nesta pasta, o atalho equivalente é
`.\start_worker.ps1`. Ele também aceita `-Headless` ou
`-CredentialsPath 'C:\caminho\outra-chave.json'`.

A chave deve apontar para o mesmo projeto Firebase do painel. O arquivo de chave
está ignorado pelo Git e não deve ser incluído em commits. Se a variável
`FIREBASE_SERVICE_ACCOUNT_JSON` também existir no terminal, ela tem precedência.

Deixe o terminal aberto e use **Verificar voos agora** no site. As linhas mostrarão
“Na fila” e depois “Verificação em andamento”. O navegador abre nesta máquina por
padrão; para ocultá-lo, configure `$env:VERIFLY_HEADLESS = '1'` antes de iniciar o
worker. Encerre com Ctrl+C.

Se a máquina estiver desligada ou o worker parado, as solicitações permanecem na
fila até ele ser iniciado. Uma execução interrompida pode ser retomada após cinco
minutos sem renovação. Cliques repetidos reutilizam a solicitação em andamento;
resultados antigos não sobrescrevem uma nova execução, reservas resolvidas ou
realizadas, nem trechos editados durante a consulta.

Para processar apenas a fila disponível e encerrar:

```powershell
.\.venv\Scripts\python.exe -m python_modules.local_worker --once
```

O intervalo de consulta pode ser ajustado com `--poll-seconds 10`. O modo contínuo
é necessário para atender novas solicitações enquanto o painel estiver em uso.

### Verificação sem acessar o banco real

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/scripts/dashboard.js
```

## Histórico de reservas

A página `history.html` lista todas as reservas do Firestore e atualiza a cada
cinco segundos enquanto estiver visível. A busca aceita passageiro, localizador
e pasta. Os filtros de 30/60 dias e de período consideram a última movimentação
da reserva; os contadores refletem as reservas filtradas. Ao abrir uma reserva,
a linha do tempo exibe os eventos do mais recente para o mais antigo, com
paginação de 25 eventos e opção de carregar os anteriores.

Cadastro, atualização do cadastro, solicitação de verificação, resultado da
consulta, falha e mudanças manuais de status são registrados na subcoleção
`reservas/{id}/historico`. Cada evento contém data/hora e os dados anteriores e
posteriores, incluindo os horários consultados. O evento e a alteração da reserva
são gravados na mesma transação. Novas verificações preservam os eventos antigos.
O endpoint de leitura é `GET /api/reservas/{id}/historico`, com parâmetros
opcionais `limit` (1 a 100) e `cursor` retornado como `nextCursor`.

Reservas anteriores à implementação aparecem com sua situação atual. Não há
reconstrução de eventos antigos que não foram armazenados. Depois da publicação,
reinicie também o worker local com o código atualizado para que ele passe a
registrar os eventos de verificação.

## Login e cadastro inicial da equipe

O acesso às páginas internas e às APIs exige uma conta. As contas ficam na
coleção `usuarios` do Firestore, com senha protegida por hash scrypt. Não há
cadastro público ou senha padrão. O comando abaixo cria a primeira conta e pode
ser repetido para os demais integrantes da equipe.

Com a credencial Firebase configurada no terminal, execute:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = (Resolve-Path '.\verifly-56717-firebase-adminsdk-fbsvc-3f1251030a.json').Path
.\.venv\Scripts\python.exe -m python_modules.create_user --email 'seu-email@agencia.com.br' --name 'Seu nome'
```

A senha é solicitada duas vezes, não aparece no terminal e deve ter de 12 a 256
caracteres. O cadastro usa o mesmo projeto Firebase configurado no painel.
Para redefinir a senha de uma conta existente, use o mesmo comando com
`--reset-password`; isso também invalida todas as sessões anteriores da conta.
Para desativar uma conta, defina seu campo `enabled` como `false` no Firestore.

Depois de publicar o código atualizado no servidor, acesse `/` ou `/login.html`.
O botão ENTRAR valida o e-mail e a senha, e o ícone de olho mostra ou oculta a
senha. As sessões duram oito horas e usam cookies HttpOnly e SameSite=Lax; os
identificadores das sessões são armazenados no banco apenas como hash. Sair
revoga a sessão no servidor e retorna ao login. Requisições de alteração exigem
também um token CSRF. Cinco tentativas por combinação de e-mail/IP em quinze
minutos bloqueiam temporariamente novas tentativas dessa combinação.

O servidor precisa de acesso às coleções `usuarios`, `sessoes`,
`tentativas_login` e `notificacoes`, além das coleções já utilizadas. Não é
necessária uma chave secreta do Flask: as sessões são mantidas no Firestore.
Em produção com HTTPS, configure `VERIFLY_COOKIE_SECURE=1` no ambiente do
servidor. Em desenvolvimento local por HTTP, mantenha essa variável em `0`.

### Verificação Cloudflare opcional

Para habilitar o desafio real do Cloudflare Turnstile no login, configure
`TURNSTILE_SITE_KEY` e `TURNSTILE_SECRET_KEY` no servidor e cadastre o domínio
do site no Cloudflare. A chave secreta nunca é enviada ao navegador. O token do
desafio é validado no servidor pela API Siteverify antes da autenticação.
Sem essas duas variáveis, o login funciona com e-mail e senha, e o desafio e a
indicação de proteção Cloudflare não são exibidos. Se apenas uma chave estiver
configurada, o login é bloqueado até a configuração ser corrigida.
Consulte a [documentação de validação do Turnstile](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/).

## Menu superior

Dashboard, histórico e cadastro usam o mesmo componente `_top_menu.html`.
A pesquisa encontra nome do cliente, localizador e pasta sem diferenciar
maiúsculas ou acentos, com até oito sugestões. Clique em um resultado ou use
as setas e Enter para abrir a reserva expandida no histórico. No dashboard e
no histórico, digitar também filtra a lista da página.

O sino apresenta cadastros, atualizações, alterações de voo, falhas e ações
manuais. Novos alertas são gravados na mesma transação do histórico da reserva;
resultados idênticos não repetem notificações de alteração ou falha. Alertas de
reservas anteriores à implementação também aparecem. A lista mostra até 50
notificações e é atualizada a cada quinze segundos, além de ser atualizada ao
abrir o sino. A leitura é salva por conta no Firestore e permanece entre sessões.
Clique em uma notificação para abrir a reserva ou em **Marcar como lidas** para
marcar os itens exibidos. Reinicie o worker local com o código atualizado para
que as novas buscas também gerem notificações.
