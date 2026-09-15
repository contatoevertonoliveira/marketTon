import React, { useEffect, useState } from "react";
import { getJSON, postJSON } from "../lib/intelApi";

const LABELS = {
  copy: "Copy",
  image: "Imagens",
  video: "Vídeo",
  voice: "Voz / narração",
  edit: "Edição",
  approval: "Aprovação",
  publication: "Publicação",
};

const ORDER = ["copy", "image", "video", "voice", "edit", "approval", "publication"];

const statusColor = { PENDING: "#f6c944", READY: "#2dce89", BLOCKED: "#8898aa" };

export function CreativeChecklist({ portfolioItemId }) {
  const [assets, setAssets] = useState([]);
  const [busy, setBusy] = useState("");

  function load() {
    if (!portfolioItemId) return;
    getJSON(`/creative/?portfolio_item=${portfolioItemId}`).then((data) =>
      setAssets((data.results || []).sort((a, b) => ORDER.indexOf(a.asset_type) - ORDER.indexOf(b.asset_type)))
    );
  }

  useEffect(load, [portfolioItemId]);

  async function toggle(asset) {
    if (asset.asset_type === "publication") return; // derived, not manual
    setBusy(asset.asset_type);
    const next = asset.status === "READY" ? "PENDING" : "READY";
    try {
      await postJSON(`/creative/${asset.id}/status/`, { status: next });
      load();
    } catch (e) {
      // eslint-disable-next-line no-alert
      alert(`Falha ao atualizar: ${e.message}`);
    } finally {
      setBusy("");
    }
  }

  if (!portfolioItemId) return null;

  return (
    <div>
      <h6 style={{ color: "#32325d", marginTop: 12 }}>Pipeline de criativos</h6>
      <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
        {assets.map((a) => (
          <label
            key={a.asset_type}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 10px",
              borderRadius: 8,
              background: "#f6f9fc",
              cursor: a.asset_type === "publication" ? "default" : "pointer",
              opacity: busy === a.asset_type ? 0.6 : 1,
            }}
          >
            <input
              type="checkbox"
              checked={a.status === "READY"}
              disabled={a.asset_type === "publication" || busy === a.asset_type}
              onChange={() => toggle(a)}
            />
            <span style={{ flex: 1, color: "#32325d", fontSize: 13 }}>{LABELS[a.asset_type] || a.asset_type}</span>
            <span
              style={{
                fontSize: 11,
                color: "#fff",
                background: statusColor[a.status] || "#8898aa",
                borderRadius: 999,
                padding: "2px 8px",
              }}
            >
              {a.status}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
