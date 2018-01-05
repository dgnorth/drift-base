# -*- coding: utf-8 -*-

import handlers


def register_blueprints(app):
    app.register_blueprint(handlers.bp)
    app.messagebus.register_consumer(handlers.on_message, 'clients')