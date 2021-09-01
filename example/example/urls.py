"""example URL Configuration"""

from django.conf.urls import include
from django.views.generic.base import RedirectView
from django.urls import path

urlpatterns = [
    path('', RedirectView.as_view(permanent=False, url='/example')),
    path('', include('django_reactive.urls')),
]
