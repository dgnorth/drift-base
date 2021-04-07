import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Unicode,
    ForeignKey,
    BigInteger,
    Float,
    Boolean,
)
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import ENUM, INET, JSON
from sqlalchemy.schema import Sequence, Index
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import DDL, event

from werkzeug.security import generate_password_hash, check_password_hash

from flask import current_app

from drift.orm import ModelBase, utc_now, Base

DEFAULT_HEARTBEAT_PERIOD = 30
DEFAULT_HEARTBEAT_TIMEOUT = 300


def utcnow():
    return datetime.datetime.utcnow()


class User(ModelBase):
    __tablename__ = "ck_users"

    user_id = Column("user_id", Integer, primary_key=True)
    user_name = Column(Unicode(200))
    provider = Column(String(50), doc="Identity provider")
    default_player_id = Column("default_player_id", Integer)
    create_date = Column(
        "create_date",
        DateTime,
        nullable=False,
        server_default=utc_now,
        doc="Timestamp when the user was created",
    )
    logon_date = Column(
        "logon_date",
        DateTime,
        nullable=False,
        server_default=utc_now,
        doc="Timestamp when the user last authenticated",
    )
    num_logons = Column(
        "num_logons",
        Integer,
        default=0,
        doc="Number of times the user has authenticated",
    )

    players = relationship(
        "CorePlayer", backref="user", doc="Players that this user owns"
    )
    status = Column(
        String(20),
        nullable=True,
        default="active",
        doc="Is the user active or disabled",
    )
    client_id = Column(
        BigInteger,
        nullable=True,
        doc="The last client that the user had when logged in.",
    )

    roles = relationship("UserRole", backref="user")
    clients = relationship("Client", lazy="dynamic", backref="user")

    @hybrid_property
    def client(self):
        return self.clients.filter(Client.client_id == self.client_id).first()


class UserRole(ModelBase):
    __tablename__ = "ck_userroles"
    role_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("ck_users.user_id", ondelete="CASCADE"))
    role = Column(String(20), nullable=False)


class UserIdentity(ModelBase):
    __tablename__ = "ck_user_identities"

    identity_id = Column(Integer, primary_key=True)
    name = Column(String(200), index=True)
    identity_type = Column(String(50), index=True)
    password_hash = Column(String(200))
    user_id = Column(Integer, ForeignKey("ck_users.user_id"), index=True)
    extra_info = Column(JSON, nullable=True)

    logon_date = Column("logon_date", DateTime, nullable=False, server_default=utc_now)
    num_logons = Column("num_logons", Integer, default=0)
    last_ip_address = Column(INET, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(
            password, method="pbkdf2:sha1:25000"
        )

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class CorePlayer(ModelBase):
    __tablename__ = "ck_players"

    player_id = Column(Integer, primary_key=True)
    player_name = Column(Unicode(200), doc="Players display name")
    user_id = Column(Integer, ForeignKey("ck_users.user_id"), index=True)
    create_date = Column(DateTime, nullable=False, server_default=utc_now)
    logon_date = Column(DateTime, nullable=False, server_default=utc_now, doc="Last logon date")
    num_logons = Column(Integer, default=0)

    clients = relationship("Client", backref="player")

    status = Column(String(20), nullable=True, default="active")

    def __marshallable__(self):
        """
        This is needed to fill in required parameters for fields.Url() in the
        player_model response model object.
        """
        ret = self.__dict__
        ret["exchange_id"] = self.player_id
        ret["exchange"] = "players"
        ret["queue"] = "{queue}"
        return ret

    @hybrid_property
    def is_online(self):
        if self.user and self.user.client:
            return self.user.client.is_online
        return False


class Client(ModelBase):
    __tablename__ = "ck_clients"

    client_id = Column(BigInteger, primary_key=True)
    client_type = Column(String(20))
    user_id = Column(Integer, ForeignKey("ck_users.user_id"), index=True)
    player_id = Column(Integer, ForeignKey("ck_players.player_id"), index=True)
    create_date = Column(DateTime, nullable=False, server_default=utc_now)
    build = Column(String(100), index=True)
    platform_type = Column(String(20))
    version = Column(String(20))
    app_guid = Column(String(100))
    heartbeat = Column(DateTime, nullable=False, server_default=utc_now)
    num_heartbeats = Column(Integer, default=1)
    platform_version = Column(String(20), nullable=True)
    ip_address = Column(INET, nullable=True, index=True)
    num_requests = Column(Integer, nullable=False, server_default="0")
    platform_info = Column(JSON, nullable=True)

    identity_id = Column(
        Integer, ForeignKey("ck_user_identities.identity_id"), index=True
    )

    status = Column(String(20), nullable=True, server_default="active", index=True)
    details = Column(JSON, nullable=True)

    @hybrid_property
    def is_online(self):
        heartbeat_timeout = current_app.config.get(
            "heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT
        )
        if (
            self.status == "active"
            and self.heartbeat + datetime.timedelta(seconds=heartbeat_timeout)
            >= utcnow()
        ):
            return True
        return False


class ConnectEvent(ModelBase):
    __tablename__ = "ck_connect_events"
    event_id = Column(BigInteger, Sequence("ck_event_id_seq"), primary_key=True)
    event_date = Column(DateTime, nullable=False, server_default=utc_now)
    event_type_id = Column(Integer, nullable=False)
    user_id = Column(
        Integer, ForeignKey("ck_users.user_id"), nullable=False, index=True
    )
    seconds = Column(Integer)


class UserEvent(ModelBase):
    __tablename__ = "ck_user_events"
    __table_args__ = (
        Index("ix_ckuserevent_user_id_event_date", "user_id", "event_date"),
    )

    event_id = Column(BigInteger, Sequence("ck_event_id_seq"), primary_key=True)
    event_date = Column(DateTime, nullable=False, server_default=utc_now)
    event_type_id = Column(Integer, nullable=False)
    user_id = Column(
        Integer, ForeignKey("ck_users.user_id"), nullable=False, index=True
    )
    data = Column(String(500))


class Counter(ModelBase):
    __tablename__ = "ck_counters"

    counter_id = Column(Integer, primary_key=True)
    name = Column(String(255), index=True, unique=True)
    label = Column(String(255), nullable=True, index=False)
    counter_type = Column(
        ENUM("count", "absolute", name="counter_type"), nullable=False, index=True
    )


class PlayerCounter(ModelBase):
    __tablename__ = "ck_playercounters"

    id = Column(Integer, primary_key=True)
    counter_id = Column(
        Integer, ForeignKey("ck_counters.counter_id"), nullable=False, index=True
    )
    player_id = Column(
        Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True
    )
    num_updates = Column(Integer, nullable=False, default=1)
    last_update = Column(DateTime, nullable=True)


class CounterEntry(Base):
    __tablename__ = "ck_counterentries"

    id = Column(Integer, primary_key=True)
    counter_id = Column(
        Integer, ForeignKey("ck_counters.counter_id"), nullable=False, index=True
    )
    player_id = Column(Integer, nullable=True, index=True)
    period = Column(
        ENUM(
            "total",
            "month",
            "week",
            "day",
            "hour",
            "minute",
            "second",
            name="counter_period",
        ),
        nullable=False,
        index=True,
    )
    date_time = Column(DateTime, nullable=False, index=True, server_default=utc_now)
    value = Column(Float, nullable=False)
    context_id = Column(Integer, nullable=True, index=True)


# GameServer models
class Machine(ModelBase):
    __tablename__ = "gs_machines"

    machine_id = Column(Integer, primary_key=True)
    realm = Column(
        ENUM("local", "aws", "other", name="realm_type"), nullable=False, index=True
    )
    instance_id = Column(String(50), nullable=True)
    instance_type = Column(String(50), nullable=True)
    instance_name = Column(String(200), nullable=True)
    placement = Column(String(50), nullable=True)
    public_ip = Column(INET, nullable=True)
    private_ip = Column(INET, nullable=True)
    server_count = Column(Integer, nullable=True, default=0)
    server_date = Column(DateTime, nullable=True)
    machine_info = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)
    status = Column(JSON, nullable=True)

    heartbeat_date = Column(DateTime, nullable=True, server_default=utc_now)
    config = Column(JSON, nullable=True)
    statistics = Column(JSON, nullable=True)
    group_name = Column(String(50), nullable=True)


class Server(ModelBase):
    __tablename__ = "gs_servers"

    server_id = Column(Integer, primary_key=True)
    machine_id = Column(Integer, nullable=False)
    version = Column(String(50), nullable=True)
    public_ip = Column(INET, nullable=True)
    port = Column(Integer, nullable=True)
    command_line = Column(String(4000), nullable=True)
    command_line_custom = Column(String(4000), nullable=True)
    pid = Column(Integer, nullable=True)
    status = Column(String(50), nullable=True)
    status_date = Column(DateTime, nullable=True, server_default=utc_now)
    heartbeat_date = Column(DateTime, nullable=True, server_default=utc_now)
    heartbeat_count = Column(Integer, nullable=False, server_default="0")
    error = Column(String(4000), nullable=True)
    image_name = Column(String(500), nullable=True)
    branch = Column(String(50), nullable=True)
    commit_id = Column(String(50), nullable=True)
    process_info = Column(JSON, nullable=True)
    server_statistics = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)
    repository = Column(String(50), nullable=True)
    ref = Column(String(50), nullable=True)
    build = Column(String(200), nullable=True)
    build_number = Column(String(50), nullable=True)
    target_platform = Column(String(50), nullable=True)
    build_info = Column(JSON, nullable=True)
    token = Column(String(20), nullable=True)


class ServerDaemonCommand(ModelBase):
    __tablename__ = "gs_serverdaemoncommands"
    command_id = Column(Integer, primary_key=True)
    server_id = Column(Integer, index=True)
    command = Column(String(50), nullable=False)
    arguments = Column(JSON, nullable=True)
    status = Column(String(50), nullable=True)
    status_date = Column(DateTime, nullable=True)
    details = Column(JSON, nullable=True)


class Match(ModelBase):
    __tablename__ = "gs_matches"

    match_id = Column(Integer, primary_key=True)
    server_id = Column(Integer, nullable=False)
    start_date = Column(DateTime, nullable=True, server_default=utc_now)
    end_date = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=True)
    num_players = Column(Integer, nullable=True)
    max_players = Column(Integer, nullable=True)
    game_mode = Column(String(50), nullable=True)
    map_name = Column(String(50), nullable=True)
    match_statistics = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)
    status_date = Column(DateTime, nullable=True)
    unique_key = Column(String(50), nullable=True)


class MatchPlayer(ModelBase):
    __tablename__ = "gs_matchplayers"

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, index=True)
    player_id = Column(Integer, index=True)
    team_id = Column(Integer, nullable=True, index=True)
    join_date = Column(DateTime, nullable=True, server_default=utc_now)
    leave_date = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=True)
    num_joins = Column(Integer, nullable=False, default=0)
    seconds = Column(Integer, nullable=False, default=0)
    statistics = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)


class MatchTeam(ModelBase):
    __tablename__ = "gs_matchteams"

    team_id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=True)
    match_id = Column(Integer, index=True)
    statistics = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)


class MatchEvent(ModelBase):
    __tablename__ = "gs_matchevents"

    event_id = Column(BigInteger, primary_key=True)
    event_type_id = Column(Integer, nullable=True)
    event_type_name = Column(String(50), nullable=False)
    match_id = Column(Integer, nullable=False, index=True)
    player_id = Column(Integer, nullable=True, index=True)
    details = Column(JSON, nullable=True)


class RunConfig(ModelBase):
    __tablename__ = "gs_runconfigs"

    runconfig_id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    repository = Column(String(255), nullable=False)
    ref = Column(String(255), nullable=False)
    build = Column(String(255), nullable=False)
    command_line = Column(String(4000), nullable=True)
    num_processes = Column(Integer, nullable=False, server_default="0")
    details = Column(JSON, nullable=True)


class MachineGroup(ModelBase):
    __tablename__ = "gs_machinegroups"

    machinegroup_id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Unicode(2000), nullable=True)
    runconfig_id = Column(Integer, nullable=True)


class MachineEvent(ModelBase):
    __tablename__ = "gs_machine_events"

    event_id = Column(Integer, primary_key=True)
    event_type_name = Column(String(50), nullable=False)
    machine_id = Column(Integer, nullable=False, index=True)
    details = Column(JSON, nullable=True)
    status = Column(JSON, nullable=True)


class MatchQueuePlayer(ModelBase):
    __tablename__ = "gs_matchqueueplayers"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    criteria = Column(JSON, nullable=True)
    status = Column(String(50), nullable=False, index=True)
    match_id = Column(Integer, nullable=True, index=False)
    placement = Column(String(50), nullable=True)
    ref = Column(String(50), nullable=True)
    token = Column(String(50), nullable=True)

    def __repr__(self):
        return "<MatchQueuePlayer %s in match %s>" % (self.player_id, self.match_id)


class GameState(ModelBase):
    __tablename__ = "ck_gamestates"

    gamestate_id = Column(BigInteger, primary_key=True)
    player_id = Column(
        Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True
    )
    namespace = Column(String(255), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    journal_id = Column(Integer, nullable=True)
    data = Column(JSON, nullable=False)
    is_valid = Column(Boolean, nullable=True)

    gamestatehistory_id = Column(BigInteger, nullable=True)


class GameStateHistory(ModelBase):
    __tablename__ = "ck_gamestateshistory"

    gamestatehistory_id = Column(BigInteger, primary_key=True)
    player_id = Column(
        Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True
    )
    namespace = Column(String(255), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    journal_id = Column(Integer, nullable=True)
    data = Column(JSON, nullable=False)
    is_valid = Column(Boolean, nullable=True)


class PlayerJournal(ModelBase):
    __tablename__ = "ck_playerjournal"

    sequence_id = Column(BigInteger, primary_key=True)
    journal_id = Column(Integer, nullable=False, server_default="0", index=True)
    timestamp = Column(DateTime, nullable=True, index=False)
    player_id = Column(
        Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True
    )
    actor_id = Column(Integer, nullable=True, index=True)
    action_type_id = Column(Integer, nullable=True, index=True)
    action_type_name = Column(String(50), nullable=False, index=True)
    details = Column(JSON, nullable=True)
    steps = Column(JSON, nullable=True)
    deleted = Column(Boolean, nullable=True, default=False)


class Ticket(ModelBase):
    __tablename__ = "ck_tickets"

    ticket_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False, index=True)
    issuer_id = Column(Integer, nullable=True, index=True)
    ticket_type = Column(String(50), nullable=False)

    details = Column(JSON, nullable=True)
    external_id = Column(String(50), nullable=True, index=True)

    # when ticket is claimed by client we add the journal_id and date
    journal_id = Column(Integer, nullable=True, index=True)
    used_date = Column(DateTime, nullable=True, index=False)


class PlayerEvent(ModelBase):
    __tablename__ = "ck_player_events"
    __table_args__ = (
        Index("ix_ckplayerevent_player_id_create_date", "player_id", "create_date"),
    )

    event_id = Column(BigInteger, Sequence("ck_event_id_seq"), primary_key=True)
    event_type_id = Column(Integer, nullable=True)
    event_type_name = Column(String(50), nullable=False)
    player_id = Column(
        Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True
    )
    details = Column(JSON, nullable=True)


class PlayerSummary(ModelBase):
    __tablename__ = "ck_player_summary"

    id = Column(Integer, primary_key=True)
    player_id = Column(
        Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True
    )
    name = Column(String(50))
    value = Column(Integer, nullable=False)

    player = relationship(
        CorePlayer, backref=backref("player_summary", uselist=False)
    )


class PlayerSummaryHistory(ModelBase):
    __tablename__ = "ck_player_summaryhistory"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False, index=True)
    name = Column(String(50))
    value = Column(Integer, nullable=False)


class Friendship(ModelBase):
    __tablename__ = "ck_friendships"

    id = Column(BigInteger, Sequence("ck_friendships_id_seq"), primary_key=True)
    player1_id = Column(
        Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True
    )
    player2_id = Column(
        Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True
    )
    status = Column(String(20), nullable=False, default="active")

    CheckConstraint("player1_id < player2_id")


class FriendInvite(ModelBase):
    __tablename__ = "ck_friend_invites"

    id = Column(BigInteger, Sequence("ck_friend_invites_id_seq"), primary_key=True)
    issued_by_player_id = Column(Integer, ForeignKey("ck_players.player_id"), nullable=False, index=True)
    token = Column(String(50), nullable=False, index=True)
    expiry_date = Column(DateTime, nullable=False)
    deleted = Column(Boolean, nullable=True, default=False)
    issued_to_player_id = Column(Integer, ForeignKey("ck_players.player_id"), nullable=True, index=True)


event.listen(
    CorePlayer.__table__,
    "after_create",
    DDL("ALTER SEQUENCE ck_players_player_id_seq RESTART WITH 1;"),
)
event.listen(
    User.__table__,
    "after_create",
    DDL("ALTER SEQUENCE ck_users_user_id_seq RESTART WITH 100000001;"),
)
event.listen(
    UserIdentity.__table__,
    "after_create",
    DDL("ALTER SEQUENCE ck_user_identities_identity_id_seq RESTART WITH 200000001;"),
)

event.listen(
    Server.__table__,
    "after_create",
    DDL("ALTER SEQUENCE gs_servers_server_id_seq RESTART WITH 100000001;"),
)
event.listen(
    Machine.__table__,
    "after_create",
    DDL("ALTER SEQUENCE gs_machines_machine_id_seq RESTART WITH 200000001;"),
)
