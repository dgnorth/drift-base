# -*- coding: utf-8 -*-
import handlers


def register_blueprints(app):
    app.register_blueprint(handlers.bp)
