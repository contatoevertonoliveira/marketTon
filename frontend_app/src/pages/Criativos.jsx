import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, deleteJSON, getJSON, getTokens, postJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };
const MODE = { sandbox: ["#eef0f6", "#525f7f", "teste (sandbox)"], live: ["#e5faf1", "#1a7a54", "ao vivo"] };
const STATUS = {
  requested: ["#fff4e5", "#b8720a", "pedido"], queued: ["#fff4e5", "#b8720a", "na fila"], planning: ["#eef2ff", "#3b4fb8", "planejando"],
  generating: ["#eef2ff", "#3b4fb8", "gerando"], assembling: ["#eef2ff", "#3b4fb8", "montando"], qa: ["#eef2ff", "#3b4fb8", "conferindo"],
  completed: ["#e5faf1", "#1a7a54", "pronto"], partial: ["#fff4e5", "#b8720a", "parcial"], failed: ["#fef1f4", "#c31e3f", "falhou"], canceled: ["#eef0f6", "#525f7f", "cancelado"],
};
const AD = { draft: ["#eef0f6", "#525f7f", "planejado"], paused: ["#fff4e5", "#b8720a", "pausado"], active: ["#e5faf1", "#1a7a54", "ativo"], ended: ["#eef0f6", "#525f7f", "encerrado"], failed: ["#fef1f4", "#c31e3f", "falhou"] };
const NET = { meta: "Meta", google: "Google" };
const brl = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
const usd = (v) => (v == null ? "—" : `US$ ${Number(v).toFixed(2)}`);
const num = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR"));
const pctTxt = (v) => (v == null ? "—" : `${String(v).replace(".", ",")}%`);
const when = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
const short = (t, n = 22) => (t && t.length > n ? `${t.slice(0, n - 1)}…` : t || "—");

function Chip({ map, k, fallback }) {
  const [bg, fg, label] = map[k] || ["#eef0f6", "#525f7f", fallback || k];
  return <span style={{ background: bg, color: fg, fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 9px", whiteSpace: "nowrap" }}>{label}</span>;
}

function Metric({ label, value, hint, big }) {
  return (
    <div title={hint}>
      <div style={{ fontSize: 10, color: "#8898aa", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: big ? 20 : 15, fontWeight: 700, color: "#32325d" }}>{value}</div>
    </div>
  );
}

// As peças ficam no AI Studio (rede interna): o marketTon as entrega, e o navegador as busca com o login.
function useBlob(path) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!path) return undefined;
    let revoke = null;
    let alive = true;
    fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${getTokens().access}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((b) => { revoke = URL.createObjectURL(b); if (alive) setUrl(revoke); })
      .catch(() => {});
    return () => { alive = false; if (revoke) URL.revokeObjectURL(revoke); };
  }, [path]);
  return url;
}

// Pré-visualização grande: clicar numa imagem abre; setas (ou botões) passam para as outras do mesmo criativo; Esc fecha.
function Preview({ pieces, index, onIndex, onClose }) {
  const d = pieces[index];
  const src = useBlob(d?.file);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") onIndex((index + 1) % pieces.length);
      else if (e.key === "ArrowLeft") onIndex((index - 1 + pieces.length) % pieces.length);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [index, pieces.length, onClose, onIndex]);
  if (!d) return null;
  const nav = { position: "absolute", top: "50%", transform: "translateY(-50%)", border: "none", background: "rgba(255,255,255,.9)", borderRadius: 999, width: 40, height: 40, fontSize: 20, cursor: "pointer" };
  return (
    <div onClick={onClose} role="dialog" aria-modal="true" aria-label="Pré-visualização da imagem"
      style={{ position: "fixed", inset: 0, background: "rgba(15,20,40,.86)", zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ position: "relative", maxWidth: "96vw", maxHeight: "94vh", display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
        {src ? <img src={src} alt="" style={{ maxWidth: "92vw", maxHeight: "84vh", objectFit: "contain", borderRadius: 8, background: "#fff" }} />
          : <div style={{ color: "#fff", padding: 60 }}>Carregando…</div>}
        <div style={{ color: "#fff", fontSize: 13, display: "flex", gap: 14, alignItems: "center" }}>
          <span>{d.aspect_ratio ? `Formato ${d.aspect_ratio}` : "Imagem"} · {index + 1} de {pieces.length}</span>
          {src && <a href={src} download={`criativo-${d.aspect_ratio || "imagem"}.png`} style={{ color: "#9fb4ff" }}>baixar</a>}
          <button onClick={onClose} style={{ border: "1px solid #fff", background: "transparent", color: "#fff", borderRadius: 6, padding: "2px 12px", cursor: "pointer" }}>fechar (Esc)</button>
        </div>
        {pieces.length > 1 && (<>
          <button aria-label="Anterior" onClick={() => onIndex((index - 1 + pieces.length) % pieces.length)} style={{ ...nav, left: -8 }}>‹</button>
          <button aria-label="Próxima" onClick={() => onIndex((index + 1) % pieces.length)} style={{ ...nav, right: -8 }}>›</button>
        </>)}
      </div>
    </div>
  );
}

function Piece({ d, onOpen }) {
  const src = useBlob(d.file);
  const box = { background: "#f6f9fc", borderRadius: 8, padding: 8, fontSize: 12, color: "#525f7f", maxWidth: 230 };
  if (d.kind === "video")
    return (
      <div style={box}>
        {src ? <video src={src} controls preload="none" style={{ width: "100%", borderRadius: 6, background: "#000" }} /> : null}
        <div style={{ marginTop: 4 }}>Vídeo {d.aspect_ratio} {d.duration_s ? `· ${d.duration_s}s` : ""} {d.variant ? `· gancho ${d.variant}` : ""}</div>
      </div>
    );
  if (d.kind === "image" || d.kind === "thumbnail")
    return (
      <div style={box}>
        {src ? <img src={src} alt="" title="Clique para ampliar" onClick={() => onOpen && onOpen(d)} style={{ width: "100%", borderRadius: 6, cursor: "zoom-in" }} /> : null}
        <div style={{ marginTop: 4 }}>{d.kind === "image" ? "Imagem" : "Miniatura"} {d.aspect_ratio}</div>
      </div>
    );
  if (d.kind === "copy") {
    const c = d.content || {};
    return (
      <div style={{ ...box, maxWidth: 320 }}>
        <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 4 }}>Texto {d.channel ? `· ${d.channel}` : ""}</div>
        {c.headline && <div><strong>{c.headline}</strong></div>}
        {c.caption && <div style={{ whiteSpace: "pre-wrap" }}>{c.caption}</div>}
        {c.hashtags && <div style={{ color: "#5e72e4" }}>{[].concat(c.hashtags).join(" ")}</div>}
      </div>
    );
  }
  return <div style={box}>{d.kind}{src ? <> · <a href={src} target="_blank" rel="noreferrer">abrir</a></> : null}</div>;
}

// Um anúncio (Meta) ou campanha (Google): números e os botões Ligar / Pausar / Parar / Excluir.
function AdPanel({ ad, onDone, onMsg }) {
  const [busy, setBusy] = useState(false);
  const net = NET[ad.platform] || ad.platform;
  const total = (ad.daily_budget_brl || 0) * (ad.duration_days || 1);
  async function run(label, fn, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true);
    try { await fn(); onMsg({ ok: true, text: `${label}: feito.` }); onDone(); } catch (e) { onMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }
  const big = (bg, color, border) => ({ border: border ? `1px solid ${border}` : "none", background: bg, color, borderRadius: 8, padding: "9px 22px", fontSize: 13, fontWeight: 800, cursor: busy ? "wait" : "pointer", opacity: busy ? 0.6 : 1 });
  const small = (color) => ({ border: `1px solid ${color}`, background: "#fff", color, borderRadius: 8, padding: "7px 14px", fontSize: 12, fontWeight: 700, cursor: busy ? "wait" : "pointer", opacity: busy ? 0.6 : 1 });
  const remote = ad.on_meta;
  const open = ["draft", "paused", "active"].includes(ad.status);
  return (
    <div style={{ border: "1px solid #eef0f6", borderRadius: 10, padding: 12, marginTop: 10, background: ad.status === "active" ? "#f4fcf8" : "#fbfcfe" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        <strong style={{ color: "#32325d", fontSize: 13 }}>{net}</strong>
        <Chip map={AD} k={ad.status} />
        {ad.variant && <span style={{ fontSize: 11, color: "#8898aa" }}>gancho {ad.variant}</span>}
        {ad.meta_status && !["PAUSED", "ACTIVE"].includes(ad.meta_status) && <span style={{ fontSize: 11, color: "#b8720a" }}>{net}: {ad.meta_status}</span>}
        {ad.notes && ad.platform === "google" && <span style={{ fontSize: 11, color: "#8898aa" }}>{ad.notes}</span>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(96px, 1fr))", gap: 12 }}>
        <Metric label="Gasto" value={brl(ad.spent_brl)} />
        <Metric label="Impressões" value={num(ad.impressions)} />
        <Metric label="Cliques" value={num(ad.clicks)} />
        <Metric label="CTR" value={pctTxt(ad.ctr_pct)} hint="Cliques ÷ impressões" />
        <Metric label="CPC" value={brl(ad.cpc_brl)} hint="Gasto ÷ cliques" />
        <Metric label="Verba/dia" value={brl(ad.daily_budget_brl)} hint={`${ad.duration_days || 1} dia(s): até ${brl(total)} no total`} />
        <Metric label="Início" value={when(ad.started_at)} />
        <Metric label="Métricas de" value={when(ad.last_metrics_at)} />
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 12 }}>
        {remote && (ad.status === "paused" || ad.status === "draft") && (
          <button disabled={busy} style={big("#2dce89", "#fff")}
            onClick={() => run("Ligar", () => postJSON(`/ads/${ad.id}/activate`), `LIGAR este anúncio no ${net}?\n\nEle começa a gastar até ${brl(ad.daily_budget_brl)} por dia, por ${ad.duration_days || 1} dia(s) (no máximo ${brl(total)} no total).`)}>
            ▶ Ligar
          </button>
        )}
        {remote && ad.status === "active" && (
          <button disabled={busy} style={big("#fb6340", "#fff")} onClick={() => run("Pausar", () => postJSON(`/ads/${ad.id}/pause`))}>⏸ Pausar</button>
        )}
        {remote && open && (
          <button disabled={busy} style={small("#8898aa")}
            onClick={() => run("Parar", () => postJSON(`/ads/${ad.id}/stop`), "PARAR de vez este anúncio?\n\nEle é pausado e encerrado: não dá mais para ligar de novo. As métricas continuam aqui.")}>
            ⏹ Parar
          </button>
        )}
        <button disabled={busy} style={small("#f5365c")}
          onClick={() => run("Excluir", () => deleteJSON(`/ads/${ad.id}`), `EXCLUIR este anúncio?\n\nEle é apagado no ${net} e some desta tela. O gasto já feito continua na sua conta de anúncios, mas deixa de aparecer aqui.`)}>
          🗑 Excluir
        </button>
        {!remote && ad.status !== "failed" && <span style={{ fontSize: 11, color: "#8898aa" }}>ainda não existe na rede de anúncios</span>}
      </div>
    </div>
  );
}

function ProductHead({ product, extra }) {
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
      <div style={{ width: 52, height: 52, borderRadius: 8, overflow: "hidden", background: "#f6f9fc", flex: "none" }}>
        {product?.image && <img src={product.image} alt="" referrerPolicy="no-referrer" style={{ width: "100%", height: "100%", objectFit: "cover" }} />}
      </div>
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14 }}>{product ? product.title : "Produto removido"}</div>
        <div style={{ fontSize: 11, color: "#8898aa" }}>{product ? `${product.marketplace} · ${brl(product.price)}` : ""}</div>
      </div>
      {extra}
    </div>
  );
}

// Anunciar na Meta com um post que VOCÊ publica na Página (a Meta recusa posts criados pelo app enquanto ele não está publicado).
function MetaPostPanel({ it, onDone, onMsg }) {
  const [open, setOpen] = useState(false);
  const [kit, setKit] = useState(null);
  const [posts, setPosts] = useState(null);
  const [pick, setPick] = useState("");
  const [daily, setDaily] = useState("10");
  const [days, setDays] = useState("3");
  const [busy, setBusy] = useState(false);
  const imgSrc = useBlob(open && kit ? kit.image_file : null);
  const copy = async (text, label) => { try { await navigator.clipboard.writeText(text); onMsg({ ok: true, text: `${label} copiado.` }); } catch { onMsg({ ok: false, text: "Não consegui copiar: selecione o texto e copie." }); } };

  async function openPanel() {
    setOpen(true);
    if (!kit) { try { setKit(await getJSON(`/ads/meta-post-kit/${it.id}`)); } catch (e) { onMsg({ ok: false, text: e.message }); } }
  }
  async function loadPosts() {
    setBusy(true);
    try { const r = await getJSON("/ads/page-posts?limit=10"); setPosts(r.posts); } catch (e) { onMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }
  async function create() {
    const d = Number(String(daily).replace(",", ".")), n = Number(days);
    if (!pick) return onMsg({ ok: false, text: "Escolha o post." });
    setBusy(true);
    try {
      const plan = await postJSON("/ads", { creative_id: it.id, daily_brl: d, days: n, dry_run: true, post_id: pick });
      if (!window.confirm(`Criar o anúncio PAUSADO na Meta com este post?\n\nVerba: ${brl(d)} por dia, ${n} dia(s) (até ${brl(d * n)}).\nDestino: ${plan.plan.link}\n\nNada gasta até você ligar.`)) return;
      await postJSON("/ads", { creative_id: it.id, daily_brl: d, days: n, dry_run: false, post_id: pick });
      onMsg({ ok: true, text: "Anúncio criado pausado. Ele aparece abaixo: ligue quando quiser." });
      setOpen(false);
      onDone();
    } catch (e) { onMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }

  const btn = { border: "1px solid #dee2e6", background: "#fff", borderRadius: 8, padding: "6px 12px", fontSize: 12, cursor: "pointer" };
  if (!open) return <button onClick={openPanel} style={{ ...btn, marginTop: 10, borderColor: "#5e72e4", color: "#5e72e4", fontWeight: 700 }}>📣 Anunciar com post da Página</button>;
  return (
    <div style={{ marginTop: 12, border: "1px solid #dfe4fb", background: "#f8f9ff", borderRadius: 10, padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ color: "#32325d", fontSize: 13 }}>Anunciar com um post da Página</strong>
        <button onClick={() => setOpen(false)} style={{ ...btn, padding: "2px 10px" }}>fechar</button>
      </div>
      <ol style={{ fontSize: 12, color: "#525f7f", margin: "8px 0", paddingLeft: 18 }}>
        <li>Publique na Página (Business Suite) com a imagem, o texto e o link abaixo. Cole o link no texto do post.</li>
        <li>Volte aqui, clique em “Buscar posts da Página” e escolha o post.</li>
        <li>Crie o anúncio: ele nasce pausado e você liga depois.</li>
      </ol>
      {kit && (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
          {imgSrc && <div><img src={imgSrc} alt="" style={{ width: 120, borderRadius: 8 }} /><div><a href={imgSrc} download={`post-${it.id}.png`} style={{ fontSize: 12 }}>baixar a imagem</a></div></div>}
          <div style={{ flex: 1, minWidth: 260, fontSize: 12, color: "#32325d" }}>
            <div style={{ fontWeight: 700 }}>{kit.headline}</div>
            <div style={{ whiteSpace: "pre-wrap", margin: "4px 0" }}>{kit.message}</div>
            <button style={btn} onClick={() => copy(`${kit.message}\n\n${kit.link}`, "Texto com o link")}>Copiar texto + link</button>{" "}
            <button style={btn} onClick={() => copy(kit.link, "Link")}>Copiar só o link</button>
            <div style={{ color: "#8898aa", marginTop: 4, wordBreak: "break-all" }}>{kit.link}</div>
          </div>
        </div>
      )}
      <div style={{ marginTop: 12 }}>
        <button style={btn} disabled={busy} onClick={loadPosts}>🔄 Buscar posts da Página</button>
        {posts && posts.length === 0 && <span style={{ fontSize: 12, color: "#8898aa", marginLeft: 8 }}>Nenhum post publicado encontrado.</span>}
        {posts && posts.map((p) => (
          <label key={p.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "6px 0", fontSize: 12, borderTop: "1px solid #eef0f6", marginTop: 6, cursor: "pointer" }}>
            <input type="radio" name={`post-${it.id}`} checked={pick === p.id} onChange={() => setPick(p.id)} />
            {p.image && <img src={p.image} alt="" referrerPolicy="no-referrer" style={{ width: 40, height: 40, objectFit: "cover", borderRadius: 6 }} />}
            <span style={{ flex: 1 }}><strong>{when(p.created_time)}</strong> · {short(p.message || "(sem texto)", 70)}<br /><span style={{ color: p.link && p.link.includes("/p/") ? "#1a7a54" : "#b8720a" }}>{p.link ? short(p.link, 60) : "sem link"}</span></span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
        <label style={{ fontSize: 12 }}>Verba/dia R$ <input value={daily} onChange={(e) => setDaily(e.target.value)} style={{ width: 64, padding: "4px 6px", border: "1px solid #dee2e6", borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12 }}>Dias <input value={days} onChange={(e) => setDays(e.target.value)} style={{ width: 44, padding: "4px 6px", border: "1px solid #dee2e6", borderRadius: 6 }} /></label>
        <button disabled={busy || !pick} onClick={create} style={{ border: "none", background: pick ? "#5e72e4" : "#adb5bd", color: "#fff", borderRadius: 8, padding: "8px 18px", fontSize: 13, fontWeight: 800, cursor: pick ? "pointer" : "default" }}>Criar anúncio pausado</button>
      </div>
    </div>
  );
}

// Slideshow vertical (15 a 20 s) das imagens do produto: gerar, ver, baixar (para pôr a música no app) e publicar como Reel.
function ReelBox({ it, caption, onMsg }) {
  const [v, setV] = useState(0);
  const [busy, setBusy] = useState("");
  const [info, setInfo] = useState(null);
  const src = useBlob(v > 0 ? `/social/reel/${it.id}/video?v=${v}` : null);
  async function build() {
    setBusy("build");
    try { const r = await postJSON(`/social/reel/${it.id}/build`); setInfo(r); setV((x) => x + 1); onMsg({ ok: true, text: `Slideshow pronto: ${r.slides} imagens, ${r.seconds} s.` }); }
    catch (e) { onMsg({ ok: false, text: e.message }); } finally { setBusy(""); }
  }
  async function publish() {
    if (!window.confirm("PUBLICAR este slideshow como REEL no Instagram do Mural?\n\nO vídeo sai SEM música (a API não deixa escolher). Para pôr música, baixe o vídeo e poste pelo app do Instagram.")) return;
    setBusy("pub");
    try { const r = await postJSON("/social/instagram/publish-reel", { creative_id: it.id, caption }); onMsg({ ok: true, text: `Reel publicado. ${r.permalink || ""}` }); }
    catch (e) { onMsg({ ok: false, text: e.message }); } finally { setBusy(""); }
  }
  const btn = { border: "1px solid #dee2e6", background: "#fff", borderRadius: 8, padding: "6px 12px", fontSize: 12, cursor: "pointer" };
  return (
    <div style={{ marginTop: 12, borderTop: "1px dashed #f3d6e6", paddingTop: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: "#32325d" }}>🎞️ Reel (slideshow de 10 a 15 s das imagens, sem custo de crédito)</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "8px 0" }}>
        <button style={btn} disabled={!!busy} onClick={build}>{busy === "build" ? "Montando…" : src ? "Montar de novo" : "Gerar slideshow"}</button>
        {src && <a href={src} download={`mural-reel-${it.id}.mp4`} style={{ ...btn, textDecoration: "none", color: "#525f7f" }}>⬇ Baixar vídeo</a>}
        {src && <button style={{ ...btn, background: "#c13584", color: "#fff", border: "none", fontWeight: 700 }} disabled={!!busy} onClick={publish}>{busy === "pub" ? "Publicando…" : "Publicar Reel agora"}</button>}
        {info && <span style={{ fontSize: 11, color: "#8898aa" }}>{info.slides} imagens · {info.seconds} s · {info.size_kb} KB</span>}
      </div>
      {src && <video src={src} controls style={{ width: 180, borderRadius: 10, background: "#000" }} />}
    </div>
  );
}

// Publicar a imagem do criativo no Instagram do Mural (só você publica; o agente só sugere o texto).
function InstagramPanel({ it, onMsg }) {
  const [open, setOpen] = useState(false);
  const [sug, setSug] = useState(null);
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const imgSrc = useBlob(open && sug ? sug.image_file : null);

  async function openPanel() {
    setOpen(true);
    if (!sug) {
      try { const r = await getJSON(`/social/instagram/caption/${it.id}`); setSug(r); setCaption(r.caption); } catch (e) { onMsg({ ok: false, text: e.message }); }
    }
  }
  async function publish() {
    if (!window.confirm("PUBLICAR agora no Instagram do Mural (@mural_na_web)?\n\nO post fica público na hora, com a imagem e o texto abaixo.")) return;
    setBusy(true);
    try {
      const r = await postJSON("/social/instagram/publish", { creative_id: it.id, caption, deliverable_id: sug.deliverable_id });
      setDone(r);
      onMsg({ ok: true, text: "Publicado no Instagram." });
    } catch (e) { onMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }

  const btn = { border: "1px solid #dee2e6", background: "#fff", borderRadius: 8, padding: "6px 12px", fontSize: 12, cursor: "pointer" };
  if (!open) return <button onClick={openPanel} style={{ ...btn, marginTop: 10, marginLeft: 8, borderColor: "#c13584", color: "#c13584", fontWeight: 700 }}>📸 Postar no Instagram</button>;
  return (
    <div style={{ marginTop: 12, border: "1px solid #f3d6e6", background: "#fff8fc", borderRadius: 10, padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ color: "#32325d", fontSize: 13 }}>Postar no Instagram (@mural_na_web)</strong>
        <button onClick={() => setOpen(false)} style={{ ...btn, padding: "2px 10px" }}>fechar</button>
      </div>
      {open && sug && <ReelBox it={it} caption={caption} onMsg={onMsg} />}
      {done ? (
        <div style={{ marginTop: 10, fontSize: 13, color: "#1a7a54" }}>✓ Publicado. {done.permalink ? <a href={done.permalink} target="_blank" rel="noreferrer">Abrir o post</a> : null}</div>
      ) : (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 10, alignItems: "flex-start" }}>
          {imgSrc ? <img src={imgSrc} alt="" style={{ width: 150, borderRadius: 8 }} /> : <div style={{ width: 150, fontSize: 12, color: "#8898aa" }}>Carregando a imagem…</div>}
          <div style={{ flex: 1, minWidth: 260 }}>
            <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={9} maxLength={2200}
              style={{ width: "100%", boxSizing: "border-box", fontSize: 12, padding: 8, border: "1px solid #dee2e6", borderRadius: 8, fontFamily: "inherit" }} />
            <div style={{ fontSize: 11, color: "#8898aa", margin: "4px 0 8px" }}>
              {caption.length} de 2200 caracteres. Legenda do Instagram não tem link clicável: o texto manda para o <strong>link da bio</strong>, que precisa ser o do Mural.
            </div>
            <button disabled={busy || !sug || !caption.trim()} onClick={publish}
              style={{ border: "none", background: "#c13584", color: "#fff", borderRadius: 8, padding: "9px 20px", fontSize: 13, fontWeight: 800, cursor: busy ? "wait" : "pointer" }}>
              {busy ? "Publicando…" : "Publicar agora"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Cartão do criativo de um produto: imagens, custo e, logo abaixo, os anúncios com números e botões.
function CreativeCard({ it, onDone, onMsg, onPreview }) {
  const p = it.product;
  const r = it.product_results;
  const [busy, setBusy] = useState(false);
  async function del() {
    if (!window.confirm("EXCLUIR este criativo da tela?\n\nEle some daqui (o histórico fica guardado). Só dá para excluir sem anúncio aberto.")) return;
    setBusy(true);
    try { await deleteJSON(`/creatives/${it.id}`); onMsg({ ok: true, text: "Criativo excluído." }); onDone(); } catch (e) { onMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }
  return (
    <div style={card}>
      <ProductHead product={p} extra={
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <Chip map={MODE} k={it.mode} />
          <Chip map={STATUS} k={it.status} />
          <Metric label="Custo do criativo" value={usd(it.cost_usd)} hint={`Teto: ${usd(it.budget_usd)}`} />
          <button disabled={busy} onClick={del} title="Excluir este criativo da tela" style={{ border: "1px solid #f5365c", background: "#fff", color: "#f5365c", borderRadius: 8, padding: "6px 12px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>🗑 Excluir criativo</button>
        </div>} />
      <div style={{ fontSize: 11, color: "#8898aa", margin: "6px 0 0" }}>
        criado {when(it.created_at)}{it.created_by ? ` por ${it.created_by}` : ""} · qualidade {it.quality}{it.angle ? ` · ângulo ${it.angle}` : ""} · {it.external_ref}
      </div>
      {it.error && <div style={{ marginTop: 10, fontSize: 12, padding: "7px 10px", borderRadius: 8, color: "#c31e3f", background: "#fef1f4" }}>{it.error}</div>}
      {it.deliverables.length > 0 && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
          {it.deliverables.map((d) => (
            <Piece key={d.id} d={d} onOpen={(piece) => {
              const imgs = it.deliverables.filter((x) => x.kind === "image" || x.kind === "thumbnail");
              onPreview(imgs, Math.max(0, imgs.findIndex((x) => x.id === piece.id)));
            }} />
          ))}
        </div>
      )}
      {it.mode === "live" && (it.status === "completed" || it.status === "partial") && <><MetaPostPanel it={it} onDone={onDone} onMsg={onMsg} /><InstagramPanel it={it} onMsg={onMsg} /></>}
      <div style={{ marginTop: 12, borderTop: "1px solid #f0f2f7", paddingTop: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#32325d" }}>Anúncios deste produto</div>
        {it.ads.length === 0
          ? <div style={{ fontSize: 12, color: "#8898aa", marginTop: 4 }}>Nenhum anúncio ainda. Quando o agente (ou você) criar o anúncio na Meta com este criativo, ele aparece aqui com os números e os botões.</div>
          : it.ads.map((a) => <AdPanel key={a.id} ad={a} onDone={onDone} onMsg={onMsg} />)}
      </div>
      {r && (
        <div style={{ marginTop: 12, display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-end", background: "#f6f9fc", borderRadius: 8, padding: "10px 12px" }}>
          <Metric label="Cliques na loja desde o criativo" value={num(r.store_clicks)} hint="Cliques de pessoas nos links curtos do produto (não de robôs)" />
          <Metric label="Vendas desde o criativo" value={num(r.sales)} />
          <Metric label="Comissão (confirmada ou estimada)" value={brl(r.commission_brl)} />
          <div style={{ fontSize: 11, color: "#8898aa", maxWidth: 360 }}>Resultado do produto no período, não atribuído a um anúncio: a venda de afiliado sai do marketplace dias depois.</div>
        </div>
      )}
    </div>
  );
}

// Campanha de pesquisa (Google): não tem imagem, então o cartão é o produto + os números e botões.
function AdCard({ ad, product, onDone, onMsg }) {
  return (
    <div style={card}>
      <ProductHead product={product} />
      <AdPanel ad={ad} onDone={onDone} onMsg={onMsg} />
    </div>
  );
}

function Empty({ children }) {
  return <div style={card}><span style={{ fontSize: 13, color: "#8898aa" }}>{children}</span></div>;
}

function sum(list, key) {
  return list.reduce((acc, a) => acc + (a[key] || 0), 0);
}

function Overview({ ads, totals, budget, onSync, onPauseAll }) {
  const spent = sum(ads, "spent_brl"), imps = sum(ads, "impressions"), clicks = sum(ads, "clicks");
  const active = ads.filter((a) => a.status === "active").length;
  const ctr = imps ? Math.round((clicks / imps) * 10000) / 100 : null;
  const cpc = clicks ? spent / clicks : null;
  const byNet = ["meta", "google"].map((n) => {
    const list = ads.filter((a) => a.platform === n);
    const c = sum(list, "clicks");
    return { net: n, count: list.length, active: list.filter((a) => a.status === "active").length, spent: sum(list, "spent_brl"), clicks: c, imps: sum(list, "impressions"), cpc: c ? sum(list, "spent_brl") / c : null };
  });
  const data = ads.map((a) => ({ label: `${short(a.product_title, 16)} · ${NET[a.platform] || a.platform}`, Gasto: Number((a.spent_brl || 0).toFixed(2)), Cliques: a.clicks || 0, Impressões: a.impressions || 0 }));
  return (
    <div>
      <div style={{ ...card, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 16 }}>
        <Metric big label="Gasto em anúncios" value={brl(spent)} />
        <Metric big label="Impressões" value={num(imps)} />
        <Metric big label="Cliques" value={num(clicks)} />
        <Metric big label="CTR" value={pctTxt(ctr)} />
        <Metric big label="CPC médio" value={brl(cpc)} />
        <Metric big label="Anúncios ativos" value={`${active} de ${ads.length}`} />
        <Metric big label="Gasto em criativos" value={usd(totals.cost_usd)} hint="Custo das gerações no AI Studio (só o modo ao vivo gasta)" />
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginBottom: 10 }}>
        <button onClick={onSync} style={{ border: "1px solid #dee2e6", background: "#fff", borderRadius: 8, padding: "7px 14px", fontSize: 12, cursor: "pointer" }}>Atualizar métricas</button>
        <button onClick={onPauseAll} style={{ border: "none", background: "#f5365c", color: "#fff", borderRadius: 8, padding: "7px 14px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>Pausar tudo (Meta e Google)</button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
        {["meta", "google"].map((n) => {
          const b = budget ? budget[n] : null;
          return (
            <div key={n} style={card}>
              <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 8 }}>Orçamento {NET[n]}</div>
              {b && b.configured ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 12 }}>
                  <Metric label="Semana" value={`${brl(b.week_committed_brl)} de ${brl(b.weekly_brl)}`} hint="Compromisso: verba por dia × dias das campanhas criadas nesta semana" />
                  <Metric label="Por dia agora" value={`${brl(b.daily_committed_brl)} de ${brl(b.daily_cap_brl)}`} hint="Campanhas abertas (planejadas, pausadas ou ativas)" />
                  <Metric label="Produtos" value={`${b.week_products} de ${b.max_products}`} />
                  <Metric label="Gasto lido (semana)" value={brl(b.week_spent_brl)} />
                </div>
              ) : budget ? (
                <div style={{ fontSize: 12, color: "#b8720a" }}>Sem orçamento do {NET[n]}. Preencha os campos {NET[n].toUpperCase()} do cartão Orçamento de anúncios em Integrações: o agente só cria campanha na rede com orçamento próprio.</div>
              ) : null}
            </div>
          );
        })}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
        {byNet.map((n) => (
          <div key={n.net} style={card}>
            <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 8 }}>{NET[n.net]}</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
              <Metric label="Campanhas" value={`${n.active} ativas de ${n.count}`} />
              <Metric label="Gasto" value={brl(n.spent)} />
              <Metric label="Cliques" value={num(n.clicks)} />
              <Metric label="Impressões" value={num(n.imps)} />
              <Metric label="CPC" value={brl(n.cpc)} />
            </div>
          </div>
        ))}
      </div>
      {data.length === 0 ? <Empty>Sem anúncios ainda. Quando houver, os gráficos de gasto, cliques e impressões por campanha aparecem aqui.</Empty> : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
          {[["Gasto por campanha (R$)", "Gasto", "#fb6340"], ["Cliques por campanha", "Cliques", "#5e72e4"], ["Impressões por campanha", "Impressões", "#2dce89"]].map(([title, key, color]) => (
            <div key={key} style={card}>
              <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 6 }}>{title}</div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={64} />
                  <YAxis tick={{ fontSize: 11 }} width={44} allowDecimals={key === "Gasto"} />
                  <Tooltip formatter={(v) => (key === "Gasto" ? brl(v) : num(v))} />
                  <Bar dataKey={key} fill={color} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const TABS = [["geral", "Visão geral"], ["live", "Ao vivo"], ["meta", "Meta Ads"], ["google", "Google (pesquisa)"], ["testes", "Testes"]];

export default function Criativos() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [budget, setBudget] = useState(null);
  const [msg, setMsg] = useState(null);
  const [preview, setPreview] = useState(null);
  const [tab, setTab] = useState(() => { try { return localStorage.getItem("criativos_tab") || "geral"; } catch { return "geral"; } });
  const pick = (k) => { setTab(k); try { localStorage.setItem("criativos_tab", k); } catch { /* sem armazenamento: segue sem lembrar a aba */ } };

  const load = useCallback(() => getJSON("/creatives/history?limit=100").then((d) => { setData(d); setError(""); }).catch((e) => setError(e.message)), []);
  const loadAll = useCallback(() => { load(); getJSON("/ads/budget").then(setBudget).catch(() => {}); }, [load]);
  useEffect(() => { loadAll(); const id = setInterval(load, 30000); return () => clearInterval(id); }, [loadAll, load]);

  async function pauseAll() {
    if (!window.confirm("PAUSAR todos os anúncios ativos agora (Meta e Google)?")) return;
    try { const r = await postJSON("/ads/pause-all"); setMsg({ ok: true, text: `${r.paused} anúncio(s) pausado(s).` }); loadAll(); } catch (e) { setMsg({ ok: false, text: e.message }); }
  }
  async function syncNow() {
    try { const r = await postJSON("/ads/sync"); setMsg({ ok: true, text: `Métricas atualizadas em ${r.updated} anúncio(s).` }); loadAll(); } catch (e) { setMsg({ ok: false, text: e.message }); }
  }

  const items = data?.items || [];
  const liveItems = useMemo(() => items.filter((i) => i.mode === "live"), [items]);
  const testItems = useMemo(() => items.filter((i) => i.mode !== "live"), [items]);
  const metaAds = useMemo(() => items.flatMap((it) => it.ads.filter((a) => a.platform === "meta").map((a) => ({ ad: a, product: it.product }))), [items]);
  const googleAds = useMemo(() => (data?.search_ads || []).map((a) => ({ ad: a, product: a.product })), [data]);
  const allAds = useMemo(() => [...metaAds, ...googleAds].map(({ ad, product }) => ({ ...ad, product_title: product?.title })), [metaAds, googleAds]);
  const counts = { live: liveItems.length, meta: metaAds.length, google: googleAds.length, testes: testItems.length };

  if (error && !data) return <p style={{ color: "#f5365c" }}>Não foi possível carregar os criativos ({error}).</p>;
  if (!data) return <p style={{ color: "#8898aa" }}>Carregando…</p>;
  const onPreview = (pieces, index) => setPreview({ pieces, index });

  return (
    <div>
      {preview && <Preview pieces={preview.pieces} index={preview.index} onIndex={(i) => setPreview({ ...preview, index: i })} onClose={() => setPreview(null)} />}
      <div role="tablist" style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14, borderBottom: "1px solid #e9ecef", paddingBottom: 8 }}>
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => pick(k)}
            style={{ border: "none", borderRadius: 8, padding: "7px 16px", fontSize: 13, fontWeight: 700, cursor: "pointer", background: tab === k ? "#5e72e4" : "#eef0f6", color: tab === k ? "#fff" : "#525f7f" }}>
            {label}{counts[k] != null ? <span style={{ marginLeft: 6, opacity: 0.8, fontWeight: 600 }}>{counts[k]}</span> : null}
          </button>
        ))}
      </div>
      {msg && <div style={{ marginBottom: 12, fontSize: 12, padding: "8px 10px", borderRadius: 8, color: msg.ok ? "#1a7a54" : "#c31e3f", background: msg.ok ? "#e5faf1" : "#fef1f4" }}>{msg.text}</div>}

      {tab === "geral" && <Overview ads={allAds} totals={data.totals} budget={budget} onSync={syncNow} onPauseAll={pauseAll} />}

      {tab === "live" && (liveItems.length === 0
        ? <Empty>Nenhum criativo ao vivo ainda. Quando o agente (ou você) pedir criativos de verdade ao AI Studio, eles aparecem aqui com as imagens, os anúncios e os botões.</Empty>
        : liveItems.map((it) => <CreativeCard key={it.id} it={it} onDone={loadAll} onMsg={setMsg} onPreview={onPreview} />))}

      {tab === "meta" && (metaAds.length === 0
        ? <Empty>Nenhum anúncio na Meta ainda. O agente cria o anúncio (pausado) a partir de um criativo ao vivo; você liga aqui.</Empty>
        : metaAds.map(({ ad, product }) => <AdCard key={ad.id} ad={ad} product={product} onDone={loadAll} onMsg={setMsg} />))}

      {tab === "google" && (googleAds.length === 0
        ? <Empty>Nenhuma campanha de pesquisa no Google ainda. O agente cria a campanha (pausada) de um produto; você liga aqui.</Empty>
        : googleAds.map(({ ad, product }) => <AdCard key={ad.id} ad={ad} product={product} onDone={loadAll} onMsg={setMsg} />))}

      {tab === "testes" && (testItems.length === 0
        ? <Empty>Nenhum teste. Criativos de teste (sandbox) não gastam crédito e nunca viram anúncio de verdade.</Empty>
        : testItems.map((it) => <CreativeCard key={it.id} it={it} onDone={loadAll} onMsg={setMsg} onPreview={onPreview} />))}
    </div>
  );
}
