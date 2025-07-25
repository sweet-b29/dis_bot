from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PlayerViewSet, PlayerBanViewSet

router = DefaultRouter()
router.register(r'players', PlayerViewSet, basename='players')
router.register(r'bans', PlayerBanViewSet, basename='ban')

urlpatterns = [
    path('', include(router.urls)),
]
