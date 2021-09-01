A minimalistic reactive framework for Django Templates.

This project brings Svelete-like thinking for Django Templates.
The computation starts at the backend and continues in the frontend.

This project is licensed under the MIT License.

This project is experimental and under development.

# Installation
You can install this package by two ways:

*. The easy way - Type the following to a command line:
    pip install --upgrade git+git://github.com/Tal500/django-reactive.git
*. The deep way (for internal development):
    1. Clone the package:
        git clone https://github.com/Tal500/rsvp-web.git
    2. Add the path for the repository directory 'src' to your system PYTHONPATH.
    This way, the python package, which is in src/django_reactive, will be visible.

Kepp in mind that this package is still under development.

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