import {
  BufferJSON,
  initAuthCreds,
  proto
} from '@whiskeysockets/baileys';

function serializar(valor) {
  return JSON.stringify(valor, BufferJSON.replacer);
}

function desserializar(valor) {
  if (valor === null || valor === undefined) {
    return null;
  }

  const texto =
    typeof valor === 'string'
      ? valor
      : JSON.stringify(valor);

  return JSON.parse(texto, BufferJSON.reviver);
}

export async function usePostgresAuthState(pool, sessionId) {
  const ler = async (keyType, keyId) => {
    const resultado = await pool.query(
      `SELECT data
         FROM cantina_whatsapp_chaves
        WHERE session_id = $1
          AND key_type = $2
          AND key_id = $3`,
      [sessionId, keyType, keyId]
    );

    return resultado.rowCount
      ? desserializar(resultado.rows[0].data)
      : null;
  };

  const gravar = async (keyType, keyId, valor) => {
    if (valor === null || valor === undefined) {
      await pool.query(
        `DELETE FROM cantina_whatsapp_chaves
          WHERE session_id = $1
            AND key_type = $2
            AND key_id = $3`,
        [sessionId, keyType, keyId]
      );
      return;
    }

    await pool.query(
      `INSERT INTO cantina_whatsapp_chaves
          (session_id, key_type, key_id, data)
       VALUES ($1, $2, $3, $4::jsonb)
       ON CONFLICT (session_id, key_type, key_id)
       DO UPDATE SET
          data = EXCLUDED.data,
          atualizado_em = NOW()`,
      [sessionId, keyType, keyId, serializar(valor)]
    );
  };

  const creds =
    (await ler('creds', 'creds')) ||
    initAuthCreds();

  return {
    state: {
      creds,
      keys: {
        get: async (type, ids) => {
          const dados = {};

          for (const id of ids) {
            let valor = await ler(type, id);

            if (type === 'app-state-sync-key' && valor) {
              valor =
                proto.Message.AppStateSyncKeyData.fromObject(valor);
            }

            dados[id] = valor;
          }

          return dados;
        },
        set: async (data) => {
          for (const [type, valores] of Object.entries(data)) {
            for (const [id, valor] of Object.entries(valores)) {
              await gravar(type, id, valor);
            }
          }
        }
      }
    },
    saveCreds: async () =>
      gravar('creds', 'creds', creds)
  };
}
