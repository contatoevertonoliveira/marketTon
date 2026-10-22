import React, { useEffect, useMemo, useState } from "react";
import { getJSON } from "../lib/apiClient";
import ProductCard from "./ProductCard";
import ProductCardModal from "./ProductCardModal";
import { approvalVerdict, demandComparator, opportunityComparator } from "../lib/productSignals";

// Produtos que o sistema coletou e analisou para este marketplace, ainda
// elegíveis para afiliação. Os já vinculados à conta aparecem marcados (e ficam
// na aba "Vinculados"); abrir um card leva ao "Afiliar-se a este produto".
export default function ProdutosSugeridos({ marketplace }) {
  const [products, setProducts] = useState(null);
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [sortMode, setSortMode] = useState("demand");
  const [onlyApproved, setOnlyApproved] = useState(false);
  const [selected, setSelected] = useState(null);

  function load() {
    Promise.all([
      getJSON(`/catalog/products?marketplace=${marketplace}&limit=100`),
      getJSON(`/portfolio/items?marketplace=${marketplace}&limit=500`),
    ])
      .then(([p, i]) => {
        setProducts(Array.isArray(p) ? p : p.items || []);
        setItems(Array.isArray(i) ? i : i.items || []);
        setError("");
      })
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    setProducts(null);
    load();
  }, [marketplace]); // eslint-disable-line react-hooks/exhaustive-deps

  const itemByProductId = useMemo(() => Object.fromEntries(items.map((i) => [i.product_id, i])), [items]);

  const list = useMemo(() => {
    const comparator = sortMode === "opportunity" ? opportunityComparator : demandComparator;
    return [...(products || [])]
      .filter((p) => !itemByProductId[p.id] || itemByProductId[p.id].state === "REMOVED")
      .filter((p) => !onlyApproved || approvalVerdict(p).approved)
      .sort(comparator);
  }, [products, itemByProductId, sortMode, onlyApproved]);

  if (error) return <p style={{ color: "#f5365c" }}>Não foi possível carregar os produtos sugeridos ({error}).</p>;
  if (products === null) return <p style={{ color: "#8898aa" }}>Carregando...</p>;

  const linkedCount = products.length - products.filter((p) => !itemByProductId[p.id] || itemByProductId[p.id].state === "REMOVED").length;

  return (
    <div>
      <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 12, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <span>
          {sortMode === "opportunity"
            ? "Menos afiliados primeiro (depois maior comissão); sem nº de afiliados informado, por demanda."
            : "Vendas reais primeiro; sem venda registrada, entra pela avaliação e pela velocidade de entrega."}
        </span>
        <select value={sortMode} onChange={(e) => setSortMode(e.target.value)} style={{ fontSize: 12 }}>
          <option value="demand">Ordenar: demanda</option>
          <option value="opportunity">Ordenar: menos afiliados</option>
        </select>
        <label style={{ display: "flex", gap: 4, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={onlyApproved} onChange={(e) => setOnlyApproved(e.target.checked)} />
          só os aprovados pelo sistema
        </label>
      </div>

      {list.length === 0 ? (
        <div style={{ background: "#fff", borderRadius: 10, padding: 20, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", fontSize: 13, color: "#8898aa" }}>
          {products.length === 0 ? (
            <>
              Nenhum produto no catálogo ainda para este marketplace. Rode <code>scripts/ingest.py --marketplace {marketplace}</code> para coletar.
            </>
          ) : onlyApproved ? (
            "Nenhum produto atende aos critérios de aprovação agora (precisa de 3 dos 4: demanda real, vendedor confiável, preço competitivo, comissão conhecida). Desmarque o filtro para ver todos."
          ) : (
            "Todos os produtos coletados já estão vinculados à sua conta — veja na aba Vinculados."
          )}
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 190px)", gap: 14 }}>
          {list.map((p) => (
            <ProductCard key={p.id} product={p} onClick={() => setSelected(p)} />
          ))}
        </div>
      )}
      {linkedCount > 0 && (
        <div style={{ fontSize: 11, color: "#8898aa", marginTop: 12 }}>
          {linkedCount} produto(s) já vinculado(s) não aparecem aqui — estão na aba Vinculados.
        </div>
      )}

      {selected && (
        <ProductCardModal
          product={selected}
          portfolioItem={itemByProductId[selected.id]}
          onClose={() => setSelected(null)}
          onChanged={load}
        />
      )}
    </div>
  );
}
