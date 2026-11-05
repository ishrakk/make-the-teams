# Deployment

The site runs on k3s, a small Kubernetes distribution, on a single VM. Manifests are in
[`k8s/`](k8s), combined with Kustomize, which is built into `kubectl`.

| File | What it creates |
| --- | --- |
| [`k8s/web.yaml`](k8s/web.yaml) | Two app pods, a migration init container and Services. |
| [`k8s/postgres.yaml`](k8s/postgres.yaml) | One PostgreSQL pod, a 1 Gi volume and a Service. |
| [`k8s/ingress.yaml`](k8s/ingress.yaml) | Public HTTPS access through Traefik. |
| [`k8s/cluster-issuer.yaml`](k8s/cluster-issuer.yaml) | Free certificates from Let's Encrypt. |
| [`k8s/backup.yaml`](k8s/backup.yaml) | The nightly encrypted backup. See [`backup/`](backup/README.md). |
| [`k8s/monitoring/`](k8s/monitoring) | Prometheus, node exporter and Grafana. |
| [`k3s/traefik-config.yaml`](k3s/traefik-config.yaml) | Keeps visitors' real IP addresses. |

```mermaid
flowchart LR
    user[Phone] -->|HTTPS| traefik[Traefik]
    traefik --> web1[web pod]
    traefik --> web2[web pod]
    web1 --> pg[(PostgreSQL)]
    web2 --> pg
    web1 -->|Reset email| resend[Resend]
    pg --> backup[Backup job]
    backup -->|Encrypted| r2[Cloudflare R2]
```

**Status:** the manifests pass `kustomize build` and `kubeconform --strict`. This guide hasn't
been run from start to finish on a real VM yet, so expect some adjustments, especially around
SELinux.

## What you need first

- **VM:** Oracle Linux 9, with at least 2 CPU cores and 4 GB of memory. k3s's minimum is 2 cores
  and 2 GB. Arm and x86 both work, because images are built for both. `VM.Standard.E2.1.Micro`
  is too small.
- **Network:** a public IP, with ports 80 and 443 open to everyone, and 22 open to your IP only.
- **Domain:** an A record pointing to the VM, set to **DNS only** in Cloudflare.
- **Accounts:** Resend with a verified domain, and an R2 bucket with an API token.
- **Backup key:** an `age` key pair. The private key stays off the VM.
- **Published images:** merge to `main` so that CI publishes them. Then, on GitHub under
  **Packages**, make `make-the-teams` and `make-the-teams-backup` public.

## First deploy

Run these on the VM. Each step depends on the one before it.

**1. Open the firewall.** Port 6443 stays closed, because `kubectl` here connects locally.

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --zone=trusted --add-source=10.42.0.0/16
sudo firewall-cmd --permanent --zone=trusted --add-source=10.43.0.0/16
sudo firewall-cmd --reload
```

k3s [recommends turning firewalld off](https://docs.k3s.io/installation/requirements), and lists
rules like these for keeping it on.

**2. Install k3s, with SELinux enforced.**

```bash
curl -sfL https://get.k3s.io | sudo sh -s - --selinux
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$USER" ~/.kube/config
chmod 600 ~/.kube/config
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
export KUBECONFIG=~/.kube/config
kubectl get nodes
```

The node should show `Ready`.

**3. Keep visitors' real IP addresses, and install cert-manager.**

```bash
sudo dnf install -y git
git clone https://github.com/ishrakk/make-the-teams.git
cd make-the-teams

kubectl apply -f deploy/k3s/traefik-config.yaml
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.yaml
kubectl -n cert-manager wait --for=condition=Available deployment --all --timeout=300s
```

**4. Fill in your values.** None of these are secret.

```bash
DOMAIN=yourdomain.com
LETSENCRYPT_EMAIL=you@example.com
EMAIL_FROM='Make the Teams <noreply@notifications.yourdomain.com>'
AGE_PUBLIC_KEY=age1...
R2_ENDPOINT=https://ACCOUNT_ID.r2.cloudflarestorage.com
R2_BUCKET=make-the-teams-backups

sed -i "s/teams.example.com/$DOMAIN/g" deploy/k8s/ingress.yaml deploy/k8s/web.yaml
sed -i "s/you@example.com/$LETSENCRYPT_EMAIL/" deploy/k8s/cluster-issuer.yaml
sed -i "s/age1replacewithyourpublickey/$AGE_PUBLIC_KEY/" deploy/k8s/backup.yaml
sed -i "s|https://ACCOUNT_ID.r2.cloudflarestorage.com|$R2_ENDPOINT|" deploy/k8s/backup.yaml
sed -i "s|r2:make-the-teams-backups|r2:$R2_BUCKET|" deploy/k8s/backup.yaml
```

In `deploy/k8s/web.yaml`, set the email values:

```yaml
- name: SMTP_HOST
  value: smtp.resend.com
- name: SMTP_USERNAME
  value: resend
- name: EMAIL_FROM
  value: Make the Teams <noreply@notifications.yourdomain.com>
```

**5. Create the secret.** This prompts for your keys, so they don't end up in your shell history.

```bash
kubectl apply -f deploy/k8s/namespace.yaml

read -rsp 'Resend API key: ' RESEND_KEY; echo
read -rsp 'R2 access key ID: ' R2_ID; echo
read -rsp 'R2 secret access key: ' R2_SECRET; echo
DB_PASSWORD=$(openssl rand -hex 24)

kubectl -n make-the-teams create secret generic make-the-teams \
  --from-literal=POSTGRES_PASSWORD="$DB_PASSWORD" \
  --from-literal=DATABASE_URL="postgresql+psycopg://teams:$DB_PASSWORD@postgres/teams" \
  --from-literal=SESSION_SECRET="$(openssl rand -hex 32)" \
  --from-literal=RATING_SECRET="$(openssl rand -hex 32)" \
  --from-literal=GRAFANA_ADMIN_PASSWORD="$(openssl rand -hex 16)" \
  --from-literal=SMTP_PASSWORD="$RESEND_KEY" \
  --from-literal=R2_ACCESS_KEY_ID="$R2_ID" \
  --from-literal=R2_SECRET_ACCESS_KEY="$R2_SECRET"

unset RESEND_KEY R2_ID R2_SECRET DB_PASSWORD
```

**Save `POSTGRES_PASSWORD`, `SESSION_SECRET` and `RATING_SECRET` in your password manager.** If
the VM is lost, restoring needs them. Without `RATING_SECRET`, people can no longer see or edit
their past ratings. To read a value:

```bash
kubectl -n make-the-teams get secret make-the-teams -o jsonpath='{.data.RATING_SECRET}' | base64 -d
```

**6. Deploy.**

```bash
kubectl apply -k deploy/k8s
kubectl -n make-the-teams rollout status deployment/web --timeout=300s
kubectl -n make-the-teams get pods,certificate
```

The certificate should show `READY True` within a few minutes.

**7. Check it.**

- **Site:** run `curl -I https://yourdomain.com/healthz`, which should return 200, then open the
  site and sign up.
- **Private pages:** `https://yourdomain.com/metrics` and `/demo` should both return 404.
- **Password reset:** request one, and check that the email arrives.
- **Backup:** run one now, and look for the file in R2:
  ```bash
  kubectl -n make-the-teams create job --from=cronjob/backup backup-now
  kubectl -n make-the-teams logs -f job/backup-now
  ```
- **Restore:** practice with [the restore steps](backup/README.md#restoring) before inviting anyone.

## Monitoring

Prometheus, node exporter and Grafana run in the same namespace. Grafana opens on one dashboard
covering uptime, active users, total users, database size, CPU, memory, disk, requests,
errors and latency. See [`app/metrics/README.md`](../app/metrics/README.md) for what each means.

None of this is public. Metrics use a separate port with no route from the Ingress, and
Grafana has no Ingress. To view it, tunnel in from your computer:

```bash
# On your computer
ssh -L 3000:localhost:3000 opc@<VM IP>

# In that SSH session
kubectl -n make-the-teams port-forward service/grafana 3000:3000
```

Then open http://localhost:3000 and sign in as `admin`, with `GRAFANA_ADMIN_PASSWORD` from the secret.

**Add an outside uptime check too.** Prometheus runs on the same VM, so it can't report that
the VM is down, and there are no alerts yet. A free external checker pointed at `/healthz`
covers this.

## Updating

```bash
git pull --rebase --autostash
kubectl apply -k deploy/k8s
kubectl -n make-the-teams rollout restart deployment/web
```

The manifests use the moving `main` image tag. For a repeatable deploy, set `newTag` in
`k8s/kustomization.yaml` to a commit's `sha-xxxxxxx` tag, which also makes rollback a one-line
change.

## Moving a group to the paid plan

See [Plans](../app/groups/README.md#plans).

## If something's wrong

| Symptom | Check |
| --- | --- |
| Pod stuck in `ImagePullBackOff` | The GitHub packages are public, and CI has published them |
| Pod stuck in `CreateContainerConfigError` | The secret has every key from step 5 |
| Certificate never ready | The A record, port 80 being open, and `kubectl describe certificaterequest -A` |
| SELinux denials | `sudo ausearch -m avc -ts recent`, especially for PostgreSQL's volume and node exporter |
| Everyone shares one attempt limit | `TRUSTED_PROXY_HOPS` and `traefik-config.yaml`. Each proxy in front adds a hop |

## Before relying on this

- **PostgreSQL is one pod on one VM.** The site is down while it restarts, and losing the VM means
  restoring from last night's backup.
- **Don't deploy `docker-compose.yml`.** It's for local testing, with test users and fixed secrets.
