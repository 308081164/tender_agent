"""Desktop OnlyOffice sidecar constants shared by settings and the launcher."""

# Localhost-only Document Server. Avoids the Docker compose port 8080.
ONLYOFFICE_DESKTOP_PORT = 18080
# DocService/FileConverter talk to a private RabbitMQ, not a system broker.
ONLYOFFICE_AMQP_PORT = 25673
# The desktop broker does not start epmd. This port is unused; it stays so
# older notes that mention 25679 still match the reserved value.
ONLYOFFICE_EPMD_PORT = 25679
ONLYOFFICE_DIST_PORT = 25674
# Long name on loopback. Never `onlyoffice@localhost`: RabbitMQ 3.13 turns
# that into a shortname prelaunch node and aborts when distribution fails.
ONLYOFFICE_RABBIT_NODENAME = "onlyoffice@127.0.0.1"
# Same value is written into Document Server local.json and the backend env.
# It only authenticates the loopback editor; it is not an account secret.
ONLYOFFICE_DESKTOP_JWT = "tender-desktop-onlyoffice-jwt"
ONLYOFFICE_DB_NAME = "onlyoffice"
ONLYOFFICE_DB_USER = "onlyoffice"
ONLYOFFICE_DB_PASSWORD = "onlyoffice"
ONLYOFFICE_STATE_FILE = "onlyoffice.json"
