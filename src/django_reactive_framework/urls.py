from django.urls import path
from django.views.generic import TemplateView

urlpatterns = [
    path('example/',
        TemplateView.as_view(template_name='reactive_example.html', extra_context={
            'example_list': ['Apple', 'Orange', 'Banana'],
            'float_binary_operation_symbols': [
                {'key': 'add', 'value': '+'},
                {'key': 'substruct', 'value': '-'},
                {'key': 'multiply', 'value': '*'},
                {'key': 'divide', 'value': '/'},
            ]
            })),
]