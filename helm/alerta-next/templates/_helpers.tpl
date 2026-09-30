{{/*
Base name of all objects: fullnameOverride; else the release name, or <release>-alerta-next when it does not contain
the chart name.
*/}}
{{- define "alerta-next.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 50 | trimSuffix "-" -}}
{{- else if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "alerta-next.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/part-of: alerta-next
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ include "alerta-next.tag" . | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Selector labels of one component: include "alerta-next.selector" (list . "backend") */}}
{{- define "alerta-next.selector" -}}
{{- $ctx := index . 0 -}}
app.kubernetes.io/name: {{ include "alerta-next.fullname" $ctx }}-{{ index . 1 }}
app.kubernetes.io/instance: {{ $ctx.Release.Name }}
{{- end -}}

{{- define "alerta-next.tag" -}}
{{- default .Chart.AppVersion .Values.image.tag -}}
{{- end -}}

{{- define "alerta-next.image" -}}
{{- $ctx := index . 0 -}}
{{- printf "%s/%s:%s" $ctx.Values.image.registry (index . 1) (include "alerta-next.tag" $ctx) -}}
{{- end -}}

{{/* secrets.mode, validated: values | existing | csi */}}
{{- define "alerta-next.secretsMode" -}}
{{- $m := .Values.secrets.mode -}}
{{- if not (has $m (list "values" "existing" "csi")) -}}
{{- fail (printf "secrets.mode must be values, existing or csi (is %q)" $m) -}}
{{- end -}}
{{- $m -}}
{{- end -}}

{{- define "alerta-next.csi" -}}
{{- if eq (include "alerta-next.secretsMode" .) "csi" }}true{{ end -}}
{{- end -}}

{{/* Kubernetes Secret with the database login (modes values / existing) */}}
{{- define "alerta-next.dbSecret" -}}
{{- if eq (include "alerta-next.secretsMode" .) "existing" -}}
{{- required "database.existingSecret is required with secrets.mode=existing" .Values.database.existingSecret -}}
{{- else -}}
{{- printf "%s-db" (include "alerta-next.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Secret with the Alertmanager login; empty = none */}}
{{- define "alerta-next.alertmanagerSecret" -}}
{{- $m := include "alerta-next.secretsMode" . -}}
{{- if eq $m "existing" -}}
{{- .Values.alertmanager.existingSecret -}}
{{- else if and (eq $m "values") (or .Values.alertmanager.token .Values.alertmanager.username) -}}
{{- printf "%s-alertmanager" (include "alerta-next.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Environment variable prefix of a named Alertmanager: waw-prod → ALERTMANAGER_WAW_PROD */}}
{{- define "alerta-next.amEnv" -}}
{{- printf "ALERTMANAGER_%s" (. | upper | replace "-" "_") -}}
{{- end -}}

{{/* Kubernetes Secret with the login of a named Alertmanager; empty = none. include ... (list $ $am) */}}
{{/* Secret with the mail relay password; empty = none */}}
{{- define "alerta-next.mailSecret" -}}
{{- $m := include "alerta-next.secretsMode" . -}}
{{- if eq $m "existing" -}}
{{- .Values.mail.existingSecret -}}
{{- else if and (eq $m "values") .Values.mail.username -}}
{{- printf "%s-mail" (include "alerta-next.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "alerta-next.namedAmSecret" -}}
{{- $ctx := index . 0 -}}
{{- $am := index . 1 -}}
{{- $m := include "alerta-next.secretsMode" $ctx -}}
{{- if eq $m "existing" -}}
{{- $am.existingSecret -}}
{{- else if and (eq $m "values") (or $am.token $am.username) -}}
{{- printf "%s-alertmanager-%s" (include "alerta-next.fullname" $ctx) $am.name -}}
{{- end -}}
{{- end -}}

{{- define "alerta-next.oidcSecret" -}}
{{- if eq (include "alerta-next.secretsMode" .) "existing" -}}
{{- required "oidc.existingSecret is required with oidc.enabled=true and secrets.mode=existing" .Values.oidc.existingSecret -}}
{{- else -}}
{{- printf "%s-oidc" (include "alerta-next.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* SecretProviderClass of the backend (all objects) and of the internal database (DB_USER, DB_PASSWORD only) */}}
{{- define "alerta-next.spcBackend" -}}
{{- default (printf "%s-secrets" (include "alerta-next.fullname" .)) .Values.secrets.csi.secretProviderClass -}}
{{- end -}}

{{- define "alerta-next.spcDatabase" -}}
{{- default (printf "%s-db-secrets" (include "alerta-next.fullname" .)) .Values.secrets.csi.secretProviderClass -}}
{{- end -}}

{{- define "alerta-next.hasCA" -}}
{{- if or .Values.internalCA.certificate .Values.internalCA.existingConfigMap -}}true{{- end -}}
{{- end -}}

{{- define "alerta-next.caConfigMap" -}}
{{- default (printf "%s-ca" (include "alerta-next.fullname" .)) .Values.internalCA.existingConfigMap -}}
{{- end -}}

{{/* JDBC URL of the database */}}
{{- define "alerta-next.dbUrl" -}}
{{- $db := .Values.database -}}
{{- if $db.internal.enabled -}}
{{- printf "jdbc:postgresql://%s-db:5432/alerta" (include "alerta-next.fullname" .) -}}
{{- else if $db.external.url -}}
{{- $db.external.url -}}
{{- else -}}
{{- $host := required "database.external.host (or database.external.url) is required when database.internal.enabled=false" $db.external.host -}}
{{- $params := list -}}
{{- with $db.external.sslMode -}}
{{- $params = append $params (printf "sslmode=%s" .) -}}
{{- if and (hasPrefix "verify" .) (include "alerta-next.hasCA" $) -}}
{{- $params = append $params "sslrootcert=/etc/alerta/ca/ca.crt" -}}
{{- end -}}
{{- end -}}
{{- printf "jdbc:postgresql://%s:%v/%s" $host $db.external.port $db.external.name -}}
{{- if $params }}?{{ join "&" $params }}{{ end -}}
{{- end -}}
{{- end -}}

{{/* Settings the chart derives from values; the user's "config" is merged over them. */}}
{{- define "alerta-next.environmentYml" -}}
{{- $ca := include "alerta-next.hasCA" . -}}
{{- $am := dict "url" .Values.alertmanager.url -}}
{{- if $ca }}{{ $_ := set $am "ca-file" "/etc/alerta/ca/ca.crt" }}{{ end -}}
{{- $oidc := dict "enabled" .Values.oidc.enabled -}}
{{- if .Values.oidc.enabled -}}
{{- $_ := set $oidc "issuer" (required "oidc.issuer is required when oidc.enabled=true" .Values.oidc.issuer) -}}
{{- $_ := set $oidc "client-id" .Values.oidc.clientId -}}
{{- with .Values.oidc.label }}{{ $_ := set $oidc "label" . }}{{ end -}}
{{- with .Values.oidc.claims }}{{ $_ := set $oidc "claims" . }}{{ end -}}
{{- if $ca }}{{ $_ := set $oidc "ca-file" "/etc/alerta/ca/ca.crt" }}{{ end -}}
{{- end -}}
{{- $logging := dict -}}
{{- $structured := dict -}}
{{- if eq .Values.logs.consoleFormat "ecs" }}{{ $_ := set $structured "format" (dict "console" "ecs") }}{{ end -}}
{{- if .Values.logs.file.enabled -}}
{{- $fmt := default (dict) (get $structured "format") -}}
{{- $_ := set $fmt "file" "ecs" -}}
{{- $_ := set $structured "format" $fmt -}}
{{- $_ := set $logging "file" (dict "name" "/var/log/alerta/alerta-next.json") -}}
{{- $_ := set $logging "logback" (dict "rollingpolicy" (dict "max-file-size" "50MB" "total-size-cap" "400MB")) -}}
{{- end -}}
{{- $ecs := dict "name" "alerta-next" -}}
{{- with .Values.logs.serviceEnvironment }}{{ $_ := set $ecs "environment" . }}{{ end -}}
{{- $_ := set $structured "ecs" (dict "service" $ecs) -}}
{{- $_ := set $logging "structured" $structured -}}
{{- $named := list -}}
{{- range $i, $a := .Values.alertmanagers -}}
{{- if not (regexMatch "^[a-z][a-z0-9-]{0,31}$" (toString $a.name)) -}}
{{- fail (printf "alertmanagers[%d].name must match [a-z][a-z0-9-]* (at most 32 characters)" $i) -}}
{{- end -}}
{{- $env := include "alerta-next.amEnv" $a.name -}}
{{- $entry := dict "name" $a.name "url" (required (printf "alertmanagers[%d].url is required" $i) $a.url)
      "bearer-token" (printf "${%s_TOKEN:}" $env) "username" (printf "${%s_USERNAME:}" $env)
      "password" (printf "${%s_PASSWORD:}" $env) -}}
{{- if $ca }}{{ $_ := set $entry "ca-file" "/etc/alerta/ca/ca.crt" }}{{ end -}}
{{- $named = append $named $entry -}}
{{- end -}}
{{- $alerta := dict "integrations" (dict "alertmanager" $am "alertmanagers" $named) "auth" (dict "oidc" $oidc) -}}
{{- if .Values.mail.smarthost -}}
{{- $mail := dict "smarthost" .Values.mail.smarthost "from" (required "mail.from is required with mail.smarthost" .Values.mail.from)
      "require-tls" .Values.mail.requireTls "time-zone" .Values.mail.timeZone -}}
{{- if not .Values.mail.allowedDomains }}{{ fail "mail.allowedDomains is required with mail.smarthost, e.g. [example.com]" }}{{ end -}}
{{- $_ := set $mail "allowed-domains" .Values.mail.allowedDomains -}}
{{- with .Values.mail.hello }}{{ $_ := set $mail "hello" . }}{{ end -}}
{{- with .Values.mail.username }}{{ $_ := set $mail "username" . }}{{ end -}}
{{- $url := .Values.mail.consoleUrl -}}
{{- if and (not $url) .Values.ingress.enabled .Values.ingress.host }}{{ $url = printf "https://%s" .Values.ingress.host }}{{ end -}}
{{- with $url }}{{ $_ := set $mail "console-url" . }}{{ end -}}
{{- if $ca }}{{ $_ := set $mail "ca-file" "/etc/alerta/ca/ca.crt" }}{{ end -}}
{{- $_ := set $alerta "mail" $mail -}}
{{- end -}}
{{- if .Values.notifications.enabled -}}
{{- if not .Values.mail.smarthost }}{{ fail "notifications.enabled needs mail.smarthost" }}{{ end -}}
{{- $_ := set $alerta "notifications" (dict "enabled" true "batch-window" .Values.notifications.batchWindow "min-interval" .Values.notifications.minInterval) -}}
{{- end -}}
{{- $base := dict "alerta" $alerta "logging" $logging -}}
{{- if include "alerta-next.csi" . -}}
{{- /* secrets mounted as files by the CSI driver: file DB_PASSWORD = property DB_PASSWORD */ -}}
{{- $_ := set $base "spring" (dict "config" (dict "import" "optional:configtree:/etc/alerta/secrets/")) -}}
{{- end -}}
{{- toYaml (mustMergeOverwrite $base (deepCopy .Values.config)) -}}
{{- end -}}
