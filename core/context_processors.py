from django.conf import settings

def marketplace_context(request):
    return {
        'MARKETPLACE_TITLE': getattr(settings, 'MARKETPLACE_TITLE', 'GraphRAG Marketplace')
    }
