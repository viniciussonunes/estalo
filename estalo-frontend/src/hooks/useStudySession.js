import { useState, useCallback } from "react";

const VALIDADE_MS = 2 * 60 * 60 * 1000; // 2 horas

function chave(deckId) {
  return `session_snapshot_${deckId}`;
}

function lerSnapshot(deckId) {
  try {
    const raw = localStorage.getItem(chave(deckId));
    if (!raw) return null;
    const snap = JSON.parse(raw);
    if (!snap.timestamp || Date.now() - snap.timestamp > VALIDADE_MS) {
      localStorage.removeItem(chave(deckId));
      return null;
    }
    return snap;
  } catch {
    return null;
  }
}

/**
 * Persiste o progresso de uma sessão de estudo no localStorage, escopado por deck.
 * Ao montar, expõe `snapshotPendente` (não-nulo só na primeira leitura, se houver
 * um snapshot válido e recente) para a tela decidir se oferece "continuar de onde parou".
 */
export default function useStudySession(deckId) {
  const [snapshotPendente, setSnapshotPendente] = useState(() => lerSnapshot(deckId));

  const salvar = useCallback((dados) => {
    try {
      localStorage.setItem(chave(deckId), JSON.stringify({ ...dados, timestamp: Date.now() }));
    } catch {
      // localStorage indisponível (modo privado, quota cheia) — progresso só não persiste
    }
  }, [deckId]);

  const limpar = useCallback(() => {
    localStorage.removeItem(chave(deckId));
  }, [deckId]);

  const descartarPendente = useCallback(() => setSnapshotPendente(null), []);

  return { snapshotPendente, salvar, limpar, descartarPendente };
}
