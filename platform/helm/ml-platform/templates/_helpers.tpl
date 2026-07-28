{{- define "ml-platform.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ml-platform.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "ml-platform.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{ include "ml-platform.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "ml-platform.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ml-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "ml-platform.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ml-platform.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "ml-platform.image" -}}
{{- if .Values.image.digest -}}
{{ printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else -}}
{{ printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end -}}
{{- end }}

{{- define "ml-platform.portalFullname" -}}
{{ printf "%s-portal" (include "ml-platform.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ml-platform.portalSelectorLabels" -}}
app.kubernetes.io/name: {{ printf "%s-portal" (include "ml-platform.name" .) | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: portal
{{- end }}

{{- define "ml-platform.portalImage" -}}
{{- if .Values.portal.image.digest -}}
{{ printf "%s@%s" .Values.portal.image.repository .Values.portal.image.digest }}
{{- else -}}
{{ printf "%s:%s" .Values.portal.image.repository (.Values.portal.image.tag | default .Chart.AppVersion) }}
{{- end -}}
{{- end }}
