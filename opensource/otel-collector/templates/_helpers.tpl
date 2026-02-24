{{/*
Expand the name of the chart.
*/}}
{{- define "otel-collector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "otel-collector.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}


{{/*
Expand the name of the aggregator
*/}}
{{- define "otel-collector.aggregator.name" -}}
{{ include "otel-collector.name" . }}-aggregator
{{- end }}

{{/*
Aggregator otel-collector labels
*/}}
{{- define "otel-collector.aggregator.labels" -}}
helm.sh/chart: {{ include "otel-collector.chart" . }}
{{ include "otel-collector.aggregator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Aggregator Selector labels
*/}}
{{- define "otel-collector.aggregator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "otel-collector.aggregator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the  aggregator headless service name
*/}}
{{- define "otel-collector.aggregator.headlessServiceName" -}}
{{ include "otel-collector.aggregator.name" . }}-headless
{{- end }}


{{/*
Expand the name of the ingestor
*/}}
{{- define "otel-collector.ingestor.name" -}}
{{ include "otel-collector.name" . }}-ingestor
{{- end }}


{{/*
otel-collector labels
*/}}
{{- define "otel-collector.ingestor.labels" -}}
helm.sh/chart: {{ include "otel-collector.chart" . }}
{{ include "otel-collector.ingestor.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "otel-collector.ingestor.selectorLabels" -}}
app.kubernetes.io/name: {{ include "otel-collector.ingestor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}


