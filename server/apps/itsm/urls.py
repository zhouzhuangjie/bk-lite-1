from rest_framework.routers import DefaultRouter

from apps.itsm.views import CatalogViewSet, ServiceViewSet, TaskViewSet, TicketViewSet

router = DefaultRouter()
router.register(r"api/services", ServiceViewSet, basename="itsm-service")
router.register(r"api/catalog", CatalogViewSet, basename="itsm-catalog")
router.register(r"api/tickets", TicketViewSet, basename="itsm-ticket")
router.register(r"api/tasks", TaskViewSet, basename="itsm-task")

urlpatterns = router.urls
