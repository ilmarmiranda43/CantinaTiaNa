# Cantina Escolar — Python + Baileys

Migração do aplicativo de cantina escolar para **Python/FastAPI**, mantendo o
PostgreSQL e o envio de mensagens pelo WhatsApp. A aplicação principal, as
regras de negócio, a autenticação e a interface estão em Python. O Baileys
continua em um serviço Node.js isolado porque a biblioteca Baileys é escrita
para o ecossistema JavaScript.

## O que está incluído

- Login e usuários com perfis `Admin`, `Prop`, `Aluno` e `Responsavel`.
- Compatibilidade com os hashes de senha do ASP.NET Core Identity v2/v3.
- Compatibilidade com os nomes das tabelas do projeto C# existente.
- Cadastro e edição de responsáveis, alunos e produtos.
- Vendas com itens, preços congelados e validação do limite mensal.
- Compras e relatório de limite, consumo e saldo por aluno.
- Menu WhatsApp visível somente para administradores ou usuários autorizados.
- Administração da permissão individual `PodeEnviarWhatsApp`.
- QR Code do Baileys visível apenas para administradores e atualizado
  automaticamente na tela.
- Envio para o telefone de um responsável ou para um número informado.
- Histórico de tentativas, sucessos, falhas e identificador da mensagem.
- CSRF nos formulários, sessão assinada e chave privada na comunicação interna.
- Dockerfiles, Docker Compose e testes automatizados.

## Arquitetura

```text
Navegador -> FastAPI (porta 8000) -> PostgreSQL
                       |
                       +-> serviço Baileys/Node (porta 3001) -> WhatsApp
```

O navegador nunca recebe a chave do serviço Baileys. Somente a aplicação
Python chama a API interna, usando o cabeçalho `X-API-Key`.

## Início rápido com Docker

Requisitos: Docker e Docker Compose.

1. Copie `.env.example` para `.env`.
2. Troque `SECRET_KEY`, `ADMIN_PASSWORD` e `WHATSAPP_API_KEY`.
3. Na raiz do projeto, execute:

   ```bash
   docker compose up --build
   ```

4. Acesse `http://localhost:8000`.
5. Entre com `ADMIN_EMAIL` e `ADMIN_PASSWORD`.
6. Abra **WhatsApp**, clique em **Conectar WhatsApp** e leia o QR Code no
   aplicativo: **Aparelhos conectados > Conectar aparelho**.

Após o primeiro acesso em um banco novo, remova `ADMIN_PASSWORD` do ambiente.
O usuário já terá sido gravado no banco.

## Execução sem Docker

Requisitos: Python 3.12+, Node.js 20+ e PostgreSQL.

Aplicação Python:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Serviço Baileys, em outro terminal:

```bash
cd whatsapp-service
npm ci
cp .env.example .env
npm start
```

Use a mesma URL do PostgreSQL nos dois arquivos `.env`. Use também o mesmo
valor em `WHATSAPP_API_KEY` (Python) e `BAILEYS_API_KEY` (Node).

## Reaproveitar o banco do projeto C#

Defina `DATABASE_URL` apontando para o mesmo PostgreSQL do aplicativo .NET. As
tabelas de domínio e de identidade usam os mesmos nomes e os logins existentes
podem ser verificados pelo Python. Antes de trocar o sistema em produção:

1. Faça um backup completo do banco.
2. Teste uma cópia em ambiente separado.
3. Confirme login, alunos, responsáveis, produtos e compras.
4. Execute somente uma versão do sistema durante o teste de gravação.

Na inicialização, a aplicação cria tabelas ausentes e adiciona
`PodeEnviarWhatsApp` caso a coluna ainda não exista. Administradores recebem a
permissão automaticamente.

## Perfis e permissão do WhatsApp

| Ação | Admin | Prop | Aluno/Responsável autorizado |
|---|---:|---:|---:|
| Gerenciar usuários | Sim | Aluno/Responsável | Não |
| Conceder WhatsApp | Sim | Não | Não |
| Gerar/ver QR Code | Sim | Não | Não |
| Enviar WhatsApp | Sim | Se autorizado | Se autorizado |
| Ver histórico | Todos os envios | Apenas os próprios | Apenas os próprios |

A proteção existe no menu e também no servidor; esconder o link não é a única
barreira.

## Testes

```bash
pytest
cd whatsapp-service
npm run check
```

## Variáveis principais

| Variável | Serviço | Finalidade |
|---|---|---|
| `DATABASE_URL` | ambos | PostgreSQL compartilhado |
| `SECRET_KEY` | Python | Assinatura das sessões |
| `ADMIN_EMAIL` | Python | Primeiro administrador |
| `ADMIN_PASSWORD` | Python | Senha usada apenas no primeiro cadastro |
| `WHATSAPP_SERVICE_URL` | Python | URL interna do serviço Node |
| `WHATSAPP_API_KEY` | Python | Chave da chamada interna |
| `BAILEYS_API_KEY` | Node | A mesma chave, para validar chamadas |
| `WHATSAPP_SESSION_ID` | Python | Identificador da conexão |

## Observação sobre o Baileys

O Baileys usa o protocolo do WhatsApp Web e não é a API oficial do WhatsApp.
Mudanças do WhatsApp podem exigir atualização do pacote e o uso automatizado
pode estar sujeito a restrições da plataforma. Para operações críticas ou alto
volume, avalie a WhatsApp Business Platform oficial.

