# Deployment

Kubernetes manifests in [`k8s/`](k8s), combined with Kustomize, which is built into
`kubectl`.

| File | What it creates |
| --- | --- |
| [`namespace.yaml`](k8s/namespace.yaml) | The `make-the-teams` namespace. |
| [`web.yaml`](k8s/web.yaml) | Two app pods, a migration init container and a Service. |
| [`postgres.yaml`](k8s/postgres.yaml) | One PostgreSQL pod, a 1 Gi volume and a Service. |
| [`ingress.yaml`](k8s/ingress.yaml) | Public HTTPS access. |

```mermaid
flowchart LR
    user[Phone] -->|HTTPS| ingress[Ingress]
    ingress --> service[web Service]
    service --> web1[web pod]
    service --> web2[web pod]
    web1 --> pg[(postgres)]
    web2 --> pg
```

**Status:** the manifests pass `kustomize build` and `kubeconform --strict`. They
haven't yet been run on a live cluster.

## First deploy

**1. Choose the host.** Replace `teams.example.com` in `k8s/ingress.yaml` and in
`PUBLIC_URL` in `k8s/web.yaml`. Set `ingressClassName` if your cluster needs it.

**2. Create the secret.** It isn't stored in this public repository.

```bash
kubectl apply -f deploy/k8s/namespace.yaml

DB_PASSWORD=$(openssl rand -hex 24)
kubectl -n make-the-teams create secret generic make-the-teams \
  --from-literal=POSTGRES_PASSWORD="$DB_PASSWORD" \
  --from-literal=DATABASE_URL="postgresql+psycopg://teams:$DB_PASSWORD@postgres/teams" \
  --from-literal=SESSION_SECRET="$(openssl rand -hex 32)" \
  --from-literal=RATING_SECRET="$(openssl rand -hex 32)"
```

`RATING_SECRET` hides who gave each rating, so keep it out of database backups. If you
change it, people can no longer see or edit their past ratings, and those scores stay
in averages. Changing `SESSION_SECRET` signs everyone out.

**Password reset email is optional, and needed before real use.** Without it, someone
who forgets their password is locked out. Fill in `SMTP_HOST`, `SMTP_USERNAME` and
`EMAIL_FROM` in `k8s/web.yaml`, and add `SMTP_PASSWORD` to the secret.

**3. Provide the TLS certificate** as a secret named `make-the-teams-tls`, or add the
annotation your certificate manager expects to `ingress.yaml`. HTTPS is required:
session cookies are only sent over it, so sign-in won't stick without it.

Check that `TRUSTED_PROXY_HOPS` matches your setup. If it's too low, every visitor looks
like the same proxy and shares one attempt limit. If it's too high, visitors can forge
their address and dodge the limits.

**4. Check the image is available.** CI publishes `ghcr.io/ishrakk/make-the-teams` when
`main` changes. Make the package public in GitHub, or add an `imagePullSecret`.

**5. Apply and watch.**

```bash
kubectl apply -k deploy/k8s
kubectl -n make-the-teams rollout status deployment/web
```

## Updating

The manifests use the moving `main` image tag, so restart to pick up a new build:

```bash
kubectl -n make-the-teams rollout restart deployment/web
```

For a repeatable deploy, set `newTag` in `k8s/kustomization.yaml` to a commit's
`sha-xxxxxxx` tag. That also makes rollback a one-line change.

## Before relying on this

- **Nothing backs up the database.** Losing the volume loses every account and group. Add a `pg_dump`
  CronJob that writes somewhere outside the cluster, or use a managed PostgreSQL by
  changing `DATABASE_URL` and removing `postgres.yaml`.
- **PostgreSQL is one pod.** The site is down while that pod restarts, which is
  acceptable for a weekly game.
- **The app pods are hardened; database traffic isn't restricted.** Pods run as non-root
  with a read-only filesystem and no Linux capabilities. A NetworkPolicy allowing
  only the web pods to reach PostgreSQL would be a good addition if your cluster
  enforces them.
