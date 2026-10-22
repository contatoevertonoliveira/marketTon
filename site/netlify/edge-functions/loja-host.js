// O endereço da loja (mural.felixsystems.com.br) abre a pasta /loja/ do mesmo site. Em qualquer outro endereço nada muda.
// Funções da API (/api/...) e links curtos (/r/...) passam direto.
const LOJA_HOSTS = new Set(["mural.felixsystems.com.br", "loja.felixsystems.com.br"]);

export default async (request, context) => {
  const url = new URL(request.url);
  if (!LOJA_HOSTS.has(url.hostname)) return context.next();
  const path = url.pathname;
  if (path.startsWith("/api/") || path.startsWith("/r/") || path.startsWith("/loja/")) return context.next();
  return context.rewrite(`/loja${path === "/" ? "/" : path}`);
};

export const config = { path: "/*" };
