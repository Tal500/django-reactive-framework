A minimalistic reactive framework for Django Templates.

This project brings Svelete-like thinking for Django Templates.
The computation starts at the backend and continues in the frontend.

This project is licensed under the MIT License.

This project is experimental and under development.

# Installation
You can install this package by two ways:

* The easy way - Type the following to a command line:

        pip install --upgrade https://github.com/Tal500/django-reactive-framework/archive/master.zip

* The deep way (for internal development):
    1. Clone the package:

            git clone https://github.com/Tal500/django-reactive-framework.git
    
    2. Add the path for the repository directory `src` to your system PYTHONPATH.
    This way, the python package, which is in `src/django_reactive`, will be visible.

Kepp in mind that this package is still under development.

# Example

You can start see an example by either one of these three methods:

* (Recomended) Browse the live example in Heroko (might take time to wake up):
https://django-reactive-example.herokuapp.com
* Starting the example server:
    1. Open the command line in the root directory and execute the following:

            python example/manage.py runserver

        You may ignore the following migration warning, since we don't use database at all:

            You have 18 unapplied migration(s). Your project may not work properly until you apply the migrations for app(s): admin, auth, contenttypes, sessions.
            Run 'python manage.py migrate' to apply them.
        
    2. Open your browser and browse to:

            http://127.0.0.1:8000/

* Import the example urls to your server (listed in `src/django_reactive_framework/urls.py`):
    1. Add the following patterns to yout urls.py:

            urlpatterns += [
                path('reactive_example/', include('django_reactive_framework.urls'))
            ]

    2. Then, the example will be in the path `reactive_example/example/` in your server.

Look more at `src/django_reactive/templates/reactive_example.html` for the source of the example.

# Communication

For any communication you may start a discussion or report an issue in the GitHub page:

https://github.com/Tal500/django-reactive-framework
