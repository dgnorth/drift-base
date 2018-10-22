from flask_restplus import fields, Model

player_statuses = ['active', 'disabled']
# {
#   "create_date": "2018-10-21T14:21:37.602518Z",
#   "is_online": false,
#   "logon_date": "2018-10-21T14:21:37.602518Z",
#   "modify_date": "2018-10-21T14:21:37.602518Z",
#   "num_logons": 0,
#   "player_id": 1,
#   "player_name": "",
#   "status": "active",
#   "user_id": 100000001,
#   "counter_url": "http://localhost:5000/players/1/counters",
#   "countertotals_url": "http://localhost:5000/players/1/countertotals",
#   "gamestates_url": "http://localhost:5000/players/1/gamestates",
#   "journal_url": "http://localhost:5000/players/1/journal",
#   "messagequeue_url": "http://localhost:5000/messages/messages/players/1/{queue}",
#   "messages_url": "http://localhost:5000/messages/messages/players/1",
#   "player_url": "http://localhost:5000/players/1",
#   "summary_url": "http://localhost:5000/players/1/summary",
#   "tickets_url": "http://localhost:5000/players/1/tickets",
#   "user_url": "http://localhost:5000/users/100000001"
# }

player_model = Model('Player', {
    'player_id': fields.Integer(description="Unique ID of the player"),
    'player_name': fields.String(description="Name of the player"),
    'user_id': fields.Integer(description="ID of the user that owns this player"),
    'is_online': fields.Boolean(description="Is the player currently online?"),
    'create_date': fields.DateTime(description="When the player was created"),
    'logon_date': fields.DateTime(description="When the player last authenticated"),
    'status': fields.String(enum=player_statuses, description="Current status of this player"),
    'player_url': fields.Url('player', absolute=True, description="URL of the player resource"),
    'counter_url': fields.Url('player_counters', absolute=True, description="URL of the countr resource"),
    'countertotals_url': fields.Url('player_countertotals', absolute=True, description="URL of the counter totals resource"),
    'gamestates_url': fields.Url('player_gamestates', absolute=True, description="URL of the gamestates resource"),
    'journal_url': fields.Url('player_journal', absolute=True, description="URL of the journal resource"),
    'messagequeue_url': fields.Url('messages_queue', absolute=True, description="URL of the message queue resource"),
    'messages_url': fields.Url('messages_exchange', absolute=True, description="URL of the messages resource"),
    'summary_url': fields.Url('player_summary', absolute=True, description="URL of the summary resource"),
    'tickets_url': fields.Url('player_tickets', absolute=True, description="URL of the tickets resource"),
    'user_url': fields.Url('user', absolute=True, description="URL of the user resource"),
})

client_descriptions = {
    'client_type': "Type of client as reported by the client itself. Example: UE4",
    'build': "Build/version information about the client executable",
    'version': "Version information about the client executable",
    'platform_type': "Name of the platform (e.g. Windows, IpadPro, etc)",
    'platform_version': "Version of the platform (e.g. Windows 10, etc)",
    'app_guid': "Globally nique name of the application",
    'platform_info': "Information about the platform in JSON format",
    'num_heartbeats': "Number of times a heartbeat has been sent on this session",
}
client_statuses = ['active', 'deleted', 'timeout', 'usurped']
client_model = Model('Client', {
    'client_id': fields.Integer(description="Unique ID of the client connection"),
    'client_type': fields.String(description=client_descriptions['client_type']),
    'user_id': fields.Integer(description="Unique ID of the user who owns this session (> 100000000)"),
    'player_id': fields.Integer(description="Unique ID of the player who owns this session"),
    'create_date': fields.DateTime(description="Timestamp when this session was created"),
    'modify_date': fields.DateTime(description="Timestamp when this session object was last modified"),
    'build': fields.String(description=client_descriptions['build']),
    'version': fields.String(description=client_descriptions['version']),
    'platform_type': fields.String(description=client_descriptions['platform_type']),
    'platform_version': fields.String(description=client_descriptions['platform_version']),
    'app_guid': fields.String(description=client_descriptions['app_guid']),
    'heartbeat': fields.DateTime(description="Last time the client sent a heartbeat on this session"),
    'num_heartbeats': fields.Integer(description=client_descriptions['num_heartbeats']),
    'ip_address': fields.String(description="IPv4 address of the client"),
    'num_requests': fields.Integer(description="Number of requests that have been sent to the drift-base app in this session"),
    'platform_info': fields.Raw(description=client_descriptions['platform_info']),
    'identity_id': fields.Integer(description="Unique ID of the identity associated with this connection"),
    'status': fields.String(enum=client_statuses, description="Current status of this client session"),
    'details': fields.Raw(description="Information about the status of the client session in JSON format"),
    'client_url': fields.Url('client', absolute=True,
                             description="Fully qualified url of the client resource"),
    'user_url': fields.Url('user', absolute=True,
                           description="Fully qualified url of the user resource"),
    'player_url': fields.Url('player', absolute=True,
                             description="Fully qualified url of the player resource")
})

client_registration_model = Model('ClientRegistration', {
    'client_id': fields.Integer(description="Unique ID of the client connection"),
    'user_id': fields.Integer(description="Unique ID of the user who owns this session (> 100000000)"),
    'player_id': fields.Integer(description="Unique ID of the player who owns this session"),
    'url': fields.Url(
        'client', absolute=True,
        description="Fully qualified url of the client resource"),
    'server_time': fields.DateTime(description="Current Server time UTC"),
    'next_heartbeat_seconds': fields.Integer(description="Number of seconds recommended for the client to heartbeat."),
    'heartbeat_timeout': fields.DateTime(description="Timestamp when the client will be removed if heartbeat has not been received"),
    'jti': fields.String(description="JTI lookup key of new JWT"),
    'jwt': fields.String(description="New JWT token that includes client information"),
})

client_heartbeat_model = Model('ClientHeartbeat', {
    "num_heartbeats": fields.Integer(description=client_descriptions['num_heartbeats']),
    "last_heartbeat": fields.DateTime(description="Timestamp of the previous heartbeat"),
    "this_heartbeat": fields.DateTime(description="Timestamp of this heartbeat"),
    "next_heartbeat": fields.DateTime(description="Timestamp when the next heartbeat is expected"),
    "next_heartbeat_seconds": fields.Integer(description="Number of seconds until the next heartbeat is expected"),
    "heartbeat_timeout": fields.DateTime(description="Timestamp when the client times out if no heartbeat is received"),
    "heartbeat_timeout_seconds": fields.Integer(description="Number of seconds until the client times out if no heartbeat is received"),
})
