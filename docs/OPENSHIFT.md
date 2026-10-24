# OpenShift / Kubernetes commands

Most commands take a **namespace** argument. It is validated against the command's configuration file (the `omni-`
prefix is optional and case is ignored). Every command is permission-checked by user and channel, see
[Permissions](PERMISSIONS.md).

Each group is enabled by an environment variable naming its configuration file (under `config/` or an absolute path):

| Group | Environment variable |
|---|---|
| `deployment` | `OPENSHIFT_DEPLOYMENT` |
| `cronjob` | `OPENSHIFT_CRONJOB` |
| `scaledown` | `OPENSHIFT_SCALEDOWN` |
| `actuator` | `OPENSHIFT_ACTUATOR_REFRESH` |
| `mock` | `MOCK_CONFIGURATION` |
| `deploy` | `DOCKER_DEPLOY_CONFIGURATION` |

The configuration of each environment sits under `environments:` in the file, with credentials and permissions in
sibling `.credentials.yml` and `.permissions.yml` files, and cluster URLs in `config/kubernetes_servers.yml`.
Connections use a static bearer token (OpenShift) or a service-principal flow (Azure AKS, `url: azure`).

Commands that return tables accept `-f/--format` with `table` (default), `markdown`, `excel` or `zip_markdown`.

## `deployment`

| Command | Description |
|---|---|
| `deployment list <namespace>` | Deployments of the namespace with replica counts and paused state. |
| `deployment pause <namespace>` | Pauses all deployments. |
| `deployment resume <namespace>` | Resumes all deployments. |

## `cronjob`

| Command | Description |
|---|---|
| `cronjob list <namespace>` | CronJobs with suspended state, last schedule and success times, and a readable schedule description (24-hour times, localised month names). |
| `cronjob pause <namespace>` | Suspends every CronJob that is running and remembers which ones it suspended (a stack kept in `data/cronjob-stack-<namespace>.yml`). |
| `cronjob resume <namespace>` | Pops the most recent pause and re-enables only the CronJobs it suspended, so CronJobs that were already suspended stay suspended. |
| `cronjob disable <namespace> <name>` | Suspends one CronJob. |
| `cronjob enable <namespace> <name>` | Re-enables one CronJob. |

## `scaledown [do] <namespace>`

Scales the Deployments and StatefulSets of a namespace to 0 replicas, except those listed under `~deployments` and
`~statefulsets` in the configuration. `do` is optional, `scaledown <namespace>` does the same.

## `actuator`

Reaches Spring Boot Actuator endpoints inside pods through a port-forward. Pods are found by the label
`deployment=<name>`. Several deployment names can be given.

| Command | Description |
|---|---|
| `actuator refresh <namespace> <deployment...>` | For each pod: reads `/actuator/env`, calls `/actuator/refresh`, reads `/actuator/env` again, and shows the before, the changes and the after. |
| `actuator view <namespace> <deployment...>` | Shows the environment properties of each pod. |
| `actuator health <namespace> <deployment...>` | Shows the health components of each pod, with free disk space. |
| `actuator pods <namespace> [deployment]` | Pods with readiness, status, restart count, host and pod IP. |

## `mock [set] <namespace> <status>`

Switches the microservice mocks of an environment by running `oc set env` for each microservice. The valid statuses,
the environment variables and `vartemplate` substitutions come from the configuration. Variable templates that refer
to themselves are rejected. Passwords in the output are masked. This group uses the `oc` (and `az`) command-line tools
rather than the Kubernetes library.

| Command | Description |
|---|---|
| `mock <namespace> <status>` / `mock set ...` | Switch the mock status. Output is attached as `mock.txt`. |
| `mock check <namespace> [-x]` | Lists the current environment variables of each mocked microservice (passwords masked). |
| `mock view <namespace>` | Table of the deployments of the namespace. |

## `deploy <microservice> <version> <source_env> <target_env> <dry_run>`

Pulls a microservice image from the source environment's registry and pushes it to the target's. It is a work in
progress and currently replies "Not implemented" for real runs.
