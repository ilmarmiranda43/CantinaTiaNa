import express from 'express';
import pino from 'pino';
import QRCodeImage from 'qrcode';
import QRCodeTerminal from 'qrcode-terminal';
import pg from 'pg';
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion
} from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import { usePostgresAuthState } from './auth_postgres.js';

const { Pool } = pg;
const app = express();
app.use(express.json({ limit: '1mb' }));

const PORT = Number(process.env.PORT || 3001);
const API_KEY = process.env.BAILEYS_API_KEY;
const DATABASE_URL = process.env.DATABASE_URL;
const QR_WAIT_TIMEOUT_MS =
  Number(process.env.QR_WAIT_TIMEOUT_MS || 12000);
const RECONNECT_DELAY_MS =
  Number(process.env.RECONNECT_DELAY_MS || 5000);

if (!API_KEY) {
  throw new Error('BAILEYS_API_KEY não configurada.');
}

if (!DATABASE_URL) {
  throw new Error('DATABASE_URL não configurada.');
}

const pool = new Pool({
  connectionString: DATABASE_URL,
  ssl: DATABASE_URL.includes('localhost')
    ? false
    : { rejectUnauthorized: false }
});

const sessoes = new Map();
const conexoesEmAndamento = new Map();
const timersReconexao = new Map();

let servidor;
let encerrando = false;

function autenticar(req, res, next) {
  if (req.get('X-API-Key') !== API_KEY) {
    return res.status(401).json({
      ok: false,
      erro: 'API key inválida.'
    });
  }

  next();
}

function validarSessionId(valor) {
  const sessionId = String(valor || '').trim();

  return /^[a-zA-Z0-9_-]{1,80}$/.test(sessionId)
    ? sessionId
    : null;
}

function normalizarTelefone(valor) {
  let telefone = String(valor || '').replace(/\D/g, '');

  if (telefone.length === 10 || telefone.length === 11) {
    telefone = `55${telefone}`;
  }

  return telefone;
}

async function garantirTabelas() {
  await pool.query(
    `CREATE TABLE IF NOT EXISTS cantina_whatsapp_sessoes (
       session_id VARCHAR(80) PRIMARY KEY,
       telefone VARCHAR(20),
       status VARCHAR(30) NOT NULL DEFAULT 'desconectado',
       conectado_em TIMESTAMPTZ,
       desconectado_em TIMESTAMPTZ,
       criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
     )`
  );

  await pool.query(
    `CREATE TABLE IF NOT EXISTS cantina_whatsapp_chaves (
       id BIGSERIAL PRIMARY KEY,
       session_id VARCHAR(80) NOT NULL,
       key_type VARCHAR(100) NOT NULL,
       key_id VARCHAR(255) NOT NULL,
       data JSONB NOT NULL,
       criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       CONSTRAINT uq_cantina_whatsapp_chave
         UNIQUE (session_id, key_type, key_id)
     )`
  );

  await pool.query(
    `CREATE INDEX IF NOT EXISTS
       idx_cantina_whatsapp_chaves_sessao
       ON cantina_whatsapp_chaves (session_id)`
  );
}

async function atualizarStatus(
  sessionId,
  status,
  telefone = null
) {
  await pool.query(
    `INSERT INTO cantina_whatsapp_sessoes
        (session_id, telefone, status)
     VALUES ($1, $2, $3)
     ON CONFLICT (session_id) DO UPDATE SET
       telefone = COALESCE(
         EXCLUDED.telefone,
         cantina_whatsapp_sessoes.telefone
       ),
       status = EXCLUDED.status,
       conectado_em = CASE
         WHEN EXCLUDED.status = 'conectado' THEN NOW()
         ELSE cantina_whatsapp_sessoes.conectado_em
       END,
       desconectado_em = CASE
         WHEN EXCLUDED.status = 'desconectado' THEN NOW()
         ELSE cantina_whatsapp_sessoes.desconectado_em
       END,
       atualizado_em = NOW()`,
    [sessionId, telefone, status]
  );
}

async function atualizarStatusSeguro(
  sessionId,
  status,
  telefone = null
) {
  try {
    await atualizarStatus(sessionId, status, telefone);
  } catch (erro) {
    console.error(
      `Falha ao atualizar o status de ${sessionId}:`,
      erro
    );
  }
}

async function limparCredenciais(sessionId) {
  await pool.query(
    `DELETE FROM cantina_whatsapp_chaves
      WHERE session_id = $1`,
    [sessionId]
  );
}

function cancelarReconexao(sessionId) {
  const timer = timersReconexao.get(sessionId);

  if (timer) {
    clearTimeout(timer);
    timersReconexao.delete(sessionId);
  }
}

function agendarReconexao(sessionId) {
  if (encerrando || timersReconexao.has(sessionId)) {
    return;
  }

  const timer = setTimeout(async () => {
    timersReconexao.delete(sessionId);

    try {
      await conectarSessao(sessionId);
    } catch (erro) {
      await atualizarStatusSeguro(sessionId, 'erro');
      console.error(
        `Erro ao reconectar ${sessionId}:`,
        erro
      );
    }
  }, RECONNECT_DELAY_MS);

  timersReconexao.set(sessionId, timer);
}

function codigoDesconexao(lastDisconnect) {
  const erro = lastDisconnect?.error;

  if (!erro) {
    return DisconnectReason.connectionClosed;
  }

  return (
    erro?.output?.statusCode ??
    new Boom(erro).output.statusCode
  );
}

function respostaSessao(sessionId, sessao) {
  const conectado =
    Boolean(sessao?.conectado) &&
    Boolean(sessao?.sock);
  const qrCode = sessao?.qrDataUrl || null;

  let status = sessao?.status || 'desconectado';

  if (conectado) {
    status = 'conectado';
  } else if (qrCode) {
    status = 'aguardando_qr';
  }

  return {
    ok: true,
    conectado,
    status,
    qr_code: qrCode,
    qrCode,
    sessao: {
      session_id: sessionId,
      telefone: sessao?.telefone || null,
      status
    }
  };
}

async function processarAtualizacao(
  sessionId,
  sessao,
  sock,
  { connection, lastDisconnect, qr }
) {
  if (qr) {
    sessao.conectado = false;
    sessao.status = 'aguardando_qr';
    sessao.qrDataUrl = await QRCodeImage.toDataURL(qr, {
      width: 350,
      margin: 2,
      errorCorrectionLevel: 'M'
    });

    await atualizarStatusSeguro(
      sessionId,
      'aguardando_qr'
    );

    console.log(`\nQR Code da sessão ${sessionId}:`);
    QRCodeTerminal.generate(qr, { small: true });
  }

  if (connection === 'open') {
    cancelarReconexao(sessionId);

    sessao.conectado = true;
    sessao.status = 'conectado';
    sessao.qrDataUrl = null;
    sessao.telefone =
      sock.user?.id?.split(':')[0]?.split('@')[0] ||
      null;

    await atualizarStatusSeguro(
      sessionId,
      'conectado',
      sessao.telefone
    );

    console.log(`Sessão ${sessionId}: conectada.`);
  }

  if (connection !== 'close') {
    return;
  }

  const codigo = codigoDesconexao(lastDisconnect);

  sessao.conectado = false;
  sessao.status = 'desconectado';
  sessao.qrDataUrl = null;

  await atualizarStatusSeguro(
    sessionId,
    'desconectado'
  );

  const credenciaisInvalidas = [
    DisconnectReason.loggedOut,
    DisconnectReason.badSession,
    DisconnectReason.multideviceMismatch,
    DisconnectReason.forbidden
  ].includes(codigo);

  if (credenciaisInvalidas) {
    cancelarReconexao(sessionId);
    sessao.status = 'conectando';
    sessao.descartada = true;
    let credenciaisRemovidas = false;

    try {
      await limparCredenciais(sessionId);
      credenciaisRemovidas = true;
    } catch (erro) {
      console.error(
        `Falha ao limpar credenciais de ${sessionId}:`,
        erro
      );
    }

    if (sessoes.get(sessionId) === sessao) {
      sessoes.delete(sessionId);
    }

    if (credenciaisRemovidas) {
      agendarReconexao(sessionId);
    } else {
      await atualizarStatusSeguro(sessionId, 'erro');
    }

    return;
  }

  if (sessoes.get(sessionId) === sessao) {
    sessoes.delete(sessionId);
  }

  if (codigo === DisconnectReason.connectionReplaced) {
    cancelarReconexao(sessionId);
    console.log(
      `Sessão ${sessionId}: substituída por outra instância.`
    );
    return;
  }

  agendarReconexao(sessionId);
}

async function conectarSessao(sessionId) {
  const atual = sessoes.get(sessionId);

  if (
    atual?.sock &&
    ['conectando', 'aguardando_qr', 'conectado']
      .includes(atual.status)
  ) {
    return atual;
  }

  if (conexoesEmAndamento.has(sessionId)) {
    return conexoesEmAndamento.get(sessionId);
  }

  cancelarReconexao(sessionId);

  const promessa = (async () => {
    await atualizarStatus(sessionId, 'conectando');

    const { state, saveCreds } =
      await usePostgresAuthState(pool, sessionId);
    const { version } =
      await fetchLatestBaileysVersion();

    const sessao = {
      sock: null,
      conectado: false,
      status: 'conectando',
      qrDataUrl: null,
      telefone: null,
      descartada: false
    };

    const sock = makeWASocket({
      version,
      auth: state,
      logger: pino({ level: 'silent' }),
      browser: ['Cantina Escolar', 'Chrome', '1.0.0'],
      markOnlineOnConnect: false,
      syncFullHistory: false
    });

    sessao.sock = sock;
    sessoes.set(sessionId, sessao);

    sock.ev.on('creds.update', () => {
      if (sessao.descartada) {
        return;
      }

      void saveCreds().catch((erro) => {
        console.error(
          `Falha ao salvar credenciais de ${sessionId}:`,
          erro
        );
      });
    });

    sock.ev.on('connection.update', (atualizacao) => {
      void processarAtualizacao(
        sessionId,
        sessao,
        sock,
        atualizacao
      ).catch(async (erro) => {
        sessao.status = 'erro';
        await atualizarStatusSeguro(sessionId, 'erro');
        console.error(
          `Erro na conexão ${sessionId}:`,
          erro
        );
      });
    });

    return sessao;
  })().catch(async (erro) => {
    sessoes.delete(sessionId);
    await atualizarStatusSeguro(sessionId, 'erro');
    throw erro;
  }).finally(() => {
    conexoesEmAndamento.delete(sessionId);
  });

  conexoesEmAndamento.set(sessionId, promessa);
  return promessa;
}

async function aguardarQrOuConexao(
  sessionId,
  timeoutMs = QR_WAIT_TIMEOUT_MS
) {
  const inicio = Date.now();

  while (Date.now() - inicio < timeoutMs) {
    const sessao = sessoes.get(sessionId);

    if (
      sessao?.conectado ||
      sessao?.qrDataUrl ||
      sessao?.status === 'erro'
    ) {
      return sessao;
    }

    await new Promise(
      (resolve) => setTimeout(resolve, 250)
    );
  }

  return sessoes.get(sessionId) || null;
}

async function aguardarConexao(
  sessionId,
  timeoutMs = 20000
) {
  const inicio = Date.now();

  while (Date.now() - inicio < timeoutMs) {
    const sessao = sessoes.get(sessionId);

    if (sessao?.conectado && sessao?.sock) {
      return sessao;
    }

    await new Promise(
      (resolve) => setTimeout(resolve, 500)
    );
  }

  return null;
}

app.get('/health', (_req, res) => {
  res.json({ ok: true });
});

app.get(
  '/sessions/:session_id/status',
  autenticar,
  async (req, res) => {
    const sessionId =
      validarSessionId(req.params.session_id);

    if (!sessionId) {
      return res.status(400).json({
        ok: false,
        erro: 'session_id inválido.'
      });
    }

    const runtime = respostaSessao(
      sessionId,
      sessoes.get(sessionId)
    );

    const resultado = await pool.query(
      `SELECT telefone, status, atualizado_em
         FROM cantina_whatsapp_sessoes
        WHERE session_id = $1`,
      [sessionId]
    );

    const banco = resultado.rows[0];

    if (!runtime.sessao.telefone && banco?.telefone) {
      runtime.sessao.telefone = banco.telefone;
    }

    runtime.status_banco = banco?.status || null;
    return res.json(runtime);
  }
);

app.post(
  '/sessions/:session_id/connect',
  autenticar,
  async (req, res) => {
    const sessionId =
      validarSessionId(req.params.session_id);

    if (!sessionId) {
      return res.status(400).json({
        ok: false,
        erro: 'session_id inválido.'
      });
    }

    await conectarSessao(sessionId);
    const sessao =
      await aguardarQrOuConexao(sessionId);
    const resposta =
      respostaSessao(sessionId, sessao);
    const pronto =
      resposta.conectado ||
      Boolean(resposta.qr_code);

    return res
      .status(pronto ? 200 : 202)
      .json(resposta);
  }
);

app.get(
  '/sessions/:session_id/qr',
  autenticar,
  async (req, res) => {
    const sessionId =
      validarSessionId(req.params.session_id);

    if (!sessionId) {
      return res.status(400).json({
        ok: false,
        erro: 'session_id inválido.'
      });
    }

    await conectarSessao(sessionId);
    const sessao =
      await aguardarQrOuConexao(sessionId);
    const resposta =
      respostaSessao(sessionId, sessao);
    const pronto =
      resposta.conectado ||
      Boolean(resposta.qr_code);

    return res
      .status(pronto ? 200 : 202)
      .json(resposta);
  }
);

app.post('/send', autenticar, async (req, res) => {
  const sessionId =
    validarSessionId(req.body.session_id);
  const telefone =
    normalizarTelefone(req.body.telefone);
  const mensagem =
    String(req.body.mensagem || '').trim();

  if (
    !sessionId ||
    telefone.length < 10 ||
    telefone.length > 15 ||
    !mensagem
  ) {
    return res.status(400).json({
      ok: false,
      erro:
        'session_id, telefone válido e mensagem são obrigatórios.'
    });
  }

  let sessao = sessoes.get(sessionId);

  if (!sessao?.conectado || !sessao?.sock) {
    await conectarSessao(sessionId);
    sessao = await aguardarConexao(sessionId);
  }

  if (!sessao?.conectado || !sessao?.sock) {
    return res.status(503).json({
      ok: false,
      erro:
        'O WhatsApp ainda não está conectado. Leia o QR Code.'
    });
  }

  const consultado = `${telefone}@s.whatsapp.net`;
  const contas =
    await sessao.sock.onWhatsApp(consultado);
  const conta =
    contas?.find((item) => item.exists);

  if (!conta) {
    return res.status(404).json({
      ok: false,
      erro: 'Número não encontrado no WhatsApp.'
    });
  }

  const envio = await sessao.sock.sendMessage(
    conta.jid,
    { text: mensagem }
  );

  return res.json({
    ok: true,
    session_id: sessionId,
    telefone,
    jid: conta.jid,
    message_id: envio?.key?.id || null
  });
});

app.use((erro, _req, res, next) => {
  console.error('Erro no serviço Baileys:', erro);

  if (res.headersSent) {
    return next(erro);
  }

  res.status(500).json({
    ok: false,
    erro:
      erro.message ||
      'Erro interno no serviço Baileys.'
  });
});

async function iniciarServico() {
  try {
    await garantirTabelas();

    await pool.query(
      `UPDATE cantina_whatsapp_sessoes
          SET status = 'desconectado',
              atualizado_em = NOW()
        WHERE status IN (
          'conectado',
          'conectando',
          'aguardando_qr'
        )`
    );

    const resultado = await pool.query(
      `SELECT DISTINCT session_id
         FROM cantina_whatsapp_chaves
        WHERE key_type = 'creds'
          AND key_id = 'creds'
        ORDER BY session_id`
    );

    servidor = app.listen(PORT, '0.0.0.0', () => {
      console.log(
        `Serviço Baileys disponível na porta ${PORT}.`
      );
    });

    for (const row of resultado.rows) {
      try {
        await conectarSessao(row.session_id);
      } catch (erro) {
        console.error(
          `Falha ao restaurar ${row.session_id}:`,
          erro
        );
      }
    }
  } catch (erro) {
    console.error(
      'Erro ao iniciar serviço Baileys:',
      erro
    );
    process.exitCode = 1;
  }
}

async function encerrarServico(sinal) {
  if (encerrando) {
    return;
  }

  encerrando = true;
  console.log(`Encerrando serviço (${sinal})...`);

  for (const sessionId of timersReconexao.keys()) {
    cancelarReconexao(sessionId);
  }

  const finalizar = async () => {
    try {
      await pool.end();
    } finally {
      process.exit(0);
    }
  };

  if (servidor) {
    servidor.close(() => {
      void finalizar();
    });
  } else {
    await finalizar();
  }
}

process.once('SIGTERM', () => {
  void encerrarServico('SIGTERM');
});

process.once('SIGINT', () => {
  void encerrarServico('SIGINT');
});

void iniciarServico();
