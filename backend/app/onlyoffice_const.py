"""Desktop OnlyOffice sidecar constants shared by settings and the launcher."""

# Localhost-only Document Server. Avoids the Docker compose port 8080.
ONLYOFFICE_DESKTOP_PORT = 18080
# DocService/FileConverter talk to a private RabbitMQ, not a system broker.
ONLYOFFICE_AMQP_PORT = 25673
ONLYOFFICE_EPMD_PORT = 25679
ONLYOFFICE_DIST_PORT = 25674
# Same value is written into Document Server local.json and the backend env.
# It only authenticates the loopback editor; it is not an account secret.
ONLYOFFICE_DESKTOP_JWT = "tender-desktop-onlyoffice-jwt"
ONLYOFFICE_DB_NAME = "onlyoffice"
ONLYOFFICE_DB_USER = "onlyoffice"
ONLYOFFICE_DB_PASSWORD = "onlyoffice"
ONLYOFFICE_STATE_FILE = "onlyoffice.json"
