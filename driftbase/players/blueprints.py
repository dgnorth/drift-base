# -*- coding: utf-8 -*-

import handlers
from counters import endpoints
from gamestate import endpoints as gs
from journal import endpoints as j
from playergroups import endpoints as pg
from summary import endpoints as summary
from tickets import endpoints as tickets


def register_blueprints(app):
    app.register_blueprint(handlers.bp)
    app.register_blueprint(endpoints.bp)
    app.register_blueprint(gs.bp)
    app.register_blueprint(j.bp)
    app.register_blueprint(pg.bp)
    app.register_blueprint(summary.bp)
    app.register_blueprint(tickets.bp)
