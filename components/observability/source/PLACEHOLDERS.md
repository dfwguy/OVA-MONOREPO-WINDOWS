# Placeholder contract

Values written as `${NAME}` or `<required-...>` must be resolved per customer.
The most important replacements are cluster identity/time zone; Grafana admin
secret; storage roots; Slurm paths; validation log roots; UFM host; Redfish
target inventory; Docker bridge addresses; and customer-specific `/cluster`
mounts.

The API export removes URL query strings and user-info. Contact-point setting
values are replaced with `${GRAFANA_SECRET_*}` placeholders. Grafana secure
datasource values are unavailable by design and must come from a secret
provider. Never commit the resolved environment or credential files.
