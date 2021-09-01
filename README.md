A minimalistic reactive framework for Django Templates.

This project brings Svelete-like thinking for Django Templates.
The computation starts at the backend and continues in the frontend.

This project is licensed under the MIT License.

This project is experimental and under development.

# Example

You may see example usage by adding the following to urlpatterns (listed in src/django_reactive/urls.py):

    urlpatterns += [
        path('reactive_example/', include('django_reactive.urls'))
    ]

By starting a new django project or importing it to existing one.

Then, you may open the following path for an example:
    reactive_example/example/

Look more at src/django_reactive/example/reactive_example.html for its source.

# Communication

For any communication you may start a discussion or report an issue in the GitHub page:
https://github.com/Tal500/django-reactive