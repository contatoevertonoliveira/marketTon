from django.core.management.base import BaseCommand

from apps.catalog.ingestion import (
    ADAPTERS,
    CredentialsMissing,
    NotImplementedIngestion,
    upsert_product_from_amazon_item,
    upsert_product_from_ml_item,
    upsert_product_from_shopee_node,
)
from apps.scoring.services import recompute_scores

DEFAULT_KEYWORDS = [
    "fone bluetooth",
    "luminária led",
    "garrafa térmica",
    "lanterna tática",
]

UPSERTERS = {
    "mercado_livre": lambda raw, cred_values: upsert_product_from_ml_item(raw),
    "shopee": lambda raw, cred_values: upsert_product_from_shopee_node(raw),
    "amazon": lambda raw, cred_values: upsert_product_from_amazon_item(
        raw,
        associate_tag=cred_values.get("associate_tag", ""),
        marketplace_domain=cred_values.get("marketplace_domain", ""),
    ),
}


class Command(BaseCommand):
    help = (
        "Ingests real products from a marketplace's live API (credentials configured via the "
        "Integrações screen / MarketplaceCredential — see apps/catalog/credentials.py) and "
        "computes their initial scores. Never fabricates data: with no/invalid credentials the "
        "underlying call simply returns nothing."
    )

    def add_arguments(self, parser):
        parser.add_argument("--marketplace", type=str, default="all", help="mercado_livre|shopee|amazon|all")
        parser.add_argument("--keywords", type=str, default=",".join(DEFAULT_KEYWORDS))
        parser.add_argument("--limit", type=int, default=10)

    def handle(self, *args, **options):
        from apps.catalog.ingestion import get_credential

        keywords = [k.strip() for k in options["keywords"].split(",") if k.strip()]
        targets = list(ADAPTERS.keys()) if options["marketplace"] == "all" else [options["marketplace"]]

        total = 0
        for slug in targets:
            adapter = ADAPTERS.get(slug)
            if adapter is None:
                self.stdout.write(self.style.ERROR(f"{slug}: marketplace desconhecido"))
                continue
            try:
                items = adapter.discover(keywords=keywords, limit=options["limit"])
            except CredentialsMissing as exc:
                self.stdout.write(self.style.WARNING(f"{slug}: {exc}"))
                continue
            except NotImplementedIngestion as exc:
                self.stdout.write(self.style.WARNING(f"{slug}: {exc}"))
                continue

            if not items:
                self.stdout.write(self.style.WARNING(f"{slug}: nenhum item retornado pela API."))
                continue

            upsert = UPSERTERS.get(slug)
            if upsert is None:
                self.stdout.write(self.style.ERROR(f"{slug}: sem mapeamento de upsert"))
                continue
            cred = get_credential(slug)
            cred_values = cred.values if cred else {}

            count = 0
            for raw in items:
                product = upsert(raw, cred_values)
                recompute_scores(product)
                count += 1
            self.stdout.write(self.style.SUCCESS(f"{slug}: {count} produtos ingeridos e pontuados."))
            total += count

        if total == 0:
            self.stdout.write(self.style.WARNING("Nenhum produto ingerido em nenhum marketplace."))
