# -*- coding: utf-8 -*-

from . import handlers


def register_blueprints(app):
    app.register_blueprint(handlers.bp)
    app.messagebus.register_consumer(handlers.on_message, 'clients')