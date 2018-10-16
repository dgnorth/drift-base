from flask_restplus import fields, Model

user_links_model = Model('UserLinks', {
    'self': fields.Url('.users_user', absolute=True,
                       description="Fully qualified url of the user resource")
})
