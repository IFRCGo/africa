from django.urls import path

from insights import views

urlpatterns = [
    path("insights/", views.insights, name="insights-list"),
]
