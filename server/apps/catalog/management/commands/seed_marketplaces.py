from django.core.management.base import BaseCommand

from apps.catalog.models import Marketplace

MARKETPLACES = [
    ("mercado_livre", "Mercado Livre", "live"),
    ("shopee", "Shopee", "live"),
    ("amazon", "Amazon", "live"),
    ("tiktok_shop", "TikTok Shop", "not_implemented"),
]


class Command(BaseCommand):
    help = "Seeds the marketplace registry (briefing §2 initial scope). Safe to re-run."

    def handle(self, *args, **options):
        for slug, name, status in MARKETPLACES:
            _, created = Marketplace.objects.update_or_create(
                slug=slug, defaults={"name": name, "integration_status": status}
            )
            self.stdout.write(f"{'created' if created else 'updated'}: {slug} ({status})")
